# Football Analyst & Coach

A personal workspace for studying football: a player database, a match library,
paused-video tactical analysis with drawing tools, a top-down tactical pitch,
searchable observations, pattern reports across matches, and a coaching notebook.

It runs entirely on your own computer. Your data is one folder. Nothing is sent
anywhere unless you ask for it: looking a player up on the web sends the name you
typed to Wikidata, and the optional AI coach sends the records you ask it about.

## Start it

```bash
cd "Football_Analyst"
python3 -m venv .venv                      # once
source .venv/bin/activate
pip install -r backend/requirements.txt    # once

cd backend
uvicorn main:app --reload
```

Then open **http://127.0.0.1:8000**. One process serves both the pages and the
API. The first start creates `backend/data/` with an empty database.

`--reload` restarts the server when you edit a Python file. Edits to files in
`frontend/` only need a browser refresh; there is no build step.

## The workflow it is built around

1. **Players** → add a player. Only the name is required; anything you leave
   empty is stored as "not known", never as a guess or a zero. To save typing,
   **Fill in from the web** at the top of the form looks the player up and fills
   in the empty boxes for you to check (see "Filling in a player from the web").
2. **Matches** → add a match, then **Link a video**. A video file on this
   computer (`.mp4`, `.mov`, `.webm`) plays inside the app. Add the players to
   the lineup so they are one click away later.
3. **Video analysis** → open the match and watch. Pause anywhere and press
   **Analyse** (or the `A` key). The app pauses the video, records the exact
   time, and captures the frame.
4. Draw over the frame, rebuild the situation on the pitch beside it, say who
   it is about and what you saw, and **Save observation**. You are returned to
   the video, still paused at the same moment. Press play and carry on.
5. Find it again from the player's profile (**Observations**, **Diagrams**),
   the match, the **Observations** page, or the **Reports** page.
6. Optional: ask the **Coach** (an AI) about what you have recorded. See
   "Optional AI" below.

### What "Analyse" can do depends on the video

| The video is… | Plays in the app | Time read automatically | Frame captured |
|---|---|---|---|
| a file on this computer | yes | yes | yes |
| a direct link to a video file on the web | if that site allows it | yes | only if that site permits it |
| YouTube | in YouTube's own player | no, you type it | no |
| any other link | no, opens in a new tab | no, you type it | no |

For everything in the "no" columns there is a manual path: **Analyse a moment
by hand**, type the timestamp, and paste, drop or choose a screenshot to draw
on. The app never bypasses a site's restrictions; a browser deliberately refuses
to let a page copy pixels from a video hosted elsewhere, and that is respected.

## Where things are

```
Football_Analyst/
├── backend/                 Python: the API and all the rules
│   ├── main.py              creates the app, plugs in the routes, serves the pages
│   ├── config.py            settings and file locations
│   ├── database.py          the SQLite connection
│   ├── vocabulary.py        the suggestion lists (positions, categories, movements…)
│   ├── models/              the database tables              ← start reading here
│   ├── schemas/             what the API accepts and returns (validation)
│   ├── services/            the rules and calculations
│   ├── routes/              the web addresses, thin wrappers around services
│   ├── alembic/             database migrations
│   ├── scripts/             restore_backup.py
│   ├── tests/               automated tests (tests/browser/ drives a real browser)
│   └── data/                YOUR DATA (created on first start, ignored by git)
├── frontend/                HTML, CSS and JavaScript, loaded directly by the browser
│   ├── *.html               one small file per page
│   ├── css/app.css          all styling; design tokens at the top
│   └── js/
│       ├── pages/           one script per page
│       ├── components/      forms and lists shared by several pages
│       ├── editor/          the drawing tools                ← the heart of the app
│       ├── api.js  dom.js  forms.js  ui.js  layout.js  format.js  charts.js
│       └── …
├── test_fixtures/           worked geometry examples shared by Python and JavaScript tests
└── docs/ARCHITECTURE.md     how it fits together, and why
```

### If you want to change…

| …this | look here |
|---|---|
| a suggestion list (positions, movement types, outcomes) | `backend/vocabulary.py` |
| what is stored about a player / match / observation | `backend/models/`, then add a migration (see `migrations_runner.py`) |
| a validation rule | `backend/schemas/` |
| what gets deleted along with what | `backend/services/deletion_service.py` |
| how a shape is drawn, or its colours | `frontend/js/editor/render.js` |
| what a click or key press does in the editor | `frontend/js/editor/controller.js` |
| a distance or angle calculation | `backend/services/geometry.py` **and** `frontend/js/editor/geometry.js`, plus the shared examples in `test_fixtures/` |
| a report | `backend/services/analytics_service.py` |
| what is read when a player is looked up on the web | `backend/services/lookup_service.py` |
| colours, fonts, spacing | the tokens at the top of `frontend/css/app.css` |

## Ideas worth understanding first

**Unknown is not zero.** An empty field becomes `NULL` in the database and is
shown as a dash. A striker with no recorded shots has *unknown* shots. Totals,
per-90 figures and comparisons all keep that distinction.

**Three kinds of time.** A *video time* (position in the file, `35:10`), a
*match clock* (the scoreboard, `32:14`), and *calendar moments* (when you saved
something, stored in UTC). They are separate fields and are never mixed.

**Four coordinate systems.** Screen pixels (never stored) → the drawing's own
view units → *frame coordinates* stored as fractions 0–1 of the picture →
*pitch coordinates* stored in metres. Because only the last two are saved, a
diagram lines up again at any window size. Read the top of
`frontend/js/editor/coords.js`.

**Opinions have dates.** A scouting assessment is a dated record. Changing your
mind means adding a new one; the old ones stay so you can compare.

**Saving is all or nothing.** An observation, its players, its diagram, every
shape and the frame picture are saved together or not at all.

**Reports count; they do not judge.** Every figure is a count of your own
records, links to exactly those records, and comes with its limits in plain
words. A drawn arrow is your reading of the play, not tracking data.

## Tests

```bash
cd backend
python -m pytest tests -q                  # everything (browser tests run if Playwright is installed)
python -m pytest tests --ignore=tests/browser -q    # without a browser

cd ../frontend
npm test                                   # the drawing logic; needs only Node, installs nothing
```

The browser tests are optional extras:

```bash
pip install -r backend/requirements-dev.txt
python -m playwright install chromium
python -m pytest tests/browser -q --headed-browser   # --headed-browser lets you watch
```

Tests always use a throwaway data folder. They cannot touch `backend/data/`.

## Backups

**Settings → Make a backup now** writes one zip (database + frame pictures) into
`backend/data/backups/` and immediately reopens it to check it: file checksums,
SQLite's integrity check, and row counts compared against the database in use.
Download copies and keep them somewhere other than this computer.

To put one back, stop the server, then:

```bash
cd backend
python scripts/restore_backup.py data/backups/football-backup-YYYYMMDD-HHMMSS.zip
```

The data being replaced is moved into `data/replaced-<time>/`, not deleted.
Before any future database upgrade the app also saves its own
`pre-migration-<time>.db` copy automatically.

## Import and export

- **Settings → Export**: everything as one JSON file, or players, matches,
  statistics and observations as CSV. The Observations page exports whatever is
  currently filtered. A diagram can be saved as a PNG or as structured data.
- **Settings → Import**: CSV rows are checked with the same rules as the forms.
  If any row is wrong, nothing is saved and you get the line, the column and
  the reason. "Check the file" validates without saving.

## Filling in a player from the web

In the player form, type a name under **Fill in from the web** and press
**Search the web**. Choose the right person from the list, and the form's empty
boxes are filled with what was found: name, date of birth, nationality, height,
preferred foot, position, club, national team, shirt number and a photo link.

- The source is [Wikidata](https://www.wikidata.org), Wikipedia's database of
  facts. It is free, open and needs no key. Sites that forbid copying, such as
  Transfermarkt, are not used.
- Nothing is saved until you press the form's own button. Check the details
  first: web data can be wrong or out of date.
- Only empty boxes are filled. What you typed is kept, and you are shown where
  the web disagrees with it.
- A fact is filled in only when Wikidata states it plainly. A date of birth
  given only as a year, a position such as "forward", or two different heights
  are left empty, and the form says why.
- A line naming the source is added to the player's notes.
- Only the name you type is sent, together with a line saying which program is
  asking. Wikidata refuses programs that do not identify themselves, so that
  line carries a contact link; set your own with `WEB_LOOKUP_CONTACT` in
  `backend/.env` (see `backend/config.py`).

Players who are not on Wikidata, which includes most amateur and youth players,
are simply not found; type their details as before.

## Optional AI

Off by default, and everything else works identically without it. Two providers
are built in; pick one.

**Google (Gemini)**, which has a free tier. Get a key at
https://aistudio.google.com/apikey, then create `backend/.env` (ignored by git):

```
AI_PROVIDER=google
GEMINI_API_KEY=your-key-here
```

Nothing needs installing. The default model is `gemini-3.8-flash`. On Google's
free tier there is a limit on requests per minute and per day, and Google may
use what you send to improve its products; on the paid tier it does not. Keep
that in mind before sending notes about real people.

**Anthropic (Claude)**, which is paid per request and is not covered by a Claude
Pro or Max subscription:

```bash
pip install -r backend/requirements-ai.txt
```

```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

Restart the server. The **Coach** page then answers your own questions: about one
player, one match, everything you have recorded, or coaching in general ("give me
a drill for pressing triggers"). Player and match pages have an **Ask the coach**
button that opens it with that player or match already chosen.

What it does and does not do:

- It is shown only your stored records for what you chose to ask about: one
  player's profile, observations, assessments and stat lines; or one match's
  observations; or, with nothing chosen, every player's profile, the most recent
  400 observations and the most recent 100 assessments.
- An answer keeps two kinds of knowledge apart. Anything about your players or
  matches must cite the records it rests on; the app checks those references
  against what was actually sent, removes any that do not exist, and flags a
  statement left with none. General coaching advice is labelled as such.
- Earlier questions and answers in the same conversation are sent along, so a
  follow-up makes sense. The conversation is not stored: it is gone when you
  leave the page.
- Output is labelled AI-generated, is never saved by itself, and never touches
  your assessments. You may keep an answer in the notebook.
- Using it sends those records to the provider. Anthropic charges per request;
  Google charges only if you turn on billing for the key.

`AI_MODEL` is an optional setting (`AI_EFFORT` too, for Anthropic only); see
`backend/config.py`. Another provider can be added as one file; see
`backend/services/ai/__init__.py`.

## What it deliberately does not do

- No login. It listens on `127.0.0.1` only. Do not expose it to a network as it is.
- No automatic tracking or computer vision. You place markers; measurements are
  estimates from where you placed them.
- No downloading, converting or unlocking of video.
- No paid data service, and no copying from sites that forbid it. A player's
  details can be looked up on Wikidata when you ask; every other fact is one you
  entered or imported.

## Known limits

- YouTube timestamps are typed by hand; the app does not read YouTube's player.
- A highlighted space is a rectangle.
- CSV import only adds records; it never updates existing ones.
- The JSON export does not contain frame pictures (the backup does).
- The web lookup reads Wikidata only, in English. It finds professional players;
  where Wikidata is out of date, so is what it fills in.
- The automated tests check the AI code against stand-ins. Google's Gemini has
  also been tried by hand with a real key; Anthropic's has not.
