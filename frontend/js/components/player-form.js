// The form for adding or editing a player's biography.

import { api, ApiError, vocabulary } from '../api.js';
import { confirmDialog, formDialog } from '../ui.js';
import { playerLookup } from './player-lookup.js';

export async function playerFields() {
  const [vocab, teams] = await Promise.all([vocabulary(), api.get('/api/teams')]);
  const clubs = teams.filter((team) => team.team_type === 'club').map((team) => team.name);
  const nations = teams.filter((team) => team.team_type === 'national').map((team) => team.name);
  return [
    { name: 'full_name', label: 'Full name', required: true, maxLength: 160 },
    { name: 'primary_position', label: 'Primary position', type: 'suggest', options: vocab.positions, width: 'third' },
    { name: 'secondary_positions', label: 'Other positions', type: 'list', width: 'third', help: 'Separate with commas' },
    { name: 'shirt_number', label: 'Shirt number', type: 'number', min: 1, max: 99, width: 'third' },
    { name: 'current_team', label: 'Current club', type: 'suggest', options: clubs, width: 'half', help: 'A name not in the list adds the club' },
    { name: 'national_team', label: 'National team', type: 'suggest', options: nations, width: 'half' },
    { name: 'date_of_birth', label: 'Date of birth', type: 'date', width: 'third' },
    { name: 'nationality', label: 'Nationality', width: 'third', maxLength: 80 },
    { name: 'height_cm', label: 'Height (cm)', type: 'number', min: 120, max: 230, width: 'third' },
    { name: 'preferred_foot', label: 'Preferred foot', type: 'select', width: 'third',
      options: [['left', 'Left'], ['right', 'Right'], ['both', 'Both']] },
    { name: 'photo_url', label: 'Photo link', type: 'url', width: 'half', maxLength: 500,
      help: 'The web address of a picture. The picture itself is not copied.' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    { type: 'note', label: 'Leave anything you do not know empty. Empty is stored as "not known", never as a guess.' },
  ];
}

/** A player as the API returns it -> the values the form expects (teams by name). */
export function playerToForm(player) {
  return {
    ...player,
    current_team: player.current_team ? player.current_team.name : null,
    national_team: player.national_team ? player.national_team.name : null,
  };
}

/**
 * Save a player. If another player with the same name and no birth date exists,
 * the server refuses and asks; this shows that question and, on "yes", repeats
 * the request with allow_duplicate.
 */
async function savePlayer(values, playerId) {
  const send = (params) => (playerId
    ? api.put(`/api/players/${playerId}`, values, params)
    : api.post('/api/players', values, params));
  try {
    return await send();
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409 || !error.body.can_override) throw error;
    const different = await confirmDialog({
      title: 'Possibly the same player',
      message: error.message,
      confirmLabel: 'They are different players',
    });
    if (!different) throw error;
    return send({ allow_duplicate: true });
  }
}

/** Open the add/edit dialog. Resolves to the saved player, or null if cancelled. */
export async function playerDialog(player = null) {
  return formDialog({
    title: player ? `Edit ${player.full_name}` : 'Add player',
    fields: await playerFields(),
    values: player ? playerToForm(player) : {},
    submitLabel: player ? 'Save changes' : 'Add player',
    intro: player ? 'This changes the biography only. Assessments and observations are kept as they are.' : null,
    // Optional: look the player up on the web and fill the empty boxes (see player-lookup.js).
    extra: (form) => playerLookup(form, { isNew: !player, name: player ? player.full_name : '' }),
    onSubmit: (values) => savePlayer(values, player ? player.id : null),
  });
}
