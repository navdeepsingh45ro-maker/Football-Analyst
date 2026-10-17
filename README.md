# Football Analyst & Coach

A personal workspace for studying football: a player database, a match library,
an analysis desk where you watch a match and draw and write about it at the same
time (from a video file, YouTube, or any website), a top-down tactical pitch,
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
2. **Matches** → add a match, then **Link a video**: a video file on this
   computer (`.mp4`, `.mov`, `.webm`), a YouTube link, or a link to any other
   website, such as a broadcaster's page. Add the players to the lineup so they
   are one click away later.
3. **Video analysis** → open the match. The match is on the left, and the moment
   you are working on is on the right, both always in view. Watch; when something
   happens, pause and press **Analyse this moment** (or the `A` key). The time and
   the picture go into the moment on the right, and the video stays where it is.
4. Draw over the picture, rebuild the situation on the pitch, say who it is about
   and what you saw, and **Save observation** (or Cmd + S). You can play, rewind
   and watch on while you do. After saving, a fresh moment is ready beside the
   video; the players and the kind of observation carry over. **Save and keep
   watching** also starts the video again.
5. Find it again from the player's profile (**Observations**, **Diagrams**),
   the match, the **Observations** page, or the **Reports** page.
6. Optional: ask the **Coach** (an AI) about what you have recorded. See
   "Optional AI" below.

### What "Analyse this moment" can do depends on the video

| The video is… | Where it plays | Time read automatically | Picture taken |
|---|---|---|---|
| a file on this computer | in the app | yes | yes, the exact frame |
| a direct link to a video file on the web | in the app, if that site allows it | yes | only if that site permits it |
| YouTube | in YouTube's own player, in the app | yes | with one-click pictures on, or a pasted screenshot |
| any other website, or a video app | in its own window, beside the app | no, you type it | yes, once that window is connected |

Whatever the video, the moment on the right also works by hand: type the time,
and paste (Cmd + V), drop or choose a screenshot to draw on.

**Keys** (when you are not typing in a box): `A` analyse this moment, `K` play or
pause, `J` and `L` back or forward 5 seconds, Cmd + S save. Pressing Analyse again
while the moment on the right has unsaved work asks first: save it, or discard it.

**Drag the bar** between the two sides to give the video or the drawing more room;
the app remembers it. In a narrow window the two sides are stacked, and a video
playing in the app stays at the top, smaller, while you draw below it.

**YouTube.** Press **Analyse this moment** under the player. The app pauses the
video and reads its time through YouTube's own player messages. For the picture,
press **Turn on one-click pictures** once: the browser asks what you want to share;
choose this browser window or the screen it is on. From then on the app keeps the
last couple of seconds of the video area, so Analyse brings in a picture without
YouTube's pause buttons on it, even when you paused with YouTube's own button. Two
small coloured marks beside the video show that sharing is on. It is the same as a
screenshot, taken with your permission; the app never reads the picture out of
YouTube's player, which browsers forbid. Without one-click pictures, take a
screenshot and paste it (on a Mac: Command + Control + Shift + 4, drag across the
video, Command + V).

**Any website, or any app: the match in its own window.** For a link to any other
site (a broadcaster's page, a streaming site) the match plays on that site, in a
window of its own:

1. Press **Open the match link** (or open the match yourself in any browser window,
   or in a video app such as QuickTime Player, which also plays files the browser
   cannot).
2. Press **Connect the match window**, and when the browser asks what to share,
   choose that window (or the whole screen).
3. Put the two windows side by side: drag one to the left edge of the screen and
   the other to the right edge, or use the Window menu, Move & Resize.
4. Watch there. When something happens, pause it there, then press **Analyse this
   moment** in the app.

The app finds the video in the shared window by itself, by its movement (a web page
stands still; a match never does), and follows it if you scroll that page. It keeps
the last couple of seconds of it in memory and notices when you pause. Analyse then
brings in the frame from just before the pause, so the player's pause symbol and
buttons are not on it, and shows a row of the frames from those seconds in case
another one is clearer. If it picks the wrong part of the window, press **Mark the
video by hand** and drag across the video. The app cannot read that player's time,
so type it from the player if you want to find the moment again.

The picture is only ever what you could see on your screen, taken with your
permission. Nothing is recorded or sent anywhere: the last seconds are kept in
memory and replaced, and only the picture you save is stored. A protected stream
(many paid services) shows as black when shared, and a player switched to full
screen leaves the window; make the window bigger instead.

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
│       ├── watch/           watching a match and taking its pictures (the analysis desk)
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
| how the video is found in a shared window, or how a pause is told | `frontend/js/watch/find-video.js` |
| what Analyse this moment does for each kind of video | `frontend/js/watch/viewers.js` |
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

To run them in Safari's engine instead of Chrome's:

```bash
python -m playwright install webkit
FOOTBALL_BROWSER=webkit python -m pytest tests/browser -q
```

One test is stricter than that engine allows: it checks clicks to a fraction of
a pixel and a paused video's time to a millionth of a second, and Safari's
engine clicks on whole pixels and settles a paused video a few milliseconds
later. Its other checks pass there.

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
- No automatic tracking of players or the ball. You place markers; measurements
  are estimates from where you placed them. The only looking at pictures the app
  does is finding where the video is in a shared window and noticing when it
  stands still.
- No downloading, converting, recording or unlocking of video.
- No paid data service, and no copying from sites that forbid it. A player's
  details can be looked up on Wikidata when you ask; every other fact is one you
  entered or imported.

## Known limits

- One-click pictures and the match in its own window depend on the browser being
  able to share a window or the screen with a page. Finding the video, telling a
  pause and choosing the frame are tested with painted stand-ins for that shared
  picture, in Chrome's and Safari's engines, not with a person pressing Allow in a
  real browser.
- Finding the video by its movement needs the match to be playing for a few
  seconds. With the camera standing still and little moving, it can take an
  animated advert beside the video in with it, until the camera moves; you can
  always mark the video by hand.
- The frame offered after a pause is the one from about half a second before the
  picture stood still. If you moved the mouse over the player before pausing, its
  buttons may be on that frame too; choose an earlier one from the row of frames.
- After a click inside YouTube's player, or in the match's own window, the
  keyboard belongs to that player, so the `A` key only works again once you click
  somewhere on the app's page.
- A highlighted space is a rectangle.
- CSV import only adds records; it never updates existing ones.
- The JSON export does not contain frame pictures (the backup does).
- The web lookup reads Wikidata only, in English. It finds professional players;
  where Wikidata is out of date, so is what it fills in.
- The automated tests check the AI code against stand-ins. Google's Gemini has
  also been tried by hand with a real key; Anthropic's has not.
