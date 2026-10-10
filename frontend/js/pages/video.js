// Video analysis: watch, pause, analyse, annotate, save, continue watching.
//
// THE THREE WAYS THIS PAGE OPENS
//   video.html                      choose a match
//   video.html?match=2&video=5      watch that match's video (add &t=612.5 to start at a moment)
//   video.html?observation=7        reopen a saved observation to edit its drawing
//
// HOW THE TIMESTAMP IS HANDLED
// When you press Analyse the video is paused and its position is read ONCE into
// the form's "Video time" field. From then on that field is the only source of
// the timestamp. Nothing reads the video again, so letting the video play on, or
// seeking somewhere else, can never change the time of an observation by itself.
//
// WHAT "ANALYSE" CAN AND CANNOT DO, BY KIND OF VIDEO (see backend/services/video_service.py)
//   a video file on this computer   pause, read the time, capture the frame: all automatic
//   a video file on the web         pause and read the time; the frame only if that website allows it
//   YouTube / any other link        nothing automatic. You type the time and add a screenshot.

import { api, ApiError, vocabulary } from '../api.js';
import { observationFields, observationToForm } from '../components/observation-form.js';
import { observationTitle, openObservation } from '../components/observation-list.js';
import { playerPicker } from '../components/player-picker.js';
import { clear, h, queryParam } from '../dom.js';
import { FrameCaptureError, captureVideoFrame, frameFromImageFile, imageFromTransfer } from '../editor/frame-capture.js';
import { createWorkspace } from '../editor/workspace.js';
import { buildForm } from '../forms.js';
import { formatClock, formatDate } from '../format.js';
import { errorNote, load, mountPage } from '../layout.js';
import { confirmDialog, emptyState, matchDate, scoreline, toast, videoClock } from '../ui.js';

const PITCH = { length: 105, width: 68 };

const page = mountPage({
  active: 'video.html', title: 'Video analysis', wide: true,
  lede: 'Watch, pause at an interesting moment, press Analyse, draw what you see, save, and carry on watching.',
});

let unsavedDrawing = false;
window.addEventListener('beforeunload', (event) => {
  if (unsavedDrawing) event.preventDefault();  // the browser then asks before leaving
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
            match.video_count ? `, ${match.video_count} video${match.video_count === 1 ? '' : 's'} linked` : ', no video linked (manual workspace)',
            `, ${match.observation_count} observation${match.observation_count === 1 ? '' : 's'}`)),
        h('a', { class: 'button small', href: `video.html?match=${match.id}` }, 'Open')))),
    ];
  });
}

// ── The analysis workspace ───────────────────────────────────────────────────
/**
 * Build the analysis view: drawing surfaces on the left, the observation form on the right.
 *
 * @param options.frame     { dataUrl | url, width, height, source } or null when there is no picture yet
 * @param options.frameNote why there is no picture (e.g. capture was blocked), shown to the user
 * @param options.time      the captured video position in seconds, or null to type it
 * @param options.existing  an observation being edited (with `snapshot`, its diagram, or null)
 * @param options.onDone    called with the saved observation, or null when cancelled
 */
function buildAnalysis({ vocab, allPlayers, suggested, match, videoId, time, frame, frameNote, existing, snapshot, onDone }) {
  let workspace = null;
  let currentFrame = frame;
  const surfaceHost = h('div', {});

  // Players offered for linking a marker: the ones chosen for this observation first.
  const picker = playerPicker({
    all: allPlayers, suggested,
    selected: existing ? existing.players.map((player) => player.id) : [],
    onChange: () => workspace && workspace.controller.refresh(),
  });
  const linkable = () => {
    const chosen = picker.players();
    const rest = [...suggested, ...allPlayers].filter((player) => !chosen.some((other) => other.id === player.id));
    return [...chosen, ...rest].filter((player, index, list) => list.findIndex((other) => other.id === player.id) === index);
  };
  const shirtNumberOf = (player) => (suggested.find((other) => other.id === player.id) || player).shirt_number;

  const form = buildForm([
    ...observationFields(vocab, { compact: true }),
    { name: 'diagram_title', label: 'Title for the diagram', help: 'Optional', maxLength: 200 },
  ], existing
    ? { ...observationToForm(existing), diagram_title: snapshot ? snapshot.title : null }
    : { category: 'Off-ball movement', video_time_seconds: time });

  function mountWorkspace(shapes) {
    if (workspace) workspace.destroy();
    workspace = createWorkspace({
      frame: currentFrame ? { url: currentFrame.dataUrl || currentFrame.url, width: currentFrame.width, height: currentFrame.height } : null,
      pitch: snapshot ? { length: snapshot.pitch_length_m, width: snapshot.pitch_width_m } : PITCH,
      shapes,
      players: linkable,
      zoneTypes: vocab.zone_types,
      // A new "studied player" marker is linked to the studied player straight away.
      defaultsFor: (kind) => {
        const primary = picker.primaryPlayer();
        if (kind !== 'subject' || !primary) return {};
        const number = shirtNumberOf(primary);
        return { player_id: primary.id, label: number ? String(number) : null };
      },
      confirmClear: () => confirmDialog({
        title: 'Remove every shape?', message: 'You can still bring them back with Undo.', confirmLabel: 'Clear the drawing', danger: true,
      }),
    });
    workspace.doc.onChange(() => { unsavedDrawing = true; });
    // With no picture yet, the box for adding one comes first. Once there is a
    // picture, replacing it is rare, so that box moves out of the way to the bottom.
    clear(surfaceHost).append(...[
      currentFrame ? null : pictureBox(),
      workspace.element,
      h('div', { class: 'panel-row' }, workspace.panels.properties, workspace.panels.measurements, workspace.panels.legend),
      currentFrame ? pictureBox() : null,
    ].filter(Boolean));
  }

  /** Use a screenshot as the picture to draw on. Shapes on the old picture would not fit the new one. */
  async function usePicture(file) {
    try {
      const picture = await frameFromImageFile(file);
      const frameShapes = workspace.doc.onLayer('frame').length;
      if (frameShapes && !await confirmDialog({
        title: 'Replace the picture?',
        message: `The ${frameShapes} shape(s) drawn over the current picture will be removed, because they would not line up with a different picture. The pitch drawing is kept.`,
        confirmLabel: 'Replace picture',
      })) return;
      currentFrame = { dataUrl: picture.dataUrl, width: picture.width, height: picture.height, source: 'upload' };
      unsavedDrawing = true;
      mountWorkspace(workspace.shapes().filter((shape) => shape.layer !== 'frame'));
      toast('Picture added. Draw over it on the left.');
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  /** The box for adding (or replacing) the picture: choose a file, drop one, or paste. */
  function pictureBox() {
    const input = h('input', { type: 'file', accept: 'image/*', 'aria-label': 'Choose a screenshot',
      onchange: () => { if (input.files[0]) usePicture(input.files[0]); } });
    const box = h('div', { class: 'dropzone stack' },
      currentFrame
        ? h('div', { class: 'row small' }, h('span', {}, 'Wrong picture? Paste, drop or choose another one to draw on:'), input)
        : [h('strong', {}, 'No picture of this moment yet'),
          frameNote ? h('p', { class: 'small' }, frameNote) : null,
          h('p', { class: 'small muted' }, 'Take a screenshot of the moment, then paste it here (Cmd/Ctrl + V), drop it on this box, '
            + 'or choose the file. You can also skip the picture and rebuild the situation on the pitch.'),
          input]);
    box.addEventListener('dragover', (event) => { event.preventDefault(); box.classList.add('is-over'); });
    box.addEventListener('dragleave', () => box.classList.remove('is-over'));
    box.addEventListener('drop', (event) => {
      event.preventDefault();
      box.classList.remove('is-over');
      const file = imageFromTransfer(event.dataTransfer);
      if (file) usePicture(file);
    });
    return box;
  }

  const onPaste = (event) => {
    const file = imageFromTransfer(event.clipboardData);
    if (file) {
      event.preventDefault();
      usePicture(file);
    }
  };
  document.addEventListener('paste', onPaste);

  function close(result) {
    document.removeEventListener('paste', onPaste);
    if (workspace) workspace.destroy();
    unsavedDrawing = false;
    onDone(result);
  }

  const saveButton = h('button', { type: 'button', class: 'button primary', onclick: save },
    existing ? 'Save changes' : 'Save observation');

  async function save() {
    const { values, errors } = form.read();
    if (Object.keys(errors).length) {
      form.showErrors(errors);
      return;
    }
    const { diagram_title: diagramTitle, ...fields } = values;
    const who = picker.read();
    if (!who.player_ids.length && !match) {
      form.showErrors({ '': 'Choose at least one player this observation is about.' });
      return;
    }

    const shapes = workspace.shapes();
    const diagram = {
      title: diagramTitle,
      frame_width: currentFrame ? currentFrame.width : null,
      frame_height: currentFrame ? currentFrame.height : null,
      pitch_length_m: workspace.pitchSurface.space.length,
      pitch_width_m: workspace.pitchSurface.space.width,
      annotations: shapes,
    };
    if (currentFrame && currentFrame.dataUrl) {
      // A picture that is not on the server yet. An unchanged saved picture is simply kept.
      diagram.frame_image = currentFrame.dataUrl;
      diagram.frame_source = currentFrame.source;
    }
    const hasDiagram = shapes.length > 0 || Boolean(currentFrame);

    saveButton.disabled = true;
    try {
      let saved;
      if (!existing) {
        // One request: the observation, its players, the diagram and the picture are saved together or not at all.
        saved = await api.post('/api/observations', {
          ...fields, ...who, match_id: match ? match.id : null, video_reference_id: videoId ?? null,
          snapshot: hasDiagram ? diagram : null,
        });
      } else {
        saved = await api.put(`/api/observations/${existing.id}`, {
          ...fields, ...who, match_id: existing.match ? existing.match.id : null,
          video_reference_id: existing.video_reference_id,
        });
        if (snapshot) await api.put(`/api/snapshots/${snapshot.id}`, { ...diagram, notes: snapshot.notes });
        else if (hasDiagram) await api.post(`/api/observations/${existing.id}/snapshots`, diagram);
      }
      toast(existing ? `Observation #${saved.id} saved` : `Observation #${saved.id} saved. Press play to carry on.`);
      close(saved);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      const fieldErrors = error.fieldErrors;
      form.showErrors(Object.keys(fieldErrors).length ? fieldErrors : { '': error.message });
    } finally {
      saveButton.disabled = false;
    }
  }

  async function cancel() {
    if (unsavedDrawing && !await confirmDialog({
      title: 'Leave without saving?', message: 'The drawing and anything typed here will be lost.', confirmLabel: 'Leave without saving', danger: true,
    })) return;
    close(null);
  }

  mountWorkspace(snapshot ? snapshot.annotations : []);
  form.element.addEventListener('input', () => { unsavedDrawing = true; });

  const heading = existing
    ? `Editing observation #${existing.id}`
    : (time === null ? 'Analysing a moment' : ['Analysing', videoClock(time)]);

  return h('div', { class: 'stage', id: 'analysis' },
    h('div', { class: 'stage-head' },
      h('h2', {}, heading),
      h('button', { type: 'button', class: 'button', onclick: cancel }, existing ? 'Close without saving' : 'Back to the video')),
    h('div', { class: 'workspace' },
      surfaceHost,
      h('aside', {},
        h('div', { class: 'panel stack' },
          h('h3', {}, 'What you saw'),
          picker.element, form.element,
          h('div', { class: 'row' }, saveButton, h('button', { type: 'button', class: 'button', onclick: cancel }, 'Cancel'))))));
}

// ── Watching a match ─────────────────────────────────────────────────────────
function describeVideoError(video) {
  const code = video.error ? video.error.code : 0;
  const reason = {
    1: 'Loading was interrupted.',
    2: 'The file could not be read (a network or disk problem).',
    3: 'The file is damaged or uses a format this browser cannot decode.',
    4: 'This browser cannot play this file\'s format, or the file is not there any more.',
  }[code] || 'The video could not be played.';
  return `${reason} A match saved as .mp4 with H.264 video plays in every browser. You can still analyse this match `
    + 'by typing the timestamp and adding a screenshot.';
}

async function showMatch(matchId, wantedVideoId, seekTo) {
  const [match, vocab, allPlayers] = await Promise.all([
    api.get(`/api/matches/${matchId}`), vocabulary(), api.get('/api/players'),
  ]);
  const video = match.videos.find((candidate) => candidate.id === wantedVideoId) || match.videos[0] || null;
  // The lineup, with the shirt number worn in THIS match when it was recorded.
  const lineup = match.appearances.map((appearance) => ({
    ...allPlayers.find((player) => player.id === appearance.player.id),
    shirt_number: appearance.shirt_number || (allPlayers.find((player) => player.id === appearance.player.id) || {}).shirt_number,
  }));

  page.setTitle(match.title);
  clear(page.heading).append(scoreline(match));
  page.setLede([formatDate(match.match_date), match.competition && match.competition.name].filter(Boolean).join(', '));
  clear(page.before).append(h('a', { class: 'back-link', href: `match.html?id=${match.id}` }, 'Match details'));

  const watchStage = h('div', { class: 'stage' });
  const analysisHost = h('div', {});
  const momentsBox = h('div', {});
  let player = null;  // the <video> element, when the app plays the video itself

  function refreshMoments() {
    return load(momentsBox, async () => {
      const result = await api.get('/api/observations', { match_id: match.id, limit: 500 });
      if (!result.items.length) return h('p', { class: 'muted small' }, 'Nothing recorded for this match yet.');
      return h('ul', { class: 'list' }, result.items.map((observation) => h('li', { class: 'moment' },
        h('div', { class: 'clocks' }, videoClock(observation.video_time_seconds, player && observation.video_time_seconds !== null
          ? { onclick: () => { player.currentTime = observation.video_time_seconds; } } : {})),
        h('div', { class: 'what' },
          h('a', { href: `observations.html?open=${observation.id}`,
            onclick: (event) => { event.preventDefault(); openObservation(observation.id, { onChanged: refreshMoments }); } },
          h('strong', {}, observationTitle(observation))),
          h('div', { class: 'small muted' }, observation.players.map((entry) => entry.full_name).join(', ') || 'No player')))));
    });
  }

  function startAnalysis({ time, frame, frameNote }) {
    watchStage.hidden = true;  // hidden, not removed: the video stays paused exactly where it was
    clear(analysisHost).append(buildAnalysis({
      vocab, allPlayers, suggested: lineup, match, videoId: video ? video.id : null, time, frame, frameNote,
      existing: null, snapshot: null,
      onDone: (saved) => {
        clear(analysisHost);
        watchStage.hidden = false;
        if (saved) refreshMoments();
        if (player) player.focus();
      },
    }));
    analysisHost.scrollIntoView({ block: 'start' });
  }

  /** Pause, note the time, capture the frame, open the workspace. */
  function analyseNow() {
    player.pause();
    const time = player.currentTime;  // read once; the form owns the timestamp from here on
    try {
      const shot = captureVideoFrame(player);
      startAnalysis({ time, frame: { ...shot, source: 'video_capture' }, frameNote: null });
    } catch (error) {
      if (error instanceof FrameCaptureError && error.reason === 'blocked') {
        startAnalysis({ time, frame: null, frameNote: error.message });
      } else {
        toast(error.message, 'error');
      }
    }
  }

  const manualButton = h('button', { type: 'button', class: 'button', onclick: () => startAnalysis({ time: null, frame: null, frameNote: null }) },
    'Analyse a moment by hand');

  let viewer;
  if (video && video.playback.mode === 'html5') {
    const analyseButton = h('button', {
      type: 'button', class: 'analyse-button', onclick: analyseNow,
      title: 'Pause here and analyse this moment (keyboard: A)',
    }, 'Analyse');
    player = h('video', { controls: true, preload: 'metadata', playsInline: true, src: video.playback.source_url });
    const problem = h('div', { class: 'note error', role: 'alert' });
    problem.hidden = true;
    player.addEventListener('play', () => analyseButton.classList.add('is-playing'));
    player.addEventListener('pause', () => analyseButton.classList.remove('is-playing'));
    player.addEventListener('loadedmetadata', () => {
      if (seekTo !== null && Number.isFinite(seekTo)) player.currentTime = Math.min(seekTo, player.duration || seekTo);
    });
    player.addEventListener('error', () => {
      problem.textContent = describeVideoError(player);
      problem.hidden = false;
      analyseButton.hidden = true;
    });
    document.addEventListener('keydown', (event) => {
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
      if (event.key.toLowerCase() === 'a' && !typing && !watchStage.hidden && !event.metaKey && !event.ctrlKey && !document.querySelector('dialog[open]')) {
        event.preventDefault();
        analyseNow();
      }
    });
    viewer = [h('div', { class: 'viewer' }, player, analyseButton), problem];
  } else if (video && video.playback.mode === 'embed') {
    viewer = h('div', { class: 'viewer' },
      h('iframe', { src: video.playback.source_url, title: video.label, allowFullscreen: true, referrerPolicy: 'strict-origin-when-cross-origin',
        allow: 'accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture' }));
  } else {
    viewer = h('div', { class: 'viewer fallback stack' },
      h('h3', {}, video ? 'This video cannot be played inside the app' : 'No video is linked to this match'),
      video && video.kind === 'external_link'
        ? h('p', {}, h('a', { href: video.location, target: '_blank', rel: 'noopener noreferrer' }, 'Open the video in a new tab'))
        : null,
      h('p', { class: 'muted' }, 'You can still record what you see: watch it wherever it plays, then type the timestamp, '
        + 'add a screenshot of the moment and draw on it.'),
      video ? null : h('p', {}, h('a', { href: `match.html?id=${match.id}` }, 'Link a video to this match')));
  }

  const videoPicker = match.videos.length > 1
    ? h('select', { 'aria-label': 'Video', onchange: (event) => { window.location.href = `video.html?match=${match.id}&video=${event.target.value}`; } },
      match.videos.map((candidate) => h('option', { value: candidate.id, selected: video && candidate.id === video.id }, candidate.label)))
    : null;

  watchStage.append(h('div', { class: 'watch' },
    h('div', { class: 'stack' },
      viewer,
      h('div', { class: 'row spread' },
        h('p', { class: 'small muted prose' }, video ? video.playback.explanation : ''),
        h('div', { class: 'row' }, videoPicker, manualButton))),
    h('aside', { class: 'side-panel' }, h('h3', {}, 'Recorded in this match'), momentsBox)));

  clear(page.content).append(watchStage, analysisHost);
  refreshMoments();
}

// ── Editing a saved observation's drawing ────────────────────────────────────
async function showExisting(observationId, wantedSnapshotId) {
  const [observation, vocab, allPlayers] = await Promise.all([
    api.get(`/api/observations/${observationId}`), vocabulary(), api.get('/api/players'),
  ]);
  const snapshot = observation.snapshots.find((candidate) => candidate.id === wantedSnapshotId) || observation.snapshots[0] || null;
  const match = observation.match ? await api.get(`/api/matches/${observation.match.id}`) : null;
  const lineup = match ? match.appearances.map((appearance) => ({
    ...allPlayers.find((player) => player.id === appearance.player.id), shirt_number: appearance.shirt_number,
  })) : [];

  page.setTitle(`Observation #${observation.id}`);
  page.heading.textContent = match ? match.title : `Observation #${observation.id}`;
  page.setLede(match ? formatDate(match.match_date) : null);
  const backTo = document.referrer && new URL(document.referrer).origin === window.location.origin
    ? document.referrer : 'observations.html';

  clear(page.content).append(buildAnalysis({
    vocab, allPlayers, suggested: lineup, match, videoId: observation.video_reference_id,
    time: observation.video_time_seconds,
    frame: snapshot && snapshot.frame_width
      ? { url: snapshot.frame_image_url, width: snapshot.frame_width, height: snapshot.frame_height, source: snapshot.frame_source }
      : null,
    frameNote: null,
    existing: observation, snapshot,
    onDone: () => { window.location.href = backTo; },
  }));
}

// ── Start ────────────────────────────────────────────────────────────────────
async function start() {
  const observationId = Number(queryParam('observation'));
  const matchId = Number(queryParam('match'));
  try {
    if (observationId) await showExisting(observationId, Number(queryParam('snapshot')));
    else if (matchId) {
      const seek = queryParam('t');
      await showMatch(matchId, Number(queryParam('video')), seek === null ? null : Number(seek));
    } else await showChooser();
  } catch (error) {
    clear(page.content).append(errorNote(error, start));
  }
}

start();
