import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth.jsx';
import Logo from '../components/Logo.jsx';

function EyeIcon({ off }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
      {off && <line x1="3" y1="3" x2="21" y2="21" />}
    </svg>
  );
}

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
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
      await login(username.trim(), password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="login-logo">
          <Logo height={64} />
        </div>

        <label className="field-label" htmlFor="username">USERNAME</label>
        <input
          id="username"
          className="field"
          type="text"
          placeholder="Enter username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />

        <label className="field-label" htmlFor="password">PASSWORD</label>
        <div className="field-wrap">
          <input
            id="password"
            className="field"
            type={showPw ? 'text' : 'password'}
            placeholder="Enter password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="button"
            className="field-eye"
            onClick={() => setShowPw((s) => !s)}
            aria-label={showPw ? 'Hide password' : 'Show password'}
          >
            <EyeIcon off={showPw} />
          </button>
        </div>

        {error && <div className="login-error">{error}</div>}

        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? 'SIGNING IN…' : 'LOGIN'}
        </button>

        <div className="login-affiliate">
          Do you want to be an affiliate?{' '}
          <span className="link" onClick={() => navigate('/register')}>
            Register here
          </span>
        </div>
      </form>
    </div>
  );
}
