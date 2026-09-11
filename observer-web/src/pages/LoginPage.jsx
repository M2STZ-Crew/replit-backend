import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth.jsx';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
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
      setError(err.message || 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="login-card" onSubmit={onSubmit}>
        <img src="/assets/logo-mark.png" alt="" width="44" height="44" />
        <span className="os-eyebrow">RepLiT · Observer console</span>
        <h1 className="login-title">Sign in</h1>
        <p className="login-sub">
          For Police, Medical and Barangay team captains. Watch incidents that asked for
          your agency, and Accept the ones Admin routes to you.
        </p>

        <label className="field">
          <span className="os-eyebrow">Official email</span>
          <input type="email" autoComplete="username" value={email}
                 onChange={(e) => setEmail(e.target.value)} placeholder="name@agency.gov.ph" required />
        </label>
        <label className="field">
          <span className="os-eyebrow">Password</span>
          <input type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} required />
        </label>

        {error && <div className="note is-error" role="alert">{error}</div>}

        <button className="btn-accent" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="login-foot">
          Fire Volunteer and BFP captains coordinate from the mobile app; Admins use the
          Admin Console.
        </p>
      </form>
    </div>
  );
}
