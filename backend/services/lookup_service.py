"""Filling in a player's details from the web, when you ask for it.

THE SOURCE IS WIKIDATA, Wikipedia's sister project: a free database of facts
that anyone may read and reuse. It has an open interface that needs no key and
no account. Sites such as Transfermarkt forbid programs from copying their
pages, so they are not used.

WHAT THIS FILE PROMISES
-----------------------
1. NOTHING HAPPENS BY ITSELF. A search runs only when you press the button, and
   the only thing sent is the name you typed.
2. NOTHING IS SAVED HERE. The details go back to the form for you to check. A
   player is stored only when you press Save, exactly as if you had typed it.
3. UNKNOWN STAYS UNKNOWN. A fact is filled in only when Wikidata states it
   plainly. Where it is vague ("forward"), missing, or contradicts itself, the
   field is left empty and you are told why. Nothing is guessed.
4. ONE ADDRESS IS CONTACTED (WIKIDATA_API below). What you type is sent as a
   search term; it is never used as a web address.

HOW WIKIDATA STORES A PERSON (what the code below is reading)
-------------------------------------------------------------
An entry has an id such as "Q615" and a list of STATEMENTS, each filed under a
numbered property:

    P569  date of birth          P2048  height
    P27   citizenship            P1532  country for sport
    P413  position played        P8006  footedness
    P18   picture (a file name on Wikimedia Commons)
    P54   member of sports team, with QUALIFIERS:
          P580 start time, P582 end time, P1618 shirt number

A statement has a RANK: "preferred" marks the current or best value and
"deprecated" a wrong one. Countries, clubs and positions are entries themselves
("Q21" is England), so turning them into names takes a second request.
"""
import re
from datetime import date
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from errors import Invalid, NotFound, Unavailable
from models import Team

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
ENTRY_PAGE = "https://www.wikidata.org/wiki/"
WIKIPEDIA_PAGE = "https://en.wikipedia.org/wiki/"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/"
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
TRANSPORT: httpx.BaseTransport | None = None  # the tests put a stand-in here, so they never touch the network

MAX_RESULTS = 8
FOOTBALLER = "Q937857"  # Wikidata's entry for "association football player"
QID = re.compile(r"Q[1-9]\d{0,11}")
UNIT_TO_CM = {"Q174728": 1, "Q11573": 100}  # centimetre, metre

# Wikidata's wording -> this app's position code, only where the wording names ONE position.
EXACT_POSITIONS = {
    "goalkeeper": "GK", "centre back": "CB", "central defender": "CB", "right back": "RB", "left back": "LB",
    "right wing back": "RWB", "left wing back": "LWB", "defensive midfielder": "DM", "central midfielder": "CM",
    "attacking midfielder": "AM", "right midfielder": "RM", "left midfielder": "LM", "right winger": "RW",
    "left winger": "LW", "second striker": "SS", "centre forward": "CF", "striker": "ST",
}
# Wording that covers several positions. Never filled in; the possibilities are offered instead.
BROAD_POSITIONS = {
    "defender": "CB, RB or LB", "full back": "RB or LB", "wing back": "RWB or LWB",
    "midfielder": "DM, CM, AM, RM or LM", "winger": "RW or LW", "forward": "ST, CF, SS, RW or LW",
}
# "England men's national association football team" -> England. Youth and Olympic sides do not match.
NATIONAL_TEAM = re.compile(
    r"(?P<country>.+?) (?:(?P<women>women's) |men's )?national (?:association football|football|soccer) team")
# Words that are part of a club's formal name but not of what people call it: "Arsenal F.C." is "Arsenal".
CLUB_AFFIXES = {"fc", "afc", "cf", "sc", "ac", "as", "ss", "ssc", "fk", "sk", "cd", "ud", "club", "de", "futbol",
                "fútbol", "football"}


# ── Talking to Wikidata ──────────────────────────────────────────────────────
def _get(params: dict) -> dict:
    """One question to Wikidata. Raises Unavailable, with words fit to show the user, when it cannot be answered."""
    # Wikidata turns away programs that do not say who runs them, so the app introduces itself.
    agent = (f"FootballAnalystCoach/1.0 ({config.WEB_LOOKUP_CONTACT}; personal football analysis app) "
             f"python-httpx/{httpx.__version__}")
    try:
        with httpx.Client(timeout=TIMEOUT, transport=TRANSPORT, headers={"User-Agent": agent}) as client:
            response = client.get(WIKIDATA_API, params={"format": "json", **params})
    except httpx.TimeoutException:
        raise Unavailable("Wikidata took too long to answer. Try again in a moment.") from None
    except httpx.HTTPError:
        raise Unavailable("Could not reach Wikidata. Check the internet connection and try again.") from None

    if response.status_code == 403:
        raise Unavailable("Wikidata refused the request. It asks every program to say who runs it: set "
                          "WEB_LOOKUP_CONTACT in backend/.env to a link or e-mail address of yours, then restart "
                          "the server.")
    if response.status_code == 429:
        raise Unavailable("Wikidata is asking for a pause. Wait a minute and try again.")
    if response.status_code != 200:
        raise Unavailable(f"Wikidata had a problem (status {response.status_code}). Try again later.")
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or "error" in data:
        raise Unavailable("Wikidata's answer could not be read. Try again.")
    return data


def _label(entry: dict) -> str | None:
    return ((entry.get("labels") or {}).get("en") or {}).get("value")


def _names(ids) -> dict[str, str]:
    """The English names of other entries (countries, clubs, positions). Wikidata takes fifty ids per request."""
    wanted = sorted({entry_id for entry_id in ids if entry_id and QID.fullmatch(entry_id)})
    names = {}
    for start in range(0, len(wanted), 50):
        entries = _get({"action": "wbgetentities", "ids": "|".join(wanted[start:start + 50]), "props": "labels",
                        "languages": "en", "languagefallback": 1}).get("entities", {})
        for entry_id, entry in entries.items():
            if _label(entry):
                names[entry_id] = _label(entry)
    return names


# ── Reading statements ───────────────────────────────────────────────────────
def _all(entry: dict, prop: str) -> list[dict]:
    """Every statement under a property that has a value and has not been marked as wrong."""
    return [statement for statement in (entry.get("claims") or {}).get(prop, [])
            if statement.get("rank") != "deprecated" and (statement.get("mainsnak") or {}).get("snaktype") == "value"]


def _best(entry: dict, prop: str) -> list[dict]:
    """The statements to believe: the "preferred" ones when there are any, otherwise all the usable ones."""
    usable = _all(entry, prop)
    return [statement for statement in usable if statement.get("rank") == "preferred"] or usable


def _value(statement: dict):
    return statement["mainsnak"]["datavalue"]["value"]


def _item(statement: dict) -> str | None:
    value = _value(statement)
    return value.get("id") if isinstance(value, dict) else None


def _qualifier_time(statement: dict, prop: str) -> str:
    """A start or end date written "2023-07-15" ("2023-00-00" when only the year is known), or "" if absent."""
    for snak in (statement.get("qualifiers") or {}).get(prop, []):
        if snak.get("snaktype") == "value":
            return str(snak["datavalue"]["value"].get("time", ""))[1:11]
    return ""


def _is_current(statement: dict) -> bool:
    """A team membership is current when it has no end date, or when its end is recorded as "none"."""
    ends = (statement.get("qualifiers") or {}).get("P582", [])
    return all(snak.get("snaktype") == "novalue" for snak in ends)


def _quoted(words: list[str]) -> str:
    return " and ".join(f'"{word}"' for word in words)


# ── One fact at a time ───────────────────────────────────────────────────────
def _date_of_birth(entry: dict, notes: list[str]) -> str | None:
    births = _best(entry, "P569")
    days = sorted({_value(statement)["time"][1:11] for statement in births if _value(statement).get("precision", 0) >= 11})
    if len(days) == 1:
        try:
            return date.fromisoformat(days[0]).isoformat()
        except ValueError:
            return None
    if len(days) > 1:
        notes.append(f"Date of birth: Wikidata lists more than one ({', '.join(days)}). Left empty.")
    elif births:
        year = _value(births[0])["time"][1:5]
        notes.append(f"Date of birth: Wikidata only gives the year ({year}). Left empty, because the day is not known.")
    return None


def _height_cm(entry: dict, notes: list[str]) -> int | None:
    heights = set()
    for statement in _best(entry, "P2048"):
        value = _value(statement)
        factor = UNIT_TO_CM.get(str(value.get("unit", "")).rsplit("/", 1)[-1])
        try:
            centimetres = round(float(value["amount"]) * factor) if factor else None
        except (KeyError, TypeError, ValueError):
            centimetres = None
        if centimetres and 120 <= centimetres <= 230:  # the same limits the player form uses
            heights.add(centimetres)
    if len(heights) > 1:
        notes.append(f"Height: Wikidata lists more than one ({', '.join(f'{h} cm' for h in sorted(heights))}). Left empty.")
    return heights.pop() if len(heights) == 1 else None


def _preferred_foot(wording: list[str]) -> str | None:
    words = " ".join(wording).casefold()
    left, right = "left" in words, "right" in words
    if (left and right) or any(word in words for word in ("both", "ambidex", "two-footed")):
        return "both"
    return "left" if left else "right" if right else None


def _position(wording: list[str], notes: list[str]) -> str | None:
    keys = [" ".join(word.casefold().replace("-", " ").replace("center", "centre").split()) for word in wording]
    exact = list(dict.fromkeys(EXACT_POSITIONS[key] for key in keys if key in EXACT_POSITIONS))
    if len(exact) == 1:
        return exact[0]
    if wording:
        hint = BROAD_POSITIONS.get(keys[0]) if len(keys) == 1 else None
        notes.append(f"Position: Wikidata says {_quoted(wording)}, which does not name one exact position"
                     + (f" (it could be {hint})" if hint else "") + ". Choose it yourself.")
    return None


def _current_club(clubs: list[dict], notes: list[str]) -> dict | None:
    pool = [club for club in clubs if club["rank"] == "preferred"] or clubs
    if len(pool) <= 1:
        return pool[0] if pool else None
    listed = ", ".join(club["name"] for club in pool)
    dated = sorted((club for club in pool if club["start"]), key=lambda club: club["start"])
    if len(dated) == len(pool) and dated[-1]["start"] != dated[-2]["start"]:
        notes.append(f"Club: Wikidata lists more than one current team ({listed}). Filled in the one joined most "
                     "recently; check it.")
        return dated[-1]
    notes.append(f"Club: Wikidata lists more than one current team ({listed}) and does not say which is the "
                 "latest. Left empty.")
    return None


def _team_key(name: str) -> str:
    words = [word for word in re.findall(r"\w+", name.casefold().replace(".", "")) if word not in CLUB_AFFIXES]
    return " ".join(words) or name.casefold()


def _your_name_for(name: str, kind: str, teams: list, notes: list[str], what: str) -> str:
    """If you already have this team under a slightly different name, use yours, so it is not added twice."""
    matches = [team.name for team in teams if team.team_type == kind and _team_key(team.name) == _team_key(name)]
    if len(matches) == 1 and matches[0].casefold() != name.casefold():
        notes.append(f'{what}: Wikidata calls it "{name}". Filled in your existing team "{matches[0]}" instead.')
        return matches[0]
    return matches[0] if len(matches) == 1 else name


# ── The two things the app can ask for ───────────────────────────────────────
def search_players(query: str) -> dict:
    """Football players on Wikidata whose name matches, best match first. Sends only the cleaned-up name."""
    cleaned = re.sub(r"[^\w\s.'’-]", " ", query or "")  # letters, digits, spaces and the marks names contain
    cleaned = " ".join(word.lstrip("-") for word in cleaned.split())[:80].strip()
    if len(cleaned) < 2:
        raise Invalid("Type at least two letters of the player's name.")

    # "haswbstatement" narrows the search to entries whose occupation is football player.
    found = _get({"action": "query", "list": "search", "srnamespace": 0, "srlimit": MAX_RESULTS,
                  "srsearch": f"{cleaned} haswbstatement:P106={FOOTBALLER}"})
    ids = [hit.get("title", "") for hit in (found.get("query") or {}).get("search", [])]
    ids = [entry_id for entry_id in ids if QID.fullmatch(entry_id)]
    if not ids:
        return {"query": cleaned, "source": "Wikidata", "results": []}

    entries = _get({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|descriptions",
                    "languages": "en", "languagefallback": 1}).get("entities", {})
    results = []
    for entry_id in ids:
        entry = entries.get(entry_id) or {}
        description = ((entry.get("descriptions") or {}).get("en") or {}).get("value")
        results.append({"id": entry_id, "name": _label(entry) or entry_id, "description": description,
                        "url": ENTRY_PAGE + entry_id})
    return {"query": cleaned, "source": "Wikidata", "results": results}


def player_details(db: Session, wikidata_id: str) -> dict:
    """What Wikidata states about one player, as values for the player form. Saves nothing.

    `fields` holds only what was found and is safe to fill in. `notes` says, in
    plain words, what was left empty and why, and what deserves a second look.
    """
    if not QID.fullmatch(wikidata_id or ""):
        raise Invalid("That is not a Wikidata id. One looks like Q615.")
    entries = _get({"action": "wbgetentities", "ids": wikidata_id, "props": "labels|descriptions|claims|sitelinks/urls",
                    "sitefilter": "enwiki", "languages": "en", "languagefallback": 1}).get("entities", {})
    entry = next(iter(entries.values()), None)
    if not entry or "missing" in entry or not QID.fullmatch(str(entry.get("id", ""))):
        raise NotFound(f"Wikidata has no entry {wikidata_id}.")
    if FOOTBALLER not in {_item(statement) for statement in _all(entry, "P106")}:
        raise Invalid("That Wikidata entry is not a football player.")

    fields, notes = {}, []
    name = _label(entry)
    if name:
        fields["full_name"] = name[:160]
    fields["date_of_birth"] = _date_of_birth(entry, notes)
    fields["height_cm"] = _height_cm(entry, notes)

    # Team memberships that are still running. Each remembers its start date and shirt number, if recorded.
    memberships = []
    for statement in _all(entry, "P54"):
        if _is_current(statement) and _item(statement):
            numbers = [snak["datavalue"]["value"] for snak in (statement.get("qualifiers") or {}).get("P1618", [])
                       if snak.get("snaktype") == "value"]
            memberships.append({"id": _item(statement), "rank": statement.get("rank"),
                                "start": _qualifier_time(statement, "P580"), "number": numbers[0] if numbers else None})

    # Countries, positions, footedness and teams are entries of their own: fetch their names in one go.
    sport_ids = [_item(statement) for statement in _best(entry, "P1532")]
    citizen_ids = [_item(statement) for statement in _best(entry, "P27")]
    position_ids = [_item(statement) for statement in _best(entry, "P413")]
    foot_ids = [_item(statement) for statement in _best(entry, "P8006")]
    names = _names([*sport_ids, *citizen_ids, *position_ids, *foot_ids, *(team["id"] for team in memberships)])

    def named(ids):
        return list(dict.fromkeys(names[entry_id] for entry_id in ids if entry_id in names))

    fields["preferred_foot"] = _preferred_foot(named(foot_ids))
    fields["primary_position"] = _position(named(position_ids), notes)

    national, clubs = [], []
    for team in memberships:
        team["name"] = names.get(team["id"])
        if not team["name"]:
            continue
        senior = NATIONAL_TEAM.fullmatch(team["name"])
        if senior:
            national.append(senior["country"] + (" Women" if senior["women"] else ""))
        elif "national" not in team["name"].casefold() and "olympic" not in team["name"].casefold():
            clubs.append(team)
        # Anything else is a youth or Olympic national side. Those are often left open by mistake, so they are ignored.

    your_teams = db.execute(select(Team.name, Team.team_type)).all()
    club = _current_club(clubs, notes)
    if club:
        fields["current_team"] = _your_name_for(club["name"][:120], "club", your_teams, notes, "Club")
        if str(club["number"] or "").isdigit() and 1 <= int(club["number"]) <= 99:
            fields["shirt_number"] = int(club["number"])
    national = list(dict.fromkeys(national))
    if len(national) == 1:
        fields["national_team"] = _your_name_for(national[0][:120], "national", your_teams, notes, "National team")

    # Nationality: the senior national team is the firmest evidence, then "country for sport", then citizenship.
    sport, citizen = named(sport_ids), named(citizen_ids)
    team_country = national[0].removesuffix(" Women") if len(national) == 1 else None
    if team_country:
        fields["nationality"] = team_country
        clash = [country for country in sport if country != team_country]
        if clash:
            notes.append(f"Nationality: filled in {team_country}, from the national team. Wikidata's \"country for "
                         f"sport\" says {', '.join(clash)}, which does not match. Check it.")
    elif len(sport) == 1:
        fields["nationality"] = sport[0]
    elif not sport and len(citizen) == 1:
        fields["nationality"] = citizen[0]
    elif sport or citizen:
        listed = ", ".join(dict.fromkeys([*sport, *citizen]))
        notes.append(f"Nationality: Wikidata lists more than one ({listed}). Left empty.")
    if fields.get("nationality"):
        fields["nationality"] = fields["nationality"][:80]

    pictures = [_value(statement) for statement in _best(entry, "P18") if isinstance(_value(statement), str)]
    if pictures:
        link = COMMONS_FILE + quote(pictures[0].replace(" ", "_"), safe="") + "?width=400"
        if len(link) <= 500:
            fields["photo_url"] = link

    wikipedia = (((entry.get("sitelinks") or {}).get("enwiki") or {}).get("url")) or ""
    return {
        "id": entry["id"],
        "name": name or entry["id"],
        "description": ((entry.get("descriptions") or {}).get("en") or {}).get("value"),
        "fields": {key: value for key, value in fields.items() if value not in (None, "")},  # unknown is left out
        "notes": notes,
        "source": {"name": "Wikidata", "url": ENTRY_PAGE + entry["id"],
                   "wikipedia_url": wikipedia if wikipedia.startswith(WIKIPEDIA_PAGE) else None},
        "checked_on": date.today().isoformat(),
    }
