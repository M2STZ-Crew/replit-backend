import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import { ConfirmDialog, EmptyState, Icon, PageHeader, StatePanel } from '../components/ui/index.js';
import ZoomablePhoto from '../components/ui/ZoomablePhoto.jsx';

/* ID reviews (REPLIT (MAIN) 10 · A50 875:7972, A51 875:8156; Section 2.1
 * Tier 2, Section 2.6): National IDs residents sent from the app. The reviewer
 * runs the QR photo through PSA's PhilSys Check, then compares what it shows
 * with the ID and the selfie. Approving awards +50%, the largest single step
 * and the only route past a light-green badge to green. Asking them to try
 * again records the reviewer and the reason — refusing someone's government ID
 * needs an audit trail — and they read the reason in the app.
 *
 * The photos stay hidden until the reviewer opens each one, and the server
 * deletes them when the review is decided. The design's failure reason, ID
 * number and channel breakdown are not returned by the server, so the details
 * list what it does return. */

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });

const TYPE = { national_id: 'National ID' };

const PHILSYS_CHECK = 'https://verify.philsys.gov.ph/';

/* What PhilSys Check can say, in PSA's own words so they match the screen. A
 * failed check goes back to the resident with PSA's advice for it. */
const RESULTS = [
  { key: 'verified', label: 'PhilID/ePhilID has been Verified' },
  {
    key: 'deactivated',
    label: 'Deactivated Card',
    reason: 'PhilSys Check says this card is deactivated. Bring your ID to the nearest PhilSys Registration Center or email info@philsys.gov.ph.',
  },
  {
    key: 'unreadable',
    label: 'QR Code could not be read',
    reason: 'PhilSys Check could not read your QR code. Take the QR photo again, close up, in good light, with the whole code in frame.',
  },
];

const NEXT = {
  verified: 'Check the name, birth date and card number it shows match the ID photo. An ePhilID also shows a portrait. Then check the selfie is the same person.',
  deactivated: 'Ask them to try again. The reason below is filled in for you.',
  unreadable: 'PSA asks for three tries. If it still fails, ask them to try again.',
};

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
        {notice && <div className="rpl-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
      </>
    );
  }

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={`${org?.name ?? 'Central hub'} · Manual National ID review`}
        title="ID reviews"
        description="National IDs residents sent from the app. Run each QR code through PhilSys Check, then decide. Approving adds 50% to a resident’s verification. Verification never blocks a report."
        actions={(
          <button type="button" className="rpl-button rpl-button--secondary" onClick={load} disabled={phase === 'loading'}>
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
          A submission appears here when a resident sends their National ID from the app.
        </EmptyState>
      ) : (
        <section className="rpl-panel" aria-labelledby="rpl-idr-waiting">
          <h2 className="rpl-decision-title" id="rpl-idr-waiting">Waiting · {items.length}</h2>
          <ul className="rpl-idr-list">
            {items.map((item) => (
              <li key={item.id}>
                <button type="button" className="rpl-idr-row" onClick={() => setOpenId(item.id)}>
                  <span className="rpl-idr-plate" aria-hidden="true"><Icon name="verification" /></span>
                  <span className="rpl-cell-text">
                    <span className="rpl-cell-title">{nameOf(item)}</span>
                    <span className="rpl-cell-meta">
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
        <div className="rpl-alert rpl-alert--info">
          <span className="rpl-alert-mark" aria-hidden="true">i</span>
          <p className="rpl-alert-body">Photos stay hidden until you open a review, and they are deleted when you decide.</p>
        </div>
      )}

      {notice && <div className="rpl-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
    </div>
  );
}

/* A hidden photo (A51): nothing is fetched or drawn until Show is pressed. */
function Photo({ label, url }) {
  const [shown, setShown] = useState(false);

  if (!url) {
    return (
      <div className="rpl-idr-photo">
        <Icon name="visibility-off" />
        <p className="rpl-cell-title">{label}</p>
        <p className="rpl-cell-meta">Not provided</p>
      </div>
    );
  }
  if (!shown) {
    return (
      <div className="rpl-idr-photo">
        <Icon name="visibility-off" />
        <p className="rpl-cell-title">{label}</p>
        <p className="rpl-cell-meta">Hidden until you open it</p>
        <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" onClick={() => setShown(true)}>
          Show<span className="web-sr-only"> {label}</span>
        </button>
      </div>
    );
  }
  return (
    <figure className="rpl-idr-photo is-shown">
      {/* Identity documents are small and detailed; a thumbnail is not enough
          to judge one against a selfie. */}
      <ZoomablePhoto src={url} alt={label} caption={label} className="rpl-idr-image-button" imageClassName="rpl-idr-image" />
      <figcaption className="rpl-idr-caption">
        {label}
        <button type="button" className="rpl-text-button" onClick={() => setShown(false)}>Hide</button>
      </figcaption>
    </figure>
  );
}

/* The check itself happens on PSA's site, so this only gets the reviewer there
 * with the right file. Camera access is not needed for an image file. */
function PhilSysSteps({ item }) {
  return (
    <section className="rpl-panel rpl-idr-check" aria-labelledby="rpl-idr-check">
      <h2 className="rpl-decision-title" id="rpl-idr-check">PhilSys Check</h2>
      <p className="rpl-decision-body">PSA’s own site confirms the QR code is genuine and the card is active.</p>
      {item.qr_download_url ? (
        <ol className="rpl-idr-steps">
          <li>
            <a className="rpl-button rpl-button--secondary rpl-button--compact" href={item.qr_download_url}>Download QR photo</a>
          </li>
          <li>
            <a className="rpl-button rpl-button--secondary rpl-button--compact" href={PHILSYS_CHECK} target="_blank" rel="noreferrer">
              Open PhilSys Check<span className="web-sr-only"> in a new tab</span>
            </a>
          </li>
          <li>Press <strong>Click to scan QR code</strong>, then <strong>Camera</strong>, then <strong>Scan an Image File</strong>. You don’t need to allow the camera.</li>
          <li>Press <strong>Select Image</strong> and pick the file you downloaded.</li>
          <li>Delete the downloaded file from this computer when you finish.</li>
        </ol>
      ) : (
        <p className="rpl-inline-error" role="alert">This submission has no QR photo, so it can’t be checked. Ask them to update the app and try again.</p>
      )}
    </section>
  );
}

function Review({ item, onBack, onDecided }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState('');
  const [result, setResult] = useState(null);
  const name = nameOf(item);
  const failed = RESULTS.find((r) => r.key === result)?.reason ? result : null;

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.approveVerification(item.id, result);
      await onDecided(`ID approved and photos deleted. ${name} is now at ${res?.verified_percent ?? '—'}%.`);
    } catch (e) {
      setError(e.message || 'The ID was not approved. Try again.');
      setBusy(false);
    }
  }

  async function askAgain() {
    if (!reason.trim()) throw new Error('Say what they should fix — they read this in the app.');
    await api.rejectVerification(item.id, reason.trim(), failed);
    setAsking(false);
    await onDecided(`${name} was asked to try again. Their photos were deleted.`);
  }

  const details = [
    ['Name entered', name],
    ['Email', item.email || 'Not on record'],
    ['ID type', TYPE[item.type] ?? item.type],
    ['Checked by', item.provider ? item.provider.replace(/^\w/, (c) => c.toUpperCase()) : '—'],
    ['Submitted', item.submitted_at ? DAY.format(new Date(item.submitted_at)) : '—'],
  ];

  return (
    <div className="rpl-page rpl-incident">
      <button type="button" className="rpl-text-button rpl-back" onClick={onBack}>← All ID reviews</button>
      <PageHeader
        eyebrow="ID review · Resident account"
        title={name}
        description={`Sent for a manual review at ${item.submitted_at ? CLOCK.format(new Date(item.submitted_at)) : '—'} · ${waiting(item.submitted_at)}.`}
      />

      <div className="rpl-idr-grid">
        <Photo label="National ID photo" url={item.id_image_url} />
        <Photo label="Selfie" url={item.selfie_image_url} />
        <Photo label="QR code" url={item.qr_image_url} />
        <PhilSysSteps item={item} />
        <section className="rpl-panel rpl-decision rpl-idr-decide" aria-labelledby="rpl-idr-details">
          <h2 className="rpl-decision-title" id="rpl-idr-details">Details</h2>
          <dl className="rpl-facts rpl-facts--wide">
            {details.map(([t, v]) => (
              <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <fieldset className="rpl-choice">
            <legend className="rpl-field-label">What did PhilSys Check say?</legend>
            <div className="rpl-choice-options rpl-choice-options--stack">
              {RESULTS.map((r) => (
                <label key={r.key} className={`rpl-choice-option${result === r.key ? ' is-on' : ''}`}>
                  <input type="radio" name="philsys-result" value={r.key} checked={result === r.key} onChange={() => setResult(r.key)} disabled={busy || !item.qr_download_url} />
                  {r.label}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="rpl-decision-body">{result ? NEXT[result] : 'Run PhilSys Check, then choose what it said to approve this ID.'}</p>
          {error && <p className="rpl-inline-error" role="alert">{error}</p>}
          <div className="rpl-idr-actions">
            <button
              type="button"
              className="rpl-button rpl-button--secondary"
              onClick={() => { setReason(RESULTS.find((r) => r.key === result)?.reason ?? ''); setAsking(true); }}
              disabled={busy}
            >
              Ask to try again
            </button>
            <button type="button" className="rpl-button rpl-button--primary" onClick={approve} disabled={busy || result !== 'verified'}>
              {busy ? 'Approving…' : 'Approve ID'}
            </button>
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={asking}
        eyebrow="ID review"
        title={`Ask ${name} to try again?`}
        description="Their ID isn’t approved and nothing is added. Their photos are deleted, and they can send new ones from the app."
        confirmLabel="Ask to try again"
        onClose={() => setAsking(false)}
        onConfirm={askAgain}
      >
        <label className="rpl-field">
          <span className="rpl-field-label">What should they fix?</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The ID photo is too blurry to read" maxLength={1000} />
          <span className="rpl-field-help">They read this in the app. It’s also recorded with the review.</span>
        </label>
      </ConfirmDialog>
    </div>
  );
}
