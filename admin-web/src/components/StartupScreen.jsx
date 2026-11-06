import { useEffect, useState } from 'react';

import Skeleton from './ui/Skeleton.jsx';
import { t } from '../i18n/i18n.jsx';

/* What the console shows while a stored session is checked on load, and when
 * that check could not finish. Before this the wait was a small grey
 * "Loading…" on the dark ground — on a slow start it read as a black screen —
 * and a server that could not be reached signed the operator out. */

const SLOW_MS = 4000;

export function StartupLoading() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), SLOW_MS);
    return () => clearTimeout(t);
  }, []);
  return (
    <main className="rpl-startup" aria-busy="true">
      <img className="rpl-startup-mark" src="/icons/auth-mark.svg" alt="" />
      <p className="rpl-startup-title" role="status">{t('Opening the Admin console…')}</p>
      <Skeleton shape="table" rows={3} />
      {slow && (
        <p className="rpl-startup-body">{t('The server is taking a while to answer. After a quiet spell it can need up to a minute to wake.')}</p>
      )}
    </main>
  );
}

export function StartupError({ message, onRetry, onSignOut }) {
  return (
    <main className="rpl-startup" role="alert">
      <img className="rpl-startup-mark" src="/icons/auth-mark.svg" alt="" />
      <p className="rpl-startup-title">{t('The console couldn’t reach the server')}</p>
      <p className="rpl-startup-body">{message}{' '}{t('You are still signed in.')}</p>
      <div className="rpl-startup-actions">
        <button type="button" className="rpl-button rpl-button--primary" onClick={onRetry}>{t('Try again')}</button>
        <button type="button" className="rpl-button rpl-button--secondary" onClick={onSignOut}>{t('Sign out')}</button>
      </div>
    </main>
  );
}
