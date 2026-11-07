import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import { ConfirmDialog, EmptyState, Icon, PageHeader, StatePanel } from '../components/ui/index.js';
import ZoomablePhoto from '../components/ui/ZoomablePhoto.jsx';
import { t } from '../i18n/i18n.jsx';

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

const TYPE = { get national_id() { return t('National ID'); } };

const PHILSYS_CHECK = 'https://verify.philsys.gov.ph/';

/* What PhilSys Check can say, in PSA's own words so they match the screen. A
 * failed check goes back to the resident with PSA's advice for it. */
const RESULTS = [
  { key: 'verified', get label() { return t('PhilID/ePhilID has been Verified'); } },
  {
    key: 'deactivated',
    get label() { return t('Deactivated Card'); },
    get reason() { return t('PhilSys Check says this card is deactivated. Bring your ID to the nearest PhilSys Registration Center or email info@philsys.gov.ph.'); },
  },
  {
    key: 'unreadable',
    get label() { return t('QR Code could not be read'); },
    get reason() { return t('PhilSys Check could not read your QR code. Take the QR photo again, close up, in good light, with the whole code in frame.'); },
  },
];

const NEXT = {
  get verified() { return t('Check the name, birth date and card number it shows match the ID photo. An ePhilID also shows a portrait. Then check the selfie is the same person.'); },
  get deactivated() { return t('Ask them to try again. The reason below is filled in for you.'); },
  get unreadable() { return t('PSA asks for three tries. If it still fails, ask them to try again.'); },
};

/* How long a submission has been waiting. A queue that quietly grows is the
 * failure mode here: nobody chases their own verification, they just stay on
 * a yellow badge and every report they file looks less credible. */
function waiting(iso) {
  if (!iso) return null;
  const hours = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (hours < 1) return t('waiting under an hour');
  if (hours < 24) return Math.floor(hours) === 1 ? t('waiting {n} hour', { n: 1 }) : t('waiting {n} hours', { n: Math.floor(hours) });
  const days = Math.floor(hours / 24);
  return days === 1 ? t('waiting {n} day', { n: 1 }) : t('waiting {n} days', { n: days });
}

const nameOf = (item) => item.full_name || t('Unnamed resident');

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
      setError(e.message || t('The reviews could not be loaded.'));
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
        eyebrow={t('{org} · Manual National ID review', { org: org?.name ?? t('Central hub') })}
        title={t('ID reviews')}
        description={t('National IDs residents sent from the app. Run each QR code through PhilSys Check, then decide. Approving adds 50% to a resident’s verification. Verification never blocks a report.')}
        actions={(
          <button type="button" className="rpl-button rpl-button--secondary" onClick={load} disabled={phase === 'loading'}>{t('Refresh')}</button>
        )}
      />

      {phase === 'loading' ? (
        <StatePanel kind="loading" skeleton="cards" rows={4} title={t('Loading reviews…')} busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title={t('The reviews couldn’t load')} description={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState icon="verification" title={t('Nothing waiting')}>{t('A submission appears here when a resident sends their National ID from the app.')}</EmptyState>
      ) : (
        <section className="rpl-panel" aria-labelledby="rpl-idr-waiting">
          <h2 className="rpl-decision-title" id="rpl-idr-waiting">{t('Waiting ·')}{' '}{items.length}</h2>
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
          <p className="rpl-alert-body">{t('Photos stay hidden until you open a review, and they are deleted when you decide.')}</p>
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
        <p className="rpl-cell-meta">{t('Not provided')}</p>
      </div>
    );
  }
  if (!shown) {
    return (
      <div className="rpl-idr-photo">
        <Icon name="visibility-off" />
        <p className="rpl-cell-title">{label}</p>
        <p className="rpl-cell-meta">{t('Hidden until you open it')}</p>
        <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" onClick={() => setShown(true)}>{t('Show')}<span className="web-sr-only"> {label}</span>
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
        <button type="button" className="rpl-text-button" onClick={() => setShown(false)}>{t('Hide')}</button>
      </figcaption>
    </figure>
  );
}

/* The check itself happens on PSA's site, so this only gets the reviewer there
 * with the right file. Camera access is not needed for an image file. */
function PhilSysSteps({ item }) {
  return (
    <section className="rpl-panel rpl-idr-check" aria-labelledby="rpl-idr-check">
      <h2 className="rpl-decision-title" id="rpl-idr-check">{t('PhilSys Check')}</h2>
      <p className="rpl-decision-body">{t('PSA’s own site confirms the QR code is genuine and the card is active.')}</p>
      {item.qr_download_url ? (
        <ol className="rpl-idr-steps">
          <li>
            <a className="rpl-button rpl-button--secondary rpl-button--compact" href={item.qr_download_url}>{t('Download QR photo')}</a>
          </li>
          <li>
            <a className="rpl-button rpl-button--secondary rpl-button--compact" href={PHILSYS_CHECK} target="_blank" rel="noreferrer">{t('Open PhilSys Check')}<span className="web-sr-only">{' '}{t('in a new tab')}</span>
            </a>
          </li>
          <li>{t('Press')}{' '}<strong>{t('Click to scan QR code')}</strong>{t(', then')}{' '}<strong>{t('Camera')}</strong>{t(', then')}{' '}<strong>{t('Scan an Image File')}</strong>{t('. You don’t need to allow the camera.')}</li>
          <li>{t('Press')}{' '}<strong>{t('Select Image')}</strong>{' '}{t('and pick the file you downloaded.')}</li>
          <li>{t('Delete the downloaded file from this computer when you finish.')}</li>
        </ol>
      ) : (
        <p className="rpl-inline-error" role="alert">{t('This submission has no QR photo, so it can’t be checked. Ask them to update the app and try again.')}</p>
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
      await onDecided(t('ID approved and photos deleted. {name} is now at {percent}%.', { name, percent: res?.verified_percent ?? '—' }));
    } catch (e) {
      setError(e.message || t('The ID was not approved. Try again.'));
      setBusy(false);
    }
  }

  async function askAgain() {
    if (!reason.trim()) throw new Error(t('Say what they should fix — they read this in the app.'));
    await api.rejectVerification(item.id, reason.trim(), failed);
    setAsking(false);
    await onDecided(t('{name} was asked to try again. Their photos were deleted.', { name }));
  }

  const details = [
    [t('Name entered'), name],
    [t('Email'), item.email || t('Not on record')],
    [t('ID type'), TYPE[item.type] ?? item.type],
    [t('Checked by'), item.provider ? item.provider.replace(/^\w/, (c) => c.toUpperCase()) : '—'],
    [t('Submitted'), item.submitted_at ? DAY.format(new Date(item.submitted_at)) : '—'],
  ];

  return (
    <div className="rpl-page rpl-incident">
      <button type="button" className="rpl-text-button rpl-back" onClick={onBack}>{t('← All ID reviews')}</button>
      <PageHeader
        eyebrow={t('ID review · Resident account')}
        title={name}
        description={t('Sent for a manual review at {time} · {waiting}.', { time: item.submitted_at ? CLOCK.format(new Date(item.submitted_at)) : '—', waiting: waiting(item.submitted_at) })}
      />

      <div className="rpl-idr-grid">
        <Photo label={t('National ID photo')} url={item.id_image_url} />
        <Photo label={t('Selfie')} url={item.selfie_image_url} />
        <Photo label={t('QR code')} url={item.qr_image_url} />
        <PhilSysSteps item={item} />
        <section className="rpl-panel rpl-decision rpl-idr-decide" aria-labelledby="rpl-idr-details">
          <h2 className="rpl-decision-title" id="rpl-idr-details">{t('Details')}</h2>
          <dl className="rpl-facts rpl-facts--wide">
            {details.map(([t, v]) => (
              <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <fieldset className="rpl-choice">
            <legend className="rpl-field-label">{t('What did PhilSys Check say?')}</legend>
            <div className="rpl-choice-options rpl-choice-options--stack">
              {RESULTS.map((r) => (
                <label key={r.key} className={`rpl-choice-option${result === r.key ? ' is-on' : ''}`}>
                  <input type="radio" name="philsys-result" value={r.key} checked={result === r.key} onChange={() => setResult(r.key)} disabled={busy || !item.qr_download_url} />
                  {r.label}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="rpl-decision-body">{result ? NEXT[result] : t('Run PhilSys Check, then choose what it said to approve this ID.')}</p>
          {error && <p className="rpl-inline-error" role="alert">{error}</p>}
          <div className="rpl-idr-actions">
            <button
              type="button"
              className="rpl-button rpl-button--secondary"
              onClick={() => { setReason(RESULTS.find((r) => r.key === result)?.reason ?? ''); setAsking(true); }}
              disabled={busy}
            >{t('Ask to try again')}</button>
            <button type="button" className="rpl-button rpl-button--primary" onClick={approve} disabled={busy || result !== 'verified'}>
              {busy ? t('Approving…') : t('Approve ID')}
            </button>
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={asking}
        eyebrow={t('ID review')}
        title={t('Ask {name} to try again?', { name })}
        description={t('Their ID isn’t approved and nothing is added. Their photos are deleted, and they can send new ones from the app.')}
        confirmLabel={t('Ask to try again')}
        onClose={() => setAsking(false)}
        onConfirm={askAgain}
      >
        <label className="rpl-field">
          <span className="rpl-field-label">{t('What should they fix?')}</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t('e.g. The ID photo is too blurry to read')} maxLength={1000} />
          <span className="rpl-field-help">{t('They read this in the app. It’s also recorded with the review.')}</span>
        </label>
      </ConfirmDialog>
    </div>
  );
}
