// The fields of an observation, shared by every place one is written:
// the Observations page, a player's profile and the video analysis workspace.

import { api, vocabulary } from '../api.js';
import { formatDate } from '../format.js';
import { formDialog } from '../ui.js';
import { matchLabel } from './match-form.js';
import { playerPicker } from './player-picker.js';

/**
 * The field list for buildForm() / formDialog().
 * @param vocab     the vocabulary lists from the API
 * @param matches   when given, a "Match" drop-down is included
 * @param compact   true inside the video workspace: narrower layout, shorter boxes
 */
export function observationFields(vocab, { matches = null, compact = false } = {}) {
  const half = compact ? undefined : 'half';
  const fields = [];
  if (matches) {
    fields.push({
      name: 'match_id', label: 'Match', type: 'select', numeric: true, emptyLabel: 'Not tied to a match',
      options: matches.map((match) => [match.id, matchLabel(match, formatDate)]),
    });
  }
  fields.push(
    { name: 'video_time_seconds', label: 'Video time', type: 'clock', width: 'half', help: 'Position in the video' },
    { name: 'match_clock_seconds', label: 'Match clock', type: 'clock', width: 'half', help: 'Scoreboard time, optional' },
    { name: 'category', label: 'What it shows', type: 'suggest', options: vocab.observation_categories, required: true, width: half },
    { name: 'movement_category', label: 'Movement', type: 'suggest', options: vocab.movement_categories, width: half,
      help: 'Pick one or write your own' },
    { name: 'tactical_situation', label: 'The situation', type: 'textarea', rows: 2 },
    { name: 'movement_trigger', label: 'What triggered it', width: half },
    { name: 'intended_space', label: 'Space being attacked', width: half },
    { name: 'defensive_shape', label: 'Defensive shape faced', placeholder: 'e.g. 4-4-2 mid block', width: half, maxLength: 80 },
    { name: 'outcome', label: 'Outcome', type: 'suggest', options: vocab.outcomes, width: half },
    { name: 'notes', label: 'Your interpretation', type: 'textarea', rows: compact ? 4 : 5 },
    { name: 'confidence', label: 'How sure are you', type: 'select', emptyLabel: 'Not stated', width: 'half',
      options: [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']] },
    { name: 'evidence', label: 'Other evidence', width: 'half', help: 'Links, clip names, page numbers' },
  );
  return fields;
}

/** An observation as the API returns it -> the values the form expects. */
export function observationToForm(observation) {
  return { ...observation, match_id: observation.match ? observation.match.id : null };
}

/**
 * Open the dialog to add an observation without a drawing, or to edit one.
 * `defaults` pre-fills a new observation, e.g. { player_ids: [3], match_id: 2 }.
 * Resolves to the saved observation, or null if cancelled.
 */
export async function observationDialog(observation = null, defaults = {}) {
  const [vocab, players, matches] = await Promise.all([
    vocabulary(), api.get('/api/players'), api.get('/api/matches'),
  ]);
  const picker = playerPicker({
    all: players,
    selected: observation ? observation.players.map((player) => player.id) : (defaults.player_ids || []),
  });
  const values = observation ? observationToForm(observation) : { category: 'Off-ball movement', ...defaults };

  return formDialog({
    title: observation ? `Edit observation #${observation.id}` : 'Add observation',
    intro: observation
      ? 'The timestamp below is exactly what is stored. It only changes if you change it here.'
      : 'A quick written observation. To draw the situation as well, start from Video analysis instead.',
    fields: observationFields(vocab, { matches }),
    values,
    wide: true,
    submitLabel: observation ? 'Save changes' : 'Add observation',
    extra: picker,
    onSubmit: (read) => {
      // A video link belongs to its match: keep it only while the match is unchanged.
      const sameMatch = observation && observation.match && observation.match.id === read.match_id;
      const body = { ...read, video_reference_id: sameMatch ? observation.video_reference_id : null };
      return observation ? api.put(`/api/observations/${observation.id}`, body) : api.post('/api/observations', body);
    },
  });
}
