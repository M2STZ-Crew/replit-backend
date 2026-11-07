import { t } from '../i18n/i18n.jsx';
/* A01 / A03, 859:21 and 859:258. Shared presentation only. */
export default function AuthBrand() {
  return (
    <aside className="lg-brand">
      <div className="lg-mark">
        <span className="auth-app-icon"><img src="/icons/auth-mark.svg" alt="" /></span>
        <div className="lg-mark-text">
          <span className="lg-wordmark">REPLIT</span>
          <span className="lg-tagline">{t('Admin console')}</span>
        </div>
      </div>
      <div className="lg-pitch">
        <h1 className="lg-headline">{t('Every organization that answers a fire in Pasay, on one map.')}</h1>
        <p className="lg-lede">{t('Live incident awareness, affiliate governance and a permanent record of every response decision.')}</p>
      </div>
      <div className="lg-foot">{t('Admin console · web only')}</div>
    </aside>
  );
}
