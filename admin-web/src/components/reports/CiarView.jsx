import { useState } from 'react';

import { StatePanel } from '../ui/index.js';

/* The CIAR, read only (REPLIT (MAIN) 10 · A62 878:8549 six parts, A63
 * 878:8767 generating, A63b 878:8929 couldn't be generated). UI READY — the
 * server writes a narrative AI summary, not a six-part CIAR, so this is shown
 * only in docs/console-ready.html.
 *
 *   state   'ready' | 'generating' | 'failed'
 *   ciar    { lockedAt, source, parts: [{ key, title, rows?: [[label, value]], text? }] }
 *   onRetry () => void        offered on 'failed' when the integrator allows it
 *
 * The parts, their titles and their order come from the integrator. */
export default function CiarView({ state, ciar, onRetry }) {
  const parts = ciar?.parts ?? [];
  const [active, setActive] = useState(parts[0]?.key ?? null);

  if (state === 'generating') {
    return (
      <StatePanel kind="loading" title="The CIAR is being written" busy
                  description="It is compiled from the filed report and the audit log, and appears here when it is ready. The report itself is already on record." />
    );
  }
  if (state === 'failed' || parts.length === 0) {
    return (
      <StatePanel kind="error" title="The CIAR couldn’t be generated"
                  description="The filed report is still on record and can be read and downloaded."
                  onRetry={onRetry} retryLabel="Try again" />
    );
  }

  return (
    <div className="ad-ciar">
      <nav className="ad-panel ad-ciar-index" aria-label="CIAR parts">
        <h3 className="ad-decision-title">{parts.length === 6 ? 'Six parts' : 'Parts'}</h3>
        <ul>
          {parts.map((p, i) => (
            <li key={p.key}>
              <a
                href={`#ad-ciar-${p.key}`}
                className={`ad-ciar-link${active === p.key ? ' is-active' : ''}`}
                onClick={() => setActive(p.key)}
                aria-current={active === p.key ? 'true' : undefined}
              >
                Part {['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'][i] ?? i + 1} · {p.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <article className="ad-panel ad-ciar-body">
        {ciar.lockedAt && (
          <p className="ad-ciar-lock"><span aria-hidden="true">🔒</span> Locked {ciar.lockedAt} · read only{ciar.source ? ` · ${ciar.source}` : ''}</p>
        )}
        {parts.map((p, i) => (
          <section key={p.key} id={`ad-ciar-${p.key}`} className="ad-ciar-part">
            <p className="web-eyebrow">Part {['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'][i] ?? i + 1}</p>
            <h4 className="ad-decision-title">{p.title}</h4>
            {p.rows && (
              <dl className="ad-facts ad-facts--wide">
                {p.rows.map(([t, v]) => <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>)}
              </dl>
            )}
            {p.text && <p className="ad-decision-body ad-report-narrative">{p.text}</p>}
          </section>
        ))}
      </article>
    </div>
  );
}
