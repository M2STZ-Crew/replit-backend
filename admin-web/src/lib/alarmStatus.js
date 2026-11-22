import { ALARM_LEVEL, alarmLabel } from './status.js';
import { t } from '../i18n/i18n.jsx';

/* A fire's alarm status (v1.12.49; 22 Nov 2026: "fire alarm status can be
 * seen in any details info"; answered "Level + situation"): BFP's level, and
 * Under control or Fire out once there is one. The app's rule
 * (lib/models/alarm_status.dart). */

const LADDER = Object.keys(ALARM_LEVEL);
const OUT = ['fire_out', 'post_incident_report', 'closed'];
const NOT_A_FIRE = ['rejected', 'declined', 'merged'];

export const alarmRank = (level) => LADDER.indexOf(level);

/* Past Positive fire alarm: BFP raised it. */
export const isRaise = (level) => alarmRank(level) > 0;

export function alarmStatusOf(inc) {
  const situation = OUT.includes(inc?.status) ? 'out' : inc?.under_control_at ? 'held' : 'burning';
  const level = inc?.alarm_level ?? null;
  const applies = !NOT_A_FIRE.includes(inc?.status);
  const raised = situation === 'burning' && isRaise(level);
  let tone = 'none';
  if (situation === 'out') tone = 'out';
  else if (situation === 'held') tone = 'held';
  else if (raised) tone = 'raised';
  else if (level) tone = 'positive';
  let label = t('No alarm yet');
  if (situation === 'out') label = t('Fire out');
  else if (situation === 'held') label = t('Under control');
  else if (level) label = alarmLabel(level);
  return {
    applies, situation, level, raised, tone, label, known: applies && (level != null || situation !== 'burning'),
  };
}

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short' });

function when(iso) {
  const at = new Date(iso);
  const day = DAY.format(at);
  return day === DAY.format(new Date()) ? CLOCK.format(at) : `${day}, ${CLOCK.format(at)}`;
}

/* When, and by whom. */
export function alarmStatusDetail(inc) {
  const s = alarmStatusOf(inc);
  const was = s.level ? t('Was {level}', { level: alarmLabel(s.level) }) : null;
  if (s.situation === 'out') {
    return [was, inc.resolved_at && when(inc.resolved_at)].filter(Boolean).join(' · ') || null;
  }
  if (s.situation === 'held') {
    return [was, when(inc.under_control_at), inc.under_control_by_org, inc.under_control_by_name].filter(Boolean).join(' · ');
  }
  if (!s.level) return t('An alarm is set once responders confirm the fire.');
  if (!inc.alarm_level_set_at) return null;
  const time = when(inc.alarm_level_set_at);
  const who = [inc.alarm_level_set_by_org, inc.alarm_level_set_by_name].filter(Boolean).join(' · ');
  if (s.raised) return who ? t('Raised {time} by {who}', { time, who }) : t('Raised {time}', { time });
  return who ? t('Set {time} by {who}', { time, who }) : t('Set {time}', { time });
}
