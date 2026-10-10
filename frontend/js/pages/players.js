// Players: the searchable list of everyone you are scouting.

import { api, vocabulary } from '../api.js';
import { playerDialog } from '../components/player-form.js';
import { h } from '../dom.js';
import { formatDate } from '../format.js';
import { load, mountPage } from '../layout.js';
import { emptyState, magnet, magnetKindFor, orUnknown, table, toast } from '../ui.js';

const page = mountPage({
  active: 'players.html', title: 'Players',
  lede: 'Everyone you are scouting. Open a player for their statistics, assessments, observations and diagrams.',
});

const search = h('input', { type: 'search', id: 'filter-search', placeholder: 'Name or nationality' });
const position = h('select', { id: 'filter-position' }, h('option', { value: '' }, 'Any position'));
const team = h('select', { id: 'filter-team' }, h('option', { value: '' }, 'Any club'));
const results = h('div', {});

async function addPlayer() {
  const player = await playerDialog();
  if (player) {
    toast(`${player.full_name} added`);
    window.location.href = `player.html?id=${player.id}`;
  }
}

page.actions.append(h('button', { type: 'button', class: 'button primary', onclick: addPlayer }, 'Add player'));

function refresh() {
  return load(results, async () => {
    const [players, vocab] = await Promise.all([
      api.get('/api/players', { q: search.value.trim(), position: position.value, team_id: team.value }),
      vocabulary(),
    ]);
    const filtering = search.value.trim() || position.value || team.value;
    if (!players.length) {
      return filtering
        ? emptyState('No player matches these filters.')
        : emptyState('No players yet. Add the first player you want to study.',
          h('button', { type: 'button', class: 'button primary', onclick: addPlayer }, 'Add player'));
    }
    return table([
      { label: '', cell: (player) => magnet(magnetKindFor(player.primary_position, vocab.position_groups),
        player.shirt_number || player.primary_position || '') },
      { label: 'Name', cell: (player) => h('a', { class: 'title-link', href: `player.html?id=${player.id}` }, player.full_name) },
      { label: 'Position', cell: (player) => orUnknown(player.primary_position) },
      { label: 'Club', cell: (player) => orUnknown(player.current_team && player.current_team.name) },
      { label: 'Nationality', cell: (player) => orUnknown(player.nationality) },
      { label: 'Age', numeric: true, cell: (player) => orUnknown(player.age) },
      { label: 'Observations', numeric: true, cell: (player) => player.observation_count },
      { label: 'Last assessed', cell: (player) => orUnknown(formatDate(player.latest_assessment_on)) },
    ], players, { onRowClick: (player) => { window.location.href = `player.html?id=${player.id}`; } });
  });
}

let searchTimer = null;
search.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(refresh, 250);  // wait until typing pauses
});
position.addEventListener('change', refresh);
team.addEventListener('change', refresh);

page.content.append(
  h('div', { class: 'filters' },
    h('div', { class: 'field' }, h('label', { for: 'filter-search' }, 'Search'), search),
    h('div', { class: 'field' }, h('label', { for: 'filter-position' }, 'Position'), position),
    h('div', { class: 'field' }, h('label', { for: 'filter-team' }, 'Club'), team)),
  results);

// Fill the filter drop-downs, then show the list.
Promise.all([vocabulary(), api.get('/api/teams')]).then(([vocab, teams]) => {
  position.append(...vocab.positions.map((code) => h('option', { value: code }, code)));
  team.append(...teams.map((entry) => h('option', { value: entry.id }, entry.name)));
}).catch(() => { /* the list below reports any connection problem */ });
refresh();
