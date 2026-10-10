// Showing observations: a row in a list, and the full record in a dialog.

import { api } from '../api.js';
import { h } from '../dom.js';
import { downloadFile, slug, surfaceToPng } from '../editor/export-image.js';
import { renderSnapshot } from '../editor/workspace.js';
import { excerpt, formatMoment } from '../format.js';
import { confirmDialog, emptyState, infoDialog, matchClock, matchDate, toast, videoClock } from '../ui.js';
import { observationDialog } from './observation-form.js';

/** Where to open the video at the moment of an observation, or null when it has no video. */
export function videoLink(observation) {
  if (!observation.match || observation.video_reference_id === null) return null;
  const params = new URLSearchParams({ match: observation.match.id, video: observation.video_reference_id });
  if (observation.video_time_seconds !== null) params.set('t', observation.video_time_seconds);
  return `video.html?${params}`;
}

export function observationTitle(observation) {
  return observation.movement_category ? `${observation.category}: ${observation.movement_category}` : observation.category;
}

/** One observation as a list row. Clicking the title opens the full record. */
export function observationRow(observation, { onChanged = () => {} } = {}) {
  const players = observation.players.map((player) => player.full_name).join(', ');
  const where = observation.match
    ? [observation.match.title, ', ', matchDate(observation.match.match_date)]
    : 'Not tied to a match';
  return h('li', { class: 'moment' },
    h('div', { class: 'clocks' },
      videoClock(observation.video_time_seconds, { href: videoLink(observation) }),
      matchClock(observation.match_clock_seconds)),
    h('div', { class: 'what' },
      h('a', { href: `observations.html?open=${observation.id}`, class: 'title-link',
        onclick: (event) => { event.preventDefault(); openObservation(observation.id, { onChanged }); } },
      h('strong', {}, observationTitle(observation))),
      h('div', { class: 'small muted' }, players || 'No player', '. ', where, '.',
        observation.outcome ? ` Outcome: ${observation.outcome}.` : '',
        observation.snapshot_ids.length ? ' Has a diagram.' : ''),
      observation.notes ? h('div', {}, excerpt(observation.notes, 200)) : null));
}

/** A list of observations, or a friendly message when there are none. */
export function observationList(observations, { onChanged = () => {}, emptyMessage = 'No observations yet.' } = {}) {
  if (!observations.length) return emptyState(emptyMessage);
  return h('ul', { class: 'list' }, observations.map((observation) => observationRow(observation, { onChanged })));
}

function fact(label, value) {
  return value === null || value === undefined || value === '' ? [] : [h('dt', {}, label), h('dd', { class: 'prose' }, value)];
}

/** The full record of one observation, with its diagrams and everything that can be done with it. */
export async function openObservation(observationId, { onChanged = () => {} } = {}) {
  let observation;
  try {
    observation = await api.get(`/api/observations/${observationId}`);
  } catch (error) {
    toast(error.message, 'error');
    return;
  }

  const diagrams = observation.snapshots.map((snapshot) => {
    const view = renderSnapshot(snapshot);
    const downloads = Object.entries(view.surfaces).map(([layer, surface]) => h('button', {
      type: 'button', class: 'button small',
      onclick: async () => downloadFile(await surfaceToPng(surface), `${slug(snapshot.title || `observation-${observation.id}`)}-${layer}.png`),
    }, `Save ${layer} as picture`));
    return h('div', { class: 'stack' },
      snapshot.title ? h('h3', {}, snapshot.title) : null,
      view.element,
      h('div', { class: 'row' }, downloads,
        h('a', { class: 'button small', href: `/api/snapshots/${snapshot.id}`, target: '_blank', rel: 'noopener',
          title: 'Every shape with its coordinates: metres on the pitch, fractions of the frame on the picture' }, 'Diagram data'),
        h('a', { class: 'button small', href: `video.html?observation=${observation.id}&snapshot=${snapshot.id}` }, 'Edit drawing')));
  });

  let dialog = null;
  const reopen = () => { dialog.close(); onChanged(); openObservation(observationId, { onChanged }); };

  const edit = h('button', { type: 'button', class: 'button', onclick: async () => {
    if (await observationDialog(observation)) reopen();
  } }, 'Edit');
  const remove = h('button', { type: 'button', class: 'button danger', onclick: async () => {
    const sure = await confirmDialog({
      title: `Delete observation #${observation.id}?`,
      message: 'Its diagrams are deleted with it. Coaching notes and training ideas written from it are kept. This cannot be undone.',
      confirmLabel: 'Delete observation', danger: true,
    });
    if (!sure) return;
    await api.delete(`/api/observations/${observation.id}`);
    toast('Observation deleted');
    dialog.close();
    onChanged();
  } }, 'Delete');

  const link = videoLink(observation);
  const content = h('div', { class: 'stack' },
    h('div', { class: 'row' },
      videoClock(observation.video_time_seconds, { href: link }),
      matchClock(observation.match_clock_seconds),
      observation.match ? h('a', { href: `match.html?id=${observation.match.id}` }, observation.match.title) : h('span', { class: 'muted' }, 'Not tied to a match'),
      observation.match ? matchDate(observation.match.match_date) : null),
    h('div', { class: 'row' }, observation.players.map((player) => h('a', { class: 'tag', href: `player.html?id=${player.id}` },
      player.full_name, player.role === 'primary' ? ' (studied)' : ''))),
    h('dl', { class: 'facts' },
      fact('What it shows', observation.category),
      fact('Movement', observation.movement_category),
      fact('The situation', observation.tactical_situation),
      fact('What triggered it', observation.movement_trigger),
      fact('Space being attacked', observation.intended_space),
      fact('Defensive shape faced', observation.defensive_shape),
      fact('Outcome', observation.outcome),
      fact('Your interpretation', observation.notes),
      fact('How sure', observation.confidence),
      fact('Other evidence', observation.evidence),
      fact('Recorded', formatMoment(observation.created_at)),
      fact('Last changed', formatMoment(observation.updated_at))),
    diagrams.length ? diagrams : h('p', { class: 'muted' }, 'No diagram was drawn for this observation.'),
    observation.derived.length ? h('div', {}, h('h3', {}, 'Written because of this observation'),
      h('ul', {}, observation.derived.map((item) => h('li', {},
        h('a', { href: `notebook.html?open=${item.kind}-${item.id}` }, item.title),
        item.kind === 'training_idea' ? ' (training idea)' : ' (coaching note)')))) : null,
    h('div', { class: 'row no-print' },
      h('a', { class: 'button small', href: `notebook.html?from_observation=${observation.id}&as=note` }, 'Turn into a coaching note'),
      h('a', { class: 'button small', href: `notebook.html?from_observation=${observation.id}&as=idea` }, 'Turn into a training idea'),
      diagrams.length ? null : h('a', { class: 'button small', href: `video.html?observation=${observation.id}` }, 'Draw a diagram for it')));

  dialog = infoDialog({ title: `Observation #${observation.id}`, content, wide: true, actions: [remove, edit] });
}
