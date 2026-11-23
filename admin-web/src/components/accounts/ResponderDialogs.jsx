import { useEffect, useState } from 'react';

import FormDialog from '../ui/FormDialog.jsx';
import Select from '../ui/Select.jsx';
import { t } from '../../i18n/i18n.jsx';

/* An Admin's forms for a staff account, a Responder's (v1.12.49; 22 Nov
 * 2026: "admin can manage responders too"; answered "Full account control"
 * and "Own org; hub manages all") or a Coordinator's (v1.12.51; 23 Nov 2026:
 * "make the account management in coordinator and responder the same"). The
 * server checks every rule again (app/services/staff_admin.py). */

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STAFF_DOMAIN = /@replit\.com$/i;

const nameOf = (person) => person?.full_name || person?.email || '';
const orgOf = (person) => person?.org || t('No organization');
const isCoordinator = (person) => person?.role === 'sub_admin';

/* "Coordinator · Pasay Fire Volunteers", over each form about one account. */
export function accountEyebrow(person) {
  if (!person) return '';
  return isCoordinator(person)
    ? t('Coordinator · {org}', { org: orgOf(person) })
    : t('Responder · {org}', { org: orgOf(person) });
}

/* Manage an account: name, title and mobile, and the ways to their sign-in
 * (a password link, off and on). With `organizations` (the central hub and the
 * system Admin), the organization too: one of the same agency, and not while
 * they are on a fire. Only what changed is sent. */
export function ManageAccountDialog({
  person, organizations = null, onSave, onLink, onTurnOff, onTurnOn, onClose,
}) {
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [mobile, setMobile] = useState('');
  const [orgId, setOrgId] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!person) return;
    setName(person.full_name ?? '');
    setTitle(person.title ?? '');
    setMobile(person.mobile ?? '');
    setOrgId(person.orgId ?? '');
    setTried(false);
    setError(null);
  }, [person]);

  const movable = Array.isArray(organizations);
  const choices = movable
    ? organizations.filter((o) => o.id === person?.orgId || (o.agency_type === person?.agency_type && o.is_active))
    : [];
  const nameError = tried && !name.trim() ? t('Enter their name.') : null;

  const changes = {};
  if (person) {
    if (name.trim() !== (person.full_name ?? '')) changes.full_name = name.trim();
    if (title.trim() !== (person.title ?? '')) changes.title = title.trim();
    if (mobile.trim() !== (person.mobile ?? '')) changes.mobile = mobile.trim();
    if (movable && orgId && orgId !== person.orgId) changes.organization_id = orgId;
  }
  const changed = Object.keys(changes).length > 0;

  async function submit() {
    if (!changed) { onClose(); return; }
    setTried(true);
    if ('full_name' in changes && !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onSave(person, changes);
    } catch (err) {
      setError(err?.message || t('The changes were not saved. Try again.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={Boolean(person)}
      eyebrow={accountEyebrow(person)}
      title={person ? t('Manage {name}', { name: nameOf(person) }) : ''}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={t('Every change is kept in the audit log.')}
      submitLabel={t('Save changes')}
      busyLabel={t('Saving…')}
    >
      <div className="rpl-field">
        <span className="rpl-field-label">{t('Sign-in address')}</span>
        <span className="rpl-coordinator-address">{person?.email ?? '—'}</span>
      </div>
      <label className="rpl-field">
        <span className="rpl-field-label">{t('Full name')}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!nameError} disabled={busy} autoComplete="off" maxLength={200} />
        {nameError && <span className="rpl-field-error">{nameError}</span>}
      </label>
      <label className="rpl-field">
        <span className="rpl-field-label">{t('Title (optional)')}</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy || !orgId} placeholder={isCoordinator(person) ? t('e.g. Lieutenant') : t('e.g. Nozzleman')} maxLength={80} />
      </label>
      <label className="rpl-field">
        <span className="rpl-field-label">{t('Mobile (optional)')}</span>
        <input type="tel" value={mobile} onChange={(e) => setMobile(e.target.value)} disabled={busy} autoComplete="off" placeholder="0917 123 4567" maxLength={32} />
      </label>
      {movable && (
        <Select
          variant="field"
          label={t('Organization')}
          value={orgId}
          onChange={setOrgId}
          options={[
            ...(person?.orgId ? [] : [{ key: '', label: t('No organization') }]),
            ...choices.map((o) => ({ key: o.id, label: o.name })),
          ]}
          disabled={busy || Boolean(person?.responding)}
          help={person?.responding
            ? t('They’re on a fire. You can move them once their response ends.')
            : t('They can move to another organization of the same agency.')}
        />
      )}
      <fieldset className="rpl-field rpl-account-signin" disabled={busy || changed}>
        <legend className="rpl-field-label">{t('Sign-in')}</legend>
        <div className="rpl-account-signin-acts">
          {person?.is_active === false ? (
            <button type="button" className="web-button web-button--secondary" onClick={() => onTurnOn(person)}>{t('Turn on')}</button>
          ) : (
            <>
              <button type="button" className="web-button web-button--secondary" onClick={() => onLink(person)}>{t('Send a password link')}</button>
              <button type="button" className="web-button web-button--secondary is-danger" onClick={() => onTurnOff(person)}>{t('Turn off')}</button>
            </>
          )}
        </div>
        {changed && <span className="rpl-field-help">{t('Save your changes first.')}</span>}
      </fieldset>
    </FormDialog>
  );
}

/* The link that sets a password. It goes to their own email: the Admin fills
 * that in where there is none or it was never confirmed, and cannot change a
 * confirmed one. */
export function PasswordLinkDialog({ person, onSend, onClose }) {
  const [email, setEmail] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // An account from before made addresses signs in with a real mailbox.
  const mailbox = Boolean(person?.email) && !STAFF_DOMAIN.test(person.email);
  const fixed = mailbox || Boolean(person?.personal_email_verified && person?.personal_email);

  useEffect(() => {
    if (!person) return;
    setEmail(person.personal_email ?? '');
    setTried(false);
    setError(null);
  }, [person]);

  const value = email.trim();
  const problem = !EMAIL.test(value) ? t('Enter an email address like name@example.com.')
    : STAFF_DOMAIN.test(value) ? t('Use their own email: @replit.com addresses have no mailbox.')
      : null;
  const emailError = tried && !fixed ? problem : null;

  async function submit() {
    setTried(true);
    if (!fixed && problem) return;
    setBusy(true);
    setError(null);
    try {
      await onSend(person, fixed ? null : value);
    } catch (err) {
      setError(err?.message || t('The link was not sent. Try again.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog
      open={Boolean(person)}
      eyebrow={accountEyebrow(person)}
      title={person ? t('Send {name} a password link?', { name: nameOf(person) }) : ''}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      note={t('The link works for one hour. Their current password works until they set a new one.')}
      submitLabel={t('Send link')}
      busyLabel={t('Sending…')}
    >
      {fixed ? (
        <div className="rpl-field">
          <span className="rpl-field-label">{t('The link goes to')}</span>
          <span className="rpl-coordinator-address">{mailbox ? person?.email : person?.personal_email}</span>
          <span className="rpl-field-help">
            {mailbox
              ? t('The email they sign in with.')
              : t('They confirmed this email. Only they can change it, in Profile.')}
          </span>
        </div>
      ) : (
        <label className="rpl-field">
          <span className="rpl-field-label">{t('Personal email')}</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!emailError} disabled={busy} autoComplete="off" placeholder="name@gmail.com" />
          {emailError
            ? <span className="rpl-field-error">{emailError}</span>
            : <span className="rpl-field-help">{t('Not confirmed yet, so check it with them first. Whoever opens the link can set the password.')}</span>}
        </label>
      )}
    </FormDialog>
  );
}
