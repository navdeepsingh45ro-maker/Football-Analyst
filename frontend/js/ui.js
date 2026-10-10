// Small interface pieces shared by the pages: dialogs, toasts, tabs, and the
// football-specific pieces (clock chips, scorelines, magnets).

import { ApiError } from './api.js';
import { clear, h, svg } from './dom.js';
import { magnet } from './editor/render.js';
import { buildForm } from './forms.js';
import { formatClock, formatDate } from './format.js';

export { magnet };

// ── Feedback ─────────────────────────────────────────────────────────────────
/** A short message in the corner that goes away by itself. */
export function toast(message, kind = 'ok') {
  const box = h('div', { class: kind === 'error' ? 'toast error' : 'toast' }, message);
  document.getElementById('toasts').append(box);
  setTimeout(() => box.remove(), kind === 'error' ? 9000 : 4500);
}

/** Shown where a value is not recorded. Never a 0, never an empty cell. */
export function unknown(title = 'Not recorded') {
  return h('span', { class: 'unknown', title }, '–');
}

/** `value`, or the "not recorded" dash when it is null/undefined/empty. */
export function orUnknown(value) {
  return value === null || value === undefined || value === '' ? unknown() : value;
}

export function emptyState(message, action = null) {
  return h('div', { class: 'empty' }, h('p', {}, message), action);
}

// ── Dialogs ──────────────────────────────────────────────────────────────────
function openDialog(dialog) {
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.showModal();
}

/**
 * Ask before doing something that cannot be undone. Resolves to true or false.
 *   await confirmDialog({ title: 'Delete this note?', message: '...', confirmLabel: 'Delete note', danger: true })
 */
export function confirmDialog({ title, message, confirmLabel = 'Confirm', danger = false }) {
  return new Promise((resolve) => {
    const dialog = h('dialog', {},
      h('div', { class: 'dialog-body' },
        h('div', { class: 'dialog-head' }, h('h2', {}, title)),
        h('div', { class: 'dialog-content' }, typeof message === 'string' ? h('p', {}, message) : message),
        h('div', { class: 'dialog-foot' },
          h('button', { type: 'button', class: 'button', onclick: () => dialog.close('cancel') }, 'Cancel'),
          h('button', { type: 'button', class: danger ? 'button danger primary' : 'button primary', onclick: () => dialog.close('confirm') }, confirmLabel))));
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'));
    openDialog(dialog);
  });
}

/**
 * A dialog holding a form (see forms.js).
 *
 *   const saved = await formDialog({
 *     title: 'Add player', fields: [...], values: {...}, submitLabel: 'Add player',
 *     onSubmit: (values) => api.post('/api/players', values),
 *   });
 *
 * `onSubmit` does the saving. If it throws an ApiError the dialog stays open and
 * shows the problem next to the field concerned. Resolves to whatever onSubmit
 * returned, or to null if the dialog was cancelled.
 */
export function formDialog({ title, fields, values = {}, submitLabel = 'Save', onSubmit, intro = null, wide = false, extra = null }) {
  // `extra` adds a hand-built control above the fields: { element, read: () => moreValues }.
  return new Promise((resolve) => {
    const form = buildForm(fields, values);
    let result = null;
    const submit = h('button', { type: 'submit', class: 'button primary' }, submitLabel);
    const dialog = h('dialog', { class: wide ? 'wide' : null },
      h('form', {
        method: 'dialog', novalidate: true,
        onsubmit: async (event) => {
          event.preventDefault();
          const { values: read, errors } = form.read();
          if (Object.keys(errors).length) {
            form.showErrors(errors);
            return;
          }
          if (extra) Object.assign(read, extra.read());
          submit.disabled = true;
          try {
            result = (await onSubmit(read)) ?? true;
            dialog.close('saved');
          } catch (error) {
            if (!(error instanceof ApiError)) throw error;
            const fieldErrors = error.fieldErrors;
            form.showErrors(Object.keys(fieldErrors).length ? fieldErrors : { '': error.message });
          } finally {
            submit.disabled = false;
          }
        },
      },
      h('div', { class: 'dialog-head' }, h('h2', {}, title)),
      h('div', { class: 'dialog-content stack' }, intro ? h('p', { class: 'muted' }, intro) : null,
        extra ? extra.element : null, form.element),
      h('div', { class: 'dialog-foot' },
        h('button', { type: 'button', class: 'button', onclick: () => dialog.close('cancel') }, 'Cancel'), submit)));
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'saved' ? result : null));
    openDialog(dialog);
  });
}

/** A dialog that just shows content with a Close button. Returns the <dialog>. */
export function infoDialog({ title, content, wide = false, actions = [] }) {
  const dialog = h('dialog', { class: wide ? 'wide' : null },
    h('div', { class: 'dialog-body' },
      h('div', { class: 'dialog-head' }, h('h2', {}, title)),
      h('div', { class: 'dialog-content' }, content),
      h('div', { class: 'dialog-foot' }, actions,
        h('button', { type: 'button', class: 'button primary', onclick: () => dialog.close() }, 'Close'))));
  openDialog(dialog);
  return dialog;
}

/**
 * Delete something that may have records attached (a player, a match).
 *
 * The first request is a plain delete. If the server answers 409 with a list of
 * what is attached, the user is shown exactly those numbers and asked again;
 * only then is the delete repeated with cascade=true. Returns true if deleted.
 */
export async function deleteWithDependencies({ api, path, name, describe }) {
  const sure = await confirmDialog({
    title: `Delete ${name}?`, message: 'This cannot be undone.', confirmLabel: 'Delete', danger: true,
  });
  if (!sure) return false;
  try {
    await api.delete(path);
    return true;
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409 || !error.body.dependencies) throw error;
    const reallySure = await confirmDialog({
      title: `${name} has records attached`,
      message: h('div', {}, h('p', {}, 'Deleting it will also permanently delete:'),
        h('ul', {}, describe(error.body.dependencies).map((line) => h('li', {}, line))),
        h('p', {}, 'Make a backup first (Settings) if you might want any of this back.')),
      confirmLabel: 'Delete everything listed', danger: true,
    });
    if (!reallySure) return false;
    await api.delete(path, { cascade: true });
    return true;
  }
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
/**
 * Tabs whose content is built the first time each is opened.
 *   tabs([{ id: 'stats', label: 'Statistics', count: 3, render: async () => element }], 'stats')
 * The open tab is kept in the address (#stats), so reloading stays on it.
 */
export function tabs(items, initial) {
  const buttons = h('div', { class: 'tabs', role: 'tablist' });
  const panel = h('div', { role: 'tabpanel' });
  const element = h('div', {}, buttons, panel);
  let current = null;

  async function show(id) {
    const item = items.find((candidate) => candidate.id === id) || items[0];
    current = item.id;
    for (const button of buttons.children) button.setAttribute('aria-selected', String(button.dataset.id === item.id));
    history.replaceState(null, '', `#${item.id}`);
    clear(panel).append(h('p', { class: 'muted' }, 'Loading…'));
    try {
      const content = await item.render();
      if (current === item.id) clear(panel).append(...[content].flat().filter(Boolean));
    } catch (error) {
      if (!(error instanceof ApiError)) console.error(error);
      clear(panel).append(h('div', { class: 'note error', role: 'alert' }, error.message));
    }
  }

  for (const item of items) {
    buttons.append(h('button', { type: 'button', role: 'tab', dataset: { id: item.id }, onclick: () => show(item.id) },
      item.label, item.count === undefined ? null : h('span', { class: 'count' }, `(${item.count})`)));
  }
  show(window.location.hash.slice(1) || initial || items[0].id);
  return { element, show, refresh: () => show(current) };
}

// ── Football pieces ──────────────────────────────────────────────────────────
function playGlyph() {
  return svg('svg', { viewBox: '0 0 9 10', 'aria-hidden': 'true' }, svg('polygon', { points: '0,0 9,5 0,10', fill: 'currentColor' }));
}

/**
 * A time inside a video, shown as a chip: ▶ 35:10. With `href` or `onclick` it
 * becomes a link or button that jumps to that moment.
 */
export function videoClock(seconds, { href = null, onclick = null } = {}) {
  const text = formatClock(seconds);
  if (text === null) return null;
  const label = `Video time ${text}`;
  if (href) return h('a', { class: 'clock', href, title: `Open the video at ${text}`, 'aria-label': label }, playGlyph(), text);
  if (onclick) return h('button', { type: 'button', class: 'clock', onclick, title: `Jump to ${text}`, 'aria-label': label }, playGlyph(), text);
  return h('span', { class: 'clock', title: 'Position in the video', 'aria-label': label }, playGlyph(), text);
}

/** The scoreboard clock at that moment, shown as an outlined chip: 32:14. */
export function matchClock(seconds) {
  const text = formatClock(seconds);
  if (text === null) return null;
  return h('span', { class: 'clock match', title: 'Match clock (as on the scoreboard)', 'aria-label': `Match clock ${text}` }, text);
}

/** "Northside FC [2][1] Riverton United". An unknown result shows empty boxes, not 0-0. */
export function scoreline(match) {
  const known = match.home_score !== null && match.home_score !== undefined;
  return h('span', { class: 'scoreline' },
    h('span', { class: 'team' }, match.home_team.name),
    h('span', { class: known ? 'score' : 'score unknown', title: known ? 'Final score' : 'Result not recorded',
      'aria-label': known ? `${match.home_score} to ${match.away_score}` : 'result not recorded' },
    h('b', {}, known ? match.home_score : '–'), h('b', {}, known ? match.away_score : '–')),
    h('span', { class: 'team' }, match.away_team.name));
}

/** "8 Mar 2026", or "date unknown". */
export function matchDate(isoDate) {
  return formatDate(isoDate) || h('span', { class: 'unknown' }, 'date unknown');
}

/** Which marker shape suits a position: goalkeepers square, defenders triangle, others circle. */
export function magnetKindFor(position, positionGroups = {}) {
  const group = positionGroups[position];
  if (group === 'Goalkeeper') return 'goalkeeper';
  if (group === 'Defender') return 'defender';
  return 'attacker';
}

/** Five dots for a 1-5 rating, with the scale's wording as the tooltip. */
export function pips(rating, scale = {}) {
  const label = `${rating} of 5${scale[rating] ? `: ${scale[rating]}` : ''}`;
  return h('span', { class: 'pips', role: 'img', title: label, 'aria-label': label },
    [1, 2, 3, 4, 5].map((step) => h('i', { class: step <= rating ? 'on' : null })));
}

/** A table from column descriptions: table([{ label, cell: (row) => node, numeric }], rows). */
export function table(columns, rows, { onRowClick = null } = {}) {
  return h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, columns.map((column) => h('th', { class: column.numeric ? 'num' : null, scope: 'col' }, column.label)))),
    h('tbody', {}, rows.map((row) => h('tr', {
      class: onRowClick ? 'link-row' : null,
      onclick: onRowClick ? (event) => { if (!event.target.closest('a, button')) onRowClick(row); } : null,
    }, columns.map((column) => h('td', { class: column.numeric ? 'num' : null }, column.cell(row))))))));
}
