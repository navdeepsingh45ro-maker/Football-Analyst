// Tactical pitch: draw a situation or an idea on a top-down pitch, without a video.
//
// Diagrams made here are "standalone": they belong to no observation. (A diagram
// drawn for an observation is edited from the Video analysis page, because it
// may also have a video-frame layer that this page does not show.)

import { api, vocabulary } from '../api.js';
import { clear, h, queryParam } from '../dom.js';
import { downloadFile, slug, surfaceToPng } from '../editor/export-image.js';
import { createWorkspace } from '../editor/workspace.js';
import { buildForm } from '../forms.js';
import { formatMoment, plural } from '../format.js';
import { errorNote, load, mountPage } from '../layout.js';
import { confirmDialog, emptyState, toast } from '../ui.js';

const PITCH = { length: 105, width: 68 };

const page = mountPage({
  active: 'pitch.html', title: 'Tactical pitch', wide: true,
  lede: 'Rebuild a situation or sketch an idea from above. Positions are in metres on a 105 × 68 m pitch, '
    + 'so distances and angles are estimates you can read off.',
});

const stage = h('div', { class: 'stage' });
const savedList = h('div', {});
page.content.append(stage, h('section', { class: 'section' },
  h('div', { class: 'section-head' }, h('h2', {}, 'Saved pitch diagrams')), savedList));

let workspace = null;
let current = null;   // the saved diagram being edited, or null for a new one
let dirty = false;    // true when there are changes that have not been saved

window.addEventListener('beforeunload', (event) => {
  if (dirty) event.preventDefault();  // the browser then asks before leaving the page
});

function refreshList() {
  return load(savedList, async () => {
    const diagrams = await api.get('/api/snapshots');
    if (!diagrams.length) return emptyState('No saved diagrams yet. Draw on the pitch above and press Save diagram.');
    return h('ul', { class: 'list' }, diagrams.map((diagram) => h('li', { class: 'row spread' },
      h('div', {},
        h('a', { class: 'title-link', href: `pitch.html?snapshot=${diagram.id}` }, diagram.title || `Diagram #${diagram.id}`),
        h('div', { class: 'small muted' }, `${plural(diagram.shape_count, 'shape')}, last saved ${formatMoment(diagram.updated_at)}`)),
      current && current.id === diagram.id ? h('span', { class: 'tag' }, 'Open above') : null)));
  });
}

async function open(snapshot) {
  const [vocab, players] = await Promise.all([vocabulary(), api.get('/api/players')]);
  if (workspace) workspace.destroy();
  current = snapshot;
  dirty = false;

  workspace = createWorkspace({
    frame: null,
    pitch: snapshot ? { length: snapshot.pitch_length_m, width: snapshot.pitch_width_m } : PITCH,
    shapes: snapshot ? snapshot.annotations : [],
    players: () => players,
    zoneTypes: vocab.zone_types,
    confirmClear: () => confirmDialog({
      title: 'Remove every shape?', message: 'You can still bring them back with Undo.', confirmLabel: 'Clear the pitch', danger: true,
    }),
  });
  workspace.doc.onChange(() => { dirty = true; });

  const form = buildForm([
    { name: 'title', label: 'Title', maxLength: 200, placeholder: 'e.g. Third-man run from a throw-in' },
    { name: 'notes', label: 'Notes', type: 'textarea', rows: 4 },
  ], snapshot || {});
  form.element.addEventListener('input', () => { dirty = true; });

  const body = () => {
    const { values } = form.read();
    return {
      ...values,
      pitch_length_m: workspace.pitchSurface.space.length,
      pitch_width_m: workspace.pitchSurface.space.width,
      annotations: workspace.shapes(),
    };
  };

  async function save(asCopy = false) {
    try {
      const saved = current && !asCopy
        ? await api.put(`/api/snapshots/${current.id}`, body())
        : await api.post('/api/snapshots', body());
      dirty = false;
      toast(asCopy ? 'Saved as a new diagram' : 'Diagram saved');
      history.replaceState(null, '', `pitch.html?snapshot=${saved.id}`);
      await open(saved);
    } catch (error) {
      form.showErrors({ '': error.message });
    }
  }

  const fileName = () => slug(form.read().values.title || (current ? `diagram-${current.id}` : 'pitch-diagram'));
  const buttons = [
    h('button', { type: 'button', class: 'button primary', onclick: () => save(false) }, 'Save diagram'),
    current ? h('button', { type: 'button', class: 'button', onclick: () => save(true) }, 'Save as a copy') : null,
    h('button', { type: 'button', class: 'button', onclick: async () => {
      downloadFile(await surfaceToPng(workspace.pitchSurface), `${fileName()}.png`);
    } }, 'Download picture'),
    h('button', { type: 'button', class: 'button', title: 'The positions as data, in metres', onclick: () => {
      const data = {
        ...body(),
        coordinate_system: 'Metres. x = 0 is the own goal line of the team being studied and x = pitch_length_m is the goal '
          + 'line they attack. y = 0 is the touchline on their left as they attack.',
      };
      downloadFile(JSON.stringify(data, null, 2), `${fileName()}.json`, 'application/json');
    } }, 'Download data'),
    current ? h('button', { type: 'button', class: 'button danger', onclick: async () => {
      const sure = await confirmDialog({
        title: 'Delete this diagram?', message: 'This cannot be undone.', confirmLabel: 'Delete diagram', danger: true,
      });
      if (!sure) return;
      await api.delete(`/api/snapshots/${current.id}`);
      toast('Diagram deleted');
      dirty = false;
      history.replaceState(null, '', 'pitch.html');
      await open(null);
    } }, 'Delete') : null,
  ];

  clear(stage).append(
    h('div', { class: 'stage-head' },
      h('h2', {}, current ? (current.title || `Diagram #${current.id}`) : 'New diagram'),
      current ? h('a', { class: 'button', href: 'pitch.html' }, 'Start a new diagram') : null),
    h('div', { class: 'workspace' },
      h('div', {},
        workspace.element,
        h('div', { class: 'panel-row' }, workspace.panels.properties, workspace.panels.measurements, workspace.panels.legend)),
      h('aside', {},
        h('div', { class: 'panel stack' }, h('h3', {}, 'This diagram'), form.element, h('div', { class: 'row' }, buttons)))));
  refreshList();
}

async function start() {
  const snapshotId = Number(queryParam('snapshot'));
  try {
    if (!snapshotId) {
      await open(null);
      return;
    }
    const snapshot = await api.get(`/api/snapshots/${snapshotId}`);
    if (snapshot.observation_id !== null) {
      // It belongs to an observation: open it in the full editor, which also shows its video frame.
      window.location.replace(`video.html?observation=${snapshot.observation_id}&snapshot=${snapshot.id}`);
      return;
    }
    await open(snapshot);
  } catch (error) {
    clear(stage).append(errorNote(error, start));
    refreshList();
  }
}

start();
