/* The Admin console's destinations, in the pass 6 sidebar's order (REPLIT
 * (MAIN) 04 · Sidebar; 10 · screen map). `badge` names a counter: `new:*`
 * counts incidents reported since the operator last viewed that surface
 * (PRD v13 §4.14); the others are pending queues.
 *
 * `central` items are the Barangay 76 central-hub duties (PRD v13 §4.1,
 * §4.12): manual National ID review and affiliate review. */
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
  { key: 'idreview', label: 'Verification', icon: 'verification', group: 'Organization', central: true, badge: 'ids' },
  { key: 'affiliates', label: 'Affiliates', icon: 'affiliates', group: 'Organization', central: true, badge: 'affiliates' },
];

export const SETTINGS = { key: 'settings', label: 'Settings', icon: 'settings' };

export const GROUPS = ['Operations', 'Resources', 'Records', 'Organization'];

/* Which sidebar this Admin gets. The design draws a Central variant (the
 * Barangay 76 hub, with Verification and Affiliates) and a Standard one.
 *
 * The API has no hub capability yet — /auth/me returns no org role, and every
 * `admin` may review IDs and affiliates today. So every Admin keeps the
 * Central sidebar: hiding duties the server still grants would strand them,
 * and the design forbids guessing the hub from an email or an organisation's
 * name. When the server reports the capability, read it here. */
export function consoleAccess(/* user */) {
  return 'central';
}

export function navFor(access) {
  return NAV.filter((item) => access === 'central' || !item.central);
}
