import { useEffect, useState } from 'react';

import FormDialog from '../ui/FormDialog.jsx';

/* Create a Coordinator account (REPLIT (MAIN) 10 · A49 875:7435; PRD v13
 * §4.6.4: an organisation's Admin creates its Coordinators).
 *
 * The design asks for a name, an email and an optional title. The server
 * (POST /admin/coordinators) creates the account in the Admin's own
 * organisation and emails the new Coordinator a link to set their password,
 * so no password passes through the console. `organizations`, when given,
 * is for the system Admin, which belongs to no organisation and names one.
 * `onCreate({ fullName, email, title, organizationId })` must resolve once
 * the account exists; a rejected promise shows its message in the dialog. */

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function CreateCoordinatorDialog({ open, organization, organizations = null, onCreate, onClose }) {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [title, setTitle] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setFullName(''); setEmail(''); setTitle(''); setOrganizationId(''); setTried(false); setError(null);
  }, [open]);

  const picking = Array.isArray(organizations);
  const chosen = picking ? organizations.find((o) => o.id === organizationId) : null;
  const orgName = picking ? (chosen?.name ?? 'the organization') : organization;
  const nameError = tried && !fullName.trim() ? 'Enter the Coordinator’s full name.' : null;
  const emailError = tried && !EMAIL.test(email.trim()) ? 'Enter an email address like name@example.com.' : null;
  const orgError = tried && picking && !organizationId ? 'Choose their organization.' : null;

  async function submit() {
    setTried(true);
    if (!fullName.trim() || !EMAIL.test(email.trim()) || (picking && !organizationId)) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        fullName: fullName.trim(),
        email: email.trim(),
        title: title.trim() || null,
        organizationId: picking ? organizationId : null,
      });
    } catch (err) {
      setError(err?.message || 'The account was not created. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={open}
      eyebrow={`Organization · ${orgName}`}
      title="Create a Coordinator account"
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={`They can acknowledge Areas and create Responder accounts for ${orgName}. We email them a link to set their password.`}
      submitLabel="Create account"
      busyLabel="Creating…"
    >
      {picking && (
        <label className="ad-field">
          <span className="ad-field-label">Organization</span>
          <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} aria-invalid={!!orgError} disabled={busy}>
            <option value="">Choose…</option>
            {organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          {orgError && <span className="ad-field-error">{orgError}</span>}
        </label>
      )}
      <label className="ad-field">
        <span className="ad-field-label">Full name</span>
        <input value={fullName} onChange={(e) => setFullName(e.target.value)} aria-invalid={!!nameError} disabled={busy} autoComplete="name" />
        {nameError && <span className="ad-field-error">{nameError}</span>}
      </label>
      <label className="ad-field">
        <span className="ad-field-label">Email</span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!emailError} disabled={busy} autoComplete="email" />
        {emailError
          ? <span className="ad-field-error">{emailError}</span>
          : <span className="ad-field-help">They sign in to the mobile app with this.</span>}
      </label>
      <label className="ad-field">
        <span className="ad-field-label">Title (optional)</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy} placeholder="e.g. Lieutenant" maxLength={80} />
      </label>
    </FormDialog>
  );
}
