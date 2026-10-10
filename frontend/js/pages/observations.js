// Observations: every observation you have recorded, with filters and search.
//
// The filters live in the page address (observations.html?player_id=3&outcome=Shot),
// which makes a filtered view something you can bookmark, and lets the Reports
// page link straight to "the 15 observations behind this number".

import { api, vocabulary } from '../api.js';
import { matchLabel } from '../components/match-form.js';
import { observationDialog } from '../components/observation-form.js';
import { observationList, openObservation } from '../components/observation-list.js';
import { clear, h } from '../dom.js';
import { buildForm } from '../forms.js';
import { formatDate, plural } from '../format.js';
import { errorNote, load, mountPage } from '../layout.js';
import { toast } from '../ui.js';

const PAGE_SIZE = 100;

const page = mountPage({
  active: 'observations.html', title: 'Observations',
  lede: 'Everything you have recorded. Combine filters to compare a player across matches, opponents and outcomes.',
});

const results = h('div', {});
let form = null;

// observations.html?open=7 shows that observation straight away (links from other
// pages use this). Read now, because the first refresh() rewrites the address.
const observationToOpen = Number(new URLSearchParams(window.location.search).get('open')) || null;

// observations.html?ids=3,7,12 lists exactly those observations. The Reports page uses it to
// show the records behind a number. It has no filter box, so it is remembered here.
const pinnedIds = new URLSearchParams(window.location.search).get('ids');

/** The filters currently in the address, as a plain object. */
function filtersFromAddress() {
  const filters = {};
  for (const [name, value] of new URLSearchParams(window.location.search)) {
    if (name !== 'open' && name !== 'ids' && value !== '') filters[name] = value;
  }
  return filters;
}

/** What the filter boxes currently say, as API parameters (empty boxes left out). */
function filtersFromForm() {
  const { values } = form.read();
  const filters = {};
  for (const [name, value] of Object.entries(values)) {
    if (value !== null && value !== '') filters[name] = value;
  }
  if (pinnedIds) filters.ids = pinnedIds;
  return filters;
}

function refresh() {
  const filters = filtersFromForm();
  history.replaceState(null, '', `observations.html${Object.keys(filters).length ? `?${new URLSearchParams(filters)}` : ''}`);
  let shown = PAGE_SIZE;

  const show = () => load(results, async () => {
    const result = await api.get('/api/observations', { ...filters, limit: shown });
    const filtered = Object.keys(filters).length > 0;
    return [
      pinnedIds ? h('div', { class: 'note' }, h('p', {}, 'These are the observations behind a figure on the Reports page. ',
        h('a', { href: 'observations.html' }, 'Show all observations'))) : null,
      h('div', { class: 'row spread' },
        h('p', { class: 'muted' }, filtered
          ? `${plural(result.total, 'observation')} ${result.total === 1 ? 'matches' : 'match'} these filters.`
          : `${plural(result.total, 'observation')} in total.`),
        result.total ? h('a', { class: 'button small', href: `/api/export/csv/observations?${new URLSearchParams(filters)}`,
          title: 'Download exactly these observations as a spreadsheet file' }, 'Download these as CSV') : null),
      observationList(result.items, {
        onChanged: show,
        emptyMessage: filtered ? 'No observation matches these filters.' : 'No observations yet. Open a match under Video analysis to record the first one.',
      }),
      result.total > result.items.length
        ? h('p', {}, h('button', { type: 'button', class: 'button', onclick: () => { shown += PAGE_SIZE; show(); } },
          `Show more (${result.items.length} of ${result.total} shown)`))
        : null,
    ];
  });
  return show();
}

// The first three filters are always shown; the others sit behind "More filters".
const MAIN_FILTERS = 3;
const FILTER_COUNT = 12;
const EXTRA_FILTER_NAMES = ['team_id', 'position', 'category', 'movement_category', 'outcome', 'ended_in_shot_or_chance',
  'has_diagram', 'date_from', 'date_to'];

async function start() {
  try {
    const [vocab, players, matches, teams] = await Promise.all([
      vocabulary(), api.get('/api/players'), api.get('/api/matches'), api.get('/api/teams'),
    ]);
    form = buildForm([
      { name: 'q', label: 'Search', placeholder: 'Words in notes, or a name' },
      { name: 'player_id', label: 'Player', type: 'select', emptyLabel: 'Any player', options: players.map((player) => [player.id, player.full_name]) },
      { name: 'match_id', label: 'Match', type: 'select', emptyLabel: 'Any match', options: matches.map((match) => [match.id, matchLabel(match, formatDate)]) },
      { name: 'team_id', label: 'Team in the match', type: 'select', emptyLabel: 'Any team', options: teams.map((team) => [team.id, team.name]) },
      { name: 'position', label: 'Player position', type: 'select', emptyLabel: 'Any position', options: vocab.positions },
      { name: 'category', label: 'What it shows', type: 'suggest', options: vocab.observation_categories },
      { name: 'movement_category', label: 'Movement', type: 'suggest', options: vocab.movement_categories },
      { name: 'outcome', label: 'Outcome', type: 'suggest', options: vocab.outcomes },
      { name: 'ended_in_shot_or_chance', label: 'Shot or chance', type: 'select', emptyLabel: 'Either',
        options: [['true', 'Ended in a shot or chance'], ['false', 'Did not']] },
      { name: 'has_diagram', label: 'Diagram', type: 'select', emptyLabel: 'With or without', options: [['true', 'Has a diagram'], ['false', 'No diagram']] },
      { name: 'date_from', label: 'Match date from', type: 'date' },
      { name: 'date_to', label: 'Match date to', type: 'date' },
    ], filtersFromAddress());
    form.element.className = 'filters';
    // Twelve filters at once is a wall. Search, Player and Match stay in view; the
    // rest open with one press, and open by themselves when one of them is in use.
    const fields = [...form.element.querySelectorAll('.field')];
    const extra = fields.slice(MAIN_FILTERS, FILTER_COUNT);
    extra.forEach((field) => field.classList.add('extra'));
    const inUse = () => Object.keys(filtersFromForm()).filter((name) => EXTRA_FILTER_NAMES.includes(name)).length;
    const more = h('button', { type: 'button', class: 'button', 'aria-expanded': 'false', onclick: () => showExtra(!form.element.hasAttribute('data-more')) });
    function showExtra(open) {
      form.element.toggleAttribute('data-more', open);
      more.setAttribute('aria-expanded', String(open));
      more.textContent = open ? 'Fewer filters' : `More filters${inUse() ? ` (${inUse()} in use)` : ''}`;
    }
    fields[MAIN_FILTERS - 1].after(h('div', { class: 'field' }, more));
    showExtra(inUse() > 0);
    form.element.addEventListener('change', () => showExtra(form.element.hasAttribute('data-more')));

    let timer = null;
    form.element.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 250);  // wait until typing pauses
    });
    form.element.addEventListener('change', () => {
      clearTimeout(timer);
      refresh();
    });

    clear(page.actions).append(
      h('a', { class: 'button', href: 'observations.html' }, 'Clear filters'),
      h('button', { type: 'button', class: 'button primary', onclick: async () => {
        const { values } = form.read();
        const defaults = {};
        if (values.player_id) defaults.player_ids = [Number(values.player_id)];
        if (values.match_id) defaults.match_id = Number(values.match_id);
        if (await observationDialog(null, defaults)) { toast('Observation added'); refresh(); }
      } }, 'Add observation'));
    clear(page.content).append(form.element, results);
    await refresh();
    if (observationToOpen) openObservation(observationToOpen, { onChanged: refresh });
  } catch (error) {
    clear(page.content).append(errorNote(error, start));
  }
}

start();
