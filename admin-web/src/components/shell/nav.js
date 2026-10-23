import { PERM, can } from '../../lib/access.js';

/* The Admin console's destinations, in the pass 6 sidebar's order (REPLIT
 * (MAIN) 04 · Sidebar; 10 · screen map). `badge` names a counter: `new:*`
 * counts incidents reported since the operator last viewed that surface
 * (PRD v13 §4.14); the others are pending queues.
 *
 * `requires` names the permission a destination needs (lib/access.js): the
 * Barangay 76 central hub's duties, manual National ID review and affiliate
 * review (PRD v13 §4.1, §4.12; A00 "Four permission variants"). */
export const NAV = [
  { key: 'dashboard', label: 'Dashboard', icon: 'dashboard', group: 'Operations', badge: 'new:dashboard' },
  { key: 'incidents', label: 'Incidents', icon: 'incidents', group: 'Operations', badge: 'new:incidents' },
  { key: 'map', label: 'Live map', icon: 'map', group: 'Operations' },
  { key: 'requests', label: 'Requests', icon: 'requests', group: 'Operations', badge: 'requests' },
  { key: 'water', label: 'Water resources', icon: 'water', group: 'Resources' },
  { key: 'reports', label: 'Reports & CIAR', icon: 'reports', group: 'Records' },
  { key: 'audit', label: 'Audit log', icon: 'audit', group: 'Records' },
  { key: 'organization', label: 'Organization', icon: 'organization', group: 'Organization' },
  { key: 'accounts', label: 'Accounts', icon: 'accounts', group: 'Organization' },
  { key: 'idreview', label: 'Verification', icon: 'verification', group: 'Organization', requires: PERM.REVIEW_IDS, badge: 'ids' },
  { key: 'affiliates', label: 'Affiliates', icon: 'affiliates', group: 'Organization', requires: PERM.REVIEW_AFFILIATES, badge: 'affiliates' },
];

export const SETTINGS = { key: 'settings', label: 'Settings', icon: 'settings' };

export const GROUPS = ['Operations', 'Resources', 'Records', 'Organization'];

/* Which sidebar this Admin gets (A00 · Sidebar): the Central variant (the
 * Barangay 76 hub, with Verification and Affiliates) or the Standard one. The
 * server says which (`console.scope` on /auth/me); the system Admin, which
 * may do everything, gets the Central list. */
export function consoleAccess(access) {
  return access?.scope === 'organization' ? 'standard' : 'central';
}

/* The destinations this Admin's permissions allow. */
export function navFor(access) {
  return NAV.filter((item) => !item.requires || can(access, item.requires));
}

/* Every destination key this Admin may open, Settings included. */
export function destinationKeys(access) {
  return new Set([...navFor(access).map((item) => item.key), SETTINGS.key]);
}
