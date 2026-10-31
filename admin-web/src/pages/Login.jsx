import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client.js';
import { useAuth } from '../auth.jsx';
import AuthBrand from '../components/AuthBrand.jsx';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [reset, setReset] = useState(null);
  const emailInput = useRef(null);

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

  // Sends the reset link to the address typed above (A01). The answer never
  // says whether the address has an account.
  async function forgot() {
    const address = email.trim();
    setError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      setReset({ tone: 'error', text: 'Type your Admin email above first, then press Forgot password? again.' });
      emailInput.current?.focus();
      return;
    }
    setReset({ tone: 'busy', text: 'Sending…' });
    try {
      const res = await api.recover(address);
      setReset({ tone: 'ok', text: res?.message || 'If that email is registered, a reset link has been sent.' });
    } catch (err) {
      setReset({ tone: 'error', text: err.message || 'The reset email could not be sent. Try again.' });
    }
  }

  return (
    <div className="lg">
      <AuthBrand />

      {/* Right: the form. */}
      <div className="lg-panel">
        <form className="lg-form" onSubmit={onSubmit}>
          <div className="lg-head">
            <span className="lg-kicker">Admin Console</span>
            <h2 className="lg-title">Sign in</h2>
            <p className="lg-sub">
              Use your organization’s Admin email.
            </p>
          </div>

          <div className="lg-fields">
            <label className="lg-field">
              <span className="dc-eyebrow">Admin email</span>
              <input
                ref={emailInput}
                type="email"
                autoComplete="username"
                placeholder="name@example.com"
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
                  <img src="/icons/visibility.svg" alt="" />
                </button>
              </span>
            </label>
          </div>

          {error && <div className="lg-error" role="alert">{error}</div>}

          <button type="submit" className="lg-submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          {reset && (
            <p className={`lg-reset is-${reset.tone}`} role={reset.tone === 'error' ? 'alert' : 'status'}>
              {reset.text}
            </p>
          )}

          <div className="lg-affiliate">
            <button type="button" className="lg-link" onClick={forgot} disabled={reset?.tone === 'busy'}>
              Forgot password?
            </button>
            <button type="button" className="lg-link" onClick={() => navigate('/register')}>
              New affiliate? Request access
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
