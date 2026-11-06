import { PERM, can } from '../../lib/access.js';
import { t } from '../../i18n/i18n.jsx';

/* The Admin console's destinations, in the pass 6 sidebar's order (REPLIT
 * (MAIN) 04 · Sidebar; 10 · screen map). `badge` names a counter: `new:*`
 * counts incidents reported since the operator last viewed that surface
 * (PRD v13 §4.14); the others are pending queues.
 *
 * `requires` names the permission a destination needs (lib/access.js): the
 * Barangay 76 central hub's duties, manual National ID review and affiliate
 * review (PRD v13 §4.1, §4.12; A00 "Four permission variants"), and Map
 * settings, for the Admins who look after the shared map. */
export const NAV = [
  { key: 'dashboard', get label() { return t('Dashboard'); }, icon: 'dashboard', get group() { return t('Operations'); }, badge: 'new:dashboard' },
  { key: 'incidents', get label() { return t('Incidents'); }, icon: 'incidents', get group() { return t('Operations'); }, badge: 'new:incidents' },
  { key: 'map', get label() { return t('Live map'); }, icon: 'map', get group() { return t('Operations'); } },
  { key: 'requests', get label() { return t('Requests'); }, icon: 'requests', get group() { return t('Operations'); }, badge: 'requests' },
  { key: 'water', get label() { return t('Water resources'); }, icon: 'water', get group() { return t('Resources'); } },
  { key: 'mapsettings', get label() { return t('Map settings'); }, icon: 'settings', get group() { return t('Resources'); }, requires: PERM.MANAGE_MAP },
  { key: 'reports', get label() { return t('Reports & CIAR'); }, icon: 'reports', get group() { return t('Records'); } },
  { key: 'audit', get label() { return t('Audit log'); }, icon: 'audit', get group() { return t('Records'); } },
  { key: 'organization', get label() { return t('Organization'); }, icon: 'organization', get group() { return t('Organization'); } },
  { key: 'accounts', get label() { return t('Accounts'); }, icon: 'accounts', get group() { return t('Organization'); } },
  { key: 'idreview', get label() { return t('Verification'); }, icon: 'verification', get group() { return t('Organization'); }, requires: PERM.REVIEW_IDS, badge: 'ids' },
  { key: 'affiliates', get label() { return t('Affiliates'); }, icon: 'affiliates', get group() { return t('Organization'); }, requires: PERM.REVIEW_AFFILIATES, badge: 'affiliates' },
];

export const SETTINGS = { key: 'settings', get label() { return t('Settings'); }, icon: 'settings' };

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
