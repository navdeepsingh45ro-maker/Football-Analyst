// Looking a player up on the web and filling the player form with what is found.
//
// The source is Wikidata, Wikipedia's database of facts (see
// backend/services/lookup_service.py for what is read and what is refused).
//
// THE RULES THIS FILE KEEPS
//   Nothing is sent until you press Search, and only the name in the box is sent.
//   Only EMPTY boxes are filled. What you typed is never replaced. (One exception:
//   when adding a new player, the name you searched with becomes the full name.)
//   Nothing is saved here. The form is filled; you check it and press the form's
//   own button.
//   A line saying where the details came from is added to the Notes box, so the
//   source travels with the player.

import { api, ApiError } from '../api.js';
import { clear, h } from '../dom.js';
import { formatDate } from '../format.js';

// form field -> what to call it in a sentence
const WORDS = {
  full_name: 'name', date_of_birth: 'date of birth', nationality: 'nationality', height_cm: 'height',
  preferred_foot: 'preferred foot', primary_position: 'position', current_team: 'club', national_team: 'national team',
  shirt_number: 'shirt number', photo_url: 'photo',
};

function sourceLink(href, text) {
  return h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, text);
}

/**
 * The "Fill in from the web" box for the player form.
 *   form    what buildForm() returned: its controls are read and filled
 *   isNew   true when adding a player (the searched name may then replace the name box)
 *   name    the name to offer in the search box (the player's, when editing)
 * Returns { element, read } as formDialog's `extra` expects; it adds no values of its own.
 */
export function playerLookup(form, { isNew, name = '' }) {
  const box = h('input', { type: 'search', id: 'lookup-name', value: name, maxLength: 80, autocomplete: 'off',
    placeholder: 'A player\'s name' });
  const button = h('button', { type: 'button', class: 'button', onclick: () => search() }, 'Search the web');
  const output = h('div', { class: 'lookup-results', 'aria-live': 'polite' });

  const show = (...content) => clear(output).append(...content.flat().filter(Boolean));
  const failure = (error) => h('div', { class: 'note error', role: 'alert' },
    h('p', {}, error instanceof ApiError ? error.message : `Something went wrong: ${error.message}`));

  /** Put the found values into the form's empty boxes. Returns what was filled and what was left as you had it. */
  function fill(details) {
    const filled = [];
    const kept = [];
    for (const [field, value] of Object.entries(details.fields)) {
      const control = form.control(field);
      if (!control || !(field in WORDS)) continue;
      const text = String(value);
      const current = control.value.trim();
      if (current === '' || (field === 'full_name' && isNew)) {
        if (current !== text) {
          control.value = text;
          filled.push(WORDS[field]);
        }
      } else if (current.toLowerCase() !== text.toLowerCase()) {
        kept.push(`${WORDS[field]} (Wikidata says "${text}")`);
      }
    }
    if (filled.length) {
      const notes = form.control('notes');
      const line = `Details filled in from Wikidata (${details.source.url}) on ${formatDate(details.checked_on)}.`;
      if (!notes.value.includes(details.source.url)) notes.value = notes.value.trim() ? `${notes.value.trim()}\n${line}` : line;
    }
    return { filled, kept };
  }

  async function use(result) {
    show(h('p', { class: 'muted' }, `Fetching what Wikidata has on ${result.name}…`));
    try {
      const details = await api.get(`/api/lookup/players/${result.id}`);
      const { filled, kept } = fill(details);
      show(h('div', { class: 'note stack' },
        h('p', {}, h('strong', {}, filled.length
          ? `Filled in from Wikidata: ${filled.join(', ')}.`
          : 'Nothing new to fill in. Wikidata has nothing beyond what is already in the form.')),
        kept.length ? h('p', {}, `Kept what you had typed for: ${kept.join('; ')}.`) : null,
        details.notes.length ? h('ul', {}, details.notes.map((note) => h('li', {}, note))) : null,
        h('p', { class: 'small' }, 'Web data can be wrong or out of date. Check each detail below before you save; nothing is saved yet. Source: ',
          sourceLink(details.source.url, 'Wikidata'),
          details.source.wikipedia_url ? [', ', sourceLink(details.source.wikipedia_url, 'Wikipedia')] : null, '.')));
    } catch (error) {
      show(failure(error));
    }
  }

  async function search() {
    const query = box.value.trim() || form.control('full_name').value.trim();
    if (!query) {
      show(h('p', { class: 'small' }, 'Type the player\'s name first.'));
      box.focus();
      return;
    }
    box.value = query;
    button.disabled = true;
    show(h('p', { class: 'muted' }, 'Searching…'));
    try {
      const found = await api.get('/api/lookup/players', { q: query });
      if (!found.results.length) {
        show(h('p', {}, `Wikidata has no football player matching "${found.query}". Try another spelling, or type the details yourself.`));
        return;
      }
      show(h('p', { class: 'small muted' }, 'Choose the right person:'),
        h('ul', { class: 'list' }, found.results.map((result) => h('li', {},
          h('div', {}, h('strong', {}, result.name),
            result.description ? h('div', { class: 'small muted' }, result.description) : null),
          h('button', { type: 'button', class: 'button small', 'aria-label': `Use the details of ${result.name}`,
            onclick: () => use(result) }, 'Use these details')))));
    } catch (error) {
      show(failure(error));
    } finally {
      button.disabled = false;
    }
  }

  // The box sits inside the dialog's form: Enter must search, not save the player.
  box.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      search();
    }
  });

  const element = h('div', { class: 'lookup' },
    h('div', { class: 'field' },
      h('label', { for: 'lookup-name' }, 'Fill in from the web (optional)'),
      h('div', { class: 'lookup-row' }, box, button),
      h('div', { class: 'help' }, 'Looks the player up on Wikidata, Wikipedia\'s database of facts, and fills in the empty boxes below '
        + 'for you to check. Only the name typed here is sent.')),
    output);
  return { element, read: () => ({}) };
}
