import { useRef, useState } from 'react';

import { t } from '../../i18n/i18n.jsx';

/* Ranked or ordered bars on one baseline (v1.12.50), as a real table: each
 * row says its name, count and share, so nothing waits on hover. `rows`:
 * [{ key, name, detail?, count, color? }]; `color` is a CSS variable, for a
 * scale whose order the colour carries or for what is not yet known. */
export default function BarTable({ caption, nameHeading, rows, total, empty }) {
  const frame = useRef(null);
  const [tip, setTip] = useState(null);

  if (!total) return <p className="rpl-chart-none is-inline">{empty}</p>;

  const most = Math.max(1, ...rows.map((r) => r.count));
  const share = (count) => `${Math.round((count / total) * 100)}%`;

  function point(event, row) {
    if (event.pointerType === 'touch') return;
    const box = frame.current.getBoundingClientRect();
    const line = event.currentTarget.getBoundingClientRect();
    setTip({
      row,
      left: Math.min(box.width - 80, Math.max(80, event.clientX - box.left)),
      top: line.top - box.top,
    });
  }

  return (
    <div className="rpl-bars" ref={frame} onPointerLeave={() => setTip(null)}>
      <table className="rpl-bar-table">
        <caption className="web-sr-only">{caption}</caption>
        <thead className="web-sr-only">
          <tr>
            <th scope="col">{nameHeading}</th>
            <th scope="col">{t('Fires')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} onPointerMove={(event) => point(event, row)}>
              <th scope="row">
                {row.name}
                {row.detail && <span className="rpl-bar-detail">{row.detail}</span>}
              </th>
              <td>
                <span className="rpl-bar-cell">
                  <span className="rpl-bar-track" aria-hidden="true">
                    {row.count > 0 && (
                      <span
                        className="rpl-hbar"
                        style={{ width: `${(row.count / most) * 100}%`, ...(row.color ? { '--bar': `var(${row.color})` } : {}) }}
                      />
                    )}
                  </span>
                  <span className={`rpl-bar-value${row.count ? '' : ' is-zero'}`}>{row.count}</span>
                  <span className="rpl-bar-share">{row.count ? share(row.count) : ''}</span>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {tip && rows.includes(tip.row) && (
        <div className="rpl-chart-tip is-row" style={{ left: tip.left, top: tip.top }} aria-hidden="true">
          <strong>{t('{count} of {total} fires', { count: tip.row.count, total })}</strong>
          <span>{[tip.row.name, tip.row.detail].filter(Boolean).join(', ')}</span>
        </div>
      )}
    </div>
  );
}
