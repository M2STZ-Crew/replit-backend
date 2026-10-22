import { useEffect, useState } from 'react';

import FormDialog from '../ui/FormDialog.jsx';

/* A request from one Admin to another (REPLIT (MAIN) 10 · A43 873:6098 water,
 * A44 874:6104 backup; PRD v13 §4.6.3). UI READY — the server has no
 * Admin-to-Admin requests yet, so this is shown only in docs/console-ready.html.
 *
 *   kind          'water' | 'backup'
 *   areas         [{ id, label }]           Areas the request can be about
 *   organizations [{ id, name }]            who it can go to
 *   roles         ['Firefighter', …]        backup roles to offer (backup only)
 *   onSend({ kind, areaId, toOrganizationId, amount?, role?, count?, urgency })
 *     -> Promise; a rejection shows its message in the dialog.
 *
 * Units, roles and who may answer are the integrator's to supply; nothing
 * here decides them. */

const URGENCY = [
  { key: 'low', label: 'Low' },
  { key: 'medium', label: 'Medium' },
  { key: 'high', label: 'High' },
];

const COPY = {
  water: { eyebrow: 'New request · Need water', title: 'Ask another organisation for water', submit: 'Send request' },
  backup: { eyebrow: 'New request · Need backup', title: 'Ask another organisation for backup', submit: 'Send request' },
};

export default function NewRequestDialog({ open, kind = 'water', areas = [], organizations = [], roles = [], onSend, onClose }) {
  const [areaId, setAreaId] = useState('');
  const [to, setTo] = useState('');
  const [amount, setAmount] = useState('');
  const [role, setRole] = useState('');
  const [count, setCount] = useState('1');
  const [urgency, setUrgency] = useState('medium');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setAreaId(areas[0]?.id ?? '');
    setTo(organizations[0]?.id ?? '');
    setAmount(''); setRole(roles[0] ?? ''); setCount('1'); setUrgency('medium');
    setTried(false); setError(null);
  }, [open]);

  const copy = COPY[kind] ?? COPY.water;
  const toName = organizations.find((o) => o.id === to)?.name ?? 'They';
  const missing = {
    area: !areaId ? 'Choose the Area this is for.' : null,
    to: !to ? 'Choose who to ask.' : null,
    amount: kind === 'water' && !amount.trim() ? 'Say roughly how much water.' : null,
    role: kind === 'backup' && !role ? 'Choose who you need.' : null,
    count: kind === 'backup' && !(Number(count) >= 1) ? 'Ask for at least one.' : null,
  };

  async function submit() {
    setTried(true);
    if (Object.values(missing).some(Boolean)) return;
    setBusy(true);
    setError(null);
    try {
      await onSend({
        kind,
        areaId,
        toOrganizationId: to,
        ...(kind === 'water' ? { amount: amount.trim() } : { role, count: Number(count) }),
        urgency,
      });
    } catch (e) {
      setError(e?.message || 'The request was not sent. Try again.');
    } finally {
      setBusy(false);
    }
  }

  const show = (key) => tried && missing[key] && <span className="ad-field-error">{missing[key]}</span>;

  return (
    <FormDialog
      open={open}
      eyebrow={copy.eyebrow}
      title={copy.title}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={`${toName} can accept, decline or acknowledge it.`}
      submitLabel={copy.submit}
      busyLabel="Sending…"
    >
      <div className="ad-form-row">
        <label className="ad-select">
          <span className="ad-select-label">Area</span>
          <select value={areaId} onChange={(e) => setAreaId(e.target.value)} disabled={busy}>
            {areas.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </label>
        <label className="ad-select">
          <span className="ad-select-label">Send to</span>
          <select value={to} onChange={(e) => setTo(e.target.value)} disabled={busy}>
            {organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </label>
      </div>
      {show('area')}{show('to')}

      {kind === 'water' ? (
        <label className="ad-field">
          <span className="ad-field-label">Estimated amount</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="e.g. 2,000 litres" disabled={busy} aria-invalid={!!(tried && missing.amount)} />
          {show('amount') || <span className="ad-field-help">Litres or gallons</span>}
        </label>
      ) : (
        <div className="ad-form-row">
          <label className="ad-select">
            <span className="ad-select-label">Need</span>
            <select value={role} onChange={(e) => setRole(e.target.value)} disabled={busy}>
              {roles.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="ad-field">
            <span className="ad-field-label">How many</span>
            <input type="number" min="1" value={count} onChange={(e) => setCount(e.target.value)} disabled={busy} aria-invalid={!!(tried && missing.count)} />
          </label>
        </div>
      )}
      {kind === 'backup' && (show('role') || show('count'))}

      <fieldset className="ad-choice">
        <legend className="ad-field-label">Urgency</legend>
        <div className="ad-choice-options">
          {URGENCY.map((u) => (
            <label key={u.key} className={`ad-choice-option${urgency === u.key ? ' is-on' : ''}`}>
              <input type="radio" name="urgency" value={u.key} checked={urgency === u.key} onChange={() => setUrgency(u.key)} disabled={busy} />
              {urgency === u.key && <span aria-hidden="true">✓</span>}
              {u.label}
            </label>
          ))}
        </div>
      </fieldset>
    </FormDialog>
  );
}
