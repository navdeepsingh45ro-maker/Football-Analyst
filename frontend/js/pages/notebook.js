// Coaching notebook: what you learn from watching, and what you would train because of it.
//
// A note or training idea remembers which observations it came from, so the
// reasoning can be followed back later:   observation -> coaching note -> training idea
//
// Ways this page opens:
//   notebook.html                                 the notebook
//   notebook.html?open=coaching_note-4            straight to one note (or training_idea-2)
//   notebook.html?from_observation=7&as=note      start a note from observation 7 (as=idea for a training idea)

import { api, vocabulary } from '../api.js';
import { matchLabel } from '../components/match-form.js';
import { observationTitle, openObservation } from '../components/observation-list.js';
import { clear, h } from '../dom.js';
import { excerpt, formatClock, formatDate, formatMoment } from '../format.js';
import { errorNote, mountPage } from '../layout.js';
import { confirmDialog, emptyState, formDialog, infoDialog, matchDate, tabs, toast, videoClock } from '../ui.js';

const page = mountPage({
  active: 'notebook.html', title: 'Coaching notebook',
  lede: 'Concepts, lessons, questions and drills. Anything written because of an observation stays linked to it.',
});

let tabset = null;
const search = h('input', { type: 'search', id: 'note-search', placeholder: 'Words in the title or text' });
const typeFilter = h('select', { id: 'note-type' }, h('option', { value: '' }, 'Any kind'));
const statusFilter = h('select', { id: 'note-status' },
  h('option', { value: '' }, 'Open or not'), h('option', { value: 'open' }, 'Still open'), h('option', { value: 'done' }, 'Done'));

const numbers = (list) => list.map(Number).filter((value) => Number.isInteger(value) && value > 0);

function observationRefs(observations, onChanged) {
  if (!observations.length) return h('p', { class: 'muted small' }, 'Not linked to any observation.');
  return h('ul', { class: 'list' }, observations.map((observation) => h('li', { class: 'moment' },
    h('div', { class: 'clocks' }, videoClock(observation.video_time_seconds)),
    h('div', { class: 'what' },
      h('a', { href: `observations.html?open=${observation.id}`,
        onclick: (event) => { event.preventDefault(); openObservation(observation.id, { onChanged }); } },
      `#${observation.id} ${observationTitle(observation)}`),
      h('div', { class: 'small muted' }, observation.match ? [observation.match.title, ', ', matchDate(observation.match.match_date)] : 'Not tied to a match')))));
}

// ── Coaching notes ───────────────────────────────────────────────────────────
async function noteDialog(note = null, defaults = {}, intro = null) {
  const [vocab, players, matches] = await Promise.all([vocabulary(), api.get('/api/players'), api.get('/api/matches')]);
  const values = note ? {
    ...note, player_id: note.player ? note.player.id : null, match_id: note.match ? note.match.id : null,
    observation_ids: note.observations.map((observation) => observation.id),
  } : { note_type: 'Lesson from a match', ...defaults };
  return formDialog({
    title: note ? 'Edit coaching note' : 'New coaching note', intro, wide: true,
    fields: [
      { name: 'note_type', label: 'Kind of note', type: 'suggest', options: vocab.note_types, required: true, width: 'half' },
      { name: 'status', label: 'Is it something to finish?', type: 'select', width: 'half', emptyLabel: 'No, just a note',
        options: [['open', 'Yes, still open'], ['done', 'Yes, and it is done']], help: 'Open questions and goals are listed on the dashboard' },
      { name: 'title', label: 'Title', required: true, maxLength: 200 },
      { name: 'body', label: 'Note', type: 'textarea', rows: 8 },
      { name: 'player_id', label: 'About a player', type: 'select', numeric: true, emptyLabel: 'No particular player', width: 'half',
        options: players.map((player) => [player.id, player.full_name]) },
      { name: 'match_id', label: 'About a match', type: 'select', numeric: true, emptyLabel: 'No particular match', width: 'half',
        options: matches.map((match) => [match.id, matchLabel(match, formatDate)]) },
      { name: 'observation_ids', label: 'Observation numbers it rests on', type: 'list', width: 'half', help: 'For example 3, 7. This is what keeps your reasoning traceable.' },
      { name: 'tags', label: 'Tags', type: 'list', width: 'half', help: 'Separate with commas' },
    ],
    values,
    submitLabel: note ? 'Save changes' : 'Save note',
    onSubmit: (read) => {
      const body = { ...read, observation_ids: numbers(read.observation_ids) };
      return note ? api.put(`/api/notes/${note.id}`, body) : api.post('/api/notes', body);
    },
  });
}

async function showNote(noteId) {
  const note = await api.get(`/api/notes/${noteId}`);
  let dialog = null;
  const again = () => { dialog.close(); refresh(); showNote(noteId); };
  dialog = infoDialog({
    title: note.title, wide: true,
    content: h('div', { class: 'stack' },
      h('div', { class: 'row' }, h('span', { class: 'tag' }, note.note_type),
        note.status ? h('span', { class: 'tag' }, note.status === 'open' ? 'Still open' : 'Done') : null,
        note.tags.map((tag) => h('span', { class: 'tag' }, tag))),
      note.player || note.match ? h('p', { class: 'muted' }, 'About ',
        note.player ? h('a', { href: `player.html?id=${note.player.id}` }, note.player.full_name) : null,
        note.player && note.match ? ', ' : null,
        note.match ? h('a', { href: `match.html?id=${note.match.id}` }, note.match.title) : null) : null,
      note.body ? h('p', { class: 'prose' }, note.body) : h('p', { class: 'muted' }, 'No text.'),
      h('h3', {}, 'Written because of'), observationRefs(note.observations, again),
      note.training_ideas.length ? [h('h3', {}, 'Training ideas that grew out of it'),
        h('ul', {}, note.training_ideas.map((idea) => h('li', {}, h('a', { href: `notebook.html?open=training_idea-${idea.id}` }, idea.title))))] : null,
      h('p', { class: 'small muted' }, `Written ${formatMoment(note.created_at)}, last changed ${formatMoment(note.updated_at)}.`)),
    actions: [
      h('button', { type: 'button', class: 'button danger', onclick: async () => {
        if (!await confirmDialog({ title: 'Delete this note?', message: 'Training ideas that grew out of it are kept. This cannot be undone.', confirmLabel: 'Delete note', danger: true })) return;
        await api.delete(`/api/notes/${note.id}`);
        toast('Note deleted');
        dialog.close();
        refresh();
      } }, 'Delete'),
      h('button', { type: 'button', class: 'button', onclick: async () => {
        const idea = await ideaDialog(null, {
          title: `Practise: ${note.title}`, source_note_id: note.id,
          observation_ids: note.observations.map((observation) => observation.id),
        }, `Growing out of your note "${note.title}".`);
        if (idea) { toast('Training idea saved'); again(); }
      } }, 'Turn into a training idea'),
      h('button', { type: 'button', class: 'button', onclick: async () => { if (await noteDialog(note)) again(); } }, 'Edit'),
    ],
  });
}

async function notesTab() {
  const notes = await api.get('/api/notes', { q: search.value.trim(), note_type: typeFilter.value, status: statusFilter.value });
  if (!notes.length) {
    return emptyState((search.value.trim() || typeFilter.value || statusFilter.value)
      ? 'No note matches these filters.'
      : 'No notes yet. Write down a concept, a lesson from a match, or a question to answer next time you watch.');
  }
  return h('ul', { class: 'list' }, notes.map((note) => h('li', { class: 'row spread' },
    h('div', { class: 'what' },
      h('a', { class: 'title-link', href: `notebook.html?open=coaching_note-${note.id}`,
        onclick: (event) => { event.preventDefault(); showNote(note.id); } }, note.title),
      h('div', { class: 'small muted' }, note.note_type, note.player ? `, about ${note.player.full_name}` : '',
        note.observations.length ? `, rests on ${note.observations.length} observation${note.observations.length === 1 ? '' : 's'}` : ''),
      note.body ? h('div', {}, excerpt(note.body, 180)) : null),
    note.status === 'open' ? h('button', { type: 'button', class: 'button small', onclick: async () => {
      await api.put(`/api/notes/${note.id}`, {
        note_type: note.note_type, title: note.title, body: note.body, tags: note.tags, status: 'done',
        player_id: note.player ? note.player.id : null, match_id: note.match ? note.match.id : null,
        observation_ids: note.observations.map((observation) => observation.id),
      });
      toast('Marked as done');
      refresh();
    } }, 'Mark as done') : (note.status === 'done' ? h('span', { class: 'tag' }, 'Done') : null))));
}

// ── Training ideas ───────────────────────────────────────────────────────────
async function ideaDialog(idea = null, defaults = {}, intro = null) {
  const notes = await api.get('/api/notes');
  const values = idea ? {
    ...idea, source_note_id: idea.source_note ? idea.source_note.id : null,
    observation_ids: idea.observations.map((observation) => observation.id),
  } : defaults;
  return formDialog({
    title: idea ? 'Edit training idea' : 'New training idea', intro, wide: true,
    fields: [
      { name: 'title', label: 'Title', required: true, maxLength: 200 },
      { name: 'objective', label: 'What the players should get better at', type: 'textarea', rows: 2 },
      { name: 'setup', label: 'Set-up', type: 'textarea', rows: 3, width: 'half', help: 'Area, numbers, equipment' },
      { name: 'instructions', label: 'How it runs', type: 'textarea', rows: 3, width: 'half' },
      { name: 'coaching_points', label: 'Coaching points', type: 'textarea', rows: 3, help: 'What to look for and correct' },
      { name: 'duration_minutes', label: 'Minutes', type: 'number', min: 1, max: 600, width: 'third' },
      { name: 'players_needed', label: 'Players needed', width: 'third', placeholder: 'e.g. 6 + GK', maxLength: 80 },
      { name: 'source_note_id', label: 'Grew out of the note', type: 'select', numeric: true, emptyLabel: 'No note', width: 'third',
        options: notes.map((note) => [note.id, note.title]) },
      { name: 'observation_ids', label: 'Observation numbers it rests on', type: 'list', help: 'For example 3, 7' },
    ],
    values,
    submitLabel: idea ? 'Save changes' : 'Save training idea',
    onSubmit: (read) => {
      const body = { ...read, observation_ids: numbers(read.observation_ids) };
      return idea ? api.put(`/api/training-ideas/${idea.id}`, body) : api.post('/api/training-ideas', body);
    },
  });
}

async function showIdea(ideaId) {
  const idea = await api.get(`/api/training-ideas/${ideaId}`);
  let dialog = null;
  const again = () => { dialog.close(); refresh(); showIdea(ideaId); };
  const part = (label, value) => (value ? [h('h3', {}, label), h('p', { class: 'prose' }, value)] : null);
  dialog = infoDialog({
    title: idea.title, wide: true,
    content: h('div', { class: 'stack' },
      h('div', { class: 'row' }, idea.duration_minutes ? h('span', { class: 'tag' }, `${idea.duration_minutes} minutes`) : null,
        idea.players_needed ? h('span', { class: 'tag' }, idea.players_needed) : null),
      part('What the players should get better at', idea.objective), part('Set-up', idea.setup),
      part('How it runs', idea.instructions), part('Coaching points', idea.coaching_points),
      idea.source_note ? h('p', {}, 'Grew out of the note ',
        h('a', { href: `notebook.html?open=coaching_note-${idea.source_note.id}` }, idea.source_note.title)) : null,
      h('h3', {}, 'Rests on'), observationRefs(idea.observations, again),
      h('p', { class: 'small muted' }, `Written ${formatMoment(idea.created_at)}, last changed ${formatMoment(idea.updated_at)}.`)),
    actions: [
      h('button', { type: 'button', class: 'button danger', onclick: async () => {
        if (!await confirmDialog({ title: 'Delete this training idea?', message: 'This cannot be undone.', confirmLabel: 'Delete training idea', danger: true })) return;
        await api.delete(`/api/training-ideas/${idea.id}`);
        toast('Training idea deleted');
        dialog.close();
        refresh();
      } }, 'Delete'),
      h('button', { type: 'button', class: 'button', onclick: async () => { if (await ideaDialog(idea)) again(); } }, 'Edit'),
    ],
  });
}

async function ideasTab() {
  const ideas = await api.get('/api/training-ideas', { q: search.value.trim() });
  if (!ideas.length) {
    return emptyState(search.value.trim() ? 'No training idea matches the search.'
      : 'No training ideas yet. Open a coaching note or an observation and turn it into one.');
  }
  return h('ul', { class: 'list' }, ideas.map((idea) => h('li', {},
    h('a', { class: 'title-link', href: `notebook.html?open=training_idea-${idea.id}`,
      onclick: (event) => { event.preventDefault(); showIdea(idea.id); } }, idea.title),
    h('div', { class: 'small muted' }, [idea.duration_minutes ? `${idea.duration_minutes} minutes` : null, idea.players_needed,
      idea.source_note ? `from the note "${idea.source_note.title}"` : null,
      idea.observations.length ? `rests on ${idea.observations.length} observation${idea.observations.length === 1 ? '' : 's'}` : null]
      .filter(Boolean).join(', ')),
    idea.objective ? h('div', {}, excerpt(idea.objective, 180)) : null)));
}

// ── Starting from an observation ─────────────────────────────────────────────
async function startFromObservation(observationId, kind) {
  const observation = await api.get(`/api/observations/${observationId}`);
  const primary = observation.players[0] || null;
  const where = observation.match ? observation.match.title : 'no match';
  const when = formatClock(observation.video_time_seconds);
  const seen = observation.notes || observation.tactical_situation || '';
  const intro = `From observation #${observation.id} (${observationTitle(observation)}, ${where}${when ? `, ${when}` : ''}). `
    + 'It stays linked to that observation.';
  if (kind === 'idea') {
    return ideaDialog(null, {
      title: `Practise: ${(observation.movement_category || observation.category).toLowerCase()}`,
      objective: seen ? `Observed: ${seen}` : null, observation_ids: [observation.id],
    }, intro);
  }
  return noteDialog(null, {
    note_type: 'Lesson from a match', title: observationTitle(observation),
    body: seen ? `Observed: ${seen}\n\nWhat it means for coaching: ` : null,
    player_id: primary ? primary.id : null, match_id: observation.match ? observation.match.id : null,
    observation_ids: [observation.id],
  }, intro);
}

// ── The page ─────────────────────────────────────────────────────────────────
function refresh() {
  if (tabset) tabset.refresh();
}

async function start() {
  try {
    const vocab = await vocabulary();
    typeFilter.append(...vocab.note_types.map((type) => h('option', { value: type }, type)),
      h('option', { value: 'AI-generated draft' }, 'AI-generated draft'));
    clear(page.actions).append(
      h('button', { type: 'button', class: 'button', onclick: async () => { if (await ideaDialog()) { toast('Training idea saved'); tabset.show('ideas'); } } }, 'New training idea'),
      h('button', { type: 'button', class: 'button primary', onclick: async () => { if (await noteDialog()) { toast('Note saved'); tabset.show('notes'); } } }, 'New coaching note'));

    tabset = tabs([
      { id: 'notes', label: 'Coaching notes', render: notesTab },
      { id: 'ideas', label: 'Training ideas', render: ideasTab },
    ], 'notes');
    let timer = null;
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(refresh, 250); });
    typeFilter.addEventListener('change', refresh);
    statusFilter.addEventListener('change', refresh);
    clear(page.content).append(
      h('div', { class: 'filters' },
        h('div', { class: 'field' }, h('label', { for: 'note-search' }, 'Search'), search),
        h('div', { class: 'field' }, h('label', { for: 'note-type' }, 'Kind of note'), typeFilter),
        h('div', { class: 'field' }, h('label', { for: 'note-status' }, 'Tasks'), statusFilter)),
      tabset.element);

    const params = new URLSearchParams(window.location.search);
    const [kind, id] = (params.get('open') || '').split('-');
    if (kind === 'coaching_note' && Number(id)) showNote(Number(id));
    if (kind === 'training_idea' && Number(id)) { tabset.show('ideas'); showIdea(Number(id)); }
    const fromObservation = Number(params.get('from_observation'));
    if (fromObservation) {
      const asIdea = params.get('as') === 'idea';
      const saved = await startFromObservation(fromObservation, asIdea ? 'idea' : 'note');
      history.replaceState(null, '', 'notebook.html');
      if (saved) {
        toast(asIdea ? 'Training idea saved, linked to the observation' : 'Note saved, linked to the observation');
        tabset.show(asIdea ? 'ideas' : 'notes');
      }
    }
  } catch (error) {
    clear(page.content).append(errorNote(error, start));
  }
}

start();
