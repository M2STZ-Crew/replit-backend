import { useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client.js';
import AuthBrand from '../components/AuthBrand.jsx';
import { t } from '../i18n/i18n.jsx';

/// /delete-account (v1.12.34): Google Play's rule that a resident can ask for
/// their account to be deleted without the app. They sign in here for this one
/// request (the console's own sign-in is not touched), and the server deletes
/// it as the app's Profile > Delete my account does (POST /auth/me/delete).
export default function DeleteAccount() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError('');
    if (!email.trim() || !password) {
      setError(t('Enter the email and password of your RepLiT account.'));
      return;
    }
    if (!sure) {
      setError(t('Tick the box to confirm. Deleting an account cannot be undone.'));
      return;
    }
    setBusy(true);
    try {
      await api.deleteMyAccount(email.trim(), password);
      setDone(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="lg rg">
        <AuthBrand />
        <div className="lg-panel rg-panel is-done">
          <div className="lg-form rg-done">
            <div className="lg-head">
              <span className="lg-kicker">{t('Account deleted')}</span>
              <h2 className="lg-title">{t('Your RepLiT account is gone')}</h2>
              <p className="lg-sub">
                {t('Your profile, sign-in, alerts and any National ID photos are deleted. The reports you sent stay in the barangay’s incident records without your name.')}
              </p>
            </div>
            <Link className="lg-link" to="/privacy">{t('Read the privacy policy')}</Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="lg rg">
      <AuthBrand />
      <div className="lg-panel rg-panel">
        <form className="lg-form rg-form" onSubmit={onSubmit} noValidate>
          <div className="lg-head">
            <span className="lg-kicker">{t('For residents')}</span>
            <h2 className="lg-title">{t('Delete your RepLiT account')}</h2>
            <p className="lg-sub">
              {t('You can also do this in the app: Profile, then Delete my account. Staff accounts are removed by their organization’s administrator.')}
            </p>
          </div>

          <div className="doc doc-tight">
            <h3>{t('What is deleted')}</h3>
            <ul>
              <li>{t('Your sign-in and profile: name, email, mobile number, birthday, gender, language and last location.')}</li>
              <li>{t('Your phones’ alert registrations, your alerts and your answers to them.')}</li>
              <li>{t('Your verification records, and any National ID photos still held.')}</li>
            </ul>
            <h3>{t('What is kept')}</h3>
            <ul>
              <li>{t('The reports you sent, without your name: they are part of the incident records responders and the barangay keep.')}</li>
              <li>{t('A line in the action record saying that an account was deleted, without your name.')}</li>
            </ul>
          </div>

          <label className="lg-field">
            <span className="rg-label"><span className="dc-eyebrow">{t('Email')}</span></span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@email.com"
            />
          </label>

          <label className="lg-field">
            <span className="rg-label"><span className="dc-eyebrow">{t('Password')}</span></span>
            <div className="doc-password">
              <input
                type={show ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button type="button" className="lg-link" onClick={() => setShow((s) => !s)}>
                {show ? t('Hide') : t('Show')}
              </button>
            </div>
          </label>

          <label className="rg-terms">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
            <span>{t('I understand that my account is deleted for good and cannot be brought back.')}</span>
          </label>

          {error && <div className="lg-error" role="alert">{error}</div>}

          <button type="submit" className="lg-submit doc-danger" disabled={busy}>
            {busy ? t('Deleting…') : t('Delete my account')}
          </button>
          <Link className="lg-link" to="/privacy">{t('Read the privacy policy')}</Link>
        </form>
      </div>
    </div>
  );
}

function messageFor(err) {
  if (err?.status === 401 || err?.code === 'invalid_credentials') return t('Wrong email or password.');
  if (err?.code === 'wrong_password') return t('Wrong email or password.');
  if (err?.code === 'staff_account') {
    return t('This is a staff account. Its organization’s administrator removes it.');
  }
  if (err?.code === 'account_delete_failed') {
    return t('Your account could not be deleted just now. Nothing was removed; try again in a minute.');
  }
  return err?.message || t('Something went wrong. Try again in a minute.');
}
