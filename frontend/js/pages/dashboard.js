// Dashboard: what you have recorded, what you worked on last, and what is waiting.
// Every number and list comes from your own records (GET /api/dashboard).

import { api } from '../api.js';
import { observationList } from '../components/observation-list.js';
import { h } from '../dom.js';
import { formatMoment, plural } from '../format.js';
import { load, mountPage } from '../layout.js';
import { emptyState, matchDate } from '../ui.js';

const page = mountPage({ active: 'index.html', title: 'Dashboard' });

function gettingStarted() {
  // A real sequence, so it is numbered: each step needs the one before it.
  return h('div', { class: 'sheet stack' },
    h('h2', {}, 'Nothing recorded yet'),
    h('p', { class: 'prose' }, 'Three steps take you from an empty database to your first saved analysis.'),
    h('ol', { class: 'stack' },
      h('li', {}, h('a', { href: 'players.html' }, 'Add a player'), ' you want to study.'),
      h('li', {}, h('a', { href: 'matches.html' }, 'Add a match'), ' and link its video: a file on this computer works best.'),
      h('li', {}, 'Open the match under ', h('a', { href: 'video.html' }, 'Video analysis'), ', pause at an interesting moment and press Analyse.')));
}

function section(title, body, link = null) {
  return h('section', { class: 'section' },
    h('div', { class: 'section-head' }, h('h2', {}, title), link),
    body);
}

function outstanding(data) {
  const items = [];
  for (const note of data.open_notes) {
    items.push(h('li', {}, h('a', { href: `notebook.html?open=coaching_note-${note.id}` }, note.title),
      h('span', { class: 'muted' }, ` (${note.note_type.toLowerCase()}, still open)`)));
  }
  for (const match of data.matches_to_analyse) {
    items.push(h('li', {}, h('a', { href: `video.html?match=${match.id}` }, match.title), ', ', matchDate(match.match_date),
      h('span', { class: 'muted' }, ': has a video but no observations yet')));
  }
  for (const player of data.players_without_assessment) {
    items.push(h('li', {}, h('a', { href: `player.html?id=${player.id}#assessments` }, player.full_name),
      h('span', { class: 'muted' }, ': no scouting assessment written yet')));
  }
  return items.length ? h('ul', { class: 'list' }, items) : emptyState('Nothing is waiting. Open questions and goals from your notebook appear here.');
}

load(page.content, async () => {
  const data = await api.get('/api/dashboard');
  const counts = data.counts;
  if (!counts.players && !counts.matches && !counts.observations) return gettingStarted();

  const tally = h('ul', { class: 'tally' },
    [[counts.players, 'player', 'players', 'players.html'],
      [counts.matches, 'match', 'matches', 'matches.html'],
      [counts.matches_analysed, 'match analysed', 'matches analysed', 'matches.html'],
      [counts.observations, 'observation', 'observations', 'observations.html'],
      [counts.diagrams, 'diagram', 'diagrams', 'observations.html?has_diagram=true'],
      [counts.assessments, 'assessment', 'assessments', 'players.html'],
      [counts.notes, 'notebook entry', 'notebook entries', 'notebook.html'],
    ].map(([count, one, many, href]) => h('li', {},
      h('span', { class: 'figure' }, count), h('a', { href }, count === 1 ? one : many))));

  const players = data.recent_players.length
    ? h('ul', { class: 'list' }, data.recent_players.map((player) => h('li', {},
      h('a', { class: 'title-link', href: `player.html?id=${player.id}` }, player.full_name),
      player.primary_position ? ` (${player.primary_position})` : '',
      h('div', { class: 'small muted' }, `Last ${player.activity} saved ${formatMoment(player.last_activity)}`))))
    : emptyState('No player has an observation or assessment yet.');

  const matches = data.recent_matches.length
    ? h('ul', { class: 'list' }, data.recent_matches.map((entry) => h('li', {},
      h('a', { class: 'title-link', href: `match.html?id=${entry.match.id}` }, entry.match.title), ', ', matchDate(entry.match.match_date),
      h('div', { class: 'small muted' }, `${plural(entry.observation_count, 'observation')}, last saved ${formatMoment(entry.last_activity)}`))))
    : emptyState('No match has observations yet.');

  return [
    tally,
    h('div', { class: 'columns' },
      section('Recently studied players', players, h('a', { href: 'players.html' }, 'All players')),
      section('Recent match analyses', matches, h('a', { href: 'matches.html' }, 'All matches'))),
    section('Latest observations', observationList(data.recent_observations), h('a', { href: 'observations.html' }, 'All observations')),
    section('Waiting for you', outstanding(data.outstanding)),
  ];
});
