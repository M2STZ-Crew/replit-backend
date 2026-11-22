import { useEffect, useState } from 'react';

import { api } from '../../api/client.js';
import FormDialog from '../ui/FormDialog.jsx';
import Select from '../ui/Select.jsx';
import { t } from '../../i18n/i18n.jsx';

/* Create a Coordinator account (REPLIT (MAIN) 10 · A49 875:7435; PRD v13
 * §4.6.4: an organisation's Admin creates its Coordinators).
 *
 * The 6 November list: the Coordinator signs in at an address made from their
 * name, the organisation's agency and the role (obryan.fircor@replit.com),
 * shown here as the name is typed (GET /admin/coordinators/email-preview).
 * @replit.com has no mailboxes, so the form also takes their personal email:
 * the server (POST /admin/coordinators) emails a link there that confirms it
 * and sets their password, and later password resets go there too. No
 * password passes through the console. `organizations`, when given, is for
 * the system Admin, which belongs to no organisation and names one.
 * With `responder`, the same form makes a Responder (v1.12.49; POST
 * /admin/responders) and asks for a mobile too.
 * `onCreate({ firstName, lastName, personalEmail, title, mobile, organizationId })`
 * must resolve once the account exists; a rejected promise shows its message
 * in the dialog. */

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STAFF_DOMAIN = /@replit\.com$/i;

export default function CreateCoordinatorDialog({ open, organization, organizations = null, responder = false, onCreate, onClose }) {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [personalEmail, setPersonalEmail] = useState('');
  const [title, setTitle] = useState('');
  const [mobile, setMobile] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [address, setAddress] = useState(null);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setFirstName(''); setLastName(''); setPersonalEmail(''); setTitle(''); setMobile('');
    setOrganizationId(''); setAddress(null); setTried(false); setError(null);
  }, [open]);

  const picking = Array.isArray(organizations);
  const chosen = picking ? organizations.find((o) => o.id === organizationId) : null;
  const orgName = picking ? (chosen?.name ?? t('the organization')) : organization;

  // The address, as the server would make it now, a moment after typing stops.
  useEffect(() => {
    const first = firstName.trim();
    const last = lastName.trim();
    if (!open || !first || !last || (picking && !organizationId)) {
      setAddress(null);
      return undefined;
    }
    let stale = false;
    const timer = setTimeout(() => {
      (responder ? api.responderEmailPreview : api.coordinatorEmailPreview)({
        firstName: first, lastName: last, organizationId: picking ? organizationId : null,
      })
        .then((r) => { if (!stale) setAddress(r?.email ?? null); })
        .catch(() => { if (!stale) setAddress(null); });
    }, 300);
    return () => { stale = true; clearTimeout(timer); };
  }, [open, firstName, lastName, organizationId, picking, responder]);

  const personal = personalEmail.trim();
  const firstError = tried && !firstName.trim() ? t('Enter their first name.') : null;
  const lastError = tried && !lastName.trim() ? t('Enter their last name.') : null;
  const emailError = !tried ? null
    : !EMAIL.test(personal) ? t('Enter an email address like name@example.com.')
      : STAFF_DOMAIN.test(personal) ? t('Use their own email: @replit.com addresses have no mailbox.')
        : null;
  const orgError = tried && picking && !organizationId ? t('Choose their organization.') : null;

  async function submit() {
    setTried(true);
    if (!firstName.trim() || !lastName.trim() || !EMAIL.test(personal) || STAFF_DOMAIN.test(personal)
      || (picking && !organizationId)) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        personalEmail: personal,
        title: title.trim() || null,
        mobile: mobile.trim() || null,
        organizationId: picking ? organizationId : null,
      });
    } catch (err) {
      setError(err?.message || t('The account was not created. Try again.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={open}
      eyebrow={t('Organization · {orgName}', { orgName })}
      title={responder ? t('Create a Responder account') : t('Create a Coordinator account')}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={responder
        ? t('They join {orgName} as a Responder, and its Coordinators dispatch them. We email their personal address a link to confirm it and set their password.', { orgName })
        : t('They can acknowledge Areas and create Responder accounts for {orgName}. We email their personal address a link to confirm it and set their password.', { orgName })}
      submitLabel={t('Create account')}
      busyLabel={t('Creating…')}
    >
      {picking && (
        <Select
          variant="field"
          label={t('Organization')}
          value={organizationId}
          onChange={setOrganizationId}
          placeholder={t('Choose…')}
          options={organizations.map((o) => ({ key: o.id, label: o.name }))}
          error={orgError}
          disabled={busy}
        />
      )}
      <label className="rpl-field">
        <span className="rpl-field-label">{t('First name')}</span>
        <input value={firstName} onChange={(e) => setFirstName(e.target.value)} aria-invalid={!!firstError} disabled={busy} autoComplete="off" maxLength={60} />
        {firstError && <span className="rpl-field-error">{firstError}</span>}
      </label>
      <label className="rpl-field">
        <span className="rpl-field-label">{t('Last name')}</span>
        <input value={lastName} onChange={(e) => setLastName(e.target.value)} aria-invalid={!!lastError} disabled={busy} autoComplete="off" maxLength={60} />
        {lastError && <span className="rpl-field-error">{lastError}</span>}
      </label>
      <div className="rpl-field" aria-live="polite">
        <span className="rpl-field-label">{t('Sign-in address')}</span>
        <span className="rpl-coordinator-address">{address ?? '—'}</span>
        <span className="rpl-field-help">{t('Made from their name. They sign in to the mobile app with it.')}</span>
      </div>
      <label className="rpl-field">
        <span className="rpl-field-label">{t('Personal email')}</span>
        <input type="email" value={personalEmail} onChange={(e) => setPersonalEmail(e.target.value)} aria-invalid={!!emailError} disabled={busy} autoComplete="off" placeholder="name@gmail.com" />
        {emailError
          ? <span className="rpl-field-error">{emailError}</span>
          : <span className="rpl-field-help">{t('Their own email. The link to set their password goes here, and so do password resets.')}</span>}
      </label>
      <label className="rpl-field">
        <span className="rpl-field-label">{t('Title (optional)')}</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy} placeholder={responder ? t('e.g. Nozzleman') : t('e.g. Lieutenant')} maxLength={80} />
      </label>
      {responder && (
        <label className="rpl-field">
          <span className="rpl-field-label">{t('Mobile (optional)')}</span>
          <input type="tel" value={mobile} onChange={(e) => setMobile(e.target.value)} disabled={busy} autoComplete="off" placeholder="0917 123 4567" maxLength={32} />
        </label>
      )}
    </FormDialog>
  );
}
