import { t } from '../i18n/i18n.jsx';

/* The prank-report ladder (v1.12.41), as the console says it. The server
 * decides each step (app/services/report_strikes.py); this only words it, and
 * previews the next one for whoever is about to mark a report. */

export function stepText(step) {
  switch (step) {
    case 1: return t('1st strike · reporting paused 24 hours');
    case 2: return t('2nd strike · paused 7 days, then 30 days of verify-first');
    case 3: return t('3rd strike · paused 30 days, then 90 days of verify-first');
    default: return t('4th strike · reporting removed until an appeal is granted');
  }
}

/* The step a new strike would be, from the strikes in effect now. */
export function nextStep(inEffect, serious = false) {
  const step = Math.min((inEffect || 0) + 1, 4);
  return serious ? Math.max(step, 3) : step;
}
