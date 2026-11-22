import { useId, useLayoutEffect, useRef, useState } from 'react';

import { countTicks, longDay, recordedFrom, shortDay } from '../../lib/metrics.js';
import { t } from '../../i18n/i18n.jsx';

/* Fires per day (v1.12.50): one series, so one colour and no legend. A
 * pointer anywhere over a day, or the arrow keys, read that day; the table
 * has every one. Labelled where it counts: the busiest day. Days before the
 * records (production was reset 13 Nov 2026) say No records, not zero. */

const HEIGHT = 206;
const TOP = 22; // room for the busiest day's label
const FOOT = 26; // the dates
const AXIS = 28; // the counts
const WIDEST = 24;
const GAP = 2;
const ROUND = 4;
const LABEL_ROOM = 64; // a date's width, with air

/* A column grown from the baseline: round at its end, square at its foot. */
function column(x, base, width, height) {
  const r = Math.min(ROUND, width / 2, height);
  const top = base - height;
  return `M${x} ${base}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + width - r}Q${x + width} ${top} ${x + width} ${top + r}V${base}Z`;
}

const firesWord = (count) => (count === 1 ? t('{count} fire', { count }) : t('{count} fires', { count }));
const known = (day, first) => !first || day >= first;
const readDay = (d, first) => (known(d.day, first) ? firesWord(d.count) : t('No records'));

export function FiresPerDayTable({ days, since = null }) {
  const first = recordedFrom(since);
  return (
    <div className="rpl-day-table" tabIndex={0} role="region" aria-label={t('Fires per day')}>
      <table className="rpl-figures">
        <thead>
          <tr>
            <th scope="col">{t('Day')}</th>
            <th scope="col">{t('Fires')}</th>
          </tr>
        </thead>
        <tbody>
          {[...days].reverse().map((d) => (
            <tr key={d.day}>
              <th scope="row">{longDay(d.day)}</th>
              <td>{known(d.day, first) ? d.count : t('No records')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function FiresPerDay({ days, since = null }) {
  const first = recordedFrom(since);
  const unknown = days.filter((d) => !known(d.day, first)).length;
  const frame = useRef(null);
  const hintId = useId();
  const [width, setWidth] = useState(0);
  const [at, setAt] = useState(null);

  useLayoutEffect(() => {
    const node = frame.current;
    const measure = () => setWidth(Math.round(node.clientWidth));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const n = days.length;
  const most = Math.max(0, ...days.map((d) => d.count));
  const total = days.reduce((sum, d) => sum + d.count, 0);
  const busiest = days.map((d) => d.count).lastIndexOf(most);
  const ticks = countTicks(most);
  const ceiling = ticks.at(-1);
  const plot = Math.max(0, width - AXIS);
  const band = n ? plot / n : 0;
  const bar = Math.max(1, Math.min(WIDEST, band - GAP));
  const base = HEIGHT - FOOT;
  const heightOf = (count) => (count / ceiling) * (base - TOP);
  const middle = (i) => AXIS + (i + 0.5) * band;
  // Dates from today back, as many as fit.
  const every = band ? Math.max(1, Math.ceil(LABEL_ROOM / band)) : 1;
  const shownAt = at != null && at < n ? at : null;

  function point(event) {
    if (!band) return;
    const x = event.clientX - event.currentTarget.getBoundingClientRect().left - AXIS;
    setAt(Math.min(n - 1, Math.max(0, Math.floor(x / band))));
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') {
      setAt(null);
      return;
    }
    const from = shownAt ?? n - 1;
    const next = {
      ArrowLeft: Math.max(0, from - 1), ArrowRight: Math.min(n - 1, from + 1), Home: 0, End: n - 1,
    }[event.key];
    if (next == null) return;
    event.preventDefault();
    setAt(next);
  }

  const summary = total
    ? t('Fires per day: {total} in {days} days, the most {most} on {day}.', {
      total, days: n, most, day: longDay(days[busiest].day),
    })
    : t('Fires per day: none in {days} days.', { days: n });

  const tipWidth = 124;
  const tip = shownAt == null ? null : {
    left: Math.min(Math.max(tipWidth / 2, middle(shownAt)), width - tipWidth / 2),
    top: base - heightOf(days[shownAt].count) - 8,
  };

  return (
    <>
      <div
        ref={frame}
        className="rpl-columns"
        style={{ height: HEIGHT }}
        tabIndex={0}
        role="group"
        aria-label={summary}
        aria-describedby={hintId}
        onKeyDown={onKeyDown}
        onFocus={(event) => { if (event.currentTarget.matches(':focus-visible')) setAt(n - 1); }}
        onBlur={() => setAt(null)}
        onPointerMove={point}
        onPointerDown={point}
        onPointerLeave={(event) => { if (event.pointerType === 'mouse') setAt(null); }}
      >
        {width > 0 && (
          <svg width={width} height={HEIGHT} aria-hidden="true" focusable="false">
            {ticks.map((tick) => {
              const y = base - heightOf(tick);
              return (
                <g key={tick}>
                  <line className={tick ? 'rpl-grid-line' : 'rpl-axis-line'} x1={AXIS} x2={width} y1={y} y2={y} />
                  <text className="rpl-axis-text" x={AXIS - 8} y={y + 4} textAnchor="end">{tick}</text>
                </g>
              );
            })}
            {unknown > 0 && (
              <rect className="rpl-unrecorded" x={AXIS} y={TOP} width={unknown * band} height={base - TOP} />
            )}
            {unknown * band >= 80 && (
              <text className="rpl-axis-text" x={AXIS + (unknown * band) / 2} y={(TOP + base) / 2 + 4} textAnchor="middle">
                {t('No records')}
              </text>
            )}
            {shownAt != null && (
              <rect className="rpl-column-band" x={AXIS + shownAt * band} y={TOP} width={band} height={base - TOP} />
            )}
            {days.map((d, i) => (d.count > 0 ? (
              <path
                key={d.day}
                className={`rpl-column${i === shownAt ? ' is-shown' : ''}`}
                d={column(middle(i) - bar / 2, base, bar, heightOf(d.count))}
              />
            ) : null))}
            {most > 0 && shownAt == null && (
              <text
                className="rpl-column-label"
                x={Math.min(width - 8, middle(busiest))}
                y={base - heightOf(most) - 6}
                textAnchor="middle"
              >
                {most}
              </text>
            )}
            {days.map((d, i) => {
              if ((n - 1 - i) % every !== 0) return null;
              const x = middle(i);
              const last = x > width - LABEL_ROOM / 2 + 8;
              // One that would run into the counts is left to the tooltip.
              if (!last && x < AXIS + LABEL_ROOM / 2 - 12) return null;
              return (
                <text key={`date-${d.day}`} className="rpl-axis-text" x={last ? width : x} y={base + 18} textAnchor={last ? 'end' : 'middle'}>
                  {shortDay(d.day)}
                </text>
              );
            })}
          </svg>
        )}
        {tip && (
          <div className="rpl-chart-tip is-column" style={{ left: tip.left, top: tip.top, width: tipWidth }} aria-hidden="true">
            <strong>{readDay(days[shownAt], first)}</strong>
            <span>{longDay(days[shownAt].day)}</span>
          </div>
        )}
        {total === 0 && unknown < n && <p className="rpl-chart-none">{t('No fires in this period.')}</p>}
      </div>
      <span id={hintId} className="web-sr-only">{t('Left and Right arrows read each day.')}</span>
      <span className="web-sr-only" aria-live="polite">
        {shownAt != null ? `${longDay(days[shownAt].day)}: ${readDay(days[shownAt], first)}` : ''}
      </span>
    </>
  );
}
