# How Football Analyst & Coach fits together

This is the map. The code files carry the detail in their opening comments; read
the file named in each section when you want more.

## 1. The shape of the app

```
 browser                                   one Python process
┌──────────────────────────┐   HTTP/JSON  ┌─────────────────────────────────────────┐
│ frontend/*.html          │─────────────▶│ routes/      read the request, shape the │
│ js/pages/*.js            │              │              answer                      │
│   uses api.js to call ───┼──────────────│ schemas/     check what came in          │
│   the API                │◀─────────────│ services/    the rules and calculations  │
│ js/editor/  drawing      │              │ models/      the database tables         │
└──────────────────────────┘              └───────────────┬─────────────────────────┘
                                                          │ SQLAlchemy
                                              backend/data/football.db   (SQLite)
                                              backend/data/media/frames/ (pictures)
```

The same process serves the pages (`frontend/`) and the API (`/api/...`). That
is why there is no CORS setup, and why a local video counts as "same origin" so
its frames may be captured.

**One request, start to finish** (saving an observation with a diagram):

1. `js/pages/video.js` collects the form and the shapes and calls
   `api.post('/api/observations', body)`.
2. FastAPI checks `body` against `ObservationCreate` in
   `schemas/observation_schema.py`. A wrong value stops here with a 422 that
   names the field.
3. `routes/observation_routes.py` hands it to
   `observation_service.create_observation`.
4. The service writes the observation, its player links, the diagram, the
   shapes and the frame picture inside `saving_files(db)`: one commit, or a
   rollback that also deletes the picture.
5. The route returns the saved record as JSON; the page shows a confirmation
   and goes back to the paused video.

## 2. The data model

```
 Team ◀──────────────┐                      Competition   Season
   ▲                 │                           ▲           ▲
   │ current/national│ home/away                 └─────┬─────┘
 Player              │                                 │
   │ ▲ ▲ ▲         Match ─────────────────────────────┘
   │ │ │ │           │ │ │
   │ │ │ └──── MatchAppearance      (who played, for which side, on/off minutes)
   │ │ │             │ └──── VideoReference          (a path or a link, never a copy)
   │ │ └────── PlayerStatistic      (measured numbers; a match line or a season line)
   │ └──────── ScoutingAssessment ──< AssessmentRating   (dated opinions, 1–5 ratings)
   │
   └──< ObservationPlayer >── Observation ──────────── Match
                                  │  │
                                  │  └──< TacticalSnapshot ──< Annotation ──▶ Player (optional)
                                  │
              CoachingNote >──────┤                       (link tables keep the "why")
                  │               │
              TrainingIdea >──────┘
```

`──<` means "has many". Files: `backend/models/`.

**Observation is the centre.** Everything analytical hangs off it: who, which
match, when in the video, what kind of thing, your reading of it, and the
diagram(s) drawn for it.

**What happens on delete** is decided column by column and summarised in
`services/deletion_service.py`:

- *Parts go with their whole* (`ON DELETE CASCADE`): lineup entries and video
  links with a match; shapes with a diagram; diagrams with an observation.
- *Cross-references block deletion* (`RESTRICT`): a team that still has
  matches, a player who still has assessments. The API then answers 409 with
  counts, and deletes only after an explicit `cascade=true`.
- *Soft links are cleared* (`SET NULL`): a marker keeps its place if its player
  is deleted; an observation keeps its timestamp if its video link is removed.

SQLite ignores foreign keys unless each connection switches them on;
`database.py` does that.

## 3. Coordinates (the part most worth understanding)

Four spaces are involved in drawing. They are not interchangeable.

| Space | Units | Stored? |
|---|---|---|
| Screen | CSS pixels (`event.clientX`) | never |
| View | the SVG's `viewBox`: frame pixels, or metres | no |
| Frame | fractions 0–1 of the picture; (0,0) top-left | **yes**, layer `frame` |
| Pitch | metres; x from own goal line, y from the left touchline | **yes**, layer `pitch` |

A click travels `screen → view → stored`; drawing goes the other way and the
browser does the last step. `frontend/js/editor/coords.js` holds both
conversions and is tested at seven display sizes and six frame resolutions.

Why a drawing stays aligned when the window is resized: the picture is drawn
*inside the same SVG* as the shapes, in the same view units, and the wrapper is
given the picture's exact aspect ratio. The browser scales them as one.

A frame also records the picture's original pixel size (`frame_width`,
`frame_height`). The stored picture may be scaled down to save space; the
fractions still point at the same spots.

The pitch is always drawn with the studied team attacking left to right. That
convention is what lets "final third" or "left half-space" mean the same thing
across every diagram, and so be counted in reports.

**What may be measured.** On the pitch, distances and angles are computed from
metres and labelled as estimates, since you placed the markers by eye. On a
frame, no distance is ever reported (a camera view is distorted by perspective)
and an angle is labelled as the angle *on the picture*. A movement arrow is a
direction of travel, never where a player was facing.

Geometry exists twice, on purpose: `services/geometry.py` for reports and
`js/editor/geometry.js` for live read-outs while dragging. Both are tested
against the same worked examples in `test_fixtures/geometry_cases.json`, so if
they ever disagree a test fails.

## 4. The editor

```
 model.js        the diagram: a list of shapes + undo/redo. No screen, no network.
 coords.js       the coordinate spaces and conversions.            (pure)
 geometry.js     distances and angles.                             (pure)
 measure.js      turns shapes into read-outs in words.             (pure)
 render.js       draws one shape as SVG. Used by the editor, the read-only
                 diagrams, the toolbar icons and the legend.
 pitch.js        draws the pitch markings.
 surface.js      one SVG showing one layer; turns a pointer event into a stored point.
 controller.js   what a click, drag or key DOES.
 panels.js       toolbar, selected-shape panel, measurements, legend.
 workspace.js    wires the above into one unit a page can drop in.
```

The four files marked *pure* have no browser dependencies, which is why
`npm test` can check them with nothing but Node.

Change flows one way: the controller calls a method on the model; the model
notifies; surfaces redraw and panels refresh from the model. Nothing edits the
SVG directly, so undo and redo cover every change.

## 5. Decisions, and the reasons

**FastAPI + SQLAlchemy + Alembic + SQLite, plain HTML/JS frontend.** The folder
was empty when this was built, so the stack follows the project you already
maintain (Budget Buddy): the same layout (`models/ routes/ schemas/ services/
tests/`), the same migration runner idea, the same no-framework frontend.
SQLite is one file, needs no server and is ample for one person's data.

**No frontend build step and no JS dependencies.** The browser loads the
modules as written. What you read is what runs, and it works offline.

**Edits are full `PUT`s with the creation schema.** One set of validation rules
per record; an empty form field unambiguously means "unknown". The cost is that
a client must send the whole record, which the forms always do.

**Suggestion lists, not enums.** Categories, movements and outcomes are free
text with suggestions (`vocabulary.py`). Text matching a suggestion is stored in
the suggestion's spelling so it counts consistently; your own wording is kept.

**Assessments are rows, not columns on the player.** That is the whole history
mechanism: new opinion, new row.

**Stat lines are wide, with a required source.** One row per player per match,
or per season + competition + team, so nothing is counted twice. Every number
is nullable and null is never read as zero.

**Shapes are rows, not one JSON blob.** A marker can then point at a real
player with a real foreign key, and reports can find the recorded movement.

**Reports are plain application logic over the same filter as the search.**
`ObservationFilters` is shared, so a figure and the list behind it cannot
disagree. Every group carries its observation ids.

**AI is isolated and optional.** Nothing imports `services/ai` except the AI
route. One file per provider talks to it (`google_provider.py`,
`anthropic_provider.py`). The grounding and reference-checking rules live
outside them, in `services/ai_service.py`, and are tested with a stand-in.

**The web lookup fills a form, never the database.** `services/lookup_service.py`
asks Wikidata about a player and returns values for the player form plus notes on
what it left empty. The page (`js/components/player-lookup.js`) puts them into
empty boxes only. Saving is the form's ordinary save, through the same validation
as typed values, so a looked-up player is stored exactly like any other. Vague or
contradictory facts are left out rather than guessed.

**The coach keeps two kinds of knowledge apart.** `ask_coach()` answers a free
question from the Coach page (`js/pages/coach.js`). A statement about your
players or matches must cite records that were really sent, and is flagged if
it does not; general coaching advice is a separate, labelled kind. The
conversation lives in the page: each request carries the last few turns, and
the server stores nothing.

**Security posture: a local, single-user tool.** No accounts. The server binds
to localhost and rejects other `Host` headers. A strict Content-Security-Policy
allows scripts and styles only from the app itself, and pages build their HTML
from text nodes, so imported or pasted text can never run as code. Only files
registered as match videos, with a video extension, are ever streamed.

## 6. Where each acceptance test lives

| Test | What it proves | File |
|---|---|---|
| A | records survive a real restart | `tests/test_restart_persistence.py` |
| B | a match and its players are linked correctly | `tests/test_matches.py` |
| C | several observations, same player and match, stay independent | `tests/test_observations.py` |
| D | observations come back from the profile with times and notes | `tests/test_observations.py` |
| E | a diagram is saved and rebuilt exactly | `tests/test_snapshots.py` |
| F | shapes stay aligned when the display is resized | `frontend/tests/coords.test.js`, `tests/browser/test_analysis_workflow.py` |
| G | angles and distances, including degenerate input | `tests/test_geometry.py`, `frontend/tests/geometry.test.js` |
| H | history survives biography changes | `tests/test_statistics_and_assessments.py`, `tests/test_observations.py` |
| I | filters and summaries return the expected records | `tests/test_observations.py`, `tests/test_analytics.py` |
| J | export, validate, re-import | `tests/test_transfer_and_backup.py` |
| K | invalid input, unplayable video, no AI, failed save | `tests/test_snapshots.py`, `tests/test_ai.py`, `tests/browser/` |
| L | the whole workflow in a browser | `tests/browser/test_analysis_workflow.py` |
