import { alarmStatusDetail, alarmStatusOf } from '../../lib/alarmStatus.js';
import { t } from '../../i18n/i18n.jsx';

/* The highlighted alarm status on an incident, and its badge on lists and map
 * cards (v1.12.49; 22 Nov 2026: "highlight it in the details because it is
 * crucial"; answered "Everyone, everywhere"). A shape and words with the
 * colour, never colour alone; a raised alarm is solid red. */

const PATH = {
  raised: 'M3 10v4h4l7 5V5l-7 5H3zm14-2v8a4.5 4.5 0 0 0 0-8z',
  positive: 'M3 10v4h4l7 5V5l-7 5H3zm14-2v8a4.5 4.5 0 0 0 0-8z',
  held: 'M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3z',
  out: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-2 15-5-5 1.4-1.4L10 14.2l7.6-7.6L19 8l-9 9z',
  none: 'M6 2v6l4 4-4 4v6h12v-6l-4-4 4-4V2H6z',
};

function Glyph({ tone, size }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
      <path d={PATH[tone]} />
    </svg>
  );
}

export function AlarmBadge({ incident }) {
  const s = alarmStatusOf(incident);
  if (!s.known) return null;
  return (
    <span className={`rpl-alarm-badge is-${s.tone}`}>
      <span className="web-sr-only">{t('Alarm status')}{': '}</span>
      <Glyph tone={s.tone} size={12} />
      {s.label}
    </span>
  );
}

export function AlarmStatusBanner({ incident, action = null, onAction }) {
  const s = alarmStatusOf(incident);
  if (!s.applies) return null;
  const detail = alarmStatusDetail(incident);
  return (
    <div className={`rpl-alarm-status is-${s.tone}`} role="status">
      <span className="rpl-alarm-status-mark"><Glyph tone={s.tone} size={24} /></span>
      <div className="rpl-alarm-status-text">
        <span className="rpl-alarm-status-eyebrow">{t('Alarm status')}</span>
        <strong className="rpl-alarm-status-word">{s.label}</strong>
        {detail && <span className="rpl-alarm-status-detail">{detail}</span>}
      </div>
      {action && <button type="button" className="rpl-alarm-status-action" onClick={onAction}>{action}</button>}
    </div>
  );
}
