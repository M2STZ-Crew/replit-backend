/// Labels and colours for public.area_status, shared by every console screen.
///
/// v11 renames the operator-facing set (Section 2.5) and drops 'dispatched':
/// v12: Accept verifies (Reported -> Verified); the first responder moves it to
/// En route. Either way there
/// is no step between the two to label. 'post_incident_report' is the wait
/// between fire out and the team captain filing; 'closed' is terminal.
/// Pass 6 (REPLIT (MAIN) 04 · Lifecycle chip; PRD v13 §4.5.1, §19.2): the
/// org's digital "seen it, going to check" is now called Acknowledged. The
/// server still sends it as 'verified' (v13 renames the enum, not the act);
/// 'acknowledged' and the new terminal 'declined' are drawn the same way the
/// day the server sends them. A person's identity "Verified" badge is a
/// different thing and keeps its word.
export const STATUS = {
  reported: { label: 'Reported', color: '#FFB020' },
  verified: { label: 'Acknowledged', color: '#5B93F5' },
  acknowledged: { label: 'Acknowledged', color: '#5B93F5' },
  declined: { label: 'Declined', color: '#9E9E9E' },
  en_route: { label: 'En route', color: '#FF9066' },
  arrived: { label: 'Arrived', color: '#FF544E' },
  fire_out: { label: 'Fire out', color: '#22C55E' },
  post_incident_report: { label: 'Report due', color: '#2DD4BF' },
  closed: { label: 'Closed', color: '#16A34A' },
  rejected: { label: 'Rejected', color: '#9E9E9E' },
  merged: { label: 'Merged', color: '#7E57C2' },
};

export function statusOf(status) {
  return STATUS[status] ?? { label: (status || '—').replace(/_/g, ' '), color: '#8a8a8a' };
}

/// Mirrors OFF_FEED_STATUSES in app/services/incident.py.
export const OFF_FEED = ['fire_out', 'post_incident_report', 'closed', 'rejected', 'declined', 'merged'];

export const AGENCY_LABEL = {
  fire_volunteer: 'Fire Volunteers',
  bfp: 'BFP',
  police: 'Police',
  medical: 'Medical',
  barangay: 'Barangay',
};

/// v11 removed Admin's manual routing (§2.6.2), and routableAgencies with it:
/// the reporter's selected_agencies already decides which agencies see an
/// incident, and each of them now presses its own Accept.

/// public.alarm_level, the BFP alarm ladder. Positive fire alarm is what a
/// verified fire starts at, set by the first verify; BFP sets every level above.
export const ALARM_LEVEL = {
  positive_fire_alarm: 'Positive fire alarm',
  first_alarm: '1st alarm',
  second_alarm: '2nd alarm',
  third_alarm: '3rd alarm',
  fourth_alarm: '4th alarm',
  fifth_alarm: '5th alarm',
  general_alarm: 'General alarm',
};

/// The levels a request can name: everything above the initial classification.
export const ASKABLE_ALARM_LEVELS = Object.keys(ALARM_LEVEL).filter((l) => l !== 'positive_fire_alarm');

export function alarmLabel(level) {
  return ALARM_LEVEL[level] ?? (level ? level.replace(/_/g, ' ') : '—');
}

export function since(iso) {
  if (!iso) return '—';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d`;
}

/// "Just now", "1 min ago", "9 min ago", "2 h ago", "3 d ago" — the age a
/// row's Updated column reads in (04 · Incident row).
export function ago(iso) {
  if (!iso) return '—';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.floor(hrs / 24)} d ago`;
}

export function when(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  });
}
