/* What this Admin may do in the console (ARBAC; PRD v13/v14 §4.6; REPLIT
 * (MAIN) 10 · A00 "Four permission variants").
 *
 * The server decides and reports it on GET /auth/me as `console`
 * (app/services/access.py): which variant this Admin is, its organisation,
 * the agencies whose incidents it acts on, and its permissions. The console
 * only draws what those allow; every action is checked again by the server.
 *
 * A server from before multi-organisation Admins sends no `console`. Every
 * Admin could do everything then, so the console falls back to the full
 * Central sidebar, as it always drew it. */

export const PERM = {
  ACKNOWLEDGE: 'incidents.acknowledge',
  DECIDE_OVERLAPS: 'incidents.overlaps',
  COORDINATE: 'incidents.coordinate',
  REVIEW_AFFILIATES: 'affiliates.review',
  REVIEW_IDS: 'verifications.review',
  MANAGE_MAP: 'map.manage',
  DELETE_WATER: 'water.delete',
  REQUEST_ALARM: 'alarm.request',
  DECIDE_ALARM: 'alarm.decide',
  CREATE_COORDINATORS: 'accounts.coordinators',
  MANAGE_ANY_ACCOUNT: 'accounts.any',
  ALL_ORGANIZATIONS: 'organizations.all',
  ALL_RECORDS: 'records.all',
};

const FIRE = ['fire_volunteer', 'bfp'];

const LEGACY = {
  variant: 'system',
  scope: 'central',
  organization: null,
  act_agencies: null,
  permissions: Object.values(PERM),
  legacy: true,
};

/// The signed-in Admin's access, from /auth/me.
export function consoleOf(user) {
  return user?.console ?? LEGACY;
}

export function can(access, permission) {
  return Boolean(access?.permissions?.includes(permission));
}

/// Whether this Admin may cancel or delete an alarm request: it asked, it is
/// an Admin of the asker's (active) organisation, or it is the system Admin.
/// The server checks the same (alarm_requests._may_withdraw).
export function mayWithdraw(access, me, request) {
  if (!request) return false;
  if (me?.id && me.id === request.requested_by) return true;
  if (access?.variant === 'system') return true;
  const orgId = access?.organization?.id;
  return Boolean(
    orgId
    && (access.permissions?.length ?? 0) > 0
    && orgId === request.requested_by_organization_id,
  );
}

/// Whether an incident was routed to this Admin: it asked for an agency this
/// organisation answers for (Fire Volunteer and BFP both answer Fire).
export function actsOn(access, incident) {
  if (!access || access.act_agencies == null) return true;
  const asked = incident?.requested_agencies ?? [];
  return access.act_agencies.some((a) => asked.includes(a));
}

/// Whether this Admin's organisation has acknowledged the incident. For the
/// system Admin, which has no organisation, whether anyone has.
export function acknowledgedByUs(access, incident) {
  const orgId = access?.organization?.id;
  if (!orgId) return incident?.status !== 'reported';
  if ((incident?.accepted_organization_ids ?? []).includes(orgId)) return true;
  return (incident?.acceptances ?? []).some((a) => a.organization_id === orgId);
}

/// The "Your org" chip of an incident row (A21, A22): routed and still to
/// acknowledge, routed and acknowledged, or someone else's (view only).
export function yourOrg(access, incident) {
  if (!actsOn(access, incident)) return { key: 'view', label: 'View only', tone: 'neutral' };
  if (acknowledgedByUs(access, incident)) return { key: 'acknowledged', label: 'Acknowledged', tone: 'ok' };
  return { key: 'routed', label: 'Routed to you', tone: 'accent' };
}

/// Whether the console splits incidents into "Routed to you" and "Other
/// organisations' incidents": only an Admin that does not act on everything.
export function splitsIncidents(access) {
  return access?.act_agencies != null;
}

const AGENCY_WORD = {
  fire_volunteer: 'Fire',
  bfp: 'Fire',
  police: 'Police',
  medical: 'Medical',
  barangay: 'Barangay',
};

const VARIANT_LABEL = {
  system: 'System',
  central: 'Central hub',
  fire_volunteer: 'Fire Volunteer',
  bfp: 'Bureau of Fire Protection',
  police: 'Police',
  medical: 'Medical',
  barangay: 'Barangay',
};

/// What this Admin answers for, in a word: "Fire", "Police" …
export function routedWord(access) {
  return AGENCY_WORD[access?.organization?.agency_type] ?? 'your agency';
}

/// The sidebar's line under the organisation's name (A00): "Police · Admin".
export function roleLine(access) {
  return `${VARIANT_LABEL[access?.variant] ?? 'Organization'} · Admin`;
}

/// The eyebrow's variant word: "Fire Volunteer", "Central hub", …
export function variantLabel(access) {
  return VARIANT_LABEL[access?.variant] ?? 'Admin';
}

/// The top bar's line (A21, A25, A46): who this organisation is and what it
/// may act on.
export function scopeLine(access) {
  if (!access || access.legacy) return 'Central hub — you review affiliates and act on every incident';
  const word = routedWord(access);
  switch (access.variant) {
    case 'system':
      return 'System administrator — you can act on every incident';
    case 'central':
      return `Central hub — you act on incidents that asked for ${word}, and review affiliates and IDs`;
    case 'bfp':
      return 'BFP — you act on Fire incidents and set the alarm level';
    case 'fire_volunteer':
      return 'Fire Volunteer — you act on incidents that asked for Fire';
    default:
      return `${VARIANT_LABEL[access.variant] ?? word} — you act on incidents that asked for ${word}`;
  }
}

/// The sound categories that ring for this Admin: its own agency's, or every
/// category for an Admin that acts on everything (sound/cues.js).
export function soundCategories(access) {
  const agency = access?.organization?.agency_type;
  if (!agency || access?.act_agencies == null) return ['fire', 'police', 'medical', 'barangay'];
  return [FIRE.includes(agency) ? 'fire' : agency];
}
