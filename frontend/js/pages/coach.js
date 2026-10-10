// Coach: ask the AI your own questions, about a player, a match, everything you
// have recorded, or coaching in general.
//
// TWO KINDS OF KNOWLEDGE, ALWAYS SHOWN APART
//   From your records / its reading of them   must point at records of yours.
//                                             The server checks every reference.
//   General coaching advice                   not from your records, and says so.
//
// The conversation lives in this page only. Each question is sent together with
// the last few turns (so "and in training?" makes sense), and nothing is saved
// unless you press "Keep in the notebook".

import { api, ApiError } from '../api.js';
import { matchLabel } from '../components/match-form.js';
import { openObservation } from '../components/observation-list.js';
import { clear, h, queryParam } from '../dom.js';
import { excerpt, formatDate, formatMoment, plural } from '../format.js';
import { errorNote, load, mountPage } from '../layout.js';
import { toast } from '../ui.js';

const page = mountPage({
  active: 'coach.html', title: 'Coach',
  lede: 'Ask about a player, a match, everything you have recorded, or coaching in general.',
});

// kind of statement -> [label shown, style]
const KINDS = {
  recorded: ['From your records', 'records'],
  hypothesis: ['Its reading of your records', 'reading'],
  general: ['General coaching advice', 'general'],
};
const TURNS_SENT = 6;

const turns = [];  // { question, result } for every answered question, oldest first
let players = [];
let matches = [];
let playerSelect;
let matchSelect;
let questionBox;
let askButton;
let restartButton;
const conversation = h('div', { class: 'conversation' });
const starters = h('div', { class: 'stack' });

function chosen(select, items) {
  const id = Number(select.value);
  return id ? items.find((item) => item.id === id) || null : null;
}

function referenceLink(reference) {
  if (reference.kind === 'observation') {
    return h('a', { href: `observations.html?open=${reference.record_id}`,
      onclick: (event) => { event.preventDefault(); openObservation(reference.record_id); } }, `observation #${reference.record_id}`);
  }
  if (reference.kind === 'player') {
    return h('a', { href: `player.html?id=${reference.record_id}` }, `${reference.label || `player #${reference.record_id}`}'s profile`);
  }
  const text = `${reference.kind} #${reference.record_id}`;
  const tab = reference.kind === 'assessment' ? 'assessments' : 'statistics';
  return reference.player_id ? h('a', { href: `player.html?id=${reference.player_id}#${tab}` }, text) : text;
}

function pointSource(point) {
  if (point.unsupported) return h('div', { class: 'small' }, h('strong', {}, 'Cites no record of yours. Do not rely on it.'));
  if (!point.references.length) return null;  // general advice: nothing of yours behind it, by design
  return h('div', { class: 'small' }, 'Rests on: ',
    point.references.map((reference, index) => [index ? ', ' : '', referenceLink(reference)]));
}

function keepButton(result) {
  const button = h('button', { type: 'button', class: 'button', onclick: async () => {
    const lines = [`Question: ${result.question}`, '', result.answer, '',
      ...result.points.map((point) => `- (${KINDS[point.kind][0]}) ${point.statement}`
        + (point.references.length ? ` [${point.references.map((reference) => reference.id).join(', ')}]` : '')),
      '', result.label];
    const observationIds = [...new Set(result.points.flatMap((point) => point.references)
      .filter((reference) => reference.kind === 'observation').map((reference) => reference.record_id))];
    try {
      const note = await api.post('/api/notes', {
        note_type: 'AI-generated draft', title: excerpt(result.question, 150), body: lines.join('\n'),
        player_id: result.scope.player ? result.scope.player.id : null,
        match_id: result.scope.match ? result.scope.match.id : null,
        observation_ids: observationIds, tags: ['AI-generated'],
      });
      toast('Saved to the notebook as an AI-generated draft');
      button.replaceWith(h('a', { class: 'button', href: `notebook.html?open=coaching_note-${note.id}` }, 'Open it in the notebook'));
    } catch (error) {
      toast(error.message, 'error');
    }
  } }, 'Keep in the notebook');
  return button;
}

function renderReply(result) {
  if (result.refused) return h('div', { class: 'note caution' }, h('p', {}, result.evidence_note));
  const used = result.evidence_used;
  const shown = used.players + used.observations + used.assessments + used.statistics
    ? `It was shown ${plural(used.players, 'player profile')}, ${plural(used.observations, 'observation')}, `
      + `${plural(used.assessments, 'assessment')} and ${plural(used.statistics, 'stat line')}.`
    : 'It was shown none of your records.';

  return h('div', { class: 'sheet reply stack' },
    h('p', { class: 'answer' }, result.answer),
    result.insufficient_evidence && result.evidence_note
      ? h('div', { class: 'note caution' }, h('p', {}, result.evidence_note)) : null,
    result.points.length ? h('div', {},
      h('h3', {}, 'What this rests on'),
      h('ul', { class: 'points' }, result.points.map((point) => h('li', {},
        h('span', { class: `tag ${KINDS[point.kind][1]}` }, KINDS[point.kind][0]), ' ', point.statement, pointSource(point))))) : null,
    result.invalid_references_removed ? h('p', { class: 'small' },
      `References to records that were never sent were removed: ${result.invalid_references_removed}.`) : null,
    result.follow_ups.length ? h('div', {},
      h('h3', {}, 'Ask next'),
      h('div', { class: 'chips' }, result.follow_ups.map((question) => chip(question)))) : null,
    h('p', { class: 'small muted' }, `${result.label} ${shown}`
      + (used.observations_left_out ? ` ${plural(used.observations_left_out, 'older observation')} did not fit and were left out.` : '')
      + ` From ${result.provider}, model ${result.model}, ${formatMoment(result.generated_at)}.`
      + (result.note ? ` ${result.note}` : '')),
    h('div', { class: 'row no-print' }, keepButton(result),
      h('span', { class: 'small muted' }, 'Nothing is saved unless you press this. Your assessments are never changed.')));
}

async function ask(text) {
  const question = text.trim();
  if (!question || askButton.disabled) return;
  const player = chosen(playerSelect, players);
  const match = chosen(matchSelect, matches);
  const about = [player && player.full_name, match && matchLabel(match, formatDate)].filter(Boolean).join(', ');

  const replyBox = h('div', { 'aria-live': 'polite' }, h('p', { class: 'muted' }, 'Thinking. This can take up to a minute…'));
  const turn = h('div', { class: 'turn' },
    h('p', { class: 'asked' }, question),
    h('p', { class: 'asked-about small muted' }, about ? `About ${about}` : 'About everything you have recorded'),
    replyBox);
  conversation.append(turn);
  starters.hidden = true;
  questionBox.value = '';
  askButton.disabled = true;
  turn.scrollIntoView({ block: 'nearest' });

  try {
    const result = await api.post('/api/ai/coach', {
      question, player_id: player ? player.id : null, match_id: match ? match.id : null,
      history: turns.slice(-TURNS_SENT).map((earlier) => ({ question: earlier.question, answer: earlier.result.answer })),
    });
    clear(replyBox).append(renderReply(result));
    if (!result.refused) turns.push({ question, result });
    restartButton.hidden = false;
  } catch (error) {
    clear(replyBox).append(error instanceof ApiError
      ? h('div', { class: 'note error', role: 'alert' }, h('p', {}, error.message),
        h('button', { type: 'button', class: 'button small', onclick: () => { turn.remove(); ask(question); } }, 'Ask again'))
      : errorNote(error));
  } finally {
    askButton.disabled = false;
    questionBox.focus({ preventScroll: true });
  }
}

/** A ready-made question: one press asks it. */
function chip(question) {
  return h('button', { type: 'button', class: 'chip', onclick: () => ask(question) }, question);
}

function showStarters() {
  const player = chosen(playerSelect, players);
  const match = chosen(matchSelect, matches);
  let questions;
  if (player) {
    questions = [`What patterns do you see in ${player.full_name}'s play?`,
      `What should ${player.full_name} work on in training?`,
      `Draft a short scouting report on ${player.full_name}.`,
      `How has my assessment of ${player.full_name} changed over time?`];
  } else if (match) {
    questions = ['Summarise what I recorded in this match.', 'What should we work on in training after this match?'];
  } else {
    questions = ['What stands out across my recent observations?', 'Which of my players have I studied least?'];
  }
  questions.push('Give me a 20-minute drill for coaching pressing triggers.');
  clear(starters).append(h('h3', {}, 'Try one of these'), h('div', { class: 'chips' }, questions.map((question) => chip(question))));
}

function scopeSelect(id, emptyLabel, options, selected) {
  return h('select', { id }, h('option', { value: '' }, emptyLabel),
    options.map(([value, label]) => h('option', { value, selected: String(value) === String(selected) }, label)));
}

load(page.content, async () => {
  const [status, playerList, matchList] = await Promise.all([
    api.get('/api/ai/status'), api.get('/api/players'), api.get('/api/matches'),
  ]);
  if (!status.enabled) {
    return h('div', { class: 'coach-main' },
      h('div', { class: 'note caution' }, h('p', {}, status.message)),
      h('p', { class: 'prose' }, 'The coach is an optional extra. It needs a key from an AI provider, which goes in a file '
        + 'named .env in the backend folder. The README explains it under "Optional AI". Google\'s Gemini has a free tier.'));
  }
  players = playerList;
  matches = matchList;

  playerSelect = scopeSelect('coach-player', 'Any player', players.map((player) => [player.id, player.full_name]), queryParam('player_id'));
  matchSelect = scopeSelect('coach-match', 'Any match', matches.map((match) => [match.id, matchLabel(match, formatDate)]), queryParam('match_id'));
  for (const select of [playerSelect, matchSelect]) {
    select.addEventListener('change', () => { if (!turns.length) showStarters(); });
  }

  questionBox = h('textarea', { id: 'coach-question', rows: 3, maxlength: 2000,
    placeholder: 'For example: what should we work on after the last match?' });
  questionBox.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {  // Enter asks; Shift+Enter starts a new line
      event.preventDefault();
      ask(questionBox.value);
    }
  });
  askButton = h('button', { type: 'button', class: 'button primary', onclick: () => ask(questionBox.value) }, 'Ask the coach');

  restartButton = h('button', { type: 'button', class: 'button small', onclick: () => {
    turns.length = 0;
    clear(conversation);
    restartButton.hidden = true;
    starters.hidden = false;
    showStarters();
    questionBox.focus();
  } }, 'Start a new conversation');
  restartButton.hidden = true;

  showStarters();
  // The "ask about" panel comes first in the page (and so first on a phone); on a wide screen it sits to the right.
  return h('div', { class: 'coach' },
    h('div', { class: 'coach-side sheet scope' },
      h('div', { class: 'field' }, h('label', { for: 'coach-player' }, 'Ask about a player'), playerSelect),
      h('div', { class: 'field' }, h('label', { for: 'coach-match' }, 'Ask about a match'), matchSelect),
      h('p', { class: 'small muted' }, 'Leave both on "Any" to ask about everything you have recorded, or about coaching in general.'),
      restartButton),
    h('div', { class: 'coach-main' },
      conversation,
      h('div', { class: 'sheet composer stack' },
        h('div', { class: 'field' }, h('label', { for: 'coach-question' }, 'Your question'), questionBox),
        h('div', { class: 'composer-foot' },
          h('p', { class: 'small muted' }, `Asking sends the records of the chosen player or match, or all of them, to ${status.provider}. `
            + 'Nothing else leaves this computer.'),
          askButton)),
      starters));
});
