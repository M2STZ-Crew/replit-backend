import { useEffect, useState } from 'react';

import FormDialog from '../ui/FormDialog.jsx';

/* Add a correction entry (REPLIT (MAIN) 10 · A65 879:9123, A66). UI READY —
 * the audit log has no correction entries yet; shown only in
 * docs/console-ready.html.
 *
 *   target  { label }                          e.g. "Example Area 1.2"
 *   fields  [{ key, label, current }]          what may be corrected, and its
 *                                              value on record
 *   onSubmit({ field, was, now, reason }) -> Promise
 *
 * A correction sits beside the record it corrects; it never changes the
 * filed report or the CIAR. */
export default function CorrectionDialog({ open, target, fields = [], onSubmit, onClose }) {
  const [field, setField] = useState('');
  const [now, setNow] = useState('');
  const [reason, setReason] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setField(fields[0]?.key ?? ''); setNow(''); setReason(''); setTried(false); setError(null);
  }, [open]);

  const chosen = fields.find((f) => f.key === field) ?? null;
  const nowError = tried && !now.trim() ? 'Enter the correct value.' : null;
  const sameError = tried && chosen && now.trim() && now.trim() === String(chosen.current ?? '') ? 'That is the value already on record.' : null;
  const reasonError = tried && !reason.trim() ? 'Say why — it is kept with the correction.' : null;

  async function submit() {
    setTried(true);
    if (!chosen || !now.trim() || !reason.trim() || now.trim() === String(chosen.current ?? '')) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ field: chosen.key, was: chosen.current ?? null, now: now.trim(), reason: reason.trim() });
    } catch (e) {
      setError(e?.message || 'The correction was not added. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={open}
      eyebrow={target?.label}
      title="Add a correction"
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note="The record doesn’t change. This entry sits beside it in the audit log."
      submitLabel="Add correction"
      busyLabel="Adding…"
    >
      <label className="ad-select">
        <span className="ad-select-label">Field</span>
        <select value={field} onChange={(e) => setField(e.target.value)} disabled={busy}>
          {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
      </label>
      <label className="ad-field">
        <span className="ad-field-label">Correct value</span>
        <input value={now} onChange={(e) => setNow(e.target.value)} disabled={busy} aria-invalid={!!(nowError || sameError)} />
        {nowError || sameError
          ? <span className="ad-field-error">{nowError || sameError}</span>
          : chosen && <span className="ad-field-help">Was: {chosen.current ?? 'not recorded'}</span>}
      </label>
      <label className="ad-field">
        <span className="ad-field-label">Why</span>
        <textarea rows={4} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} aria-invalid={!!reasonError} maxLength={1000} />
        {reasonError && <span className="ad-field-error">{reasonError}</span>}
      </label>
    </FormDialog>
  );
}
