import { useEffect, useState } from 'react';

import FormDialog from '../ui/FormDialog.jsx';

/* Create a Coordinator account (REPLIT (MAIN) 10 · A49 875:7435; PRD v13
 * §4.6.4: an organisation's Admin creates its Coordinators). UI READY — not
 * in the live console; see docs/console-ready.html.
 *
 * The server's POST /admin/users needs a password the Admin chooses and an
 * agency, has no title field and cannot turn an account off, and today's
 * Admin has no organisation of its own to create Coordinators in. The design
 * asks only for a name, an email and an optional title, so this form hands
 * `onCreate({ fullName, email, title })` to whoever wires it; they decide
 * how credentials reach the new Coordinator
 * (docs/FRONTEND_INTEGRATION_HANDOFF.md). A rejected promise shows its
 * message in the dialog. */

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function CreateCoordinatorDialog({ open, organization, onCreate, onClose }) {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [title, setTitle] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setFullName(''); setEmail(''); setTitle(''); setTried(false); setError(null);
  }, [open]);

  const nameError = tried && !fullName.trim() ? 'Enter the Coordinator’s full name.' : null;
  const emailError = tried && !EMAIL.test(email.trim()) ? 'Enter an email address like name@example.com.' : null;

  async function submit() {
    setTried(true);
    if (!fullName.trim() || !EMAIL.test(email.trim())) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({ fullName: fullName.trim(), email: email.trim(), title: title.trim() || null });
    } catch (err) {
      setError(err?.message || 'The account was not created. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={open}
      eyebrow={`Organisation · ${organization}`}
      title="Create a Coordinator account"
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={`They can acknowledge Areas and create Responder accounts for ${organization}.`}
      submitLabel="Create account"
      busyLabel="Creating…"
    >
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
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy} placeholder="e.g. Lieutenant" />
      </label>
    </FormDialog>
  );
}
