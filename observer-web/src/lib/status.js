/// Labels and colours for public.area_status, shared by every console screen.
///
/// v11 renames the operator-facing set (Section 2.5) and drops 'dispatched':
/// Accept now carries an incident from Reported straight to En route, so there
/// is no step between the two to label. 'post_incident_report' is the wait
/// between fire out and the team captain filing; 'closed' is terminal.
export const STATUS = {
  reported: { label: 'Reported', color: '#EAB308' },
  verified: { label: 'Verified', color: '#42A5F5' },
  en_route: { label: 'En route', color: '#FF9066' },
  arrived: { label: 'On scene', color: '#F4511E' },
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
export const OFF_FEED = ['fire_out', 'post_incident_report', 'closed', 'rejected', 'merged'];

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

export function since(iso) {
  if (!iso) return '—';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d`;
}

export function when(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  });
}
