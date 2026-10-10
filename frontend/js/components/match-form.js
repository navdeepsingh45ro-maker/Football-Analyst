// The form for adding or editing a match.

import { api } from '../api.js';
import { formDialog } from '../ui.js';

export async function matchFields() {
  const [teams, competitions, seasons] = await Promise.all([
    api.get('/api/teams'), api.get('/api/competitions'), api.get('/api/seasons'),
  ]);
  const teamNames = teams.map((team) => team.name);
  return [
    { name: 'home_team', label: 'Home team', type: 'suggest', options: teamNames, required: true, width: 'half' },
    { name: 'away_team', label: 'Away team', type: 'suggest', options: teamNames, required: true, width: 'half' },
    { name: 'match_date', label: 'Date', type: 'date', width: 'third' },
    { name: 'competition', label: 'Competition', type: 'suggest', options: competitions.map((c) => c.name), width: 'third' },
    { name: 'season', label: 'Season', type: 'suggest', options: seasons.map((s) => s.name), placeholder: '2025/26', width: 'third' },
    { name: 'home_score', label: 'Home score', type: 'number', min: 0, max: 99, width: 'third', help: 'Leave both scores empty if you do not know the result' },
    { name: 'away_score', label: 'Away score', type: 'number', min: 0, max: 99, width: 'third' },
    { name: 'venue', label: 'Venue', width: 'third', maxLength: 160 },
    { name: 'home_formation', label: 'Home formation', placeholder: '4-3-3', width: 'half', maxLength: 40 },
    { name: 'away_formation', label: 'Away formation', placeholder: '4-4-2', width: 'half', maxLength: 40 },
    { name: 'notes', label: 'Match notes', type: 'textarea' },
  ];
}

/** A match as the API returns it -> the values the form expects (names instead of objects). */
export function matchToForm(match) {
  return {
    ...match,
    home_team: match.home_team.name,
    away_team: match.away_team.name,
    competition: match.competition ? match.competition.name : null,
    season: match.season ? match.season.name : null,
  };
}

/** Open the add/edit dialog. Resolves to the saved match, or null if cancelled. */
export async function matchDialog(match = null) {
  return formDialog({
    title: match ? 'Edit match' : 'Add match',
    fields: await matchFields(),
    values: match ? matchToForm(match) : {},
    submitLabel: match ? 'Save changes' : 'Add match',
    intro: 'Teams, competitions and seasons are created as you type them. Nothing needs a paid data service.',
    onSubmit: (values) => (match ? api.put(`/api/matches/${match.id}`, values) : api.post('/api/matches', values)),
  });
}

/** "Northside FC v Riverton United, 8 Mar 2026" for drop-down lists. */
export function matchLabel(match, formatDate) {
  const when = match.match_date ? formatDate(match.match_date) : 'date unknown';
  return `${match.title}, ${when}`;
}
