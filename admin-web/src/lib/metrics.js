import { t } from '../i18n/i18n.jsx';

/// How the Dashboard's statistics read (v1.12.50; the numbers are the server's,
/// app/services/incident_statistics.py). Until then this file worked out the
/// five response measures from the 500 newest incidents.
///
/// A median nobody has reached yet is "—", never a zero that would read as
/// instant; a change is given only against a period the records cover.

const MINUS = '−';

export function formatMinutes(m) {
  if (m == null) return '—';
  if (m < 1) return `${Math.round(m * 60)} s`;
  if (m < 60) return t('{n} min', { n: m < 10 ? m.toFixed(1) : Math.round(m) });
  let hours = Math.floor(m / 60);
  let minutes = Math.round(m % 60);
  if (minutes === 60) {
    hours += 1;
    minutes = 0;
  }
  return t('{h} h {m} min', { h: hours, m: minutes });
}

export function formatShare(share) {
  return share == null ? '—' : `${Math.round(share * 100)}%`;
}

const signed = (change, text) => `${change > 0 ? '+' : MINUS}${text}`;

/* A measure against the period before: what to write, and whether that is
 * better. More fires is neither. */
function change(value, previous, { nothing, text, judged }) {
  if (value == null || previous == null) return null;
  const by = value - previous;
  if (nothing(by)) return { direction: 0, text: null, better: null };
  return {
    direction: by > 0 ? 1 : -1,
    text: signed(by, text(Math.abs(by))),
    better: judged ? by < 0 : null,
  };
}

export const changeInMinutes = (value, previous) => change(value, previous, {
  nothing: (by) => Math.round(Math.abs(by) * 60) === 0, text: formatMinutes, judged: true,
});

export const changeInCount = (value, previous) => change(value, previous, {
  nothing: (by) => by === 0, text: String, judged: false,
});

export const changeInShare = (value, previous) => change(value, previous, {
  nothing: (by) => Math.round(Math.abs(by) * 100) === 0, text: formatShare, judged: true,
});

const MANILA_MS = 8 * 3600e3;
const SHORT = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', month: 'short', day: 'numeric' });
const LONG = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', weekday: 'short', month: 'short', day: 'numeric' });

// The server's days are Manila's, as "2026-11-16".
const dayDate = (day) => new Date(`${day}T00:00:00+08:00`);
export const shortDay = (day) => SHORT.format(dayDate(day));
export const longDay = (day) => LONG.format(dayDate(day));
export const shortDate = (iso) => SHORT.format(new Date(iso));

/* The Manila day records begin on, as the server writes a day: the days
 * before it are unknown, not days without a fire. */
export const recordedFrom = (iso) => (iso
  ? new Date(new Date(iso).getTime() + MANILA_MS).toISOString().slice(0, 10)
  : null);

/* Clean whole ticks from zero to at least `max`, four steps at most. */
export function countTicks(max) {
  if (max <= 0) return [0, 1];
  let step = 1;
  for (let scale = 1; ; scale *= 10) {
    const found = [1, 2, 5].map((n) => n * scale).find((n) => max / n <= 4);
    if (found) {
      step = found;
      break;
    }
  }
  const steps = Math.ceil(max / step);
  return Array.from({ length: steps + 1 }, (_, i) => i * step);
}
