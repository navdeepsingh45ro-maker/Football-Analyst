// Matches: the match library.

import { api } from '../api.js';
import { matchDialog } from '../components/match-form.js';
import { h } from '../dom.js';
import { load, mountPage } from '../layout.js';
import { emptyState, matchDate, orUnknown, scoreline, table, toast } from '../ui.js';

const page = mountPage({
  active: 'matches.html', title: 'Matches',
  lede: 'Every match you have recorded. Open one for its lineups, videos and observations.',
});

const search = h('input', { type: 'search', id: 'filter-search', placeholder: 'Team or venue' });
const competition = h('select', { id: 'filter-competition' }, h('option', { value: '' }, 'Any competition'));
const season = h('select', { id: 'filter-season' }, h('option', { value: '' }, 'Any season'));
const results = h('div', {});

async function addMatch() {
  const match = await matchDialog();
  if (match) {
    toast('Match added');
    window.location.href = `match.html?id=${match.id}`;
  }
}

page.actions.append(h('button', { type: 'button', class: 'button primary', onclick: addMatch }, 'Add match'));

function refresh() {
  return load(results, async () => {
    const matches = await api.get('/api/matches', {
      q: search.value.trim(), competition_id: competition.value, season_id: season.value,
    });
    if (!matches.length) {
      return (search.value.trim() || competition.value || season.value)
        ? emptyState('No match fits these filters.')
        : emptyState('No matches yet. Add a match, then link its video to start analysing.',
          h('button', { type: 'button', class: 'button primary', onclick: addMatch }, 'Add match'));
    }
    return table([
      { label: 'Date', cell: (match) => matchDate(match.match_date) },
      { label: 'Match', cell: (match) => h('a', { class: 'title-link', href: `match.html?id=${match.id}` }, scoreline(match)) },
      { label: 'Competition', cell: (match) => orUnknown(match.competition && match.competition.name) },
      { label: 'Season', cell: (match) => orUnknown(match.season && match.season.name) },
      { label: 'Videos', numeric: true, cell: (match) => match.video_count },
      { label: 'Observations', numeric: true, cell: (match) => match.observation_count },
      { label: '', cell: (match) => (match.video_count
        ? h('a', { class: 'button small', href: `video.html?match=${match.id}` }, 'Analyse')
        : null) },
    ], matches, { onRowClick: (match) => { window.location.href = `match.html?id=${match.id}`; } });
  });
}

let searchTimer = null;
search.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(refresh, 250);
});
competition.addEventListener('change', refresh);
season.addEventListener('change', refresh);

page.content.append(
  h('div', { class: 'filters' },
    h('div', { class: 'field' }, h('label', { for: 'filter-search' }, 'Search'), search),
    h('div', { class: 'field' }, h('label', { for: 'filter-competition' }, 'Competition'), competition),
    h('div', { class: 'field' }, h('label', { for: 'filter-season' }, 'Season'), season)),
  results);

Promise.all([api.get('/api/competitions'), api.get('/api/seasons')]).then(([competitions, seasons]) => {
  competition.append(...competitions.map((entry) => h('option', { value: entry.id }, entry.name)));
  season.append(...seasons.map((entry) => h('option', { value: entry.id }, entry.name)));
}).catch(() => { /* the list below reports any connection problem */ });
refresh();
