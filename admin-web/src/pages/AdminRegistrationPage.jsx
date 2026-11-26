import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client.js';
import AuthBrand from '../components/AuthBrand.jsx';
import { t } from '../i18n/i18n.jsx';
import AdminRegistration from './AdminRegistration.jsx';

/* /admin-registration?token=… (v1.12.53; answered "One-time Admin link"):
 * an accepted organization's contact chooses its Admin sign-in. The link is
 * the server's to judge (app/api/routes/affiliate_admin.py); this page asks
 * it, shows A07–A11 from AdminRegistration, and says where the password link
 * went. */

const RULE = /^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$/;

function Panel({ kicker, title, children }) {
  return (
    <div className="lg">
      <AuthBrand />
      <div className="lg-panel">
        <div className="lg-form">
          <div className="lg-head">
            {kicker && <span className="lg-kicker">{kicker}</span>}
            <h2 className="lg-title">{title}</h2>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

export default function AdminRegistrationPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [link, setLink] = useState(null);
  const [failed, setFailed] = useState(null);
  const [done, setDone] = useState(null);

  useEffect(() => {
    let alive = true;
    if (!token) { setFailed(t('This link is not valid.')); return undefined; }
    api.adminRegistration(token)
      .then((l) => { if (alive) setLink(l); })
      .catch((e) => { if (alive) setFailed(e?.message || t('This link is not valid.')); });
    return () => { alive = false; };
  }, [token]);

  const rule = useMemo(() => ({
    test: (prefix) => RULE.test(prefix),
    help: link?.prefix_help ?? t('3 to 30 letters or numbers; a hyphen may join them.'),
  }), [link]);

  const checkPrefix = useCallback(
    (prefix) => api.adminRegistrationCheck(token, prefix).then((r) => r?.status ?? null),
    [token],
  );

  const create = useCallback(async ({ prefix }) => {
    setDone(await api.adminRegistrationCreate(token, prefix));
  }, [token]);

  if (done) {
    return (
      <Panel kicker={link?.organization} title={t('Check your email')}>
        <p className="lg-sub">{t('{email} is your Admin sign-in. We sent a link to {sent_to} to set its password.', { email: done.email, sent_to: done.sent_to })}</p>
        <button type="button" className="lg-submit" onClick={() => navigate('/login')}>{t('Go to sign in')}</button>
      </Panel>
    );
  }
  if (failed) {
    return (
      <Panel title={t('This link is not valid')}>
        <p className="lg-sub">{failed}</p>
        <button type="button" className="lg-submit" onClick={() => navigate('/login')}>{t('Go to sign in')}</button>
      </Panel>
    );
  }
  if (!link) {
    return (
      <Panel title={t('Opening your link…')} />
    );
  }
  return (
    <AdminRegistration
      link={{ state: link.state, organization: link.organization, expiresAt: new Date(link.expires_at).toLocaleString('en-PH', { timeZone: 'Asia/Manila' }) }}
      domain={link.suffix}
      rule={rule}
      checkPrefix={checkPrefix}
      onCreate={create}
    />
  );
}
