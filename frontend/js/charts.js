// The small charts on the Reports page: ranked bars and the pitch-zone grid.
//
// WHY THEY LOOK THE WAY THEY DO
// * Ranked bars (movements, outcomes, opponents ...) are ONE colour. The groups
//   are just names with no order, and bar length already shows the count, so
//   colouring bars by size would say the same thing twice. Groups that mean
//   "nothing was recorded" are grey, because they are a different kind of thing.
// * The zone grid uses ONE hue from light to dark: more observations, darker.
//   The count is printed in every cell, so nothing depends on judging a shade.
// * Hovering or tabbing onto a bar or cell shows its details, but never anything
//   that is not also readable on the page itself.
// * Every number links to the observations it counts.
//
// The colours below were checked with a contrast and colour-vision validator
// against this app's page colour (#f3f5f0); change them together, not one by one.

import { clear, h } from './dom.js';

export const BAR_COLOUR = '#34496b';            // 8.3:1 against the page
export const NOT_RECORDED_COLOUR = '#78838f';   // 3.5:1 against the page
// One hue, light to dark. Evenly stepped; the lightest still stands out from the page (2.2:1).
export const ZONE_RAMP = ['#77b593', '#539c79', '#38805f', '#266549', '#144733'];
const INK = '#16263f';
const WHITE = '#ffffff';

// ── Tooltip (one for the whole page) ─────────────────────────────────────────
let tip = null;

function showTip(x, y, { value, label, detail }) {
  if (!tip) {
    tip = h('div', { class: 'chart-tip', role: 'tooltip' });
    document.body.append(tip);
  }
  // The number leads; the name follows. Built from text nodes, never from HTML.
  clear(tip).append(h('strong', {}, value), h('span', {}, label), detail ? h('span', { class: 'detail' }, detail) : null);
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  tip.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - box.width - 8))}px`;
  tip.style.top = `${Math.max(8, y - box.height - 12)}px`;
}

function hideTip() {
  if (tip) tip.hidden = true;
}

/** Show `content` when `element` is hovered, and the same when it gets keyboard focus. */
export function describeOnHover(element, content) {
  element.addEventListener('pointermove', (event) => showTip(event.clientX, event.clientY, content));
  element.addEventListener('pointerleave', hideTip);
  element.addEventListener('focus', () => {
    const box = element.getBoundingClientRect();
    showTip(box.left + box.width / 2, box.top, content);
  });
  element.addEventListener('blur', hideTip);
}

// ── Colour helpers ───────────────────────────────────────────────────────────
function luminance(hex) {
  const channel = (start) => {
    const value = parseInt(hex.slice(start, start + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

/** White or dark text, whichever is easier to read on `fill`. */
export function textOn(fill) {
  const light = luminance(fill);
  const withWhite = 1.05 / (light + 0.05);
  const withInk = (light + 0.05) / (luminance(INK) + 0.05);
  return withWhite >= withInk ? WHITE : INK;
}

/** Which of the five ramp steps a count gets: 1..max spread evenly over the steps. */
export function rampStep(count, max) {
  if (!count || !max) return null;
  return Math.min(ZONE_RAMP.length - 1, Math.ceil((count / max) * ZONE_RAMP.length) - 1);
}

// ── Ranked bars ──────────────────────────────────────────────────────────────
/**
 * A table of groups with a bar for each count.
 *   groups     [{ label, count, share, matches, recorded, small_sample }]
 *   linkFor    (group) => address of the observations that group counts
 */
export function rankedBars(groups, { heading, linkFor }) {
  const largest = Math.max(1, ...groups.map((group) => group.count));
  const rows = groups.map((group) => {
    const percent = Math.round(group.share * 100);
    const bar = h('span', { class: 'chart-bar' });
    bar.style.width = `${(group.count / largest) * 100}%`;
    bar.style.background = group.recorded ? BAR_COLOUR : NOT_RECORDED_COLOUR;
    const link = h('a', { href: linkFor(group) }, `Show ${group.count === 1 ? 'it' : `these ${group.count}`}`);
    const content = {
      value: `${group.count} observation${group.count === 1 ? '' : 's'}`,
      label: group.label,
      detail: `${percent}% of the selection, from ${group.matches} match${group.matches === 1 ? '' : 'es'}`,
    };
    const plot = h('div', { class: 'bar-plot' }, bar, h('span', { class: 'bar-value numeric' }, group.count));
    describeOnHover(plot, content);
    describeOnHover(link, content);
    return h('tr', {},
      h('th', { scope: 'row', class: group.recorded ? null : 'muted' }, group.label),
      h('td', { class: 'bar-cell' }, plot),
      h('td', { class: 'num' }, `${percent}%`),
      h('td', { class: 'num' }, group.matches),
      h('td', {}, link, group.small_sample ? h('span', { class: 'small muted' }, ' (a small number)') : null));
  });
  return h('div', { class: 'table-wrap' }, h('table', { class: 'bars' },
    h('thead', {}, h('tr', {},
      h('th', { scope: 'col' }, heading), h('th', { scope: 'col' }, 'Observations'),
      h('th', { scope: 'col', class: 'num' }, 'Share'), h('th', { scope: 'col', class: 'num' }, 'Matches'),
      h('th', { scope: 'col' }, 'The records'))),
    h('tbody', {}, rows)));
}

// ── Pitch-zone grid ──────────────────────────────────────────────────────────
// How wide each lane really is on a 68 m pitch, so the grid has the pitch's proportions.
const LANE_WIDTHS = [13.84, 11, 18.32, 11, 13.84];

/**
 * Recorded movements on a grid of the pitch: 5 lanes down, 3 thirds across,
 * drawn the same way round as the pitch diagram (attacking left to right).
 *   data     the answer of /api/analytics/zones
 *   linkFor  (observationIds) => address listing them
 */
export function zoneGrid(data, { linkFor }) {
  const largest = Math.max(0, ...data.cells.flat().map((cell) => cell.count));
  const grid = h('div', { class: 'zone-grid', role: 'table', 'aria-label': `Where recorded movements ${data.point === 'start' ? 'started' : 'ended'}` });
  grid.style.gridTemplateRows = LANE_WIDTHS.map((width) => `${width}fr`).join(' ');

  data.lanes.forEach((lane, laneIndex) => {
    data.thirds.forEach((third, thirdIndex) => {
      const cell = data.cells[laneIndex][thirdIndex];
      const step = rampStep(cell.count, largest);
      const zone = `${third}, ${lane}`;
      const box = cell.count
        ? h('a', { class: 'zone', href: linkFor(cell.observation_ids), 'aria-label': `${cell.count} in the ${zone}. Show them.` }, cell.count)
        : h('span', { class: 'zone is-zero', 'aria-label': `None in the ${zone}` }, '0');
      if (step !== null) {
        box.style.background = ZONE_RAMP[step];
        box.style.color = textOn(ZONE_RAMP[step]);
      }
      describeOnHover(box, { value: `${cell.count} observation${cell.count === 1 ? '' : 's'}`, label: zone });
      grid.append(box);
    });
  });

  const scale = h('div', { class: 'zone-scale', 'aria-hidden': 'true' },
    h('span', { class: 'small muted' }, 'fewer'),
    ZONE_RAMP.map((colour) => {
      const swatch = h('i', {});
      swatch.style.background = colour;
      return swatch;
    }),
    h('span', { class: 'small muted' }, largest ? `more (most in one zone: ${largest})` : 'more'));

  return h('figure', { class: 'zone-figure' },
    h('div', { class: 'zone-axis small muted' }, data.thirds.map((third) => h('span', {}, third))),
    h('div', { class: 'zone-body' },
      h('div', { class: 'zone-lanes small muted' }, data.lanes.map((lane, index) => {
        const label = h('span', {}, lane);
        label.style.flex = `${LANE_WIDTHS[index]} 1 0`;
        return label;
      })),
      grid),
    h('figcaption', { class: 'small muted' }, 'Own goal on the left, the goal being attacked on the right; the left '
      + 'touchline at the top. Lanes follow the edges of the penalty area and the goal area.'),
    scale);
}
