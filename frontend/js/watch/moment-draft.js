// The right-hand side of the analysis desk: the moment you are working on.
//
// It is always there, next to the video, so you can watch, draw and write at the
// same time. You can sketch on the pitch and take notes while the match plays.
// Pressing Analyse this moment fills in the time and the picture. Saving stores
// everything as one observation and starts a fresh moment. The players you chose
// and the kind of observation carry over to the next moment, because a session
// usually follows one player.
//
// HOW THE TIMESTAMP IS HANDLED
// When you press Analyse, the video's position is read ONCE into the form's "Video
// time" field. From then on that field is the only source of the timestamp. Nothing
// reads the video again, so letting the video play on, or seeking somewhere else,
// can never change the time of an observation by itself. The one exception is on
// purpose: choosing an earlier frame from the row of recent frames moves the time
// back by the same amount, so that picture and time still belong together.

import { api, ApiError } from '../api.js';
import { observationFields, observationToForm } from '../components/observation-form.js';
import { playerPicker } from '../components/player-picker.js';
import { clear, h } from '../dom.js';
import { createWorkspace } from '../editor/workspace.js';
import { buildForm } from '../forms.js';
import { formatClockExact } from '../format.js';
import { confirmDialog, toast, videoClock } from '../ui.js';
import { frameFromImageFile, imageFromTransfer } from './frame-capture.js';

const PITCH = { length: 105, width: 68 };
const FIRST_CATEGORY = 'Off-ball movement';

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('The picture could not be read.'));
    reader.readAsDataURL(blob);
  });
}

/**
 * Build the moment draft.
 *
 *   vocab, allPlayers   from the API
 *   suggested           players to offer with one click: the match lineup
 *   match               the match being watched, or null
 *   videoId()           the id of the video being watched now, or null
 *   canResume()         true when "Save and keep watching" can start the video again
 *   onSaved(observation, { resume, edited })   called after every save
 *
 * Returns { element, loadMoment, loadExisting, hasWork, workNote, save, reset }. A moment, as the
 * viewers make it (viewers.js), is { time, timeFromVideo, frame, pictures, chosen, note, videoId }.
 */
export function createDraft({ vocab, allPlayers, suggested, match, videoId, canResume, onSaved }) {
  let moment = null;     // the captured moment, or null before Analyse
  let frame = null;      // the picture to draw on: { url, width, height, source, blob?, dataUrl? }, or null
  let existing = null;   // a saved observation being changed, or null for a new one
  let snapshot = null;   // its diagram, or null
  let work = false;      // has anything been drawn, typed or chosen since this moment was started
  let workspace = null;
  let form = null;
  let picker = null;
  let ownUrls = [];      // picture addresses made for this moment, given back when it is done

  const head = h('div', { class: 'draft-head' });
  const strip = h('div', { class: 'filmstrip' });
  const pictureTop = h('div', {});
  const surfaceHost = h('div', {});
  const pictureBottom = h('div', {});
  const pickerHost = h('div', {});
  const formHost = h('div', {});
  const buttons = h('div', { class: 'row' });
  const element = h('section', { class: 'desk-work stage', 'aria-label': 'The moment you are working on' },
    head, strip, pictureTop, surfaceHost, pictureBottom,
    h('div', { class: 'panel stack draft-notes' }, h('h3', {}, 'What you saw'), pickerHost, formHost, buttons));

  const noteWork = () => { work = true; };
  element.addEventListener('input', (event) => {
    if (!formHost.contains(event.target)) return;
    noteWork();
    if (event.target === form.control('video_time_seconds')) renderHead();
  });

  // ── The players and the form ───────────────────────────────────────────────
  function buildPicker(selected) {
    picker = playerPicker({
      all: allPlayers, suggested, selected,
      onChange: () => {
        noteWork();
        if (workspace) workspace.controller.refresh();
      },
    });
    clear(pickerHost).append(picker.element);
  }

  function buildNotes(values) {
    form = buildForm([
      ...observationFields(vocab, { compact: true }),
      { name: 'diagram_title', label: 'Title for the diagram', help: 'Optional', maxLength: 200 },
    ], values);
    clear(formHost).append(form.element);
  }

  // Players offered for linking a marker: the ones chosen for this observation first.
  const linkable = () => {
    const chosen = picker.players();
    const rest = [...suggested, ...allPlayers].filter((player) => !chosen.some((other) => other.id === player.id));
    return [...chosen, ...rest].filter((player, index, list) => list.findIndex((other) => other.id === player.id) === index);
  };
  const shirtNumberOf = (player) => (suggested.find((other) => other.id === player.id) || player).shirt_number;

  // ── The drawing ────────────────────────────────────────────────────────────
  function mountWorkspace(shapes) {
    if (workspace) workspace.destroy();
    workspace = createWorkspace({
      frame: frame ? { url: frame.url || frame.dataUrl, width: frame.width, height: frame.height } : null,
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
    workspace.doc.onChange(noteWork);
    workspace.panels.legend.querySelector('details').open = false;  // there when wanted, out of the way otherwise
    clear(surfaceHost).append(workspace.element,
      h('div', { class: 'panel-row' }, workspace.panels.properties, workspace.panels.measurements, workspace.panels.legend));
    // With no picture yet, the box for adding one comes first. Once there is a picture,
    // replacing it is rare, so that box moves out of the way, below the drawing.
    clear(pictureTop).append(...[frame ? null : pictureBox()].filter(Boolean));
    clear(pictureBottom).append(...[frame ? pictureBox() : null].filter(Boolean));
  }

  /** Show `picture` to draw on. Shapes on a different picture would not line up, unless asked to keep them. */
  function setFrame(picture, { keepFrameShapes = false } = {}) {
    const shapes = workspace ? workspace.shapes() : [];
    frame = picture;
    mountWorkspace(keepFrameShapes ? shapes : shapes.filter((shape) => shape.layer !== 'frame'));
  }

  /** Use a screenshot you supply as the picture to draw on. */
  async function usePicture(file) {
    try {
      const picture = await frameFromImageFile(file);
      const frameShapes = workspace.doc.onLayer('frame').length;
      if (frameShapes && !await confirmDialog({
        title: 'Replace the picture?',
        message: `The ${frameShapes} shape(s) drawn over the current picture will be removed, because they would not line up with a different picture. The pitch drawing is kept.`,
        confirmLabel: 'Replace picture',
      })) return;
      if (moment) moment.pictures = null;  // the row of recent frames belonged to the old picture
      clear(strip);
      setFrame({ dataUrl: picture.dataUrl, width: picture.width, height: picture.height, source: 'upload' });
      noteWork();
      toast('Picture added. Draw over it.');
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  /** The box for adding (or replacing) the picture: choose a file, drop one, or paste. */
  function pictureBox() {
    const input = h('input', { type: 'file', accept: 'image/*', 'aria-label': 'Choose a screenshot',
      onchange: () => { if (input.files[0]) usePicture(input.files[0]); } });
    const note = moment && moment.note;
    const box = h('div', { class: 'dropzone stack' },
      frame
        ? h('div', { class: 'row small' }, h('span', {}, 'Wrong picture? Paste, drop or choose another one to draw on:'), input)
        : [h('strong', {}, moment ? 'Now add the picture of this moment' : 'No picture of this moment yet'),
          note ? h('p', { class: 'small' }, note) : null,
          h('p', { class: 'small muted' }, moment
            ? 'Paste a screenshot here (Cmd/Ctrl + V), drop one on this box, or choose the file. Or carry on without one and use the pitch.'
            : 'Press Analyse this moment beside the video, or paste a screenshot (Cmd/Ctrl + V), drop one here or choose '
              + 'the file. You can also draw on the pitch and write straight away.'),
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

  document.addEventListener('paste', (event) => {
    if (!element.isConnected || document.querySelector('dialog[open]')) return;
    const file = imageFromTransfer(event.clipboardData);
    if (file) {
      event.preventDefault();
      usePicture(file);
    }
  });

  // ── The row of recent frames ───────────────────────────────────────────────
  /** Offer the frames of the last seconds, so the clearest can be picked. */
  function showStrip() {
    clear(strip);
    if (!moment || !moment.pictures || moment.pictures.length < 2) return;
    const last = moment.pictures.length - 1;
    const choices = moment.pictures.map((picture, index) => {
      const when = picture.before < 0.05
        ? (moment.paused ? 'when paused' : 'now')
        : `${picture.before.toFixed(1)} s earlier`;
      return h('button', {
        type: 'button', class: 'frame-choice', 'aria-pressed': String(index === moment.chosen),
        title: index === last && moment.paused ? 'The paused picture. It may show the player\'s buttons.' : `The frame from ${when}`,
        onclick: () => choose(index),
      }, h('img', { src: picture.thumb, alt: '' }), h('span', {}, when));
    });
    const row = h('div', { class: 'frame-choices', role: 'group', 'aria-label': 'Frames from the last seconds' }, choices);
    row.addEventListener('keydown', (event) => {
      const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
      if (!step) return;
      event.preventDefault();
      const next = Math.min(last, Math.max(0, moment.chosen + step));
      choose(next);
      choices[next].focus();
    });
    strip.append(
      h('p', { class: 'small' }, h('strong', {}, 'Pick the clearest frame. '),
        h('span', { class: 'muted' }, moment.paused
          ? 'The one from just before the pause is chosen, so the player\'s buttons are not on it.'
          : 'The latest is chosen; an earlier one may be the moment you meant.')),
      row);
    // Bring the chosen frame into view along the row, without moving the page.
    requestAnimationFrame(() => {
      const button = choices[moment.chosen];
      if (button) row.scrollLeft = button.offsetLeft - (row.clientWidth - button.clientWidth) / 2;
    });
  }

  function choose(index) {
    if (!moment || !moment.pictures || index === moment.chosen) return;
    moment.chosen = index;
    const picture = moment.pictures[index];
    // The frames are fractions of a second apart: what was drawn still fits.
    setFrame({ url: picture.url, blob: picture.blob, width: picture.width, height: picture.height, source: 'video_capture' },
      { keepFrameShapes: true });
    if (moment.timeFromVideo && moment.base !== null) {
      setTime(moment.base - picture.before);
      renderHead();
    }
    for (const [position, button] of [...strip.querySelectorAll('.frame-choice')].entries()) {
      button.setAttribute('aria-pressed', String(position === index));
    }
  }

  // ── Heading and buttons ────────────────────────────────────────────────────
  function setTime(seconds) {
    form.control('video_time_seconds').value = formatClockExact(seconds === null ? null : Math.max(0, seconds));
  }

  /** The time in the form now, in seconds, or null when it is empty or not a time yet. */
  const typedTime = () => {
    const seconds = form.read().values.video_time_seconds;
    return seconds === undefined ? null : seconds;
  };

  function renderHead() {
    const seconds = typedTime();
    let title;
    let hint = null;
    if (existing) {
      title = `Editing observation #${existing.id}`;
    } else if (seconds !== null) {
      title = ['Moment at', videoClock(seconds)];
    } else if (moment) {
      title = 'Moment captured';
      hint = 'Type the time shown in the match\'s own player if you want to find this moment again.';
    } else {
      title = 'New moment';
      hint = 'Press Analyse this moment (A) to capture the video, or draw and write straight away.';
    }
    clear(head).append(...[
      h('div', { class: 'row spread' },
        h('h2', {}, title),
        h('button', { type: 'button', class: 'button small', onclick: () => leave() },
          existing ? 'Close without saving' : 'Start a new moment')),
      hint ? h('p', { class: 'small muted' }, hint) : null,
    ].filter(Boolean));
  }

  function renderButtons() {
    const save = h('button', { type: 'button', class: 'button primary', onclick: () => saveDraft() },
      existing ? 'Save changes' : 'Save observation');
    const saveAndPlay = canResume() && !existing
      ? h('button', { type: 'button', class: 'button', onclick: () => saveDraft({ resume: true }) }, 'Save and keep watching')
      : null;
    clear(buttons).append(...[save, saveAndPlay].filter(Boolean));
  }

  function render() {
    renderHead();
    renderButtons();
    showStrip();
  }

  // ── Starting, loading and leaving a moment ─────────────────────────────────
  function giveBackUrls() {
    ownUrls.forEach((url) => URL.revokeObjectURL(url));
    ownUrls = [];
  }

  /** A fresh moment. The players and the kind of observation are kept for it. */
  function reset() {
    giveBackUrls();
    const players = picker ? picker.read().player_ids : [];
    const category = form ? form.read().values.category : null;
    moment = null;
    frame = null;
    existing = null;
    snapshot = null;
    buildPicker(players);
    buildNotes({ category: category || FIRST_CATEGORY });
    mountWorkspace([]);
    work = false;
    render();
  }

  /**
   * Fill in what Analyse captured. With `fresh`, whatever was there is dropped first;
   * otherwise a pitch drawing and notes you made while watching are kept with it.
   */
  function loadMoment(next, { fresh = false } = {}) {
    if (fresh || existing) reset();
    giveBackUrls();
    moment = { base: next.time, paused: false, ...next };
    if (moment.pictures) ownUrls = moment.pictures.flatMap((picture) => [picture.url, picture.thumb]);
    const picture = moment.pictures ? moment.pictures[moment.chosen] : moment.frame;
    if (moment.pictures && moment.timeFromVideo && moment.base !== null) moment.time = moment.base - picture.before;
    if (moment.time !== null) setTime(moment.time);  // a time you typed stays when the video cannot tell its own
    setFrame(picture
      ? { url: picture.url, dataUrl: picture.dataUrl, blob: picture.blob, width: picture.width, height: picture.height, source: picture.source || 'video_capture' }
      : null);
    work = work && !fresh;
    render();
  }

  /** Change a saved observation: its notes and its diagram (the first, or `wantedSnapshotId`). */
  function loadExisting(observation, wantedSnapshotId = null) {
    giveBackUrls();
    existing = observation;
    snapshot = observation.snapshots.find((candidate) => candidate.id === wantedSnapshotId) || observation.snapshots[0] || null;
    moment = null;
    frame = snapshot && snapshot.frame_width
      ? { url: snapshot.frame_image_url, width: snapshot.frame_width, height: snapshot.frame_height, source: snapshot.frame_source }
      : null;
    buildPicker(observation.players.map((player) => player.id));
    buildNotes({ ...observationToForm(observation), diagram_title: snapshot ? snapshot.title : null });
    mountWorkspace(snapshot ? snapshot.annotations : []);
    work = false;
    render();
  }

  /** Is there work on a captured moment (or a saved observation) that would be lost? */
  const hasWork = () => work && Boolean(moment || existing);

  /** "the moment at 1:15", for questions about it. */
  function workNote() {
    if (existing) return `your changes to observation #${existing.id}`;
    const seconds = typedTime();
    return seconds === null ? 'the moment you are working on' : `the moment at ${formatClockExact(seconds)}`;
  }

  let onLeaveExisting = null;  // where to go after changing an observation that was opened from elsewhere
  async function leave() {
    if (work && !await confirmDialog({
      title: existing ? 'Close without saving?' : 'Start a new moment?',
      message: 'The drawing and anything typed here will be lost.', confirmLabel: existing ? 'Close without saving' : 'Start a new moment', danger: true,
    })) return;
    if (existing && onLeaveExisting) {
      work = false;
      onLeaveExisting(null);
      return;
    }
    reset();
  }

  // ── Saving ─────────────────────────────────────────────────────────────────
  let saving = false;
  /** Save as one observation. Resolves to the saved observation, or null when something needs fixing. */
  async function saveDraft({ resume = false } = {}) {
    if (saving) return null;
    const { values, errors } = form.read();
    if (Object.keys(errors).length) {
      form.showErrors(errors);
      return null;
    }
    const { diagram_title: diagramTitle, ...fields } = values;
    const who = picker.read();
    if (!who.player_ids.length && !match) {
      form.showErrors({ '': 'Choose at least one player this observation is about.' });
      return null;
    }

    saving = true;
    for (const button of buttons.querySelectorAll('button')) button.disabled = true;
    try {
      const shapes = workspace.shapes();
      const diagram = {
        title: diagramTitle,
        frame_width: frame ? frame.width : null,
        frame_height: frame ? frame.height : null,
        pitch_length_m: workspace.pitchSurface.space.length,
        pitch_width_m: workspace.pitchSurface.space.width,
        annotations: shapes,
      };
      if (frame && (frame.dataUrl || frame.blob)) {
        // A picture that is not on the server yet. An unchanged saved picture is simply kept.
        diagram.frame_image = frame.dataUrl || await blobToDataUrl(frame.blob);
        diagram.frame_source = frame.source;
      }
      const hasDiagram = shapes.length > 0 || Boolean(frame);

      let saved;
      const edited = Boolean(existing);
      if (!existing) {
        // One request: the observation, its players, the diagram and the picture are saved together or not at all.
        saved = await api.post('/api/observations', {
          ...fields, ...who, match_id: match ? match.id : null,
          video_reference_id: (moment && moment.videoId !== undefined ? moment.videoId : videoId()) ?? null,
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
      work = false;
      toast(edited || resume ? `Observation #${saved.id} saved` : `Observation #${saved.id} saved. Ready for the next moment.`);
      if (edited && onLeaveExisting) {
        onLeaveExisting(saved);
        return saved;
      }
      reset();
      onSaved(saved, { resume, edited });
      return saved;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      const fieldErrors = error.fieldErrors;
      form.showErrors(Object.keys(fieldErrors).length ? fieldErrors : { '': error.message });
      return null;
    } finally {
      saving = false;
      for (const button of buttons.querySelectorAll('button')) button.disabled = false;
    }
  }

  reset();

  return {
    element,
    loadMoment,
    /** Change a saved observation. `returnTo(saved | null)` is called when it is saved or closed; without it, a fresh moment follows. */
    loadExisting(observation, wantedSnapshotId = null, { returnTo = null } = {}) {
      onLeaveExisting = returnTo;
      loadExisting(observation, wantedSnapshotId);
    },
    hasWork,
    /** Is anything unsaved at all (for the warning when leaving the page)? */
    unsaved: () => work,
    workNote,
    save: saveDraft,
    reset,
    refreshButtons: renderButtons,
  };
}
