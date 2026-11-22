import { PERM, can } from '../../lib/access.js';
import { t } from '../../i18n/i18n.jsx';

/* The Admin console's destinations, in the pass 6 sidebar's order (REPLIT
 * (MAIN) 04 · Sidebar; 10 · screen map). `badge` names a counter: `new:*`
 * counts incidents reported since the operator last viewed that surface
 * (PRD v13 §4.14); the others are pending queues.
 *
 * `requires` names the permission a destination needs (lib/access.js): the
 * Barangay 76 central hub's duties, manual National ID review and affiliate
 * review (PRD v13 §4.1, §4.12; A00 "Four permission variants"). Map settings
 * is every Admin's since v1.12.50, when Water resources moved into it (22 Nov
 * 2026; answered "All open, same rights"). */
export const NAV = [
  { key: 'dashboard', get label() { return t('Dashboard'); }, icon: 'dashboard', group: 'operations', badge: 'new:dashboard' },
  { key: 'incidents', get label() { return t('Incidents'); }, icon: 'incidents', group: 'operations', badge: 'new:incidents' },
  { key: 'map', get label() { return t('Live map'); }, icon: 'map', group: 'operations' },
  { key: 'requests', get label() { return t('Alarm Escalations'); }, get shortLabel() { return t('Escalations'); }, icon: 'requests', group: 'operations', badge: 'requests' },
  { key: 'mapsettings', get label() { return t('Map settings'); }, icon: 'layers', group: 'resources', badge: 'water' },
  { key: 'reports', get label() { return t('Reports & CIAR'); }, icon: 'reports', group: 'records' },
  { key: 'audit', get label() { return t('Audit log'); }, icon: 'audit', group: 'records' },
  { key: 'organization', get label() { return t('Organization'); }, icon: 'organization', group: 'organization' },
  { key: 'accounts', get label() { return t('Accounts'); }, icon: 'accounts', group: 'organization' },
  { key: 'idreview', get label() { return t('Verification'); }, icon: 'verification', group: 'organization', requires: PERM.REVIEW_IDS, badge: 'ids' },
  { key: 'strikes', get label() { return t('Prank reports'); }, icon: 'escalate', group: 'organization', requires: PERM.REVIEW_STRIKES, badge: 'strikes' },
  { key: 'affiliates', get label() { return t('Affiliates'); }, icon: 'affiliates', group: 'organization', requires: PERM.REVIEW_AFFILIATES, badge: 'affiliates' },
];

export const SETTINGS = { key: 'settings', get label() { return t('Settings'); }, icon: 'settings' };

/* The sidebar's four groups: an item names its group by a key that never
 * changes, and the heading is said in the reader's language. Until 1.12.36 an
 * item's group was its translated heading, matched against these headings in
 * English, so in Tagalog no item matched and the whole nav vanished but
 * Settings (17 Nov 2026: "if the user presses tagalog in admin the nav bar
 * closes"). */
export const GROUPS = [
  { key: 'operations', get label() { return t('Operations'); } },
  { key: 'resources', get label() { return t('Resources'); } },
  { key: 'records', get label() { return t('Records'); } },
  { key: 'organization', get label() { return t('Organization'); } },
];

/* Which sidebar this Admin gets (A00 · Sidebar): the Central variant (the
 * Barangay 76 hub, with Verification and Affiliates) or the Standard one. The
 * server says which (`console.scope` on /auth/me); the system Admin, which
 * may do everything, gets the Central list. */
export function consoleAccess(access) {
  return access?.scope === 'organization' ? 'standard' : 'central';
}

/* Pages that moved: their old address opens the new one. */
export const MOVED = { water: 'mapsettings' };

/* The destinations this Admin's permissions allow. */
export function navFor(access) {
  return NAV.filter((item) => !item.requires || can(access, item.requires));
}

/* Every destination key this Admin may open, Settings included. */
export function destinationKeys(access) {
  return new Set([...navFor(access).map((item) => item.key), SETTINGS.key]);
}
