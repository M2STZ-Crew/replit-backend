import { t } from '../i18n/i18n.jsx';

/* A water source's status, and when it was last looked at: for Map settings'
 * list and both maps' details (v1.12.47, v1.12.50). A row carries
 * its `kind`: 'hydrant', 'water' (a body of water) or 'cistern'. */

// In the words of 19 Nov 2026: working, low pressure, broken, no access.
export const WATER_STATUS = {
  operational: { get label() { return t('Working'); }, tone: 'ok' },
  low_pressure: { get label() { return t('Low pressure'); }, tone: 'warn' },
  non_operational: { get label() { return t('Broken'); }, tone: 'danger' },
  no_access: { get label() { return t('No access'); }, tone: 'warn' },
  under_maintenance: { get label() { return t('Under maintenance'); }, tone: 'warn' },
  unknown: { get label() { return t('Not checked'); }, tone: 'neutral' },
};

export function waterStatusOf(row) {
  if (row.kind === 'water') {
    return row.is_accessible ? { label: t('Accessible'), tone: 'ok' } : { label: t('Not accessible'), tone: 'danger' };
  }
  const value = row.kind === 'hydrant' ? row.effective_status : row.status;
  return WATER_STATUS[value] ?? WATER_STATUS.unknown;
}

const WHEN = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
});

export const when = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : WHEN.format(d);
};

/* When the source was last looked at: a hydrant's on-the-ground check, else
 * the record's last change. */
export function checkedOf(row) {
  if (row.kind === 'hydrant' && row.ground_truth_at) {
    // Who checked it, for which organisation (v1.12.43).
    const by = row.checked_by_org || row.checked_by_name;
    const at = when(row.ground_truth_at);
    return { title: t('Checked on the ground'), at: at && by ? t('{at} · {by}', { at, by }) : at };
  }
  return { title: t('Record updated'), at: when(row.updated_at) };
}
