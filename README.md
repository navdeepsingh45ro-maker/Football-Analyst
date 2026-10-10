# Football Analyst & Coach

A personal workspace for studying football: a player database, a match library,
paused-video tactical analysis with drawing tools, a top-down tactical pitch,
searchable observations, pattern reports across matches, and a coaching notebook.

It runs entirely on your own computer. Your data is one folder. Nothing is sent
anywhere unless you switch on the optional AI assistance.

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
   empty is stored as "not known", never as a guess or a zero.
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

## Optional AI

Off by default, and everything else works identically without it. To enable:

```bash
pip install -r backend/requirements-ai.txt
```

Create `backend/.env` (ignored by git):

```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

Restart the server. **Reports → AI assistance** then offers summaries, possible
recurring movements, questions for further analysis, a draft scouting report and
coaching ideas for one player.

What it does and does not do:

- It is shown only that player's stored observations, assessments and stat lines.
- Each statement must cite the records it rests on. The app checks those
  references against what was actually sent, removes any that do not exist, and
  flags statements with none.
- With nothing recorded it is not called at all.
- Output is labelled AI-generated, is never saved by itself, and never touches
  your assessments. You may keep a result in the notebook.
- Using it sends that player's records to the provider and costs money per request.

`AI_MODEL` and `AI_EFFORT` are optional settings; see `backend/config.py`. A
different provider can be added as one file; see `backend/services/ai/__init__.py`.

## What it deliberately does not do

- No login. It listens on `127.0.0.1` only. Do not expose it to a network as it is.
- No automatic tracking or computer vision. You place markers; measurements are
  estimates from where you placed them.
- No downloading, converting or unlocking of video.
- No data service. Every fact is one you entered or imported.

## Known limits

- YouTube timestamps are typed by hand; the app does not read YouTube's player.
- A highlighted space is a rectangle.
- CSV import only adds records; it never updates existing ones.
- The JSON export does not contain frame pictures (the backup does).
- The AI provider code is tested against a stand-in, not against the live service.
