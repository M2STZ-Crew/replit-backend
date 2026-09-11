/// Labels and colours for public.area_status, shared by every console screen.
///
/// v10 adds two post-fire statuses (Section 2.5): 'post_incident_report' is the
/// wait between fire out and the team captain filing, and 'closed' is terminal.
export const STATUS = {
  pending: { label: 'Pending', color: '#EAB308' },
  verified: { label: 'Verified', color: '#42A5F5' },
  dispatched: { label: 'Dispatched', color: '#1976D2' },
  en_route: { label: 'En route', color: '#FF9066' },
  arrived: { label: 'On scene', color: '#F4511E' },
  resolved: { label: 'Resolved', color: '#22C55E' },
  post_incident_report: { label: 'Report due', color: '#2DD4BF' },
  closed: { label: 'Closed', color: '#16A34A' },
  rejected: { label: 'Rejected', color: '#9E9E9E' },
  merged: { label: 'Merged', color: '#7E57C2' },
};

export function statusOf(status) {
  return STATUS[status] ?? { label: (status || '—').replace(/_/g, ' '), color: '#8a8a8a' };
}

/// Mirrors OFF_FEED_STATUSES in app/services/incident.py.
export const OFF_FEED = ['resolved', 'post_incident_report', 'closed', 'rejected', 'merged'];

export const AGENCY_LABEL = {
  fire_volunteer: 'Fire Volunteers',
  bfp: 'BFP',
  police: 'Police',
  medical: 'Medical',
  barangay: 'Barangay',
};

/// Mirrors routable_agencies() in app/services/incident.py: routing follows the
/// report, and the two fire agencies count as one request.
export function routableAgencies(requested = []) {
  const out = new Set(requested);
  if (out.has('fire_volunteer') || out.has('bfp')) {
    out.add('fire_volunteer');
    out.add('bfp');
  }
  return ['fire_volunteer', 'bfp', 'police', 'medical', 'barangay'].filter((a) => out.has(a));
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

export function when(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  });
}
