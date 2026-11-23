import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client.js';
import AuthBrand from '../components/AuthBrand.jsx';
import { t } from '../i18n/i18n.jsx';

const AGENCY_TYPES = [
  { value: 'fire_volunteer', get label() { return t('Fire Volunteer'); } },
  { value: 'bfp', get label() { return t('Bureau of Fire Protection (BFP)'); } },
  { value: 'barangay', get label() { return t('Barangay'); } },
  { value: 'medical', get label() { return t('Medical'); } },
  { value: 'police', get label() { return t('Police'); } },
];

const EQUIPMENT_TYPES = ['Fire Truck', 'Water Tanker', 'Ambulance', 'Rescue Vehicle', 'Other'];

/* The type is stored in English; only what the menu shows is translated. */
function equipmentLabel(type) {
  return {
    'Fire Truck': t('Fire Truck'),
    'Water Tanker': t('Water Tanker'),
    Ambulance: t('Ambulance'),
    'Rescue Vehicle': t('Rescue Vehicle'),
    Other: t('Other'),
  }[type] ?? type;
}
const MAX_FILE_BYTES = 10 * 1024 * 1024;
// As the server takes them (app/schemas/affiliate.py).
const MAX_ROSTER = 200;
const MAX_EQUIPMENT = 100;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STAFF_DOMAIN = /@replit\.com$/i;

function megabytes(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 1024 * 1024 ? 2 : 1)} MB`;
}

function UploadIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </svg>
  );
}

function RemoveIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.2" strokeLinecap="round">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function MailIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </svg>
  );
}

/// A field label in the sign-in screen's style, with an optional "Required" mark.
function Label({ children, required }) {
  return (
    <span className="rg-label">
      <span className="dc-eyebrow">{children}</span>
      {required && <span className="rg-req">{t('Required')}</span>}
    </span>
  );
}

export default function Register() {
  const navigate = useNavigate();
  const fileRef = useRef(null);

  const [orgName, setOrgName] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [agencyType, setAgencyType] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [address, setAddress] = useState('');
  const [secFile, setSecFile] = useState(null);
  const [roster, setRoster] = useState([{ full_name: '', role: '' }]);
  const [equipment, setEquipment] = useState([{ name: '', type: '' }]);
  const [agree, setAgree] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  function setMember(i, key, val) {
    setRoster((r) => r.map((m, idx) => (idx === i ? { ...m, [key]: val } : m)));
  }
  function setUnit(i, key, val) {
    setEquipment((e) => e.map((u, idx) => (idx === i ? { ...u, [key]: val } : u)));
  }
  function onFile(e) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > MAX_FILE_BYTES) {
      setError(t('The SEC certificate must be 10 MB or smaller.'));
      return;
    }
    setError(null);
    setSecFile(f);
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    if (!orgName.trim()) return setError(t('Enter your organization’s name.'));
    if (!agencyType) return setError(t('Choose the type of organization.'));
    if (!firstName.trim() || !lastName.trim()) return setError(t('Enter your first name and surname.'));
    if (!email.trim()) return setError(t('Enter the email we should reply to.'));
    if (!EMAIL.test(email.trim())) return setError(t('Enter an email address like name@example.com.'));
    if (STAFF_DOMAIN.test(email.trim())) return setError(t('Use your own email: @replit.com addresses have no mailbox.'));
    if (!secFile) return setError(t('Attach your SEC certificate.'));
    if (!agree) return setError(t('Agree to the Terms and Agreements to submit.'));

    setBusy(true);
    setError(null);
    try {
      await api.registerAffiliate({
        organization_name: orgName.trim(),
        agency_type: agencyType,
        contact_email: email.trim(),
        contact_first_name: firstName.trim(),
        contact_last_name: lastName.trim(),
        contact_phone: phone.trim() || null,
        address: address.trim() || null,
        roster: roster
          .filter((m) => m.full_name.trim())
          .map((m) => ({ full_name: m.full_name.trim(), role: m.role.trim() || null })),
        equipment: equipment
          .filter((u) => u.name.trim())
          .map((u) => ({ name: u.name.trim(), type: u.type || null })),
        sec_certificate_name: secFile.name.slice(0, 300),
      });
      setDone(true);
    } catch (err) {
      setError(err.message || t('The application could not be sent. Try again.'));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="lg rg">
        <AuthBrand />
        <div className="lg-panel rg-panel is-done">
          <div className="lg-form rg-done">
            <div className="lg-head">
              <span className="lg-kicker">{t('Application received')}</span>
              <h2 className="lg-title">{t('Thank you')}</h2>
              <p className="lg-sub">
                {t('{org} is now in the admin’s review queue.', { org: orgName.trim() })}</p>
            </div>

            <div className="lg-note rg-done-note">
              <MailIcon />
              <span>{t('A confirmation is on its way to')}{' '}<strong>{email.trim()}</strong>{t('. Once an admin approves the application, a second email there will have your Coordinator sign-in and a link to set its password. Check your spam folder if either is not in your inbox.')}</span>
            </div>

            <button type="button" className="lg-submit" onClick={() => navigate('/login')}>{t('Back to sign in')}</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="lg rg">
      <AuthBrand />

      <div className="lg-panel rg-panel">
        <form className="lg-form rg-form" onSubmit={onSubmit} noValidate>
          <div className="lg-head">
            <span className="lg-kicker">{t('Join RepLiT · Pasay City')}</span>
            <h2 className="lg-title">{t('Request to join as an organization')}</h2>
            <p className="lg-sub">{t('Tell us who you are and what you bring to a fire. No account is needed to apply. If an admin accepts you, we email your sign-in.')}</p>
          </div>

          {/* Organisation ------------------------------------------------ */}
          <section className="rg-section">
            <h3 className="rg-section-title">{t('Organization')}</h3>

            <label className="lg-field">
              <Label required>{t('Organization name')}</Label>
              <input
                autoComplete="organization"
                placeholder={t('e.g. Barangay Fire Brigade')}
                maxLength={200}
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
              />
            </label>

            <div className="rg-pair">
              <label className="lg-field">
                <Label required>{t('Type of organization')}</Label>
                <select
                  className={agencyType ? '' : 'is-empty'}
                  value={agencyType}
                  onChange={(e) => setAgencyType(e.target.value)}
                >
                  <option value="" disabled>{t('Select type')}</option>
                  {AGENCY_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className="lg-field">
                <Label>{t('Phone number')}</Label>
                <input
                  type="tel"
                  autoComplete="tel"
                  placeholder="09XX XXX XXXX"
                  maxLength={40}
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </label>
            </div>

            <div className="rg-pair">
              <label className="lg-field">
                <Label required>{t('Your first name')}</Label>
                <input
                  autoComplete="given-name"
                  maxLength={60}
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                />
              </label>
              <label className="lg-field">
                <Label required>{t('Your surname')}</Label>
                <input
                  autoComplete="family-name"
                  maxLength={60}
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                />
              </label>
            </div>
            <p className="rg-hint">{t('You become your organization’s first Coordinator. Your sign-in is made from your name.')}</p>

            <label className="lg-field">
              <Label required>{t('Email')}</Label>
              <input
                type="email"
                autoComplete="email"
                placeholder="name@organization.ph"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <span className="rg-hint">{t('Your sign-in link goes here once you are approved.')}</span>
            </label>

            <label className="lg-field">
              <Label>{t('Address')}</Label>
              <input
                autoComplete="street-address"
                placeholder={t('Street, barangay, city')}
                maxLength={500}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
          </section>

          {/* SEC certificate --------------------------------------------- */}
          <section className="rg-section">
            <h3 className="rg-section-title">{t('SEC certificate')}</h3>
            <div className="lg-field">
              <Label required>{t('Certificate of registration')}</Label>
              <button
                type="button"
                className={`rg-upload${secFile ? ' has-file' : ''}`}
                onClick={() => fileRef.current?.click()}
              >
                <span className="rg-upload-icon"><UploadIcon /></span>
                <span className="rg-upload-text">
                  <span className="rg-upload-name">
                    {secFile ? secFile.name : t('Choose a PDF or an image')}
                  </span>
                  <span className="rg-upload-meta">
                    {secFile ? t('{megabytes} · Click to replace', { megabytes: megabytes(secFile.size) }) : t('Up to 10 MB')}
                  </span>
                </span>
              </button>
              <input ref={fileRef} type="file" accept=".pdf,image/*" hidden onChange={onFile} />
              <span className="rg-hint">{t('Only the file’s name is sent for now. The hub will ask you for the certificate.')}</span>
            </div>
          </section>

          {/* Roster ------------------------------------------------------ */}
          <section className="rg-section">
            <div className="rg-section-head">
              <h3 className="rg-section-title">{t('Roster')}</h3>
              <button
                type="button"
                className="rg-add"
                disabled={roster.length >= MAX_ROSTER}
                onClick={() => setRoster((r) => [...r, { full_name: '', role: '' }])}
              >{t('+ Add member')}</button>
            </div>
            <p className="rg-hint">{t('Everyone who would respond under your organization.')}</p>
            <div className="rg-rows">
              {roster.map((m, i) => (
                <div className="rg-row" key={i}>
                  <span className="rg-row-n">{i + 1}</span>
                  <div className="lg-field">
                    <input
                      aria-label={t('Member {n} full name', { n: i + 1 })}
                      placeholder={t('Full name')}
                      maxLength={200}
                      value={m.full_name}
                      onChange={(e) => setMember(i, 'full_name', e.target.value)}
                    />
                  </div>
                  <div className="lg-field">
                    <input
                      aria-label={t('Member {n} role', { n: i + 1 })}
                      placeholder={t('Role, e.g. Driver')}
                      maxLength={120}
                      value={m.role}
                      onChange={(e) => setMember(i, 'role', e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="rg-remove"
                    aria-label={t('Remove member {n}', { n: i + 1 })}
                    disabled={roster.length === 1}
                    onClick={() => setRoster((r) => r.filter((_, idx) => idx !== i))}
                  >
                    <RemoveIcon />
                  </button>
                </div>
              ))}
            </div>
          </section>

          {/* Equipment --------------------------------------------------- */}
          <section className="rg-section">
            <div className="rg-section-head">
              <h3 className="rg-section-title">{t('Equipment')}</h3>
              <button
                type="button"
                className="rg-add"
                disabled={equipment.length >= MAX_EQUIPMENT}
                onClick={() => setEquipment((e) => [...e, { name: '', type: '' }])}
              >{t('+ Add unit')}</button>
            </div>
            <p className="rg-hint">{t('Trucks, tankers and vehicles you can send to a fire.')}</p>
            <div className="rg-rows">
              {equipment.map((u, i) => (
                <div className="rg-row" key={i}>
                  <span className="rg-row-n">{i + 1}</span>
                  <div className="lg-field">
                    <input
                      aria-label={t('Unit {n} name', { n: i + 1 })}
                      placeholder={t('Name or plate, e.g. Engine 1')}
                      maxLength={200}
                      value={u.name}
                      onChange={(e) => setUnit(i, 'name', e.target.value)}
                    />
                  </div>
                  <div className="lg-field">
                    <select
                      aria-label={t('Unit {n} type', { n: i + 1 })}
                      className={u.type ? '' : 'is-empty'}
                      value={u.type}
                      onChange={(e) => setUnit(i, 'type', e.target.value)}
                    >
                      <option value="" disabled>{t('Select type')}</option>
                      {EQUIPMENT_TYPES.map((type) => (
                        <option key={type} value={type}>{equipmentLabel(type)}</option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="button"
                    className="rg-remove"
                    aria-label={t('Remove unit {n}', { n: i + 1 })}
                    disabled={equipment.length === 1}
                    onClick={() => setEquipment((e) => e.filter((_, idx) => idx !== i))}
                  >
                    <RemoveIcon />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <label className="rg-terms">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>{t('I agree to the Terms and Agreements and acknowledge the privacy policy on sensitive emergency data.')}</span>
          </label>
          <a className="lg-link" href="https://reportwhatslit-app.vercel.app/privacy" target="_blank" rel="noopener">{t('Read the privacy policy')}</a>

          {error && <div className="lg-error" role="alert">{error}</div>}

          <button type="submit" className="lg-submit" disabled={busy}>
            {busy ? t('Submitting…') : t('Submit application')}
          </button>

          <div className="lg-affiliate">{t('Already affiliated?')}{' '}
            <button type="button" className="lg-link" onClick={() => navigate('/login')}>{t('Sign in')}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
