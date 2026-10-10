"""Looking a player up on Wikidata, against a stand-in for Wikidata's server.

No test here uses the network. httpx.MockTransport answers inside this process
from the made-up entries below, so we can check exactly what would be sent and
how every kind of answer is read. All players, clubs and countries are invented.
"""
import httpx
import pytest

import vocabulary
from services import lookup_service
from tests.helpers import create_player

FOOTBALLER = lookup_service.FOOTBALLER
SAM = "Q900001"

# The names of the entries a player's statements point at.
WORLD = {
    "Q21": "Exampleland", "Q22": "Otherland", "Q23": "Thirdland",
    "Q500": "Northside F.C.", "Q501": "Riverton United F.C.", "Q502": "Harbour City",
    "Q510": "Exampleland men's national association football team",
    "Q511": "Exampleland women's national under-17 association football team",
    "Q512": "Otherland women's national football team",
    "Q600": "winger", "Q601": "defensive midfielder", "Q602": "goalkeeper", "Q603": "centre-back", "Q604": "forward",
    "Q700": "left-footedness",
}
NO_END = [{"snaktype": "novalue"}]  # Wikidata's way of writing "this has not ended"
UNKNOWN_END = [{"snaktype": "somevalue"}]  # "it ended, nobody recorded when"


def item(entry_id, rank="normal", **qualifiers):
    return {"rank": rank, "qualifiers": qualifiers,
            "mainsnak": {"snaktype": "value", "datavalue": {"type": "wikibase-entityid", "value": {"id": entry_id}}}}


def moment(day, precision=11):
    return {"snaktype": "value", "datavalue": {"type": "time", "value": {"time": f"+{day}T00:00:00Z", "precision": precision}}}


def born(day, precision=11, rank="normal"):
    return {"rank": rank, "mainsnak": moment(day, precision)}


def tall(amount, unit="Q174728"):
    return {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {
        "type": "quantity", "value": {"amount": amount, "unit": f"http://www.wikidata.org/entity/{unit}"}}}}


def text(value):
    return {"snaktype": "value", "datavalue": {"type": "string", "value": value}}


def player(entry_id=SAM, name="Sam Finisher", occupation=FOOTBALLER, **claims):
    return {"id": entry_id, "labels": {"en": {"value": name}}, "descriptions": {"en": {"value": "Examplelandic footballer (born 2001)"}},
            "claims": {"P106": [item(occupation)], **claims},
            "sitelinks": {"enwiki": {"url": "https://en.wikipedia.org/wiki/Sam_Finisher"}}}


@pytest.fixture
def wikidata(monkeypatch):
    """Stand in for Wikidata. Set `.entry` (one player) and `.hits` (search results); `.sent` records every request."""
    class Stub:
        entry, hits, reply, sent = None, [], None, []

    stub = Stub()
    stub.sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        stub.sent.append(request)
        if stub.reply is not None:
            if isinstance(stub.reply, Exception):
                raise stub.reply
            return stub.reply
        params = request.url.params
        if params["action"] == "query":
            return httpx.Response(200, json={"query": {"search": [{"title": entry["id"]} for entry in stub.hits]}})
        ids = params["ids"].split("|")
        if "claims" in params["props"]:
            found = stub.entry if stub.entry else {"id": ids[0], "missing": ""}
            return httpx.Response(200, json={"entities": {found["id"]: found}})
        if params["props"] == "labels":
            return httpx.Response(200, json={"entities": {i: {"labels": {"en": {"value": WORLD[i]}}} for i in ids if i in WORLD}})
        return httpx.Response(200, json={"entities": {entry["id"]: entry for entry in stub.hits}})

    monkeypatch.setattr(lookup_service, "TRANSPORT", httpx.MockTransport(handler))
    return stub


def details(client, entry_id=SAM):
    response = client.get(f"/api/lookup/players/{entry_id}")
    assert response.status_code == 200, response.text
    return response.json()


# ── Searching ────────────────────────────────────────────────────────────────
def test_a_search_asks_only_for_football_players_and_says_who_is_asking(client, wikidata):
    wikidata.hits = [player(), player("Q900002", "Samira Finisher")]
    body = client.get("/api/lookup/players", params={"q": "  finisher  "}).json()
    assert [(hit["id"], hit["name"]) for hit in body["results"]] == [(SAM, "Sam Finisher"), ("Q900002", "Samira Finisher")]
    assert body["results"][0]["description"] == "Examplelandic footballer (born 2001)"
    assert body["results"][0]["url"] == f"https://www.wikidata.org/wiki/{SAM}"

    search = wikidata.sent[0]
    assert search.url.host == "www.wikidata.org" and search.url.path == "/w/api.php"
    assert search.url.params["srsearch"] == f"finisher haswbstatement:P106={FOOTBALLER}"
    assert "https://github.com/" in search.headers["user-agent"]  # Wikidata turns away anonymous programs
    assert len(wikidata.sent) == 2  # one search, one request for the names: nothing else


def test_what_you_type_is_sent_as_a_plain_name(client, wikidata):
    client.get("/api/lookup/players", params={"q": 'O\'Neil-Smith Jr. -haswbstatement:P31=Q5 "x" (y)'})
    assert wikidata.sent[0].url.params["srsearch"] == f"O'Neil-Smith Jr. haswbstatement P31 Q5 x y haswbstatement:P106={FOOTBALLER}"


def test_a_search_that_finds_nobody_says_so_and_asks_nothing_more(client, wikidata):
    assert client.get("/api/lookup/players", params={"q": "nobody at all"}).json()["results"] == []
    assert len(wikidata.sent) == 1
    assert client.get("/api/lookup/players", params={"q": " a "}).status_code == 422  # too short to mean anything
    assert len(wikidata.sent) == 1


# ── Reading one player ───────────────────────────────────────────────────────
def test_plainly_stated_facts_are_turned_into_form_values(client, wikidata):
    wikidata.entry = player(
        P569=[born("2001-04-12")], P2048=[tall("+1.83", unit="Q11573")], P1532=[item("Q21")], P27=[item("Q21"), item("Q22")],
        P413=[item("Q601")], P8006=[item("Q700")], P18=[{"rank": "normal", "mainsnak": text("Sam Finisher (2026) & co.jpg")}],
        P54=[item("Q501", P580=[moment("2019-00-00", 9)], P582=[moment("2022-06-30")]),  # a club he has left
             item("Q500", rank="preferred", P580=[moment("2022-07-01")], P582=NO_END, P1618=[text("9")]),
             item("Q510", P580=[moment("2023-00-00", 9)])])
    body = details(client)
    assert body["fields"] == {
        "full_name": "Sam Finisher", "date_of_birth": "2001-04-12", "height_cm": 183, "preferred_foot": "left",
        "primary_position": "DM", "current_team": "Northside F.C.", "shirt_number": 9, "national_team": "Exampleland",
        "nationality": "Exampleland",
        "photo_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Sam_Finisher_%282026%29_%26_co.jpg?width=400",
    }
    assert body["notes"] == []
    assert body["source"] == {"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/{SAM}",
                              "wikipedia_url": "https://en.wikipedia.org/wiki/Sam_Finisher"}
    assert body["id"] == SAM and len(body["checked_on"]) == 10


def test_what_is_vague_or_missing_stays_empty_and_you_are_told_why(client, wikidata):
    wikidata.entry = player(P569=[born("2001-00-00", precision=9)], P413=[item("Q600")], P2048=[tall("+183"), tall("+185")],
                            P27=[item("Q21"), item("Q22")])
    body = details(client)
    assert body["fields"] == {"full_name": "Sam Finisher"}  # no day of birth, no exact position, no single height
    assert body["notes"] == [
        "Date of birth: Wikidata only gives the year (2001). Left empty, because the day is not known.",
        "Height: Wikidata lists more than one (183 cm, 185 cm). Left empty.",
        'Position: Wikidata says "winger", which does not name one exact position (it could be RW or LW). Choose it yourself.',
        "Nationality: Wikidata lists more than one (Exampleland, Otherland). Left empty.",
    ]


def test_a_statement_marked_as_wrong_is_ignored_and_a_preferred_one_wins(client, wikidata):
    wikidata.entry = player(P569=[born("1999-01-01", rank="deprecated"), born("2001-04-12", rank="preferred"), born("2001-04-13")],
                            P2048=[tall("+999")])  # an impossible height is not a height
    assert details(client)["fields"] == {"full_name": "Sam Finisher", "date_of_birth": "2001-04-12"}


def test_only_exact_wording_becomes_a_position(client, wikidata):
    assert set(lookup_service.EXACT_POSITIONS.values()) <= set(vocabulary.POSITIONS)
    wikidata.entry = player(P413=[item("Q602")])
    assert details(client)["fields"]["primary_position"] == "GK"
    wikidata.entry = player(P413=[item("Q601"), item("Q604")])  # one exact, one broad: the exact one is taken
    assert details(client)["fields"]["primary_position"] == "DM"
    wikidata.entry = player(P413=[item("Q601"), item("Q603")])  # two exact: which is "primary" is your call
    body = details(client)
    assert "primary_position" not in body["fields"]
    assert body["notes"] == ['Position: Wikidata says "defensive midfielder" and "centre-back", which does not name '
                             "one exact position. Choose it yourself."]


def test_a_retired_player_has_no_current_club(client, wikidata):
    wikidata.entry = player(P54=[item("Q500", P582=[moment("2020-06-30")]), item("Q501", P582=UNKNOWN_END),
                                 item("Q511")])  # a youth national side left open by mistake: ignored
    body = details(client)
    assert body["fields"] == {"full_name": "Sam Finisher"} and body["notes"] == []


def test_with_two_current_clubs_the_latest_is_filled_in_and_flagged_or_neither(client, wikidata):
    wikidata.entry = player(P54=[item("Q500", P580=[moment("2022-07-01")]), item("Q501", P580=[moment("2026-01-10")])])
    body = details(client)
    assert body["fields"]["current_team"] == "Riverton United F.C."
    assert body["notes"] == ["Club: Wikidata lists more than one current team (Northside F.C., Riverton United F.C.). "
                             "Filled in the one joined most recently; check it."]

    wikidata.entry = player(P54=[item("Q500"), item("Q501", P580=[moment("2026-01-10")])])  # one has no start date
    body = details(client)
    assert "current_team" not in body["fields"] and "does not say which is the latest. Left empty." in body["notes"][0]

    wikidata.entry = player(P54=[item("Q500"), item("Q501", rank="preferred")])  # Wikidata marks the current one itself
    assert details(client)["fields"]["current_team"] == "Riverton United F.C."


def test_nationality_comes_from_the_national_team_and_a_mismatch_is_flagged(client, wikidata):
    wikidata.entry = player(P1532=[item("Q23")], P27=[item("Q22")], P54=[item("Q510")])
    body = details(client)
    assert body["fields"]["nationality"] == "Exampleland" and body["fields"]["national_team"] == "Exampleland"
    assert body["notes"] == ['Nationality: filled in Exampleland, from the national team. Wikidata\'s "country for sport" '
                             "says Thirdland, which does not match. Check it."]

    wikidata.entry = player(P27=[item("Q22")])  # no national team, no country for sport: the one citizenship
    assert details(client)["fields"]["nationality"] == "Otherland"

    wikidata.entry = player(P54=[item("Q512")])  # a women's senior side keeps the word, so it is not mixed up with the men's
    body = details(client)
    assert body["fields"]["national_team"] == "Otherland Women" and body["fields"]["nationality"] == "Otherland"


def test_a_club_you_already_have_is_recognised_under_its_shorter_name(client, db, wikidata):
    create_player(client, full_name="Lee Wide", current_team="Northside", national_team="Exampleland")
    create_player(client, full_name="Pat Stopper", current_team="Northside City")  # a different club
    wikidata.entry = player(P54=[item("Q500"), item("Q510")])
    body = details(client)
    assert body["fields"]["current_team"] == "Northside" and body["fields"]["national_team"] == "Exampleland"
    assert body["notes"] == ['Club: Wikidata calls it "Northside F.C.". Filled in your existing team "Northside" instead.']


def test_looking_a_player_up_saves_nothing(client, db, wikidata):
    wikidata.entry = player(P54=[item("Q500"), item("Q510")])
    details(client)
    assert client.get("/api/players").json() == [] and client.get("/api/teams").json() == []


# ── When it cannot be done ───────────────────────────────────────────────────
def test_only_a_wikidata_id_for_a_football_player_is_accepted(client, wikidata):
    for bad in ("Q0", "P569", "615", "Q1e3", "Q615|Q42"):
        assert client.get(f"/api/lookup/players/{bad}").status_code == 422
    assert wikidata.sent == []  # nothing was asked of Wikidata

    assert client.get("/api/lookup/players/Q999").status_code == 404  # no such entry
    wikidata.entry = player(occupation="Q36180")  # a writer
    response = client.get(f"/api/lookup/players/{SAM}")
    assert response.status_code == 422 and response.json()["detail"] == "That Wikidata entry is not a football player."


def test_every_kind_of_failure_is_explained_in_plain_words(client, wikidata):
    cases = [
        (httpx.Response(403, text="Please respect our robot policy"), "WEB_LOOKUP_CONTACT"),
        (httpx.Response(429, text="slow down"), "asking for a pause"),
        (httpx.Response(503, text="down"), "status 503"),
        (httpx.Response(200, text="<html>not json</html>"), "could not be read"),
        (httpx.Response(200, json={"error": {"code": "badvalue"}}), "could not be read"),
        (httpx.ConnectError("no route"), "Could not reach Wikidata"),
        (httpx.ReadTimeout("slow"), "took too long"),
    ]
    for reply, expected in cases:
        wikidata.reply = reply
        for address in ("/api/lookup/players?q=finisher", f"/api/lookup/players/{SAM}"):
            response = client.get(address)
            assert response.status_code == 503 and expected in response.json()["detail"], (address, response.text)
