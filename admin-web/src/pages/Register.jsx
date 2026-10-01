import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client.js';

const AGENCY_TYPES = [
  { value: 'fire_volunteer', label: 'Fire Volunteer' },
  { value: 'bfp', label: 'Bureau of Fire Protection (BFP)' },
  { value: 'barangay', label: 'Barangay' },
  { value: 'medical', label: 'Medical' },
  { value: 'police', label: 'Police' },
];

const EQUIPMENT_TYPES = ['Fire Truck', 'Water Tanker', 'Ambulance', 'Rescue Vehicle', 'Other'];
const MAX_FILE_BYTES = 10 * 1024 * 1024;

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
      {required && <span className="rg-req">Required</span>}
    </span>
  );
}

/// The identity panel, shared by the form and the "received" screen. Hidden
/// below 900px with the sign-in screen's, so a phone gets straight to the form.
function Brand() {
  return (
    <aside className="lg-brand rg-brand">
      <div className="lg-ember" aria-hidden="true" />
      <div className="lg-grid" aria-hidden="true" />

      <div className="lg-mark">
        <img src="/assets/logo-mark.png" alt="" width="44" height="44" />
        <div className="lg-mark-text">
          <span className="lg-wordmark">RepLiT</span>
          <span className="lg-tagline">Fire Response Network</span>
        </div>
      </div>

      <div className="lg-pitch">
        <div className="lg-pill">
          <span className="lg-pill-dot" />
          <span>Affiliate application</span>
        </div>
        <h1 className="lg-headline">
          Join the<br />response<br />network.
        </h1>
        <p className="lg-lede">
          Fire brigades, BFP stations, police, medical and barangay teams apply
          here. An admin reviews every application before any account is made.
        </p>

        <ol className="rg-steps">
          <li>
            <span className="rg-step-n">1</span>
            <span className="rg-step-text">
              <strong>Apply</strong>
              Your organisation, its roster and equipment, and its SEC certificate.
            </span>
          </li>
          <li>
            <span className="rg-step-n">2</span>
            <span className="rg-step-text">
              <strong>Review</strong>
              A confirmation email arrives now. An admin then checks the application.
            </span>
          </li>
          <li>
            <span className="rg-step-n">3</span>
            <span className="rg-step-text">
              <strong>Sign in</strong>
              Once approved, a second email lets you set your password.
            </span>
          </li>
        </ol>
      </div>

      <div className="lg-foot">Republic of the Philippines · NCR · City of Pasay</div>
    </aside>
  );
}

export default function Register() {
  const navigate = useNavigate();
  const fileRef = useRef(null);

  const [orgName, setOrgName] = useState('');
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
      setError('The SEC certificate must be 10 MB or smaller.');
      return;
    }
    setError(null);
    setSecFile(f);
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    if (!orgName.trim()) return setError('Enter your organisation’s name.');
    if (!agencyType) return setError('Choose the type of organisation.');
    if (!email.trim()) return setError('Enter the email we should reply to.');
    if (!secFile) return setError('Attach your SEC certificate.');
    if (!agree) return setError('Agree to the Terms and Agreements to submit.');

    setBusy(true);
    setError(null);
    try {
      await api.registerAffiliate({
        organization_name: orgName.trim(),
        agency_type: agencyType,
        contact_email: email.trim(),
        contact_phone: phone.trim() || null,
        address: address.trim() || null,
        roster: roster
          .filter((m) => m.full_name.trim())
          .map((m) => ({ full_name: m.full_name.trim(), role: m.role.trim() || null })),
        equipment: equipment
          .filter((u) => u.name.trim())
          .map((u) => ({ name: u.name.trim(), type: u.type || null })),
        sec_certificate_name: secFile.name,
      });
      setDone(true);
    } catch (err) {
      setError(err.message || 'The application could not be sent. Try again.');
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="lg rg">
        <Brand />
        <div className="lg-panel rg-panel is-done">
          <div className="lg-form rg-done">
            <div className="lg-head">
              <span className="lg-kicker">Application received</span>
              <h2 className="lg-title">Thank you</h2>
              <p className="lg-sub">
                {orgName.trim()} is now in the admin’s review queue.
              </p>
            </div>

            <div className="lg-note rg-done-note">
              <MailIcon />
              <span>
                A confirmation is on its way to <strong>{email.trim()}</strong>. Once an
                admin approves the application, a second email there will have a link
                to set your password. Check your spam folder if either is not in
                your inbox.
              </span>
            </div>

            <button type="button" className="lg-submit" onClick={() => navigate('/login')}>
              Back to sign in
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="lg rg">
      <Brand />

      <div className="lg-panel rg-panel">
        <form className="lg-form rg-form" onSubmit={onSubmit} noValidate>
          <div className="lg-head">
            <span className="lg-kicker">Affiliate registration</span>
            <h2 className="lg-title">Apply to join</h2>
            <p className="lg-sub">
              Tell us who you are and what you bring to a fire. No account is needed
              to apply; we email you once an admin has decided.
            </p>
          </div>

          {/* Organisation ------------------------------------------------ */}
          <section className="rg-section">
            <h3 className="rg-section-title">Organisation</h3>

            <label className="lg-field">
              <Label required>Organisation name</Label>
              <input
                autoComplete="organization"
                placeholder="e.g. Barangay 76 Fire Brigade"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
              />
            </label>

            <div className="rg-pair">
              <label className="lg-field">
                <Label required>Type of organisation</Label>
                <select
                  className={agencyType ? '' : 'is-empty'}
                  value={agencyType}
                  onChange={(e) => setAgencyType(e.target.value)}
                >
                  <option value="" disabled>Select type</option>
                  {AGENCY_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className="lg-field">
                <Label>Phone number</Label>
                <input
                  type="tel"
                  autoComplete="tel"
                  placeholder="09XX XXX XXXX"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </label>
            </div>

            <label className="lg-field">
              <Label required>Email</Label>
              <input
                type="email"
                autoComplete="email"
                placeholder="name@organisation.ph"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <span className="rg-hint">
                Your sign-in link goes here once you are approved.
              </span>
            </label>

            <label className="lg-field">
              <Label>Address</Label>
              <input
                autoComplete="street-address"
                placeholder="Street, barangay, city"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
          </section>

          {/* SEC certificate --------------------------------------------- */}
          <section className="rg-section">
            <h3 className="rg-section-title">SEC certificate</h3>
            <div className="lg-field">
              <Label required>Certificate of registration</Label>
              <button
                type="button"
                className={`rg-upload${secFile ? ' has-file' : ''}`}
                onClick={() => fileRef.current?.click()}
              >
                <span className="rg-upload-icon"><UploadIcon /></span>
                <span className="rg-upload-text">
                  <span className="rg-upload-name">
                    {secFile ? secFile.name : 'Upload a PDF or an image'}
                  </span>
                  <span className="rg-upload-meta">
                    {secFile ? `${megabytes(secFile.size)} · Click to replace` : 'Up to 10 MB'}
                  </span>
                </span>
              </button>
              <input ref={fileRef} type="file" accept=".pdf,image/*" hidden onChange={onFile} />
            </div>
          </section>

          {/* Roster ------------------------------------------------------ */}
          <section className="rg-section">
            <div className="rg-section-head">
              <h3 className="rg-section-title">Roster</h3>
              <button
                type="button"
                className="rg-add"
                onClick={() => setRoster((r) => [...r, { full_name: '', role: '' }])}
              >
                + Add member
              </button>
            </div>
            <p className="rg-hint">Everyone who would respond under your organisation.</p>
            <div className="rg-rows">
              {roster.map((m, i) => (
                <div className="rg-row" key={i}>
                  <span className="rg-row-n">{i + 1}</span>
                  <div className="lg-field">
                    <input
                      aria-label={`Member ${i + 1} full name`}
                      placeholder="Full name"
                      value={m.full_name}
                      onChange={(e) => setMember(i, 'full_name', e.target.value)}
                    />
                  </div>
                  <div className="lg-field">
                    <input
                      aria-label={`Member ${i + 1} role`}
                      placeholder="Role, e.g. Driver"
                      value={m.role}
                      onChange={(e) => setMember(i, 'role', e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="rg-remove"
                    aria-label={`Remove member ${i + 1}`}
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
              <h3 className="rg-section-title">Equipment</h3>
              <button
                type="button"
                className="rg-add"
                onClick={() => setEquipment((e) => [...e, { name: '', type: '' }])}
              >
                + Add unit
              </button>
            </div>
            <p className="rg-hint">Trucks, tankers and vehicles you can send to a fire.</p>
            <div className="rg-rows">
              {equipment.map((u, i) => (
                <div className="rg-row" key={i}>
                  <span className="rg-row-n">{i + 1}</span>
                  <div className="lg-field">
                    <input
                      aria-label={`Unit ${i + 1} name`}
                      placeholder="Name or plate, e.g. Engine 1"
                      value={u.name}
                      onChange={(e) => setUnit(i, 'name', e.target.value)}
                    />
                  </div>
                  <div className="lg-field">
                    <select
                      aria-label={`Unit ${i + 1} type`}
                      className={u.type ? '' : 'is-empty'}
                      value={u.type}
                      onChange={(e) => setUnit(i, 'type', e.target.value)}
                    >
                      <option value="" disabled>Select type</option>
                      {EQUIPMENT_TYPES.map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="button"
                    className="rg-remove"
                    aria-label={`Remove unit ${i + 1}`}
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
            <span>
              I agree to the Terms and Agreements and acknowledge the privacy policy
              on sensitive emergency data.
            </span>
          </label>

          {error && <div className="lg-error" role="alert">{error}</div>}

          <button type="submit" className="lg-submit" disabled={busy}>
            {busy ? 'Submitting…' : 'Submit application'}
          </button>

          <div className="lg-affiliate">
            Already affiliated?{' '}
            <button type="button" className="lg-link" onClick={() => navigate('/login')}>
              Sign in
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
