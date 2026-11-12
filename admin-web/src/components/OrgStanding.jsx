import { useState } from 'react';

import { api } from '../api/client.js';
import { t } from '../i18n/i18n.jsx';

/* An affiliate's standing, and what the central hub may do about it
 * (v1.12.28; 12 November 2026: "affiliate management (freeze account, or soft
 * delete, or hard delete, for revoked reasons)").
 *
 *   Suspend            freezes it: nobody of it signs in or acts. Restore
 *                      undoes it at any time.
 *   Revoke             takes it off the network, frozen, its records kept.
 *                      Restore undoes it for 30 days.
 *   Delete permanently removes it and every account of it, only when it has
 *                      no incidents on record; the name is typed to confirm.
 *
 * Each asks why, from the list; Other needs a note. The server checks all of
 * it again (app/api/routes/affiliate_standing.py) and writes the audit log. */

export const REASONS = [
  ['misconduct', () => t('Misconduct')],
  ['inactive', () => t('Inactive')],
  ['duplicate', () => t('Duplicate')],
  ['fraudulent_application', () => t('Fraudulent application')],
  ['organization_request', () => t('The organization’s request')],
  ['other', () => t('Other')],
];

const reasonLabel = (key) => (REASONS.find(([k]) => k === key)?.[1] ?? (() => key ?? '—'))();

function stamp(iso) {
  return iso
    ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : '—';
}

export function standingLabel(org) {
  if (org.standing === 'suspended') return t('Suspended');
  if (org.standing === 'revoked') return t('Revoked');
  return org.is_active ? t('Active') : t('Inactive');
}

const ACTIONS = {
  suspend: {
    label: () => t('Suspend'),
    title: () => t('Suspend this organization?'),
    body: () => t('Nobody of it can sign in or act until you restore it. Its records stay.'),
    button: 'rpl-button--secondary',
  },
  revoke: {
    label: () => t('Revoke'),
    title: () => t('Revoke this organization?'),
    body: () => t('It leaves the network and nobody of it can sign in. Its records stay, and you can restore it for 30 days.'),
    button: 'rpl-button--secondary',
  },
  delete: {
    label: () => t('Delete permanently'),
    title: () => t('Delete this organization permanently?'),
    body: () => t('It and every account of it are removed for good. Only an organization with no incidents on record can be deleted; otherwise revoke it.'),
    button: 'rpl-button--danger',
  },
  restore: {
    label: () => t('Restore'),
    title: () => t('Restore this organization?'),
    body: () => t('Its people can sign in and act again.'),
    button: 'rpl-button--primary',
  },
};

export default function OrgStanding({ org, canManage, onChanged }) {
  const [action, setAction] = useState(null);
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const standing = org.standing ?? 'active';
  const restorable = standing === 'suspended'
    || (standing === 'revoked' && (!org.restorable_until || new Date(org.restorable_until) > new Date()));
  const offered = standing === 'active'
    ? ['suspend', 'revoke', 'delete']
    : standing === 'suspended'
      ? ['restore', 'revoke', 'delete']
      : [...(restorable ? ['restore'] : []), 'delete'];

  function open(key) {
    setAction(key);
    setReason('');
    setNote('');
    setName('');
    setError(null);
  }

  async function confirm() {
    setError(null);
    if (action !== 'restore' && !reason) {
      setError(t('Pick a reason.'));
      return;
    }
    if (reason === 'other' && !note.trim()) {
      setError(t('Say why: a note is needed when the reason is Other.'));
      return;
    }
    setBusy(true);
    try {
      let updated = null;
      if (action === 'suspend') updated = await api.affiliateSuspend(org.id, reason, note);
      else if (action === 'revoke') updated = await api.affiliateRevoke(org.id, reason, note);
      else if (action === 'restore') updated = await api.affiliateRestore(org.id, note);
      else if (action === 'delete') await api.affiliateDelete(org.id, reason, note, name);
      setAction(null);
      onChanged?.(action, updated);
    } catch (e) {
      setError(e.message || t('That did not go through. Try again.'));
    } finally {
      setBusy(false);
    }
  }

  const facts = standing === 'active'
    ? null
    : [
      [t('Since'), stamp(org.standing_changed_at)],
      [t('Reason'), reasonLabel(org.standing_reason)],
      ...(org.standing_note ? [[t('Note'), org.standing_note]] : []),
      ...(standing === 'revoked'
        ? [[t('Can be restored until'), restorable ? stamp(org.restorable_until) : t('No longer')]]
        : []),
    ];

  return (
    <section className="od-section" aria-labelledby={`od-standing-${org.id}`}>
      <h3 className="od-section-title" id={`od-standing-${org.id}`}>{t('Standing')}</h3>
      <p className="od-desc">
        <strong>{standingLabel(org)}</strong>
        {standing === 'active' && ' — '}
        {standing === 'active' && t('Its people sign in and take part as usual.')}
      </p>
      {facts && (
        <dl className="od-facts">
          {facts.map(([k, v]) => (
            <div className="od-fact" key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}

      {!canManage ? (
        <p className="od-empty">
          {org.is_central_hub
            ? t('The central hub cannot be suspended, revoked or deleted.')
            : t('You cannot suspend, revoke or delete your own organization.')}
        </p>
      ) : action === null ? (
        <div className="rpl-aff-actions">
          {offered.map((key) => (
            <button
              key={key}
              type="button"
              className={`rpl-button rpl-button--compact ${ACTIONS[key].button}`}
              onClick={() => open(key)}
            >
              {ACTIONS[key].label()}
            </button>
          ))}
        </div>
      ) : (
        <div className={`rpl-alert ${action === 'delete' ? 'rpl-alert--danger' : 'rpl-alert--warn'}`} role="group" aria-label={ACTIONS[action].title()}>
          <div className="rpl-alert-text">
            <p className="rpl-alert-title">{ACTIONS[action].title()}</p>
            <p className="rpl-alert-body">{ACTIONS[action].body()}</p>
            {action !== 'restore' && (
              <label className="rpl-field">
                <span className="rpl-field-label">{t('Reason')}</span>
                <select value={reason} onChange={(e) => setReason(e.target.value)} required>
                  <option value="" disabled>{t('Pick a reason')}</option>
                  {REASONS.map(([key, label]) => <option key={key} value={key}>{label()}</option>)}
                </select>
              </label>
            )}
            <label className="rpl-field">
              <span className="rpl-field-label">
                {reason === 'other' ? t('Note (needed for Other)') : t('Note (optional)')}
              </span>
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
              <span className="rpl-field-help">{t('Recorded in the audit log.')}</span>
            </label>
            {action === 'delete' && (
              <label className="rpl-field">
                <span className="rpl-field-label">{t('Type {name} to confirm', { name: org.name })}</span>
                <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
              </label>
            )}
            {error && <p className="rpl-field-error" role="alert">{error}</p>}
            <div className="rpl-aff-actions">
              <button type="button" className="rpl-button rpl-button--secondary" onClick={() => setAction(null)} disabled={busy}>
                {t('Cancel')}
              </button>
              <button
                type="button"
                className={`rpl-button ${ACTIONS[action].button === 'rpl-button--secondary' ? 'rpl-button--primary' : ACTIONS[action].button}`}
                onClick={confirm}
                disabled={busy || (action === 'delete' && name.trim().toLowerCase() !== org.name.trim().toLowerCase())}
              >
                {busy ? t('Working…') : ACTIONS[action].label()}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
