// Reports: patterns across matches, player comparisons, a printable player report,
// and the optional AI assistance.
//
// EVERY NUMBER HERE IS A COUNT OF YOUR OWN RECORDS, and each one links to the
// observations it counts. The page keeps four kinds of information apart and
// says which is which:
//   recorded facts          what you entered
//   calculated statistics   counts and shares worked out from those records
//   your interpretations    notes and assessments
//   AI hypotheses           only on the last tab, labelled, and off unless you enable it

import { api, ApiError, vocabulary } from '../api.js';
import { matchLabel } from '../components/match-form.js';
import { openObservation } from '../components/observation-list.js';
import { rankedBars, zoneGrid } from '../charts.js';
import { clear, h } from '../dom.js';
import { buildForm } from '../forms.js';
import { formatDate, formatMoment, humanize, plural } from '../format.js';
import { errorNote, mountPage } from '../layout.js';
import { emptyState, orUnknown, pips, tabs, toast, unknown } from '../ui.js';

const page = mountPage({
  active: 'reports.html', title: 'Reports',
  lede: 'Counts and comparisons worked out from your own records. Every figure opens the observations behind it.',
});

function limitations(notes) {
  return h('div', { class: 'note caution' }, h('strong', {}, 'How far these numbers go'),
    h('ul', {}, notes.map((note) => h('li', {}, note))));
}

function section(title, ...body) {
  return h('section', { class: 'section' }, h('div', { class: 'section-head' }, h('h2', {}, title)), body);
}

const idsLink = (ids) => `observations.html?ids=${ids.join(',')}`;

// ── Patterns ─────────────────────────────────────────────────────────────────
async function patternsTab() {
  const [vocab, players, matches, teams, dimensions] = await Promise.all([
    vocabulary(), api.get('/api/players'), api.get('/api/matches'), api.get('/api/teams'), api.get('/api/analytics/dimensions'),
  ]);
  const dimensionOptions = Object.entries(dimensions);
  // One row of filters, above everything it applies to. All three views below use the same selection.
  const form = buildForm([
    { name: 'player_id', label: 'Player', type: 'select', emptyLabel: 'Any player', options: players.map((p) => [p.id, p.full_name]) },
    { name: 'match_id', label: 'Match', type: 'select', emptyLabel: 'Any match', options: matches.map((m) => [m.id, matchLabel(m, formatDate)]) },
    { name: 'team_id', label: 'Team in the match', type: 'select', emptyLabel: 'Any team', options: teams.map((t) => [t.id, t.name]) },
    { name: 'movement_category', label: 'Movement', type: 'suggest', options: vocab.movement_categories },
    { name: 'outcome', label: 'Outcome', type: 'suggest', options: vocab.outcomes },
    { name: 'date_from', label: 'Match date from', type: 'date' },
    { name: 'date_to', label: 'Match date to', type: 'date' },
  ], Object.fromEntries(new URLSearchParams(window.location.search)));
  form.element.className = 'filters';

  const choose = (id, label, options, value) => {
    const select = h('select', { id }, options.map(([key, text]) => h('option', { value: key }, text)));
    select.value = value;
    return { select, field: h('div', { class: 'field' }, h('label', { for: id }, label), select) };
  };
  const groupBy = choose('group-by', 'Count by', dimensionOptions, 'movement_category');
  const point = choose('zone-point', 'Show where movements', [['start', 'started'], ['end', 'ended']], 'end');
  const rows = choose('cross-rows', 'Rows', dimensionOptions, 'movement_category');
  const columns = choose('cross-columns', 'Columns', dimensionOptions, 'outcome');
  const output = h('div', {});

  const filters = () => Object.fromEntries(Object.entries(form.read().values).filter(([, value]) => value !== null && value !== ''));

  async function refresh() {
    output.classList.add('is-stale');  // keep the old numbers in place, dimmed, until the new ones arrive
    const chosen = filters();
    try {
      const [pattern, zones, cross] = await Promise.all([
        api.get('/api/analytics/patterns', { ...chosen, group_by: groupBy.select.value }),
        api.get('/api/analytics/zones', { ...chosen, point: point.select.value }),
        api.get('/api/analytics/crosstab', { ...chosen, rows: rows.select.value, columns: columns.select.value })
          .catch((error) => ({ error: error.message })),
      ]);
      const linkFor = (group) => (group.filter
        ? `observations.html?${new URLSearchParams({ ...chosen, ...group.filter })}`
        : idsLink(group.observation_ids));
      // Caveats about the selection as a whole are said once, at the top. Each
      // section below then adds only the ones that are about that view.
      const lists = [pattern.limitations, zones.limitations, cross.limitations || []];
      const shared = pattern.limitations.filter((note) => lists.every((list) => list.includes(note)));
      const only = (notes) => {
        const specific = notes.filter((note) => !shared.includes(note));
        return specific.length ? limitations(specific) : null;
      };

      clear(output).append(
        h('p', {}, h('strong', {}, plural(pattern.total, 'observation')), ' match this selection. ',
          h('a', { href: `observations.html?${new URLSearchParams(chosen)}` }, 'List them')),
        limitations(shared),

        section(`Counted by: ${pattern.heading.toLowerCase()}`,
          h('div', { class: 'filters' }, groupBy.field),
          pattern.groups.length ? rankedBars(pattern.groups, { heading: pattern.heading, linkFor }) : emptyState('Nothing to count for this selection.'),
          only(pattern.limitations)),

        section('On the pitch',
          h('div', { class: 'filters' }, point.field),
          h('div', { class: 'columns' },
            zoneGrid(zones, { linkFor: idsLink }),
            h('div', { class: 'stack' },
              h('p', {}, `${zones.placed} of ${zones.total} observations have a movement drawn on a pitch diagram and are shown on the grid.`),
              zones.without_position.count ? h('p', {}, h('a', { href: idsLink(zones.without_position.observation_ids) },
                `${plural(zones.without_position.count, 'observation')} without a drawn movement`), ' cannot be placed.') : null,
              zones.off_pitch.count ? h('p', {}, h('a', { href: idsLink(zones.off_pitch.observation_ids) },
                `${zones.off_pitch.count} drawn off the pitch`)) : null,
              only(zones.limitations)))),

        section('Two things side by side',
          h('div', { class: 'filters' }, rows.field, columns.field),
          cross.error ? h('div', { class: 'note caution' }, cross.error) : crossTable(cross),
          cross.error ? null : only(cross.limitations)),
      );
    } catch (error) {
      clear(output).append(errorNote(error, refresh));
    } finally {
      output.classList.remove('is-stale');
    }
  }

  for (const control of [form.element, groupBy.select, point.select, rows.select, columns.select]) {
    control.addEventListener('change', refresh);
  }
  refresh();
  return [form.element, output];
}

function crossTable(cross) {
  if (!cross.total) return emptyState('Nothing to count for this selection.');
  const cell = (entry) => h('td', { class: entry.count ? 'num count-cell' : 'num count-cell zero' },
    entry.count ? h('a', { href: idsLink(entry.observation_ids), title: 'Show these observations' }, entry.count) : '0');
  return h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {},
      h('th', { scope: 'col' }, `${cross.row_heading} \\ ${cross.column_heading}`),
      cross.column_labels.map((label) => h('th', { scope: 'col', class: 'num' }, label)),
      h('th', { scope: 'col', class: 'num' }, 'Total'))),
    h('tbody', {}, cross.row_labels.map((label, index) => h('tr', {},
      h('td', {}, label), cross.cells[index].map(cell), h('td', { class: 'num numeric' }, cross.row_totals[index])))),
    h('tfoot', {}, h('tr', {}, h('td', {}, 'Total'),
      cross.column_totals.map((total) => h('td', { class: 'num numeric' }, total)),
      h('td', { class: 'num numeric' }, cross.total)))));
}

// ── Compare players ──────────────────────────────────────────────────────────
async function compareTab() {
  const [players, seasons, competitions, vocab] = await Promise.all([
    api.get('/api/players'), api.get('/api/seasons'), api.get('/api/competitions'), vocabulary(),
  ]);
  if (players.length < 2) return emptyState('Record at least two players to compare them.');

  const form = buildForm([
    { name: 'player_ids', label: 'Players to compare (two or more)', type: 'choices', options: players.map((p) => [p.id, p.full_name]) },
    { name: 'basis', label: 'Use', type: 'select', required: true, width: 'third',
      options: [['season', 'Season stat lines'], ['match', 'Single-match stat lines']] },
    { name: 'season_id', label: 'Season', type: 'select', emptyLabel: 'Any season', width: 'third', options: seasons.map((s) => [s.id, s.name]) },
    { name: 'competition_id', label: 'Competition', type: 'select', emptyLabel: 'Any competition', width: 'third', options: competitions.map((c) => [c.id, c.name]) },
  ]);
  const output = h('div', { class: 'section' });

  async function refresh() {
    const { values } = form.read();
    if (values.player_ids.length < 2) {
      clear(output).append(emptyState('Tick at least two players.'));
      return;
    }
    output.classList.add('is-stale');
    try {
      const data = await api.get('/api/analytics/compare-players', {
        player_ids: values.player_ids.join(','), basis: values.basis,
        season_id: values.season_id, competition_id: values.competition_id,
      });
      const column = (cellFor) => data.players.map((row) => h('td', { class: 'num' }, cellFor(row)));
      const number = (value, digits = 0) => (value === null || value === undefined ? unknown() : Number(value).toFixed(digits));
      const rate = (entry) => (entry.value === null ? unknown() : [`${Math.round(entry.value * 100)}%`, h('div', { class: 'small muted' }, entry.from)]);
      const perNinety = new Set(data.stat_fields.filter((field) => !['appearances', 'minutes_played'].includes(field)));

      clear(output).append(
        limitations(data.limitations),
        h('div', { class: 'table-wrap section' }, h('table', {},
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Measured (from stat lines)'),
            data.players.map((row) => h('th', { scope: 'col', class: 'num' },
              h('a', { href: `player.html?id=${row.player.id}#statistics` }, row.player.full_name),
              h('div', {}, row.position_group || 'position not recorded'))))),
          h('tbody', {},
            h('tr', {}, h('td', {}, 'Stat lines used'), column((row) => row.stat_lines)),
            h('tr', {}, h('td', {}, 'Covers'), column((row) => (row.covers.length ? row.covers.join('; ') : unknown()))),
            h('tr', {}, h('td', {}, 'Source'), column((row) => (row.sources.length ? row.sources.join('; ') : unknown()))),
            data.stat_fields.map((field) => h('tr', {}, h('td', {}, humanize(field)),
              column((row) => [number(row.totals[field]),
                perNinety.has(field) && row.per_90[field] !== null
                  ? h('div', { class: 'small muted' }, `${row.per_90[field].toFixed(2)} per 90 min`) : null]))),
            h('tr', {}, h('td', {}, 'Shots on target'), column((row) => rate(row.rates.shot_accuracy))),
            h('tr', {}, h('td', {}, 'Passes completed'), column((row) => rate(row.rates.pass_completion))),
            h('tr', {}, h('td', {}, 'Duels won'), column((row) => rate(row.rates.duel_success)))))),
        h('p', { class: 'small muted' }, 'A dash means not recorded, which is not the same as zero. "Per 90 min" uses only stat lines that record both the number and the minutes.'),

        section('Your latest ratings (opinions, not measurements)',
          h('div', { class: 'table-wrap' }, h('table', {},
            h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Attribute'),
              data.players.map((row) => h('th', { scope: 'col', class: 'num' }, row.player.full_name,
                h('div', {}, row.latest_assessment ? `assessed ${formatDate(row.latest_assessment.assessed_on)}` : 'no assessment'))))),
            h('tbody', {}, Object.entries(vocab.rating_attributes).map(([attribute, label]) => h('tr', {}, h('td', {}, label),
              column((row) => {
                const rating = row.latest_assessment && row.latest_assessment.ratings[attribute];
                return rating ? [pips(rating, vocab.rating_scale), ` ${rating}`] : unknown('Not rated');
              })))))),
          h('p', { class: 'small muted' }, data.rating_scale_note)));
    } catch (error) {
      clear(output).append(errorNote(error, refresh));
    } finally {
      output.classList.remove('is-stale');
    }
  }
  form.element.addEventListener('change', refresh);
  refresh();
  return [form.element, output];
}

// ── Printable player report ──────────────────────────────────────────────────
async function buildPlayerReport(playerId) {
  const [player, assessments, history, statistics, observations, byMovement, byOutcome, byOpponent, vocab] = await Promise.all([
    api.get(`/api/players/${playerId}`), api.get(`/api/players/${playerId}/assessments`),
    api.get(`/api/players/${playerId}/rating-history`), api.get(`/api/players/${playerId}/statistics`),
    api.get('/api/observations', { player_id: playerId, limit: 500 }),
    api.get('/api/analytics/patterns', { player_id: playerId, group_by: 'movement_category' }),
    api.get('/api/analytics/patterns', { player_id: playerId, group_by: 'outcome' }),
    api.get('/api/analytics/patterns', { player_id: playerId, group_by: 'opponent' }),
    vocabulary(),
  ]);
  const latest = assessments[0];
  const facts = [
    ['Position', [player.primary_position, ...player.secondary_positions].filter(Boolean).join(', ')],
    ['Club', player.current_team && player.current_team.name], ['National team', player.national_team && player.national_team.name],
    ['Born', player.date_of_birth ? `${formatDate(player.date_of_birth)} (age ${player.age})` : null],
    ['Nationality', player.nationality], ['Height', player.height_cm ? `${player.height_cm} cm` : null],
    ['Preferred foot', player.preferred_foot ? humanize(player.preferred_foot) : null],
  ];
  // Wide tables scroll inside their own box, so a narrow screen never has to scroll the whole page sideways.
  const scrollable = (table) => h('div', { class: 'table-wrap' }, table);
  const countTable = (pattern) => scrollable(h('table', {},
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, pattern.heading), h('th', { scope: 'col', class: 'num' }, 'Observations'),
      h('th', { scope: 'col' }, 'Record numbers'))),
    h('tbody', {}, pattern.groups.map((group) => h('tr', {}, h('td', {}, group.label), h('td', { class: 'num numeric' }, group.count),
      h('td', { class: 'small' }, group.observation_ids.map((id) => `#${id}`).join(', ')))))));
  const rated = history.trends.filter((trend) => trend.latest_rating !== null);

  return h('article', { class: 'sheet stack' },
    h('div', { class: 'row spread' },
      h('h2', {}, `Scouting report: ${player.full_name}`),
      h('button', { type: 'button', class: 'button no-print', onclick: () => window.print() }, 'Print or save as PDF')),
    h('p', { class: 'small muted' }, `Compiled ${formatMoment(new Date().toISOString())} from your own records. `
      + 'Numbers in brackets such as #12 are observation numbers, so every statement can be checked.'),

    section('Recorded facts',
      h('dl', { class: 'facts' }, facts.map(([label, value]) => [h('dt', {}, label), h('dd', {}, orUnknown(value))]))),

    section('Measured statistics',
      statistics.length ? h('div', { class: 'table-wrap' }, h('table', {},
        h('thead', {}, h('tr', {}, ['Covers', 'Min', 'Goals', 'Assists', 'Shots', 'On target', 'Source']
          .map((label, index) => h('th', { scope: 'col', class: index > 0 && index < 6 ? 'num' : null }, label)))),
        h('tbody', {}, statistics.map((line) => h('tr', {}, h('td', {}, line.context),
          [line.minutes_played, line.goals, line.assists, line.shots, line.shots_on_target]
            .map((value) => h('td', { class: 'num' }, orUnknown(value))),
          h('td', {}, line.source))))))
        : h('p', { class: 'muted' }, 'No statistics recorded.'),
      h('p', { class: 'small muted' }, 'A dash means not recorded, not zero.')),

    section('Your assessment (opinion)',
      latest ? [
        h('p', { class: 'muted' }, `Dated ${formatDate(latest.assessed_on)}${latest.basis ? `, based on ${latest.basis}` : ''}. `
          + `${assessments.length > 1 ? `${assessments.length} assessments on record.` : 'The only assessment on record.'}`),
        latest.summary ? h('p', { class: 'prose' }, latest.summary) : null,
        h('dl', { class: 'facts' }, Object.entries(vocab.assessment_sections).filter(([name]) => latest[name])
          .map(([name, label]) => [h('dt', {}, label), h('dd', { class: 'prose' }, latest[name])])),
        rated.length ? scrollable(h('table', {},
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Rating, 1 to 5'), h('th', { scope: 'col', class: 'num' }, 'First'),
            h('th', { scope: 'col', class: 'num' }, 'Latest'))),
          h('tbody', {}, rated.map((trend) => h('tr', {}, h('td', {}, trend.label),
            h('td', { class: 'num numeric' }, trend.first_rating), h('td', { class: 'num numeric' }, trend.latest_rating)))))) : null,
        h('p', { class: 'small muted' }, history.scale_note),
      ] : h('p', { class: 'muted' }, 'No assessment written.')),

    section(`Calculated from ${plural(observations.total, 'observation')}`,
      observations.total ? [
        h('div', { class: 'columns' }, countTable(byMovement), countTable(byOutcome), countTable(byOpponent)),
        limitations(byMovement.limitations),
      ] : h('p', { class: 'muted' }, 'No observations recorded.')),

    observations.total ? section('The observations (your interpretations)',
      scrollable(h('table', {},
        h('thead', {}, h('tr', {}, ['#', 'Match', 'What', 'Outcome', 'Your note'].map((label) => h('th', { scope: 'col' }, label)))),
        h('tbody', {}, observations.items.map((o) => h('tr', {},
          h('td', { class: 'numeric' }, h('a', { href: `observations.html?open=${o.id}`,
            onclick: (event) => { event.preventDefault(); openObservation(o.id); } }, `#${o.id}`)),
          h('td', {}, o.match ? [o.match.title, h('div', { class: 'small muted' }, formatDate(o.match.match_date) || 'date unknown')] : unknown()),
          h('td', {}, o.movement_category ? `${o.category}: ${o.movement_category}` : o.category),
          h('td', {}, orUnknown(o.outcome)), h('td', {}, o.notes || o.tactical_situation || unknown()))))))) : null);
}

async function playerReportTab() {
  const players = await api.get('/api/players');
  if (!players.length) return emptyState('Record a player first.');
  const select = h('select', { id: 'report-player' }, h('option', { value: '' }, 'Choose a player'),
    players.map((player) => h('option', { value: player.id }, player.full_name)));
  const output = h('div', { class: 'section' });
  select.addEventListener('change', async () => {
    if (!select.value) { clear(output); return; }
    output.classList.add('is-stale');
    try {
      const report = await buildPlayerReport(Number(select.value));
      clear(output).append(report);
    } catch (error) {
      clear(output).append(errorNote(error));
    } finally {
      output.classList.remove('is-stale');
    }
  });
  const wanted = new URLSearchParams(window.location.search).get('player_id');
  if (wanted) { select.value = wanted; select.dispatchEvent(new Event('change')); }
  return [h('div', { class: 'filters no-print' }, h('div', { class: 'field' }, h('label', { for: 'report-player' }, 'Player'), select)), output];
}

// ── Optional AI ──────────────────────────────────────────────────────────────
function referenceLink(reference, playerId) {
  if (reference.kind === 'observation') {
    return h('a', { href: `observations.html?open=${reference.record_id}`,
      onclick: (event) => { event.preventDefault(); openObservation(reference.record_id); } }, `observation #${reference.record_id}`);
  }
  const tab = reference.kind === 'assessment' ? 'assessments' : 'statistics';
  return h('a', { href: `player.html?id=${playerId}#${tab}` }, `${reference.kind} #${reference.record_id}`);
}

function renderAiResult(result) {
  if (!result.called_ai || result.refused) {
    return h('div', { class: 'note caution' }, h('p', {}, result.evidence_note));
  }
  const used = result.evidence_used;
  const save = h('button', { type: 'button', class: 'button', onclick: async () => {
    const lines = [result.summary, '',
      ...result.findings.map((finding) => `- (${finding.kind}) ${finding.statement} [${finding.references.map((r) => r.id).join(', ') || 'no record cited'}]`),
      '', ...result.open_questions.map((question) => `? ${question}`), '', result.label];
    const observationIds = [...new Set(result.findings.flatMap((finding) => finding.references)
      .filter((reference) => reference.kind === 'observation').map((reference) => reference.record_id))];
    const note = await api.post('/api/notes', {
      note_type: 'AI-generated draft', title: `${result.task_name}: ${result.player.full_name}`,
      body: lines.join('\n'), player_id: result.player.id, observation_ids: observationIds, tags: ['AI-generated'],
    });
    toast('Saved to the notebook as an AI-generated draft');
    save.replaceWith(h('a', { class: 'button', href: `notebook.html?open=coaching_note-${note.id}` }, 'Open it in the notebook'));
  } }, 'Keep this in the notebook');

  return h('div', { class: 'note ai stack' },
    h('p', {}, h('strong', {}, result.label)),
    h('p', { class: 'small muted' }, `From ${result.provider}, model ${result.model}, ${formatMoment(result.generated_at)}. `
      + `It was shown ${plural(used.observations, 'observation')}, ${plural(used.assessments, 'assessment')} and `
      + `${plural(used.statistics, 'stat line')} of ${result.player.full_name}, and nothing else.`
      + (used.observations_left_out ? ` ${used.observations_left_out} older observations were left out.` : '')
      + (result.note ? ` ${result.note}` : '')),
    result.insufficient_evidence ? h('div', { class: 'note caution' }, 'The AI judged the records too thin for a firm answer.') : null,
    result.summary ? h('p', { class: 'prose' }, result.summary) : null,
    result.findings.length ? h('ul', { class: 'list' }, result.findings.map((finding) => h('li', {},
      h('span', { class: 'tag' }, finding.kind === 'recorded' ? 'Restates your records' : 'Hypothesis'), ' ', finding.statement,
      h('div', { class: 'small' }, finding.unsupported
        ? h('strong', {}, 'Cites no record of yours. Do not rely on it.')
        : ['Rests on: ', finding.references.map((reference, index) => [index ? ', ' : '', referenceLink(reference, result.player.id)])])))) : null,
    result.open_questions.length ? h('div', {}, h('h3', {}, 'Questions it suggests'),
      h('ul', {}, result.open_questions.map((question) => h('li', {}, question)))) : null,
    result.evidence_note ? h('p', { class: 'small muted' }, `On the evidence: ${result.evidence_note}`) : null,
    result.invalid_references_removed ? h('p', { class: 'small' },
      `${result.invalid_references_removed} reference(s) to records that were never sent were removed.`) : null,
    h('div', { class: 'row no-print' }, save,
      h('span', { class: 'small muted' }, 'Nothing is saved unless you press this. Your assessments are never changed.')));
}

async function aiTab() {
  const [status, players] = await Promise.all([api.get('/api/ai/status'), api.get('/api/players')]);
  const intro = h('div', { class: 'stack' },
    h('p', { class: 'prose' }, 'Optional. The AI is given one player\'s stored observations, assessments and stat lines, and must '
      + 'point at the records behind each statement. The app checks those references and flags any statement that has none. '
      + 'What comes back is a set of hypotheses for you to test, not a verdict.'),
    h('div', { class: status.enabled ? 'note' : 'note caution' }, status.message));
  if (!status.enabled) return intro;
  if (!players.length) return [intro, emptyState('Record a player first.')];

  const form = buildForm([
    { name: 'player_id', label: 'Player', type: 'select', numeric: true, required: true, width: 'half', options: players.map((p) => [p.id, p.full_name]) },
    { name: 'task', label: 'What to ask for', type: 'select', required: true, width: 'half', options: Object.entries(status.tasks) },
  ]);
  const output = h('div', { class: 'section' });
  const ask = h('button', { type: 'button', class: 'button primary', onclick: async () => {
    const { values } = form.read();
    ask.disabled = true;
    clear(output).append(h('p', { class: 'muted' }, 'Asking. This can take a minute…'));
    try {
      clear(output).append(renderAiResult(await api.post('/api/ai/player-analysis', values)));
    } catch (error) {
      clear(output).append(error instanceof ApiError ? h('div', { class: 'note error', role: 'alert' }, error.message) : errorNote(error));
    } finally {
      ask.disabled = false;
    }
  } }, 'Ask the AI');
  return [intro, h('div', { class: 'section stack' }, form.element,
    h('p', { class: 'small muted' }, `Pressing the button sends that player's records to ${status.provider}. Nothing else leaves this computer.`),
    ask), output];
}

// ── The page ─────────────────────────────────────────────────────────────────
page.content.append(tabs([
  { id: 'patterns', label: 'Patterns', render: patternsTab },
  { id: 'compare', label: 'Compare players', render: compareTab },
  { id: 'player', label: 'Player report', render: playerReportTab },
  { id: 'ai', label: 'AI assistance (optional)', render: aiTab },
], 'patterns').element);
