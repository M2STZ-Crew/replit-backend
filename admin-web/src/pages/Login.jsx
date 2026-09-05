import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth.jsx';

function EyeIcon({ off }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
      {off && <line x1="3" y1="3" x2="21" y2="21" />}
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)"
         strokeWidth="2" strokeLinecap="round">
      <path d="M12 3l8 4v5c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V7l8-4z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lg">
      {/* Left: the identity panel. Decorative only, and hidden below 900px so a
          phone gets straight to the form rather than a screenful of artwork. */}
      <div className="lg-brand" aria-hidden="true">
        <div className="lg-ember" />
        <div className="lg-grid" />

        <div className="lg-mark">
          <img src="/assets/logo-mark.png" alt="" width="44" height="44" />
          <div className="lg-mark-text">
            <span className="lg-wordmark">RepLiT</span>
            <span className="lg-tagline">Fire Response Network</span>
          </div>
        </div>

        <div className="lg-pitch">
          <div className="lg-pill">
            <span className="lg-pill-dot" />
            <span>Pasay City · Barangay 76</span>
          </div>
          <h1 className="lg-headline">
            Eyes on the<br />whole city,<br />all at once.
          </h1>
          <p className="lg-lede">
            Live incident awareness, affiliate governance and a permanent record
            of every response decision.
          </p>
        </div>

        <div className="lg-foot">Republic of the Philippines · NCR · City of Pasay</div>
      </div>

      {/* Right: the form. */}
      <div className="lg-panel">
        <form className="lg-form" onSubmit={onSubmit}>
          <div className="lg-head">
            <span className="lg-kicker">Response Console</span>
            <h2 className="lg-title">Sign in</h2>
            <p className="lg-sub">
              Credentialed officials only. Every session is recorded in the audit log.
            </p>
          </div>

          <div className="lg-fields">
            <label className="lg-field">
              <span className="dc-eyebrow">Official email</span>
              <input
                type="email"
                autoComplete="username"
                placeholder="name@agency.gov.ph"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>

            <label className="lg-field">
              <span className="dc-eyebrow">Password</span>
              <span className="lg-pw">
                <input
                  type={showPw ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="Your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="lg-eye"
                  onClick={() => setShowPw((s) => !s)}
                  aria-label={showPw ? 'Hide password' : 'Show password'}
                >
                  <EyeIcon off={showPw} />
                </button>
              </span>
            </label>
          </div>

          {error && <div className="lg-error" role="alert">{error}</div>}

          <button type="submit" className="lg-submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          <div className="lg-note">
            <ShieldIcon />
            <span>
              Fire Volunteer and BFP coordinators verify and dispatch. Police,
              medical and barangay accounts see incidents for awareness only.
            </span>
          </div>

          <div className="lg-affiliate">
            Want your organisation to join?{' '}
            <button type="button" className="lg-link" onClick={() => navigate('/register')}>
              Register as an affiliate
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
