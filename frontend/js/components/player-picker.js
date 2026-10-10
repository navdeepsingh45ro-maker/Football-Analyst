// Choosing the player(s) an observation is about.
//
// One observation can involve several players; exactly one of them is the
// PRIMARY player, the one being studied. The picker shows:
//   - the chosen players, each with a "studied" radio button and a remove button
//   - one-click buttons for likely players (the match lineup), when given
//   - a search box over every player you have recorded

import { clear, h } from '../dom.js';

let pickerCounter = 0;

/**
 * @param all        every player: [{ id, full_name, primary_position }]
 * @param suggested  players to offer as one-click buttons (e.g. the lineup)
 * @param selected   ids already chosen; the first is the primary player
 * @param onChange   called after every change
 */
export function playerPicker({ all, suggested = [], selected = [], onChange = () => {} }) {
  pickerCounter += 1;
  const groupName = `picker-primary-${pickerCounter}`;
  const listId = `picker-list-${pickerCounter}`;
  let chosen = selected.filter((id) => all.some((player) => player.id === id));
  let primary = chosen[0] ?? null;

  const chosenBox = h('div', { class: 'stack' });
  const quickBox = h('div', { class: 'row' });
  const error = h('div', { class: 'error' });
  error.hidden = true;
  const search = h('input', { type: 'text', list: listId, placeholder: 'Type a name to add another player', autocomplete: 'off', 'aria-label': 'Add another player by name' });
  const options = h('datalist', { id: listId });

  const byId = (id) => all.find((player) => player.id === id);

  function add(id) {
    if (chosen.includes(id)) return;
    chosen.push(id);
    if (primary === null) primary = id;
    render();
    onChange();
  }

  function remove(id) {
    chosen = chosen.filter((other) => other !== id);
    if (primary === id) primary = chosen[0] ?? null;
    render();
    onChange();
  }

  function addFromSearch() {
    const typed = search.value.trim().toLowerCase();
    if (!typed) return;
    const match = all.find((player) => player.full_name.toLowerCase() === typed)
      || all.find((player) => player.full_name.toLowerCase().includes(typed) && !chosen.includes(player.id));
    if (match) {
      add(match.id);
      search.value = '';
      error.hidden = true;
    } else {
      error.textContent = 'No recorded player matches that name. Add the player on the Players page first.';
      error.hidden = false;
    }
  }

  function render() {
    clear(chosenBox);
    if (!chosen.length) chosenBox.append(h('p', { class: 'muted small' }, 'No player chosen yet.'));
    for (const id of chosen) {
      const player = byId(id);
      const radioId = `${groupName}-${id}`;
      chosenBox.append(h('div', { class: 'row' },
        h('input', {
          type: 'radio', name: groupName, id: radioId, checked: primary === id,
          onchange: () => { primary = id; render(); onChange(); },
        }),
        h('label', { for: radioId }, player.full_name, primary === id ? ' (studied)' : ''),
        h('button', { type: 'button', class: 'button small quiet', onclick: () => remove(id), 'aria-label': `Remove ${player.full_name}` }, 'Remove')));
    }

    clear(quickBox);
    for (const player of suggested.filter((candidate) => !chosen.includes(candidate.id))) {
      quickBox.append(h('button', { type: 'button', class: 'button small', onclick: () => add(player.id) }, `Add ${player.full_name}`));
    }
    clear(options).append(...all.filter((player) => !chosen.includes(player.id)).map((player) => h('option', { value: player.full_name })));
  }

  search.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();  // do not submit the surrounding form
      addFromSearch();
    }
  });
  search.addEventListener('change', addFromSearch);

  render();
  const element = h('fieldset', { class: 'field' },
    h('legend', {}, 'Players'),
    chosenBox, quickBox,
    h('div', { class: 'row' }, search, options),
    h('div', { class: 'help' }, 'The "studied" player is the one the observation is about. Others are involved in the same situation.'),
    error);

  return {
    element,
    /** { player_ids: [...], primary_player_id } with the primary player first. */
    read() {
      const ordered = primary === null ? chosen : [primary, ...chosen.filter((id) => id !== primary)];
      return { player_ids: ordered, primary_player_id: primary };
    },
    /** The chosen players as objects, primary first (used to offer them for linking markers). */
    players() {
      return this.read().player_ids.map(byId);
    },
    primaryPlayer() {
      return primary === null ? null : byId(primary);
    },
  };
}
