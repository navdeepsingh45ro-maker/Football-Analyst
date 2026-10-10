// Turning stored values into text and back. Pure functions: no page, no network,
// so they are tested directly with `npm test` (frontend/tests/format.test.js).
//
// THE THREE KINDS OF TIME (see backend/models/observation_model.py)
//   video time / match clock   a number of seconds  -> shown as a clock, "35:10"
//   calendar date              "2026-03-08"         -> shown as "8 Mar 2026"
//   calendar moment (UTC)      "2026-10-09T21:45Z"  -> shown in your local time

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const pad = (number) => String(number).padStart(2, '0');

/**
 * Seconds -> clock text for display: 2110.4 -> "35:10", 3723 -> "1:02:03".
 * Rounds DOWN, so the clock never shows a second that has not been reached.
 * Returns null for an unknown time.
 */
export function formatClock(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  return hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`;
}

/**
 * Seconds -> clock text that loses nothing: 612.5 -> "10:12.5".
 *
 * Used to fill the time field of an edit form. If the form showed "10:12" and
 * you pressed Save without touching it, the stored 612.5 would silently become
 * 612. Showing the exact value means an untouched timestamp is saved unchanged.
 */
export function formatClockExact(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '';
  const thousandths = Math.round(seconds * 1000);
  const fraction = thousandths % 1000;
  const clock = formatClock(Math.floor(thousandths / 1000));
  return fraction ? `${clock}.${String(fraction).padStart(3, '0').replace(/0+$/, '')}` : clock;
}

/**
 * Clock text -> seconds: "35:10" -> 2110, "1:02:03" -> 3723, "10:12.5" -> 612.5, "95" -> 95.
 * Returns null for an empty field. Throws an Error with a readable message for anything else.
 */
export function parseClock(text) {
  const value = String(text ?? '').trim();
  if (value === '') return null;
  const parts = value.split(':');
  const numbers = parts.map((part) => (/^\d+(\.\d+)?$/.test(part) ? Number(part) : NaN));
  const invalid = parts.length > 3
    || numbers.some((number) => Number.isNaN(number))
    || numbers.slice(1).some((number) => number >= 60);
  if (invalid) throw new Error('Use a clock like 32:14 or 1:02:03');
  return numbers.reduce((total, number) => total * 60 + number, 0);
}

/** "2026-03-08" -> "8 Mar 2026". Done by hand so no timezone can shift the day. */
export function formatDate(isoDate) {
  if (!isoDate) return null;
  const [year, month, day] = isoDate.slice(0, 10).split('-').map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** "2026-10-09T21:45:04Z" (UTC) -> the same moment in your local time. */
export function formatMoment(isoMoment) {
  if (!isoMoment) return null;
  return new Date(isoMoment).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Today's date as "2026-03-08", in local time (for the default of a date field). */
export function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** plural(1, 'observation') -> "1 observation"; plural(3, 'observation') -> "3 observations". */
export function plural(count, word, manyWord) {
  return `${count} ${count === 1 ? word : (manyWord || `${word}s`)}`;
}

/** A number with a fixed count of decimals, e.g. round(15.437, 1) -> "15.4". */
export function round(number, decimals = 1) {
  return Number(number).toFixed(decimals);
}

/** Shorten long text for a list row. */
export function excerpt(text, length = 140) {
  if (!text) return '';
  return text.length > length ? `${text.slice(0, length - 1).trimEnd()}…` : text;
}

/** "first_touch" -> "First touch". */
export function humanize(key) {
  const words = String(key).replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
