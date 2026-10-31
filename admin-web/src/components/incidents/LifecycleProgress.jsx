import { statusOf } from '../../lib/status.js';

/* How far an Area has come (REPLIT (MAIN) 10 · A23, A26): six steps, the
 * reached ones in coral, the current one named in bold, and the status in
 * words on the right. A terminal outcome off the main path — rejected,
 * merged, declined — is said in words instead of a half-filled bar. */

const STEPS = [
  { key: 'reported', label: 'Reported' },
  { key: 'acknowledged', label: 'Acknowledged', also: ['verified'] },
  { key: 'en_route', label: 'En route' },
  { key: 'arrived', label: 'Arrived' },
  { key: 'fire_out', label: 'Fire out', also: ['post_incident_report'] },
  { key: 'closed', label: 'Closed' },
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
        <span className="rpl-eyebrow rpl-eyebrow--quiet">Progress</span>
        <span className="rpl-progress-now">{label}</span>
      </div>
      {at < 0 ? (
        <p className="rpl-progress-off">
          This Area left the response as {label.toLowerCase()}; it has no further steps.
        </p>
      ) : (
        <ol className="rpl-progress-steps" aria-label={`Progress: ${label}, step ${at + 1} of ${STEPS.length}`}>
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
