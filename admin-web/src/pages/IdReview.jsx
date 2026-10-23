import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import { ConfirmDialog, EmptyState, Icon, PageHeader, StatePanel } from '../components/ui/index.js';
import ZoomablePhoto from '../components/ui/ZoomablePhoto.jsx';

/* ID reviews (REPLIT (MAIN) 10 · A50 875:7972, A51 875:8156; Section 2.1
 * Tier 2, Section 2.6): National ID submissions the automatic check sent to
 * a person. Approving awards +50%, the largest single step and the only
 * route past a light-green badge to green. Asking them to try again records
 * the reviewer and the reason — refusing someone's government ID needs an
 * audit trail — and they can start a new check from the app.
 *
 * The photos stay hidden until the reviewer opens each one. The design's
 * failure reason, ID number and channel breakdown are not returned by the
 * server, so the details list what it does return. */

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });

const TYPE = { national_id: 'National ID' };

/* How long a submission has been waiting. A queue that quietly grows is the
 * failure mode here: nobody chases their own verification, they just stay on
 * a yellow badge and every report they file looks less credible. */
function waiting(iso) {
  if (!iso) return null;
  const hours = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (hours < 1) return 'waiting under an hour';
  if (hours < 24) return `waiting ${Math.floor(hours)} hour${Math.floor(hours) === 1 ? '' : 's'}`;
  const days = Math.floor(hours / 24);
  return `waiting ${days} day${days === 1 ? '' : 's'}`;
}

const nameOf = (item) => item.full_name || 'Unnamed resident';

export default function IdReview() {
  const { org, refreshQueues } = useConsole();
  const [items, setItems] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      const rows = await api.pendingVerifications();
      setItems(Array.isArray(rows) ? rows : []);
      setPhase('ready');
    } catch (e) {
      setError(e.message || 'The reviews could not be loaded.');
      setPhase('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  const open = items.find((i) => i.id === openId) ?? null;

  async function decided(message) {
    setOpenId(null);
    setNotice(message);
    refreshQueues?.();
    await load();
  }

  if (open) {
    return (
      <>
        <Review item={open} onBack={() => setOpenId(null)} onDecided={decided} />
        {notice && <div className="ad-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
      </>
    );
  }

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={`${org?.name ?? 'Central hub'} · Manual National ID review`}
        title="ID reviews"
        description="Shown when the automatic ID check can’t decide. Approving adds 50% to a resident’s verification. Verification never blocks a report."
        actions={(
          <button type="button" className="ad-button ad-button--secondary" onClick={load} disabled={phase === 'loading'}>
            Refresh
          </button>
        )}
      />

      {phase === 'loading' ? (
        <StatePanel kind="loading" title="Loading reviews…" busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title="The reviews couldn’t load" description={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState icon="verification" title="Nothing waiting">
          A submission appears here when the automatic check can’t decide on someone’s National ID.
        </EmptyState>
      ) : (
        <section className="ad-panel" aria-labelledby="ad-idr-waiting">
          <h2 className="ad-decision-title" id="ad-idr-waiting">Waiting · {items.length}</h2>
          <ul className="ad-idr-list">
            {items.map((item) => (
              <li key={item.id}>
                <button type="button" className="ad-idr-row" onClick={() => setOpenId(item.id)}>
                  <span className="ad-idr-plate" aria-hidden="true"><Icon name="verification" /></span>
                  <span className="ad-cell-text">
                    <span className="ad-cell-title">{nameOf(item)}</span>
                    <span className="ad-cell-meta">
                      {TYPE[item.type] ?? item.type} · {waiting(item.submitted_at)}
                    </span>
                  </span>
                  <Icon name="chevron-right" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {phase === 'ready' && items.length > 0 && (
        <div className="ad-alert ad-alert--info">
          <span className="ad-alert-mark" aria-hidden="true">i</span>
          <p className="ad-alert-body">ID photos and selfies stay hidden until you open a review.</p>
        </div>
      )}

      {notice && <div className="ad-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
    </div>
  );
}

/* A hidden photo (A51): nothing is fetched or drawn until Show is pressed. */
function Photo({ label, url }) {
  const [shown, setShown] = useState(false);

  if (!url) {
    return (
      <div className="ad-idr-photo">
        <Icon name="visibility-off" />
        <p className="ad-cell-title">{label}</p>
        <p className="ad-cell-meta">Not provided</p>
      </div>
    );
  }
  if (!shown) {
    return (
      <div className="ad-idr-photo">
        <Icon name="visibility-off" />
        <p className="ad-cell-title">{label}</p>
        <p className="ad-cell-meta">Hidden until you open it</p>
        <button type="button" className="ad-button ad-button--secondary ad-button--compact" onClick={() => setShown(true)}>
          Show<span className="web-sr-only"> {label}</span>
        </button>
      </div>
    );
  }
  return (
    <figure className="ad-idr-photo is-shown">
      {/* Identity documents are small and detailed; a thumbnail is not enough
          to judge one against a selfie. */}
      <ZoomablePhoto src={url} alt={label} caption={label} className="ad-idr-image-button" imageClassName="ad-idr-image" />
      <figcaption className="ad-idr-caption">
        {label}
        <button type="button" className="ad-text-button" onClick={() => setShown(false)}>Hide</button>
      </figcaption>
    </figure>
  );
}

function Review({ item, onBack, onDecided }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState('');
  const name = nameOf(item);

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.approveVerification(item.id);
      await onDecided(`ID approved. ${name} is now at ${res?.verified_percent ?? '—'}%.`);
    } catch (e) {
      setError(e.message || 'The ID was not approved. Try again.');
      setBusy(false);
    }
  }

  async function askAgain() {
    if (!reason.trim()) throw new Error('Say what they should fix — it is recorded with this review.');
    await api.rejectVerification(item.id, reason.trim());
    setAsking(false);
    await onDecided(`${name} was asked to try again.`);
  }

  const details = [
    ['Name entered', name],
    ['Email', item.email || 'Not on record'],
    ['ID type', TYPE[item.type] ?? item.type],
    ['Checked by', item.provider ? item.provider.replace(/^\w/, (c) => c.toUpperCase()) : '—'],
    ['Submitted', item.submitted_at ? DAY.format(new Date(item.submitted_at)) : '—'],
  ];

  return (
    <div className="ad-page ad-incident">
      <button type="button" className="ad-text-button ad-back" onClick={onBack}>← All ID reviews</button>
      <PageHeader
        eyebrow="ID review · Resident account"
        title={name}
        description={`Sent for a manual review at ${item.submitted_at ? CLOCK.format(new Date(item.submitted_at)) : '—'} · ${waiting(item.submitted_at)}.`}
      />

      <div className="ad-idr-grid">
        <Photo label="National ID photo" url={item.id_image_url} />
        <Photo label="Selfie" url={item.selfie_image_url} />
        <section className="ad-panel ad-decision" aria-labelledby="ad-idr-details">
          <h2 className="ad-decision-title" id="ad-idr-details">Details</h2>
          <dl className="ad-facts ad-facts--wide">
            {details.map(([t, v]) => (
              <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <p className="ad-decision-body">Check the selfie is the same person as the ID photo, and that the name on the ID matches the account.</p>
          {error && <p className="ad-inline-error" role="alert">{error}</p>}
          <div className="ad-idr-actions">
            <button type="button" className="ad-button ad-button--secondary" onClick={() => { setReason(''); setAsking(true); }} disabled={busy}>
              Ask to try again
            </button>
            <button type="button" className="ad-button ad-button--primary" onClick={approve} disabled={busy}>
              {busy ? 'Approving…' : 'Approve ID'}
            </button>
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={asking}
        eyebrow="ID review"
        title={`Ask ${name} to try again?`}
        description="Their ID isn’t approved and nothing is added. They can start a new check from the app."
        confirmLabel="Ask to try again"
        onClose={() => setAsking(false)}
        onConfirm={askAgain}
      >
        <label className="ad-field">
          <span className="ad-field-label">What should they fix?</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The ID photo is too blurry to read" maxLength={1000} />
          <span className="ad-field-help">Recorded with the review.</span>
        </label>
      </ConfirmDialog>
    </div>
  );
}
