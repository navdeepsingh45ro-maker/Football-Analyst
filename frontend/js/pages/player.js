// One player's profile: biography, measured statistics, dated assessments,
// match history, observations, saved diagrams and the development timeline.
//
// Each tab below is a function that fetches what it needs and returns elements.
// After anything is changed, show() rebuilds the page so every count is current.

import { api, ApiError, vocabulary } from '../api.js';
import { matchLabel } from '../components/match-form.js';
import { observationDialog } from '../components/observation-form.js';
import { observationList, openObservation } from '../components/observation-list.js';
import { playerDialog } from '../components/player-form.js';
import { clear, h, queryParam } from '../dom.js';
import { downloadFile, slug, surfaceToPng } from '../editor/export-image.js';
import { renderSnapshot } from '../editor/workspace.js';
import { formatDate, formatMoment, humanize, plural, todayIso } from '../format.js';
import { load, mountPage } from '../layout.js';
import {
  confirmDialog, deleteWithDependencies, emptyState, formDialog, magnet, magnetKindFor, matchDate, orUnknown,
  pips, table, tabs, toast, unknown, videoClock,
} from '../ui.js';

const playerId = Number(queryParam('id'));
const page = mountPage({ active: 'players.html', title: 'Player' });
page.before.append(h('a', { class: 'back-link', href: 'players.html' }, 'All players'));
page.heading.classList.add('row');

let tabset = null;

// ── Overview ─────────────────────────────────────────────────────────────────
async function overviewTab(player) {
  const assessments = await api.get(`/api/players/${player.id}/assessments`);
  const latest = assessments[0];
  const born = player.date_of_birth ? `${formatDate(player.date_of_birth)} (age ${player.age})` : null;
  const facts = [
    ['Date of birth', born],
    ['Nationality', player.nationality],
    ['Height', player.height_cm ? `${player.height_cm} cm` : null],
    ['Preferred foot', player.preferred_foot ? humanize(player.preferred_foot) : null],
    ['Primary position', player.primary_position],
    ['Other positions', player.secondary_positions.join(', ')],
    ['Current club', player.current_team && player.current_team.name],
    ['National team', player.national_team && player.national_team.name],
    ['Shirt number', player.shirt_number],
    ['Profile created', formatMoment(player.created_at)],
    ['Last updated', formatMoment(player.updated_at)],
  ];
  return h('div', { class: 'columns' },
    h('section', {},
      h('div', { class: 'section-head' }, h('h2', {}, 'Biography')),
      player.photo_url ? h('img', {
        class: 'photo', src: player.photo_url, alt: `Photo of ${player.full_name}`, loading: 'lazy',
        referrerPolicy: 'no-referrer',  // the site hosting the picture is not told which page asked for it
        onerror: (event) => { event.target.hidden = true; },  // a dead link shows nothing rather than a broken image
      }) : null,
      h('dl', { class: 'facts' }, facts.map(([label, value]) => [h('dt', {}, label), h('dd', {}, orUnknown(value))])),
      player.notes ? [h('h3', { class: 'section' }, 'Notes'), h('p', { class: 'prose' }, player.notes)] : null,
      h('p', { class: 'small muted section' }, 'A dash means not known. Nothing here is filled in by the app.')),
    h('section', {},
      h('div', { class: 'section-head' }, h('h2', {}, 'Latest assessment'),
        h('button', { type: 'button', class: 'button small quiet', onclick: () => tabset.show('assessments') }, 'All assessments')),
      latest
        ? [h('p', { class: 'muted' }, `Your opinion on ${formatDate(latest.assessed_on)}`, latest.basis ? `, based on ${latest.basis}` : '', '.'),
          h('p', { class: 'prose' }, latest.summary || 'No summary written.')]
        : emptyState('No assessment yet. An assessment records what you think of the player on a given date.',
          h('button', { type: 'button', class: 'button', onclick: () => tabset.show('assessments') }, 'Write one'))));
}

// ── Statistics ───────────────────────────────────────────────────────────────
function parseExtraMetrics(text) {
  // "saves=4, clearances=7" -> { saves: 4, clearances: 7 }
  const metrics = {};
  for (const part of (text || '').split(',').map((piece) => piece.trim()).filter(Boolean)) {
    const [name, value] = part.split('=').map((piece) => piece.trim());
    if (!name || value === undefined || value === '' || !Number.isFinite(Number(value))) {
      throw new ApiError(422, 'Write other numbers as name=value, separated by commas. Example: saves=4, clearances=7');
    }
    metrics[name] = Number(value);
  }
  return metrics;
}

async function statisticDialog(player, scope, existing = null) {
  const [vocab, matches, seasons, competitions, teams] = await Promise.all([
    vocabulary(), api.get('/api/matches'), api.get('/api/seasons'), api.get('/api/competitions'), api.get('/api/teams'),
  ]);
  const context = scope === 'match'
    ? [{ name: 'match_id', label: 'Match', type: 'select', numeric: true, required: true,
      options: matches.map((match) => [match.id, matchLabel(match, formatDate)]) }]
    : [{ name: 'season', label: 'Season', type: 'suggest', options: seasons.map((s) => s.name), required: true, width: 'third', placeholder: '2025/26' },
      { name: 'competition', label: 'Competition', type: 'suggest', options: competitions.map((c) => c.name), width: 'third' },
      { name: 'team', label: 'Team', type: 'suggest', options: teams.map((t) => t.name), width: 'third' }];
  const numbers = vocab.stat_fields
    .filter((name) => !(scope === 'match' && name === 'appearances'))
    .map((name) => ({ name, label: humanize(name), type: 'number', min: 0, width: 'third' }));

  const values = existing ? {
    ...existing,
    match_id: existing.match ? existing.match.id : null,
    season: existing.season && existing.season.name,
    competition: existing.competition && existing.competition.name,
    team: existing.team && existing.team.name,
    extra: Object.entries(existing.extra_metrics).map(([name, value]) => `${name}=${value}`).join(', '),
  } : {};

  return formDialog({
    title: `${existing ? 'Edit' : 'Add'} ${scope} stat line for ${player.full_name}`,
    intro: 'Leave a number empty if you do not know it. Empty is stored as "not recorded", which is not the same as 0.',
    wide: true,
    fields: [
      ...context, ...numbers,
      { name: 'extra', label: 'Other numbers', help: 'Position-specific, as name=value pairs. Example: saves=4, clearances=7' },
      { name: 'source', label: 'Where these numbers come from', required: true, width: 'half',
        help: 'For example "Counted myself from the video", or the name of a website' },
      { name: 'source_url', label: 'Link to the source', type: 'url', width: 'half' },
      { name: 'notes', label: 'Notes', type: 'textarea', rows: 2 },
    ],
    values,
    submitLabel: existing ? 'Save changes' : 'Add stat line',
    onSubmit: ({ extra, ...read }) => {
      const body = { scope, ...read, extra_metrics: parseExtraMetrics(extra) };
      return existing ? api.put(`/api/statistics/${existing.id}`, body) : api.post(`/api/players/${player.id}/statistics`, body);
    },
  });
}

async function statisticsTab(player) {
  const lines = await api.get(`/api/players/${player.id}/statistics`);
  const pair = (part, whole) => (part === null && whole === null ? unknown() : `${part ?? '–'} / ${whole ?? '–'}`);
  const add = (scope) => h('button', { type: 'button', class: 'button', onclick: async () => {
    if (await statisticDialog(player, scope)) { toast('Stat line added'); show(); }
  } }, `Add ${scope} line`);

  const body = lines.length ? table([
    { label: 'Covers', cell: (line) => [line.context, h('div', { class: 'small muted' }, line.scope === 'match' ? 'One match' : 'Season total')] },
    { label: 'Apps', numeric: true, cell: (line) => orUnknown(line.appearances) },
    { label: 'Minutes', numeric: true, cell: (line) => orUnknown(line.minutes_played) },
    { label: 'Goals', numeric: true, cell: (line) => orUnknown(line.goals) },
    { label: 'Assists', numeric: true, cell: (line) => orUnknown(line.assists) },
    { label: 'Shots on target / shots', numeric: true, cell: (line) => pair(line.shots_on_target, line.shots) },
    { label: 'Chances created', numeric: true, cell: (line) => orUnknown(line.chances_created) },
    { label: 'Passes completed / attempted', numeric: true, cell: (line) => pair(line.passes_completed, line.passes_attempted) },
    { label: 'Dribbles', numeric: true, cell: (line) => orUnknown(line.dribbles_completed) },
    { label: 'Duels won / contested', numeric: true, cell: (line) => pair(line.duels_won, line.duels_contested) },
    { label: 'Other', cell: (line) => orUnknown(Object.entries(line.extra_metrics).map(([name, value]) => `${name} ${value}`).join(', ')) },
    { label: 'Source', cell: (line) => (line.source_url
      ? h('a', { href: line.source_url, target: '_blank', rel: 'noopener noreferrer' }, line.source) : line.source) },
    { label: '', cell: (line) => h('div', { class: 'row' },
      h('button', { type: 'button', class: 'button small', onclick: async () => {
        if (await statisticDialog(player, line.scope, line)) { toast('Stat line saved'); show(); }
      } }, 'Edit'),
      h('button', { type: 'button', class: 'button small danger', onclick: async () => {
        if (!await confirmDialog({ title: 'Delete this stat line?', message: `${line.context}. This cannot be undone.`, confirmLabel: 'Delete stat line', danger: true })) return;
        await api.delete(`/api/statistics/${line.id}`);
        toast('Stat line deleted');
        show();
      } }, 'Delete')) },
  ], lines) : emptyState('No statistics recorded. Add a season total or the numbers from a single match.');

  return [
    h('div', { class: 'row spread' },
      h('p', { class: 'muted prose' }, 'Measured numbers, each with its source. A dash means not recorded, which is different from zero.'),
      h('div', { class: 'row' }, add('season'), add('match'))),
    body,
  ];
}

// ── Scouting assessments ─────────────────────────────────────────────────────
async function assessmentDialog(player, vocab, { existing = null, startFrom = null } = {}) {
  const source = existing || startFrom;
  const values = source ? { ...source } : {};
  if (source) for (const rating of source.ratings) values[`rating_${rating.attribute}`] = rating.rating;
  if (!existing) { values.assessed_on = todayIso(); values.basis = null; }

  return formDialog({
    title: existing ? `Edit the assessment of ${formatDate(existing.assessed_on)}` : `New assessment of ${player.full_name}`,
    intro: existing
      ? 'Use this to correct a mistake. If your opinion has changed, add a new assessment instead, so the old one stays on record.'
      : 'This is saved as a new dated entry. Earlier assessments are not changed.',
    wide: true,
    fields: [
      { name: 'assessed_on', label: 'Date of this opinion', type: 'date', required: true, width: 'third' },
      { name: 'basis', label: 'Based on', width: 'half', placeholder: 'e.g. three league matches in October', maxLength: 300 },
      { name: 'summary', label: 'Summary', type: 'textarea', rows: 3 },
      ...Object.entries(vocab.assessment_sections).map(([name, label]) => ({ name, label, type: 'textarea', rows: 2, width: 'half' })),
      { type: 'heading', label: 'Ratings' },
      { type: 'note', label: `${vocab.rating_scale_note} Leave an attribute unrated if you have not seen enough.` },
      ...Object.entries(vocab.rating_attributes).map(([name, label]) => ({
        name: `rating_${name}`, label, type: 'select', numeric: true, emptyLabel: 'Not rated', width: 'third',
        options: [1, 2, 3, 4, 5].map((value) => [value, `${value}: ${vocab.rating_scale[value]}`]),
      })),
    ],
    values,
    submitLabel: existing ? 'Save changes' : 'Save assessment',
    onSubmit: (read) => {
      const body = { ratings: [] };
      for (const [name, value] of Object.entries(read)) {
        if (!name.startsWith('rating_')) body[name] = value;
        else if (value !== null) {
          const attribute = name.slice('rating_'.length);
          const before = existing && existing.ratings.find((rating) => rating.attribute === attribute);
          body.ratings.push({ attribute, rating: value, note: before ? before.note : null });
        }
      }
      return existing ? api.put(`/api/assessments/${existing.id}`, body) : api.post(`/api/players/${player.id}/assessments`, body);
    },
  });
}

function ratingHistoryTable(history) {
  const rated = history.trends.filter((trend) => trend.latest_rating !== null);
  if (!rated.length) return null;
  const dates = rated[0].points;
  const change = (value) => (value === null ? unknown('Rated fewer than twice') : (value > 0 ? `+${value}` : String(value)));
  return h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Attribute'),
      dates.map((point) => h('th', { class: 'num', scope: 'col' }, formatDate(point.assessed_on))),
      h('th', { class: 'num', scope: 'col' }, 'Change, first to latest'))),
    h('tbody', {}, rated.map((trend) => h('tr', {}, h('td', {}, trend.label),
      trend.points.map((point) => h('td', { class: 'num numeric' }, point.rating === null ? unknown('Not rated that time') : point.rating)),
      h('td', { class: 'num numeric' }, change(trend.change)))))));
}

async function assessmentsTab(player, vocab) {
  const [assessments, history] = await Promise.all([
    api.get(`/api/players/${player.id}/assessments`), api.get(`/api/players/${player.id}/rating-history`),
  ]);
  const saved = (message) => { toast(message); show(); };
  const buttons = h('div', { class: 'row' },
    h('button', { type: 'button', class: 'button primary', onclick: async () => {
      if (await assessmentDialog(player, vocab)) saved('Assessment saved');
    } }, 'New assessment'),
    assessments.length ? h('button', { type: 'button', class: 'button', onclick: async () => {
      if (await assessmentDialog(player, vocab, { startFrom: assessments[0] })) saved('Assessment saved');
    } }, 'New, starting from the latest') : null);

  const intro = h('div', { class: 'row spread' },
    h('p', { class: 'muted prose' }, 'Each assessment is your opinion on one date. Adding a new one never changes the older ones, '
      + 'so you can see how your view of the player developed.'), buttons);
  if (!assessments.length) return [intro, emptyState('No assessments yet.')];

  const historyTable = ratingHistoryTable(history);
  const scaleText = Object.entries(vocab.rating_scale).map(([value, label]) => `${value} ${label.toLowerCase()}`).join(', ');

  return [
    intro,
    historyTable ? h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'How your ratings changed')),
      historyTable,
      h('p', { class: 'small muted' }, `${history.scale_note} Scale: ${scaleText}. "Change" compares your first and latest rating; `
        + 'it shows how your opinion moved, not a measurement of the player.')) : null,
    h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'Assessments, newest first')),
      assessments.map((assessment) => h('article', { class: 'sheet stack section' },
        h('div', { class: 'row spread' },
          h('h3', {}, formatDate(assessment.assessed_on), assessment.basis ? h('span', { class: 'muted' }, `, based on ${assessment.basis}`) : null),
          h('div', { class: 'row' },
            h('button', { type: 'button', class: 'button small', onclick: async () => {
              if (await assessmentDialog(player, vocab, { existing: assessment })) saved('Assessment saved');
            } }, 'Edit'),
            h('button', { type: 'button', class: 'button small danger', onclick: async () => {
              if (!await confirmDialog({ title: `Delete the assessment of ${formatDate(assessment.assessed_on)}?`,
                message: 'This removes that opinion from the player\'s history. It cannot be undone.', confirmLabel: 'Delete assessment', danger: true })) return;
              await api.delete(`/api/assessments/${assessment.id}`);
              saved('Assessment deleted');
            } }, 'Delete'))),
        assessment.summary ? h('p', { class: 'prose' }, assessment.summary) : null,
        h('dl', { class: 'facts' }, Object.entries(vocab.assessment_sections)
          .filter(([name]) => assessment[name])
          .map(([name, label]) => [h('dt', {}, label), h('dd', { class: 'prose' }, assessment[name])])),
        assessment.ratings.length ? h('div', { class: 'row' }, assessment.ratings.map((rating) => h('span', { class: 'tag' },
          vocab.rating_attributes[rating.attribute], ' ', pips(rating.rating, vocab.rating_scale), ` ${rating.rating}`))) : null,
        h('p', { class: 'small muted' }, `Written ${formatMoment(assessment.created_at)}`,
          assessment.updated_at !== assessment.created_at ? `, corrected ${formatMoment(assessment.updated_at)}` : '')))),
  ];
}

// ── Observations, diagrams, history ──────────────────────────────────────────
async function observationsTab(player) {
  const result = await api.get('/api/observations', { player_id: player.id, limit: 500 });
  return [
    h('div', { class: 'row spread' },
      h('p', { class: 'muted' }, `${plural(result.total, 'observation')} involving ${player.full_name}. `,
        h('a', { href: `observations.html?player_id=${player.id}` }, 'Filter and search them')),
      h('button', { type: 'button', class: 'button', onclick: async () => {
        if (await observationDialog(null, { player_ids: [player.id] })) { toast('Observation added'); show(); }
      } }, 'Add observation')),
    observationList(result.items, {
      onChanged: show,
      emptyMessage: 'No observations yet. Add a written one here, or open a match under Video analysis to draw one.',
    }),
  ];
}

async function diagramsTab(player) {
  const summaries = await api.get(`/api/players/${player.id}/diagrams`);
  if (!summaries.length) {
    return emptyState('No diagrams yet. They are created when you press Analyse on a paused video and save the drawing.');
  }
  const snapshots = await Promise.all(summaries.map((summary) => api.get(`/api/snapshots/${summary.id}`)));
  return h('div', { class: 'diagram-grid' }, snapshots.map((snapshot, index) => {
    const summary = summaries[index];
    const view = renderSnapshot(snapshot);
    return h('article', { class: 'diagram-card stack' },
      h('div', { class: 'row' },
        videoClock(summary.video_time_seconds),
        h('strong', {}, snapshot.title || summary.observation_category || 'Diagram')),
      summary.match ? h('div', { class: 'small muted' }, summary.match.title, ', ', matchDate(summary.match.match_date)) : null,
      view.element,
      h('div', { class: 'row' },
        h('button', { type: 'button', class: 'button small', onclick: () => openObservation(summary.observation_id, { onChanged: show }) }, 'Open observation'),
        h('a', { class: 'button small', href: `video.html?observation=${summary.observation_id}&snapshot=${snapshot.id}` }, 'Edit drawing'),
        Object.entries(view.surfaces).map(([layer, surface]) => h('button', {
          type: 'button', class: 'button small',
          onclick: async () => downloadFile(await surfaceToPng(surface), `${slug(snapshot.title || player.full_name)}-${layer}.png`),
        }, `Save ${layer} as picture`))));
  }));
}

const EVENT_LABELS = { assessment: 'Assessment', observation: 'Observation', appearance: 'Match', note: 'Notebook' };

function eventLink(event) {
  if (event.kind === 'observation') {
    return h('a', { href: `observations.html?open=${event.record_id}`,
      onclick: (click) => { click.preventDefault(); openObservation(event.record_id, { onChanged: show }); } }, event.title);
  }
  if (event.kind === 'appearance') return h('a', { href: `match.html?id=${event.match_id}` }, event.title);
  if (event.kind === 'note') return h('a', { href: `notebook.html?open=coaching_note-${event.record_id}` }, event.title);
  return h('a', { href: '#assessments', onclick: (click) => { click.preventDefault(); tabset.show('assessments'); } }, event.title);
}

function timelineTable(events) {
  return table([
    { label: 'Date', cell: (event) => formatDate(event.date) || h('span', { class: 'unknown' }, 'date unknown') },
    { label: 'Kind', cell: (event) => EVENT_LABELS[event.kind] },
    { label: 'What', cell: (event) => [eventLink(event), event.detail ? h('div', { class: 'small muted' }, event.detail) : null] },
  ], events);
}

async function matchesTab(player) {
  const events = (await api.get(`/api/players/${player.id}/timeline`)).filter((event) => event.kind === 'appearance');
  if (!events.length) {
    return emptyState('Not in any lineup yet. Open a match and add the player to its lineup.',
      h('a', { class: 'button', href: 'matches.html' }, 'Go to matches'));
  }
  return timelineTable(events);
}

async function developmentTab(player) {
  const events = await api.get(`/api/players/${player.id}/timeline`);
  if (!events.length) return emptyState('Nothing recorded about this player yet.');
  return [
    h('p', { class: 'muted prose' }, 'Everything recorded about the player, newest first. The date is when it happened '
      + '(the match date, the assessment date), not when you typed it in.'),
    timelineTable(events),
  ];
}

// ── The page ─────────────────────────────────────────────────────────────────
function show() {
  return load(page.content, async () => {
    const [player, vocab] = await Promise.all([api.get(`/api/players/${playerId}`), vocabulary()]);
    page.setTitle(player.full_name);
    clear(page.heading).append(
      magnet(magnetKindFor(player.primary_position, vocab.position_groups), player.shirt_number || player.primary_position || '', { large: true }),
      player.full_name);
    page.setLede([player.primary_position, player.current_team && player.current_team.name,
      player.age !== null ? `${player.age} years old` : null, player.nationality].filter(Boolean).join(', '));

    clear(page.actions).append(
      h('button', { type: 'button', class: 'button', onclick: async () => {
        if (await playerDialog(player)) { toast('Player saved'); show(); }
      } }, 'Edit'),
      h('button', { type: 'button', class: 'button danger', onclick: async () => {
        const deleted = await deleteWithDependencies({
          api, path: `/api/players/${player.id}`, name: player.full_name,
          describe: (found) => [
            plural(found.assessments, 'scouting assessment'),
            plural(found.statistics, 'stat line'),
            plural(found.appearances, 'lineup entry', 'lineup entries'),
            `${plural(found.observations_deleted, 'observation')} about this player alone, with their diagrams`,
            `(${plural(found.observations_kept, 'observation')} shared with other players will be kept, without this player)`,
          ],
        });
        if (deleted) window.location.href = 'players.html';
      } }, 'Delete'));

    const counts = player.counts;
    tabset = tabs([
      { id: 'overview', label: 'Overview', render: () => overviewTab(player) },
      { id: 'statistics', label: 'Statistics', count: counts.statistics, render: () => statisticsTab(player) },
      { id: 'assessments', label: 'Assessments', count: counts.assessments, render: () => assessmentsTab(player, vocab) },
      { id: 'matches', label: 'Match history', count: counts.appearances, render: () => matchesTab(player) },
      { id: 'observations', label: 'Observations', count: counts.observations, render: () => observationsTab(player) },
      { id: 'diagrams', label: 'Diagrams', count: counts.diagrams, render: () => diagramsTab(player) },
      { id: 'development', label: 'Development', render: () => developmentTab(player) },
    ], 'overview');
    return tabset.element;
  });
}

if (!playerId) {
  page.content.append(emptyState('No player was chosen.', h('a', { class: 'button', href: 'players.html' }, 'Go to players')));
} else {
  show();
}
