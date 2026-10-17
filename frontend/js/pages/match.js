// One match: its facts, the lineups, where the footage is, and what you observed.

import { api, vocabulary } from '../api.js';
import { matchDialog } from '../components/match-form.js';
import { observationDialog } from '../components/observation-form.js';
import { observationList } from '../components/observation-list.js';
import { clear, h, queryParam } from '../dom.js';
import { plural } from '../format.js';
import { load, mountPage } from '../layout.js';
import {
  confirmDialog, deleteWithDependencies, emptyState, formDialog, magnet, magnetKindFor, matchDate, orUnknown,
  scoreline, toast,
} from '../ui.js';

const matchId = Number(queryParam('id'));
const page = mountPage({ active: 'matches.html', title: 'Match' });
page.before.append(h('a', { class: 'back-link', href: 'matches.html' }, 'All matches'));

const VIDEO_KINDS = {
  local_file: 'Video file on this computer',
  direct_url: 'Video file on the web',
  youtube: 'YouTube',
  external_link: 'Web link',
};
const PLAYBACK = {
  html5: 'Plays in the app',
  embed: 'Plays in YouTube\'s player inside the app',
  window: 'Plays in its own window beside the app',
  none: 'Cannot be played as it is',
};

function section(title, action, ...body) {
  return h('section', { class: 'section' }, h('div', { class: 'section-head' }, h('h2', {}, title), action), body);
}

// ── Lineups ──────────────────────────────────────────────────────────────────
async function lineupDialog(match, existing = null) {
  const [players, vocab] = await Promise.all([api.get('/api/players'), vocabulary()]);
  const taken = new Set(match.appearances.map((appearance) => appearance.player.id));
  const available = players.filter((player) => !taken.has(player.id));
  if (!existing && !available.length) {
    toast(players.length ? 'Every recorded player is already in this lineup.' : 'Add players on the Players page first.', 'error');
    return null;
  }
  const playerField = existing
    ? { type: 'note', label: `Player: ${existing.player.full_name}` }
    : { name: 'player_id', label: 'Player', type: 'select', numeric: true, required: true,
      options: available.map((player) => [player.id, player.primary_position ? `${player.full_name} (${player.primary_position})` : player.full_name]) };

  return formDialog({
    title: existing ? `Edit ${existing.player.full_name} in the lineup` : 'Add a player to the lineup',
    fields: [
      playerField,
      { name: 'side', label: 'Played for', type: 'select', required: true, width: 'half',
        options: [['home', match.home_team.name], ['away', match.away_team.name]] },
      { name: 'is_starter', label: 'Started the match', type: 'checkbox', default: true, width: 'half' },
      { name: 'shirt_number', label: 'Shirt number', type: 'number', min: 1, max: 99, width: 'third' },
      { name: 'position', label: 'Position in this match', type: 'suggest', options: vocab.positions, width: 'third' },
      { type: 'note', label: 'Substitutions: for a substitute, untick "Started" and enter the minute they came on. '
        + 'For a player who was replaced, enter the minute they went off.' },
      { name: 'minute_on', label: 'Came on (minute)', type: 'number', min: 0, max: 130, width: 'half' },
      { name: 'minute_off', label: 'Went off (minute)', type: 'number', min: 0, max: 130, width: 'half' },
    ],
    values: existing || {},
    submitLabel: existing ? 'Save changes' : 'Add to lineup',
    onSubmit: (values) => (existing
      ? api.put(`/api/appearances/${existing.id}`, { ...values, player_id: existing.player.id })
      : api.post(`/api/matches/${match.id}/appearances`, values)),
  });
}

function lineupColumn(match, side, vocab) {
  const team = side === 'home' ? match.home_team : match.away_team;
  const formation = side === 'home' ? match.home_formation : match.away_formation;
  const entries = match.appearances.filter((appearance) => appearance.side === side);
  return h('div', {},
    h('h3', {}, team.name, formation ? h('span', { class: 'muted' }, ` (${formation})`) : null),
    entries.length ? entries.map((appearance) => {
      const role = [appearance.is_starter ? 'Started' : 'Substitute',
        appearance.minute_on !== null ? `on at ${appearance.minute_on}'` : null,
        appearance.minute_off !== null ? `off at ${appearance.minute_off}'` : null].filter(Boolean).join(', ');
      const position = appearance.position || appearance.player.primary_position;
      return h('div', { class: 'player' },
        magnet(magnetKindFor(position, vocab.position_groups), appearance.shirt_number || position || ''),
        h('div', { class: 'grow' },
          h('a', { class: 'name', href: `player.html?id=${appearance.player.id}` }, appearance.player.full_name),
          h('div', { class: 'small muted' }, [position, role].filter(Boolean).join(', '))),
        h('button', { type: 'button', class: 'button small quiet', onclick: async () => {
          if (await lineupDialog(match, appearance)) { toast('Lineup saved'); show(); }
        } }, 'Edit'),
        h('button', { type: 'button', class: 'button small quiet', onclick: async () => {
          await api.delete(`/api/appearances/${appearance.id}`);
          toast(`${appearance.player.full_name} removed from the lineup`);
          show();
        } }, 'Remove'));
    }) : h('p', { class: 'muted small' }, 'No players recorded for this side.'));
}

// ── Videos ───────────────────────────────────────────────────────────────────
function videoDialog(match, existing = null) {
  return formDialog({
    title: existing ? 'Edit video' : 'Link a video to this match',
    intro: 'The app stores only WHERE the video is; it never copies it. A video file on this computer (.mp4, .mov, '
      + '.webm) plays in the app and lets you capture frames. A YouTube link plays inside the app too. Any other link, '
      + 'such as a match on a broadcaster\'s website, is watched in its own window beside the app, and Analyse takes '
      + 'the picture from that window.',
    fields: [
      { name: 'location', label: 'File path or web link', required: true, maxLength: 1000,
        help: 'A full path such as /Users/you/Movies/match.mp4. In Finder: hold Option, right-click the file and choose "Copy as Pathname".' },
      { name: 'label', label: 'Label', placeholder: 'Full match', width: 'half', maxLength: 120 },
      { name: 'notes', label: 'Notes', type: 'textarea', rows: 2 },
    ],
    values: existing || {},
    submitLabel: existing ? 'Save changes' : 'Link video',
    onSubmit: (values) => (existing ? api.put(`/api/videos/${existing.id}`, values) : api.post(`/api/matches/${match.id}/videos`, values)),
  });
}

function videoRow(match, video) {
  return h('li', { class: 'stack' },
    h('div', { class: 'row spread' },
      h('div', {}, h('strong', {}, video.label), h('span', { class: 'muted' }, `, ${VIDEO_KINDS[video.kind]}. ${PLAYBACK[video.playback.mode]}.`)),
      h('div', { class: 'row' },
        h('a', { class: 'button small primary', href: `video.html?match=${match.id}&video=${video.id}` }, 'Analyse'),
        h('button', { type: 'button', class: 'button small', onclick: async () => {
          if (await videoDialog(match, video)) { toast('Video saved'); show(); }
        } }, 'Edit'),
        h('button', { type: 'button', class: 'button small danger', onclick: async () => {
          const sure = await confirmDialog({
            title: `Remove the link to "${video.label}"?`,
            message: 'Only the link is removed; the video itself is not touched. Observations made from it are kept, with their timestamps.',
            confirmLabel: 'Remove link', danger: true,
          });
          if (!sure) return;
          await api.delete(`/api/videos/${video.id}`);
          toast('Video link removed');
          show();
        } }, 'Remove'))),
    h('div', { class: video.playback.available ? 'small muted' : 'note caution small' }, video.playback.explanation),
    h('div', { class: 'small muted breakable' }, video.location));
}

// ── The page ─────────────────────────────────────────────────────────────────
function show() {
  return load(page.content, async () => {
    const [match, vocab, observations] = await Promise.all([
      api.get(`/api/matches/${matchId}`), vocabulary(), api.get('/api/observations', { match_id: matchId, limit: 500 }),
    ]);
    page.setTitle(match.title);
    clear(page.heading).append(scoreline(match));
    page.setLede([match.competition && match.competition.name, match.season && match.season.name, match.venue]
      .filter(Boolean).join(', '));

    clear(page.actions).append(
      h('a', { class: 'button primary', href: `video.html?match=${match.id}` }, 'Analyse'),
      h('a', { class: 'button', href: `coach.html?match_id=${match.id}` }, 'Ask the coach'),
      h('button', { type: 'button', class: 'button', onclick: async () => {
        if (await matchDialog(match)) { toast('Match saved'); show(); }
      } }, 'Edit'),
      h('button', { type: 'button', class: 'button danger', onclick: async () => {
        const deleted = await deleteWithDependencies({
          api, path: `/api/matches/${match.id}`, name: match.title,
          describe: (found) => [
            `${plural(found.observations, 'observation')}, with their diagrams`,
            `${plural(found.statistics, 'stat line')} for this match`,
            plural(found.appearances, 'lineup entry', 'lineup entries'),
            `${plural(found.videos, 'video link')} (the videos themselves are not touched)`,
          ],
        });
        if (deleted) window.location.href = 'matches.html';
      } }, 'Delete'));

    return [
      h('dl', { class: 'facts' },
        h('dt', {}, 'Date'), h('dd', {}, matchDate(match.match_date)),
        h('dt', {}, 'Competition'), h('dd', {}, orUnknown(match.competition && match.competition.name)),
        h('dt', {}, 'Season'), h('dd', {}, orUnknown(match.season && match.season.name)),
        h('dt', {}, 'Venue'), h('dd', {}, orUnknown(match.venue)),
        h('dt', {}, 'Formations'), h('dd', {}, orUnknown([match.home_formation, match.away_formation].filter(Boolean).join(' v ')))),
      match.notes ? section('Match notes', null, h('p', { class: 'prose' }, match.notes)) : null,

      section('Videos',
        h('button', { type: 'button', class: 'button', onclick: async () => {
          if (await videoDialog(match)) { toast('Video linked'); show(); }
        } }, 'Link a video'),
        match.videos.length
          ? h('ul', { class: 'list' }, match.videos.map((video) => videoRow(match, video)))
          : emptyState('No video linked. You can still analyse this match: watch it in any window and connect that window, '
            + 'or type timestamps and add screenshots.',
            h('a', { class: 'button', href: `video.html?match=${match.id}` }, 'Open the analysis desk'))),

      section('Lineups',
        h('button', { type: 'button', class: 'button', onclick: async () => {
          if (await lineupDialog(match)) { toast('Added to the lineup'); show(); }
        } }, 'Add a player'),
        h('div', { class: 'lineup' }, lineupColumn(match, 'home', vocab), lineupColumn(match, 'away', vocab))),

      section(`Observations (${observations.total})`,
        h('button', { type: 'button', class: 'button', onclick: async () => {
          if (await observationDialog(null, { match_id: match.id })) { toast('Observation added'); show(); }
        } }, 'Add observation'),
        observationList(observations.items, {
          onChanged: show,
          emptyMessage: 'No observations for this match yet. Press Analyse to watch the video and record what you see.',
        })),
    ];
  });
}

if (!matchId) {
  page.content.append(emptyState('No match was chosen.', h('a', { class: 'button', href: 'matches.html' }, 'Go to matches')));
} else {
  show();
}
