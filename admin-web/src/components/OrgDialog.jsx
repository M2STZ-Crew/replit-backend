import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { api } from '../api/client.js';
import { agencyAuthority, agencyLabel } from '../auth.jsx';

const ROLE = {
  admin: 'Admin',
  sub_admin: 'Sub-Admin',
  response_team: 'Response Team',
  general_user: 'Member',
};

const EQ_STATUS = {
  available: { label: 'Ready', tone: 'ok' },
  in_use: { label: 'Deployed', tone: 'accent' },
  maintenance: { label: 'Maintenance', tone: 'warn' },
  out_of_service: { label: 'Out of service', tone: 'off' },
};

const FOCUSABLE = 'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function prettify(s) {
  if (!s) return '—';
  return String(s).split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

function day(iso) {
  return iso
    ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : '—';
}

function stamp(iso) {
  return iso
    ? new Date(iso).toLocaleString(undefined, {
      day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
    })
    : '—';
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.2" strokeLinecap="round">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/// One label/value line. Empty values read as a dash, never a blank gap.
function Fact({ k, children }) {
  return (
    <div className="od-fact">
      <dt>{k}</dt>
      <dd>{children || '—'}</dd>
    </div>
  );
}

/* An accredited organisation, opened from the Affiliates table.
 *
 * Three sources make up the picture: the organisation row itself (from the
 * table), the affiliation application that created it, if there was one, and
 * the people and equipment registered to it now. Organisations made by a seed
 * script or by hand have no application, which the dialog says rather than
 * showing an empty section.
 *
 * It behaves as a dialog: focus moves in, Tab stays inside, Escape or the
 * backdrop closes it, and focus returns to the row that opened it. It renders
 * into <body> so the console's bottom bar cannot sit on top of it. */
export default function OrgDialog({ org, application, glyph, color, onClose }) {
  const panel = useRef(null);
  // Read through a ref so a parent that passes a fresh function each render
  // does not re-run the focus effect below and steal focus back to Close.
  const close = useRef(onClose);
  close.current = onClose;
  const [personnel, setPersonnel] = useState(null);
  const [equipment, setEquipment] = useState(null);

  useEffect(() => {
    let alive = true;
    setPersonnel(null);
    setEquipment(null);
    api.orgPersonnel(org.id).catch(() => []).then((p) => alive && setPersonnel(p ?? []));
    api.orgEquipment(org.id).catch(() => []).then((e) => alive && setEquipment(e ?? []));
    return () => { alive = false; };
  }, [org.id]);

  useEffect(() => {
    const opener = document.activeElement;
    const node = panel.current;
    node?.querySelector('.od-close')?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKey(e) {
      if (e.key === 'Escape') {
        close.current();
        return;
      }
      if (e.key !== 'Tab' || !node) return;
      const items = [...node.querySelectorAll(FOCUSABLE)];
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      opener?.focus?.();
    };
  }, []);

  const auth = agencyAuthority(org.agency_type);
  const app = application;
  const details = app?.details ?? {};
  const declaredRoster = Array.isArray(details.roster) ? details.roster : [];
  const declaredUnits = Array.isArray(details.equipment) ? details.equipment : [];

  // The organisation row is what an approval copied across; the application
  // keeps what was typed, including the address the row does not carry.
  const contactEmail = org.contact_email || app?.contact_email;
  const contactPhone = org.contact_phone || app?.contact_phone;
  const address = org.address || app?.address;

  const titleId = `od-title-${org.id}`;

  return createPortal(
    <div className="od-layer">
      <div className="od-scrim" onClick={onClose} aria-hidden="true" />
      <div
        className="od"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panel}
      >
        {/* Identity ------------------------------------------------------- */}
        <header className="od-head">
          <span className="od-chip" style={{ background: `${color}1f` }}>
            <img src={`/assets/${glyph}.png`} alt="" width="22" height="22" />
          </span>
          <div className="od-id">
            <span className="dc-eyebrow">{agencyLabel(org.agency_type)}</span>
            <h2 className="od-title" id={titleId}>{org.name}</h2>
            <div className="od-tags">
              <span className="ar-tag" style={{ color: auth.color, background: `${auth.color}1f` }}>
                {auth.label}
              </span>
              <span className={`af-status${org.is_active ? ' is-on' : ''}`}>
                <span className="af-status-dot" />
                {org.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>
          <button type="button" className="od-close" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </header>

        <div className="od-body">
          {/* Key figures -------------------------------------------------- */}
          <dl className="od-band">
            <div>
              <dt className="dc-eyebrow">Personnel</dt>
              <dd>{org.personnel_count ?? 0}</dd>
            </div>
            <div>
              <dt className="dc-eyebrow">Units</dt>
              <dd>{org.equipment_count ?? 0}</dd>
            </div>
            <div>
              <dt className="dc-eyebrow">Accredited</dt>
              <dd className="od-band-date">{day(app?.reviewed_at || org.created_at)}</dd>
            </div>
            <div>
              <dt className="dc-eyebrow">Applied</dt>
              <dd className="od-band-date">{app ? day(app.created_at) : '—'}</dd>
            </div>
          </dl>

          {org.description && <p className="od-desc">{org.description}</p>}

          {/* Contact ------------------------------------------------------ */}
          <section className="od-section">
            <h3 className="od-section-title">Contact</h3>
            <dl className="od-facts">
              <Fact k="Contact person">{app?.contact_name}</Fact>
              <Fact k="Email">
                {contactEmail && <a href={`mailto:${contactEmail}`}>{contactEmail}</a>}
              </Fact>
              <Fact k="Phone">
                {contactPhone && <a href={`tel:${contactPhone.replace(/\s+/g, '')}`}>{contactPhone}</a>}
              </Fact>
              <Fact k="Address">{address}</Fact>
            </dl>
          </section>

          {/* On RepLiT now ------------------------------------------------- */}
          <div className="od-split">
            <section className="od-section">
              <div className="od-section-head">
                <h3 className="od-section-title">Personnel</h3>
                <span className="od-count">{personnel ? personnel.length : '·'}</span>
              </div>
              {personnel === null ? (
                <p className="od-empty">Loading…</p>
              ) : personnel.length === 0 ? (
                <p className="od-empty">No accounts belong to this organisation yet.</p>
              ) : (
                <ul className="od-list">
                  {personnel.map((m) => (
                    <li className="od-person" key={m.id}>
                      <span className="od-avatar" style={{ color, background: `${color}1f` }}>
                        {initials(m.full_name)}
                      </span>
                      <span className="od-person-text">
                        <span className="od-person-name">{m.full_name || 'Unnamed'}</span>
                        <span className="od-person-sub">{ROLE[m.role] ?? prettify(m.role)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="od-section">
              <div className="od-section-head">
                <h3 className="od-section-title">Equipment</h3>
                <span className="od-count">{equipment ? equipment.length : '·'}</span>
              </div>
              {equipment === null ? (
                <p className="od-empty">Loading…</p>
              ) : equipment.length === 0 ? (
                <p className="od-empty">No equipment registered yet.</p>
              ) : (
                <ul className="od-list">
                  {equipment.map((e) => {
                    const st = EQ_STATUS[e.status] ?? { label: prettify(e.status), tone: 'off' };
                    const sub = [
                      e.category ? prettify(e.category) : 'Equipment',
                      e.quantity > 1 ? `× ${e.quantity}` : null,
                      e.capacity_liters ? `${Number(e.capacity_liters).toLocaleString()} L` : null,
                    ].filter(Boolean).join(' · ');
                    return (
                      <li className="od-unit" key={e.id}>
                        <span className="od-person-text">
                          <span className="od-person-name">{e.name}</span>
                          <span className="od-person-sub">{sub}</span>
                        </span>
                        <span className={`od-pill is-${st.tone}`}>{st.label}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>

          {/* Application -------------------------------------------------- */}
          <section className="od-section">
            <h3 className="od-section-title">Application</h3>
            {!app ? (
              <p className="od-empty">
                No application on file. This organisation was added directly rather than
                through the affiliation form.
              </p>
            ) : (
              <>
                <dl className="od-facts">
                  <Fact k="Submitted">{stamp(app.created_at)}</Fact>
                  <Fact k="Approved">{stamp(app.reviewed_at)}</Fact>
                  <Fact k="SEC certificate">{details.sec_certificate_name}</Fact>
                  {app.review_notes && <Fact k="Review notes">{app.review_notes}</Fact>}
                </dl>
                {app.message && <p className="od-quote">“{app.message}”</p>}

                <div className="od-split od-declared">
                  <div>
                    <span className="dc-eyebrow">Roster as submitted · {declaredRoster.length}</span>
                    {declaredRoster.length === 0 ? (
                      <p className="od-empty">None listed.</p>
                    ) : (
                      <ul className="od-plain">
                        {declaredRoster.map((m, i) => (
                          <li key={i}>
                            <span>{m.full_name}</span>
                            {m.role && <span className="od-plain-sub">{m.role}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <span className="dc-eyebrow">Equipment as submitted · {declaredUnits.length}</span>
                    {declaredUnits.length === 0 ? (
                      <p className="od-empty">None listed.</p>
                    ) : (
                      <ul className="od-plain">
                        {declaredUnits.map((u, i) => (
                          <li key={i}>
                            <span>{u.name}</span>
                            {u.type && <span className="od-plain-sub">{u.type}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}
