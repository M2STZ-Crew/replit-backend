import { useEffect, useState } from 'react';

import AuthBrand from '../components/AuthBrand.jsx';
import { t } from '../i18n/i18n.jsx';

/* Set up an organisation's Admin account from its one-time link (REPLIT
 * (MAIN) 10 · A07 862:1013 available, A08 taken, A09 not allowed, A10 link
 * expired, A11 already used). UI READY — the server's accept flow creates a
 * Coordinator and emails a password link instead, so this screen is not
 * routed; it is shown only in docs/console-ready.html.
 *
 *   link        { state: 'valid' | 'expired' | 'used', organization, expiresAt? }
 *   domain      the fixed ending of the email, e.g. '.admin@example.org'
 *   rule        { test(prefix) -> boolean, help }   the integrator's prefix rule
 *   checkPrefix(prefix) -> Promise<'available' | 'taken' | 'not_allowed'>
 *   onCreate({ prefix, email }) -> Promise
 *
 * The prefix rule, the domain and the link's lifetime are the server's to
 * decide; none is assumed here. */

const STATUS = {
  available: { tone: 'ok', mark: '✓', get text() { return t('Available'); } },
  taken: { tone: 'danger', mark: '✕', get text() { return t('Already taken — try another'); } },
  not_allowed: { tone: 'danger', mark: '✕', get text() { return t('Not allowed — choose another'); } },
  invalid: { tone: 'danger', mark: '!', text: null },
  checking: { tone: 'quiet', mark: '…', get text() { return t('Checking…'); } },
};

function Ended({ link }) {
  const used = link.state === 'used';
  return (
    <div className="lg-form">
      <div className="lg-head">
        <span className="lg-kicker">{link.organization}</span>
        <h2 className="lg-title">{used ? t('This link was already used') : t('This link has expired')}</h2>
        <p className="lg-sub">
          {used
            ? t('The Admin account for this organization is already set up. Sign in with it, or ask the central hub for a new link.')
            : t('Registration links work once and for a limited time. Ask the central hub that accepted your organization for a new one.')}
        </p>
      </div>
      {used && <a className="lg-submit lg-submit--link" href="/login">{t('Go to sign in')}</a>}
    </div>
  );
}

export default function AdminRegistration({ link, domain, rule, checkPrefix, onCreate }) {
  const [prefix, setPrefix] = useState('');
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const value = prefix.trim();
    if (!value) { setStatus(null); return undefined; }
    if (rule && !rule.test(value)) { setStatus('invalid'); return undefined; }
    let alive = true;
    setStatus('checking');
    const t = setTimeout(() => {
      Promise.resolve(checkPrefix(value))
        .then((s) => { if (alive) setStatus(STATUS[s] ? s : null); })
        .catch(() => { if (alive) setStatus(null); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [prefix, rule, checkPrefix]);

  if (link.state !== 'valid') {
    return (
      <div className="lg">
        <AuthBrand />
        <div className="lg-panel"><Ended link={link} /></div>
      </div>
    );
  }

  const email = `${prefix.trim()}${domain}`;
  const shown = status ? STATUS[status] : null;

  async function submit(e) {
    e.preventDefault();
    if (busy || status !== 'available') return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({ prefix: prefix.trim(), email });
    } catch (err) {
      setError(err?.message || t('The account was not created. Try again.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lg">
      <AuthBrand />
      <div className="lg-panel">
        <form className="lg-form" onSubmit={submit} noValidate>
          <div className="lg-head">
            <span className="lg-kicker">{link.organization}{' '}{t('· Accepted')}</span>
            <h2 className="lg-title">{t('Set up your Admin account')}</h2>
            <p className="lg-sub">{t('Choose the first part of your Admin email. The ending {domain} is fixed.', { domain })}</p>
          </div>

          <label className="lg-field">
            <span className="dc-eyebrow">{t('Prefix')}</span>
            <span className="lg-prefix">
              <input value={prefix} onChange={(e) => setPrefix(e.target.value.toLowerCase())} autoComplete="off" spellCheck="false" disabled={busy} aria-describedby="lg-prefix-help" />
              <span className="lg-prefix-domain"><span aria-hidden="true">🔒</span> {domain}</span>
            </span>
            {rule?.help && <span className="lg-help" id="lg-prefix-help">{rule.help}</span>}
          </label>

          {prefix.trim() && (
            <div className="lg-preview" aria-live="polite">
              <span className="dc-eyebrow">{t('Your Admin sign-in')}</span>
              <span className="lg-preview-email">{email}</span>
              {shown && (
                <span className={`lg-preview-status is-${shown.tone}`}>
                  <span aria-hidden="true">{shown.mark}</span> {shown.text ?? rule?.help}
                </span>
              )}
            </div>
          )}

          {error && <div className="lg-error" role="alert">{error}</div>}

          <button type="submit" className="lg-submit" disabled={busy || status !== 'available'}>
            {busy ? t('Creating…') : t('Create Admin account')}
          </button>
          {link.expiresAt && <p className="lg-help">{t('This link works once and expires')}{' '}{link.expiresAt}.</p>}
        </form>
      </div>
    </div>
  );
}
