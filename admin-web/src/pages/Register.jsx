import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client.js';
import Logo from '../components/Logo.jsx';

const AGENCY_TYPES = [
  { value: 'fire_volunteer', label: 'Fire Volunteer' },
  { value: 'bfp', label: 'Bureau of Fire Protection (BFP)' },
  { value: 'barangay', label: 'Barangay' },
  { value: 'medical', label: 'Medical' },
  { value: 'police', label: 'Police' },
];

const EQUIPMENT_TYPES = ['Fire Truck', 'Water Tanker', 'Ambulance', 'Rescue Vehicle', 'Other'];
const MAX_FILE_BYTES = 10 * 1024 * 1024;

// The registration emblem: uses /register-icon.png if present, else an inline
// person-with-plus icon (orange).
function RegisterIcon() {
  const [ok, setOk] = useState(true);
  if (ok) {
    return (
      <img src="/register-icon.png" alt="" width="48" height="48" onError={() => setOk(false)} />
    );
  }
  return (
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#FF9066" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <line x1="19" y1="8" x2="19" y2="14" />
      <line x1="16" y1="11" x2="22" y2="11" />
    </svg>
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
    if (!f) return;
    if (f.size > MAX_FILE_BYTES) {
      setError('SEC certificate must be 10 MB or smaller.');
      return;
    }
    setError(null);
    setSecFile(f);
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    if (!orgName.trim()) return setError('Organization name is required.');
    if (!agencyType) return setError('Please choose the type of organization.');
    if (!email.trim()) return setError('Email is required.');
    if (!secFile) return setError('The SEC certificate is required.');
    if (!agree) return setError('Please agree to the Terms and privacy policy.');

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
      setError(err.message || 'Submission failed.');
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="reg-screen">
        <div className="reg-card reg-done">
          <RegisterIcon />
          <h1 className="reg-title">Application submitted</h1>
          <p className="muted">
            Your affiliation request has been received. Once an admin approves it, your
            login credentials will be sent to <strong>{email}</strong>.
          </p>
          <button className="btn-primary" onClick={() => navigate('/login')}>
            BACK TO LOGIN
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="reg-screen">
      <form className="reg-card" onSubmit={onSubmit}>
        <div className="reg-head">
          <RegisterIcon />
          <Logo height={48} />
        </div>
        <h1 className="reg-title">AFFILIATION FORM</h1>

        <label className="field-label">ORGANIZATION NAME</label>
        <input className="field" placeholder="Organization name" value={orgName}
               onChange={(e) => setOrgName(e.target.value)} />

        <div className="reg-row2">
          <div>
            <label className="field-label">TYPE OF ORGANIZATION</label>
            <select className={`field${agencyType ? '' : ' is-empty'}`} value={agencyType}
                    onChange={(e) => setAgencyType(e.target.value)}>
              <option value="" disabled>Select type</option>
              {AGENCY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">PHONE NUMBER</label>
            <input className="field" placeholder="Phone number" value={phone}
                   onChange={(e) => setPhone(e.target.value)} />
          </div>
        </div>

        <label className="field-label">EMAIL</label>
        <input className="field" type="email" placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)} />
        <div className="reg-hint">Username and password will be sent to this email</div>

        <label className="field-label">ADDRESS</label>
        <input className="field" placeholder="Address" value={address}
               onChange={(e) => setAddress(e.target.value)} />

        <div className="reg-label-row">
          <label className="field-label">SEC CERTIFICATE</label>
          <span className="reg-required">REQUIRED</span>
        </div>
        <button type="button" className="reg-upload" onClick={() => fileRef.current?.click()}>
          <span className="reg-upload-left">
            <span className="reg-upload-icon">⬆</span>
            {secFile ? secFile.name : 'Upload PDF or image'}
          </span>
          <span className="reg-upload-max">Max 10 MB</span>
        </button>
        <input ref={fileRef} type="file" accept=".pdf,image/*" hidden onChange={onFile} />

        <div className="reg-label-row">
          <label className="field-label">FULL ROSTER</label>
          <button type="button" className="reg-add"
                  onClick={() => setRoster((r) => [...r, { full_name: '', role: '' }])}>
            + ADD
          </button>
        </div>
        {roster.map((m, i) => (
          <div className="reg-subcard" key={i}>
            <div className="reg-subcard-head">MEMBER {i + 1}</div>
            <div className="reg-row2">
              <input className="field" placeholder="Full name" value={m.full_name}
                     onChange={(e) => setMember(i, 'full_name', e.target.value)} />
              <input className="field" placeholder="Role" value={m.role}
                     onChange={(e) => setMember(i, 'role', e.target.value)} />
            </div>
          </div>
        ))}

        <div className="reg-label-row">
          <label className="field-label">EQUIPMENT</label>
          <button type="button" className="reg-add"
                  onClick={() => setEquipment((e) => [...e, { name: '', type: '' }])}>
            + ADD
          </button>
        </div>
        {equipment.map((u, i) => (
          <div className="reg-subcard" key={i}>
            <div className="reg-subcard-head">UNIT {i + 1}</div>
            <div className="reg-row2">
              <input className="field" placeholder="Name" value={u.name}
                     onChange={(e) => setUnit(i, 'name', e.target.value)} />
              <select className={`field${u.type ? '' : ' is-empty'}`} value={u.type}
                      onChange={(e) => setUnit(i, 'type', e.target.value)}>
                <option value="" disabled>Select type</option>
                {EQUIPMENT_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
        ))}

        <label className="reg-terms">
          <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
          <span>
            I agree to the <span className="link">Terms and Agreements</span> and acknowledge
            the privacy policy regarding sensitive emergency data.
          </span>
        </label>

        {error && <div className="login-error">{error}</div>}

        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? 'SUBMITTING…' : 'SIGN UP'}
        </button>

        <div className="login-affiliate">
          Already affiliated? <span className="link" onClick={() => navigate('/login')}>Log in</span>
        </div>
      </form>
    </div>
  );
}
