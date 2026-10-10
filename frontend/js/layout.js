// The frame every page shares: the navigation strip, the page heading, and a
// standard way to show "loading" and "that failed".
//
// A page script starts like this:
//
//   const page = mountPage({ active: 'players.html', title: 'Players' });
//   load(page.content, async () => { ...fetch data, build elements, return them... });

import { ApiError } from './api.js';
import { clear, h, svg } from './dom.js';

const NAVIGATION = [
  ['index.html', 'Dashboard'],
  ['players.html', 'Players'],
  ['matches.html', 'Matches'],
  ['video.html', 'Video analysis'],
  ['pitch.html', 'Tactical pitch'],
  ['observations.html', 'Observations'],
  ['reports.html', 'Reports'],
  ['notebook.html', 'Notebook'],
  ['settings.html', 'Settings'],
];

/** The small pitch drawing next to the app's name. */
function brandMark() {
  const chalk = { fill: 'none', stroke: '#f3f5f0', 'stroke-width': 1.6 };
  return svg('svg', { class: 'brand-mark', viewBox: '0 0 30 30', 'aria-hidden': 'true' },
    svg('rect', { x: 1.5, y: 5, width: 27, height: 20, rx: 2, fill: '#2e6b4e', stroke: '#f3f5f0', 'stroke-width': 1.6 }),
    svg('line', { x1: 15, y1: 5, x2: 15, y2: 25, ...chalk }),
    svg('circle', { cx: 15, cy: 15, r: 4, ...chalk }));
}

/**
 * Build the page frame and return the places a page fills in.
 *   active   the file name of the current page, to highlight it in the navigation
 *   title    the page heading (can be changed later through the returned `heading`)
 *   lede     an optional sentence under the heading
 */
export function mountPage({ active, title, lede = null, wide = false }) {
  document.title = `${title} – Football Analyst`;
  const heading = h('h1', {}, title);
  const ledeBox = h('p', { class: 'lede' }, lede);
  ledeBox.hidden = !lede;
  const actions = h('div', { class: 'actions' });
  const before = h('div', {});  // e.g. a "back to all players" link
  const content = h('div', {});

  document.body.append(
    h('header', { class: 'bar' },
      h('a', { class: 'brand', href: 'index.html' }, brandMark(), 'Football Analyst'),
      h('nav', { class: 'nav', 'aria-label': 'Main' }, NAVIGATION.map(([href, label]) => h('a', {
        href, 'aria-current': href === active ? 'page' : null,
      }, label)))),
    h('main', { class: wide ? 'page wide' : 'page' },
      before,
      h('div', { class: 'page-head' }, h('div', {}, heading, ledeBox), actions),
      content),
    h('div', { id: 'toasts', role: 'status', 'aria-live': 'polite' }),
  );

  return {
    content, heading, actions, before,
    setTitle(text) {
      document.title = `${text} – Football Analyst`;
    },
    setLede(text) {
      ledeBox.textContent = text || '';
      ledeBox.hidden = !text;
    },
  };
}

/** A box that explains a failure and, when given, offers to try again. */
export function errorNote(error, retry = null) {
  const message = error instanceof ApiError ? error.message : `Something went wrong in the page: ${error.message}`;
  if (!(error instanceof ApiError)) console.error(error);  // a bug in the page: keep the details for debugging
  return h('div', { class: 'note error', role: 'alert' }, h('p', {}, message),
    retry ? h('button', { type: 'button', class: 'button small', onclick: retry }, 'Try again') : null);
}

/**
 * Fill `container` with whatever `build` returns, showing "Loading…" meanwhile
 * and an explanation with a retry button if it fails. `build` may be async and
 * returns an element or an array of elements.
 */
export async function load(container, build) {
  clear(container).append(h('p', { class: 'muted' }, 'Loading…'));
  try {
    const result = await build();
    clear(container).append(...[result].flat().filter(Boolean));
  } catch (error) {
    clear(container).append(errorNote(error, () => load(container, build)));
  }
}
