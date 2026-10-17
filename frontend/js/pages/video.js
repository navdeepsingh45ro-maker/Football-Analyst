// Video analysis: watch the match and analyse it at the same time.
//
// THE THREE WAYS THIS PAGE OPENS
//   video.html                      choose a match
//   video.html?match=2&video=5      the desk for that match's video (add &t=612.5 to start at a moment)
//   video.html?observation=7        change a saved observation, with its match beside it
//
// THE DESK
// Two sides, both always in view:
//
//   ┌ the match ───────────────┐ ┃ ┌ the moment you are working on ┐
//   │ the video, YouTube, or   │ ┃ │ the picture to draw on        │
//   │ the match's own window   │ ┃ │ the pitch                     │
//   │ [Analyse this moment]    │ ┃ │ what you saw         [Save]   │
//   │ recorded in this match   │ ┃ └───────────────────────────────┘
//   └──────────────────────────┘ ┃ <- drag the bar to give either side more room
//
// The video never goes away while you draw. Analyse pauses it (where the app can),
// reads the time and puts the picture into the moment on the right. You can play,
// rewind and watch on while you draw and write. Saving leaves the video where it is,
// or starts it again with "Save and keep watching".
//
// The left side is one of the viewers in watch/viewers.js; the right side is the
// draft in watch/moment-draft.js.
//
// KEYS, when you are not typing in a box
//   A      Analyse this moment          K      play or pause
//   J, L   back or forward 5 seconds    Cmd/Ctrl + S   save the observation (also while typing)

import { api, vocabulary } from '../api.js';
import { observationTitle, openObservation } from '../components/observation-list.js';
import { clear, h, queryParam } from '../dom.js';
import { formatDate } from '../format.js';
import { errorNote, load, mountPage } from '../layout.js';
import { choiceDialog, emptyState, matchDate, scoreline, videoClock } from '../ui.js';
import { createDraft } from '../watch/moment-draft.js';
import { fileViewer, noVideoViewer, windowViewer, youtubeViewer } from '../watch/viewers.js';

const page = mountPage({
  active: 'video.html', title: 'Video analysis', wide: true,
  lede: 'Watch on one side and analyse on the other: pause at a moment, press Analyse, draw and write, save, and carry on.',
});

let draft = null;
window.addEventListener('beforeunload', (event) => {
  if (draft && draft.unsaved()) event.preventDefault();  // the browser then asks before leaving
});

// ── Choosing a match ─────────────────────────────────────────────────────────
function showChooser() {
  return load(page.content, async () => {
    const matches = await api.get('/api/matches');
    if (!matches.length) {
      return emptyState('No matches yet. Add a match and link its video, then come back here.',
        h('a', { class: 'button primary', href: 'matches.html' }, 'Go to matches'));
    }
    return [
      h('p', { class: 'muted' }, 'Choose a match to analyse.'),
      h('ul', { class: 'list' }, matches.map((match) => h('li', { class: 'row spread' },
        h('div', {}, h('a', { class: 'title-link', href: `video.html?match=${match.id}` }, scoreline(match)),
          h('div', { class: 'small muted' }, matchDate(match.match_date),
            match.video_count ? `, ${match.video_count} video${match.video_count === 1 ? '' : 's'} linked` : ', no video linked',
            `, ${match.observation_count} observation${match.observation_count === 1 ? '' : 's'}`)),
        h('a', { class: 'button small', href: `video.html?match=${match.id}` }, 'Open')))),
    ];
  });
}

// ── The bar between the two sides ────────────────────────────────────────────
const SPLIT_LIMITS = [26, 74];  // per cent of the desk the match side may take

/** Drag (or use the arrow keys on) `handle` to share the desk's width between the two sides. Remembered per kind of viewer. */
function splitDesk(desk, handle) {
  let share = 54;
  let key = null;
  let usual = 54;
  const apply = () => {
    desk.style.setProperty('--watch', `${share}%`);
    handle.setAttribute('aria-valuenow', String(Math.round(share)));
  };
  const keep = () => {
    try { localStorage.setItem(key, String(Math.round(share))); } catch { /* private browsing: not remembered */ }
  };
  const setShare = (value) => {
    share = Math.min(SPLIT_LIMITS[1], Math.max(SPLIT_LIMITS[0], value));
    apply();
  };

  handle.addEventListener('pointerdown', (event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    desk.classList.add('is-resizing');  // a video frame under the pointer would otherwise swallow the drag
    const box = desk.getBoundingClientRect();
    // Where on the bar it was grabbed, so that the bar stays under the pointer while it moves.
    const grabbed = event.clientX - (box.left + (box.width * share) / 100);
    const move = (moved) => setShare(((moved.clientX - grabbed - box.left) / box.width) * 100);
    const done = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', done);
      handle.removeEventListener('pointercancel', done);
      desk.classList.remove('is-resizing');
      keep();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', done);
    handle.addEventListener('pointercancel', done);
  });
  handle.addEventListener('keydown', (event) => {
    const step = { ArrowLeft: -2, ArrowRight: 2 }[event.key];
    if (!step && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    if (step) setShare(share + step);
    else setShare(event.key === 'Home' ? SPLIT_LIMITS[0] : SPLIT_LIMITS[1]);
    keep();
  });
  handle.addEventListener('dblclick', () => {
    setShare(usual);
    keep();
  });

  return {
    /** Use the share remembered for this kind of viewer, or `fallback`. */
    use(kind, fallback) {
      key = `football.desk.${kind}`;
      usual = fallback;
      let remembered = null;
      try { remembered = Number(localStorage.getItem(key)); } catch { /* not available */ }
      setShare(remembered >= SPLIT_LIMITS[0] && remembered <= SPLIT_LIMITS[1] ? remembered : fallback);
    },
  };
}

// ── The desk ─────────────────────────────────────────────────────────────────
/**
 * @param match      the match (with videos and appearances), or null for an observation without one
 * @param video      the video to watch, or null
 * @param seekTo     where to start the video, in seconds, or null
 */
function showDesk({ match, video, seekTo, vocab, allPlayers }) {
  // The lineup, with the shirt number worn in THIS match when it was recorded.
  const lineup = match ? match.appearances.map((appearance) => {
    const player = allPlayers.find((candidate) => candidate.id === appearance.player.id) || appearance.player;
    return { ...player, shirt_number: appearance.shirt_number || player.shirt_number };
  }) : [];
  const canPlayHere = Boolean(video && ['html5', 'embed'].includes(video.playback.mode));
  let mode = canPlayHere || !video || video.playback.mode === 'none' ? 'here' : 'window';
  let viewer = null;
  let firstSeek = seekTo;

  const viewerHost = h('div', {});
  const below = h('div', { class: 'stack watch-below' });
  const momentsBox = h('div', {});
  const viewerSection = h('section', { class: 'desk-viewer stage', 'aria-label': 'The match' }, viewerHost, below);
  const handle = h('div', {
    class: 'desk-split', role: 'separator', tabindex: 0, 'aria-orientation': 'vertical',
    'aria-label': 'Give the video or the drawing more room', 'aria-valuemin': SPLIT_LIMITS[0], 'aria-valuemax': SPLIT_LIMITS[1],
    title: 'Drag to give the video or the drawing more room. Double-click to even it out again.',
  }, h('span', {}));
  // Shown at the bottom of the window when the real Analyse button has scrolled out of view.
  const floating = h('button', { type: 'button', class: 'button primary analyse-float', onclick: () => analyse(), title: 'Keyboard: A' },
    'Analyse this moment');
  floating.hidden = true;

  draft = createDraft({
    vocab, allPlayers, suggested: lineup, match,
    videoId: () => (video ? video.id : null),
    canResume: () => Boolean(viewer && viewer.canResume),
    onSaved: (_saved, { resume }) => {
      refreshMoments();
      if (resume && viewer) viewer.play();
      revealDraft();  // the fresh moment starts at the top, where the picture will go
    },
  });

  const desk = h('div', { class: 'desk' },
    h('div', { class: 'desk-watch' }, viewerSection,
      h('section', { class: 'desk-moments stage', 'aria-label': 'Recorded in this match' },
        h('h3', {}, match ? 'Recorded in this match' : 'This observation'), momentsBox)),
    handle, draft.element);
  const split = splitDesk(desk, handle);
  clear(page.content).append(desk, floating);

  // ── The left side ──────────────────────────────────────────────────────────
  function buildViewer() {
    const options = { seekTo: firstSeek, onAnalyse: analyse };
    firstSeek = null;
    if (mode === 'window') return windowViewer(video, options);
    if (canPlayHere && video.playback.mode === 'html5') return fileViewer(video, options);
    if (canPlayHere) return youtubeViewer(video, options);
    return noVideoViewer({ video, matchId: match ? match.id : null, onUseWindow: () => switchTo('window') });
  }

  function showViewer() {
    if (viewer) viewer.destroy();
    viewer = buildViewer();
    clear(viewerHost).append(viewer.element);
    viewerSection.classList.toggle('plays-here', mode === 'here' && canPlayHere);
    split.use(mode === 'window' ? 'window' : 'here', mode === 'window' ? 38 : 54);

    const keys = mode === 'window'
      ? 'Keys here: A analyse, Cmd/Ctrl + S save. Pause the match in its own window.'
      : 'Keys: A analyse, K play or pause, J and L back or forward 5 s, Cmd/Ctrl + S save.';
    clear(below).append(...[
      mode === 'here' && canPlayHere ? h('p', { class: 'small muted watch-explain' }, video.playback.explanation) : null,
      h('p', { class: 'small muted keys' }, keys),
      canPlayHere
        ? h('div', { class: 'row' }, h('button', { type: 'button', class: 'button small quiet', onclick: () => switchTo(mode === 'window' ? 'here' : 'window') },
          mode === 'window' ? 'Watch it here instead' : 'Watch it in another window instead'))
        : null,
    ].filter(Boolean));
    draft.refreshButtons();
    refreshMoments();
    watchForBar();
  }

  function switchTo(next) {
    mode = next;
    showViewer();
  }

  // The floating button: only when the viewer's own Analyse button is out of sight.
  let barWatch = null;
  function watchForBar() {
    if (barWatch) barWatch.disconnect();
    floating.hidden = true;
    const bar = viewerHost.querySelector('.watch-bar');
    if (!bar || !('IntersectionObserver' in window)) return;
    barWatch = new IntersectionObserver(([entry]) => { floating.hidden = entry.isIntersecting || bar.hidden; });
    barWatch.observe(bar);
  }

  // ── Recorded in this match ─────────────────────────────────────────────────
  /** A saved moment's time can be jumped to when it belongs to the video shown here. */
  const jumpable = (observation) => viewer && viewer.canJump && observation.video_time_seconds !== null
    && (observation.video_reference_id === null || (video && observation.video_reference_id === video.id));

  function refreshMoments() {
    if (!match) {
      clear(momentsBox).append(h('p', { class: 'muted small' }, 'Not tied to a match.'));
      return null;
    }
    return load(momentsBox, async () => {
      const result = await api.get('/api/observations', { match_id: match.id, limit: 500 });
      if (!result.items.length) return h('p', { class: 'muted small' }, 'Nothing recorded for this match yet.');
      return h('ul', { class: 'list' }, result.items.map((observation) => h('li', { class: 'moment' },
        h('div', { class: 'clocks' }, videoClock(observation.video_time_seconds, jumpable(observation)
          ? { onclick: () => viewer.jumpTo(observation.video_time_seconds) } : {})),
        h('div', { class: 'what' },
          h('a', {
            href: `observations.html?open=${observation.id}`,
            onclick: (event) => {
              event.preventDefault();
              openObservation(observation.id, { onChanged: refreshMoments, onEditDrawing: editHere });
            },
          }, h('strong', {}, observationTitle(observation))),
          h('div', { class: 'small muted' }, observation.players.map((entry) => entry.full_name).join(', ') || 'No player')))));
    });
  }

  // ── Analyse, and work that would be lost ───────────────────────────────────
  /**
   * There is unsaved work in the moment on the right: save it, drop it, or keep working on it?
   * Resolves to true when the way is clear. With `any`, notes and a pitch drawing made without
   * pressing Analyse count too.
   */
  async function makeRoom({ any = false } = {}) {
    if (any ? !draft.unsaved() : !draft.hasWork()) return true;
    const choice = await choiceDialog({
      title: 'Keep the moment you are working on?',
      message: `You have not saved ${draft.workNote()} yet.`,
      choices: [{ value: 'discard', label: 'Discard it', danger: true }, { value: 'save', label: 'Save it first', primary: true }],
      cancelLabel: 'Keep working on it',
    });
    if (choice === 'save') return Boolean(await draft.save());
    return choice === 'discard';
  }

  /** Put the moment's heading in view, below the video when the video stays at the top of a narrow window. */
  function revealDraft() {
    const sticky = getComputedStyle(viewerSection).position === 'sticky' && getComputedStyle(desk).display === 'flex';
    const covered = sticky ? viewerSection.getBoundingClientRect().bottom : 0;
    const top = draft.element.getBoundingClientRect().top;
    if (top < covered || top > window.innerHeight * 0.75) window.scrollBy(0, top - covered - 8);
  }

  /** Forget the pictures of a moment that is not used after all. */
  const forget = (moment) => {
    for (const picture of moment.pictures || []) {
      URL.revokeObjectURL(picture.url);
      URL.revokeObjectURL(picture.thumb);
    }
  };

  let analysing = false;
  async function analyse() {
    if (analysing || !viewer) return;
    analysing = true;
    try {
      const moment = await viewer.analyse();  // the picture is taken now, before any question is asked
      if (!moment) return;
      if (draft.hasWork()) {
        if (!await makeRoom()) {
          forget(moment);
          return;
        }
        draft.loadMoment(moment, { fresh: true });
      } else {
        draft.loadMoment(moment);  // a pitch drawing or notes made while watching stay with it
      }
      revealDraft();
    } finally {
      analysing = false;
    }
  }

  /** "Edit drawing" from the list: change that observation on the right, without leaving the video. */
  async function editHere(observation, snapshotId) {
    if (!await makeRoom({ any: true })) return;
    draft.loadExisting(observation, snapshotId);
    revealDraft();
  }

  // ── Keys ───────────────────────────────────────────────────────────────────
  document.addEventListener('keydown', (event) => {
    if (document.querySelector('dialog[open]')) return;
    const key = event.key.toLowerCase();
    if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && key === 's') {
      event.preventDefault();  // instead of the browser's "save this page"
      draft.save();
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) || active.isContentEditable)) return;
    const action = { a: analyse, k: () => viewer.togglePlay(), j: () => viewer.skip(-5), l: () => viewer.skip(5) }[key];
    if (action) {
      event.preventDefault();
      action();
    }
  });

  showViewer();
  return { editHere };
}

// ── Opening the page ─────────────────────────────────────────────────────────
function headFor(match) {
  page.setTitle(match.title);
  clear(page.heading).append(scoreline(match));
  page.setLede([formatDate(match.match_date), match.competition && match.competition.name].filter(Boolean).join(', '));
  clear(page.before).append(h('a', { class: 'back-link', href: `match.html?id=${match.id}` }, 'Match details'));
}

async function showMatch(matchId, wantedVideoId, seekTo) {
  const [match, vocab, allPlayers] = await Promise.all([
    api.get(`/api/matches/${matchId}`), vocabulary(), api.get('/api/players'),
  ]);
  const video = match.videos.find((candidate) => candidate.id === wantedVideoId) || match.videos[0] || null;
  headFor(match);
  showDesk({ match, video, seekTo, vocab, allPlayers });
  if (match.videos.length > 1) {
    page.actions.append(h('select', {
      'aria-label': 'Video',
      onchange: (event) => { window.location.href = `video.html?match=${match.id}&video=${event.target.value}`; },
    }, match.videos.map((candidate) => h('option', { value: candidate.id, selected: video && candidate.id === video.id }, candidate.label))));
  }
}

/** A saved observation, opened from elsewhere: change it on the right, with its video on the left. */
async function showExisting(observationId, wantedSnapshotId) {
  const [observation, vocab, allPlayers] = await Promise.all([
    api.get(`/api/observations/${observationId}`), vocabulary(), api.get('/api/players'),
  ]);
  const match = observation.match ? await api.get(`/api/matches/${observation.match.id}`) : null;
  const ownVideo = match ? match.videos.find((candidate) => candidate.id === observation.video_reference_id) : null;
  const video = ownVideo || (match ? match.videos[0] || null : null);
  if (match) headFor(match);
  else {
    page.setTitle(`Observation #${observation.id}`);
    page.heading.textContent = `Observation #${observation.id}`;
    page.setLede(null);
  }
  const backTo = document.referrer && new URL(document.referrer).origin === window.location.origin
    ? document.referrer : 'observations.html';
  showDesk({ match, video, seekTo: ownVideo ? observation.video_time_seconds : null, vocab, allPlayers });
  draft.loadExisting(observation, wantedSnapshotId, { returnTo: () => { window.location.href = backTo; } });
}

async function start() {
  const observationId = Number(queryParam('observation'));
  const matchId = Number(queryParam('match'));
  try {
    if (observationId) await showExisting(observationId, Number(queryParam('snapshot')) || null);
    else if (matchId) {
      const seek = queryParam('t');
      await showMatch(matchId, Number(queryParam('video')), seek === null ? null : Number(seek));
    } else await showChooser();
  } catch (error) {
    clear(page.content).append(errorNote(error, start));
  }
}

start();
