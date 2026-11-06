import { statusOf } from '../../lib/status.js';
import { t } from '../../i18n/i18n.jsx';

/* How far an Area has come (REPLIT (MAIN) 10 · A23, A26): six steps, the
 * reached ones in coral, the current one named in bold, and the status in
 * words on the right. A terminal outcome off the main path — rejected,
 * merged, declined — is said in words instead of a half-filled bar. */

const STEPS = [
  { key: 'reported', get label() { return t('Reported'); } },
  { key: 'acknowledged', get label() { return t('Acknowledged'); }, also: ['verified'] },
  { key: 'en_route', get label() { return t('En route'); } },
  { key: 'arrived', get label() { return t('Arrived'); } },
  { key: 'fire_out', get label() { return t('Fire out'); }, also: ['post_incident_report'] },
  { key: 'closed', get label() { return t('Closed'); } },
];

function stepOf(status) {
  return STEPS.findIndex((s) => s.key === status || s.also?.includes(status));
}

export default function LifecycleProgress({ status }) {
  const at = stepOf(status);
  const label = statusOf(status).label;
  return (
    <div className="rpl-progress">
      <div className="rpl-progress-head">
        <span className="rpl-eyebrow rpl-eyebrow--quiet">{t('Progress')}</span>
        <span className="rpl-progress-now">{label}</span>
      </div>
      {at < 0 ? (
        <p className="rpl-progress-off">{t('This Area left the response as {status}; it has no further steps.', { status: label.toLowerCase() })}</p>
      ) : (
        <ol className="rpl-progress-steps" aria-label={t('Progress: {label}, step {n} of {count}', { label, n: at + 1, count: STEPS.length })}>
          {STEPS.map((s, i) => (
            <li
              key={s.key}
              className={`${i <= at ? 'is-reached' : ''}${i === at ? ' is-current' : ''}`}
              aria-current={i === at ? 'step' : undefined}
            >
              <span className="rpl-progress-bar" aria-hidden="true" />
              <span className="rpl-progress-label">{s.label}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
