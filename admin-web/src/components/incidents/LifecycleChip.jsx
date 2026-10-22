import { statusOf } from '../../lib/status.js';

/* An Area's status in the PRD's fixed vocabulary (REPLIT (MAIN) 04 ·
 * Lifecycle chip): amber needs a decision or a record, blue is acknowledged,
 * red is under way, green is out, grey has left the live feed. The word
 * carries the meaning; the tint and dot only reinforce it. */
const TONE = {
  reported: 'warn',
  post_incident_report: 'warn',
  verified: 'info',
  acknowledged: 'info',
  en_route: 'danger',
  arrived: 'danger',
  fire_out: 'ok',
  closed: 'neutral',
  rejected: 'neutral',
  declined: 'neutral',
  merged: 'neutral',
};

export default function LifecycleChip({ status }) {
  return (
    <span className={`web-chip web-chip--${TONE[status] ?? 'neutral'}`}>
      {statusOf(status).label}
    </span>
  );
}
