import { useEffect, useState } from 'react';

import { ALARM_LEVEL, ASKABLE_ALARM_LEVELS, alarmLabel } from '../../lib/status.js';
import FormDialog from '../ui/FormDialog.jsx';

/* Ask BFP to raise the alarm (REPLIT (MAIN) 10 · A45 874:6513; PRD v13 §4.7:
 * Fire Volunteer Admins request, BFP sets the level). A Fire Volunteer
 * organisation's Admin picks the Area and the level above its current one;
 * BFP decides on the Requests screen or the mobile app.
 *
 * `areas` are the live Areas routed to this organisation (one, when opened
 * from an incident). `onSend({ areaId, level, justification })` must resolve
 * once the server has the request; a rejected promise shows its message. The
 * design's Task Force levels are left out: the server has no such levels. */

const LEVELS = Object.keys(ALARM_LEVEL);

function above(current) {
  const at = current ? LEVELS.indexOf(current) : -1;
  return ASKABLE_ALARM_LEVELS.filter((l) => LEVELS.indexOf(l) > at);
}

export default function AlarmEscalationDialog({ open, areas, bfpName = 'BFP', onSend, onClose }) {
  const [areaId, setAreaId] = useState('');
  const [level, setLevel] = useState('');
  const [justification, setJustification] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setAreaId(areas?.[0]?.id ?? '');
    setLevel('');
    setJustification('');
    setTried(false);
    setError(null);
  }, [open, areas]);

  const area = (areas ?? []).find((a) => a.id === areaId) ?? null;
  const choices = above(area?.alarm_level);
  const levelError = tried && !level ? 'Choose the level to ask for.' : null;

  async function submit() {
    setTried(true);
    if (!area || !level) return;
    setBusy(true);
    setError(null);
    try {
      await onSend({ areaId: area.id, level, justification: justification.trim() || null });
    } catch (err) {
      setError(err?.message || 'The request was not sent. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={open}
      eyebrow="New request · Alarm escalation"
      title={`Ask ${bfpName} to raise the alarm`}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={`Only ${bfpName} sets the alarm level.`}
      submitLabel="Send escalation request"
      busyLabel="Sending…"
    >
      {(areas ?? []).length > 1 ? (
        <label className="rpl-field">
          <span className="rpl-field-label">Area</span>
          <select value={areaId} onChange={(e) => { setAreaId(e.target.value); setLevel(''); }} disabled={busy}>
            {areas.map((a) => <option key={a.id} value={a.id}>{a.designation}</option>)}
          </select>
        </label>
      ) : (
        <p className="rpl-field-static">
          <span className="rpl-field-label">Area</span>
          <span>{area?.designation ?? '—'}</span>
        </p>
      )}
      <p className="rpl-field-static">
        <span className="rpl-field-label">Send to</span>
        <span>{bfpName}</span>
      </p>
      <fieldset className="rpl-field" aria-invalid={!!levelError}>
        <legend className="rpl-field-label">
          Proposed level{area?.alarm_level ? ` · now ${alarmLabel(area.alarm_level)}` : ''}
        </legend>
        {choices.length === 0 ? (
          <p className="rpl-field-help">This Area is already at the highest level.</p>
        ) : (
          <div className="rpl-segment">
            {choices.map((key) => (
              <button
                key={key}
                type="button"
                className={`rpl-chip${level === key ? ' is-selected' : ''}`}
                aria-pressed={level === key}
                onClick={() => setLevel(key)}
                disabled={busy}
              >
                {level === key && <span aria-hidden="true">✓</span>}
                {alarmLabel(key)}
              </button>
            ))}
          </div>
        )}
        {levelError && <span className="rpl-field-error">{levelError}</span>}
      </fieldset>
      <label className="rpl-field">
        <span className="rpl-field-label">Why (optional)</span>
        <textarea
          rows={3}
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          disabled={busy}
          placeholder="e.g. The fire has reached the next building."
          maxLength={2000}
        />
      </label>
    </FormDialog>
  );
}
