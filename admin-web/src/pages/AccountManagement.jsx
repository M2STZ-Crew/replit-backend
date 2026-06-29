import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';

// Agency filter tabs.
const TABS = [
  { key: 'all', label: 'All' },
  { key: 'fire_volunteer', label: 'Fire Volunteer' },
  { key: 'bfp', label: 'BFP' },
  { key: 'barangay', label: 'Barangay' },
  { key: 'medical', label: 'Medical' },
  { key: 'police', label: 'Police' },
];

const AGENCY = {
  fire_volunteer: { label: 'Fire Volunteer', color: '#FF9066' },
  bfp: { label: 'BFP', color: '#FF9066' },
  barangay: { label: 'Barangay', color: '#CFCFCF' },
  medical: { label: 'Medical', color: '#CFCFCF' },
  police: { label: 'Police', color: '#CFCFCF' },
};

const STATUS = {
  pending: { label: 'Pending', color: '#FF9066' },
  approved: { label: 'Approved', color: '#22C55E' },
  rejected: { label: 'Rejected', color: '#FF544E' },
};

function agencyOf(t) {
  return AGENCY[t] || { label: prettify(t), color: '#767575' };
}

function statusOf(s) {
  return STATUS[s] || { label: prettify(s), color: '#767575' };
}

function prettify(s) {
  if (!s) return '—';
  return String(s)
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function initialOf(name) {
  const n = (name || '').trim();
  return n ? n[0].toUpperCase() : '?';
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return '—';
  }
}

function shortId(id) {
  return id ? `#${String(id).slice(0, 8)}` : '';
}

function fileExt(name) {
  const m = /\.([a-z0-9]+)$/i.exec(name || '');
  return m ? m[1].toUpperCase() : 'File';
}

function detailsOf(r) {
  const d = r.details || {};
  return {
    roster: Array.isArray(d.roster) ? d.roster : [],
    equipment: Array.isArray(d.equipment) ? d.equipment : [],
    sec: d.sec_certificate_name || null,
  };
}

export default function AccountManagement({ query = '' }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('all');
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState(null); // `${id}:${action}`
  const [toast, setToast] = useState(null);

  async function load() {
    setLoading(true);
    setError('');
    try {
      const rows = await api.affiliates(''); // all statuses
      setItems(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setError(e.message || 'Failed to load requests.');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function flash(msg, kind = 'ok') {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3200);
  }

  const stats = useMemo(() => {
    let pending = 0;
    let accepted = 0;
    for (const r of items) {
      if (r.status === 'pending') pending += 1;
      else if (r.status === 'approved') accepted += 1;
    }
    return { pending, accepted, total: items.length };
  }, [items]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    return items.filter((r) => {
      if (tab !== 'all' && r.agency_type !== tab) return false;
      if (term && !(r.organization_name || '').toLowerCase().includes(term)) return false;
      return true;
    });
  }, [items, tab, query]);

  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !filtered.some((r) => r.id === selectedId)) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  const selected = useMemo(
    () => items.find((r) => r.id === selectedId) || null,
    [items, selectedId],
  );

  async function review(id, action) {
    setBusy(`${id}:${action}`);
    try {
      if (action === 'accept') {
        const res = await api.affiliateAccept(id, '');
        const em = res?.account_email;
        if (res?.invite_email_sent) {
          flash(`Approved — sub-admin account created. Setup email sent to ${em}.`);
        } else if (res?.account_provisioned) {
          flash(
            `Approved & account ready${em ? ` for ${em}` : ''}, but the setup email failed to send.`,
            'err',
          );
        } else {
          flash(`Approved — organization created.${res?.detail ? ` ${res.detail}` : ''}`, 'err');
        }
      } else {
        await api.affiliateReject(id, '');
        flash('Request rejected.');
      }
      await load();
    } catch (e) {
      flash(e.message || 'Action failed.', 'err');
    } finally {
      setBusy(null);
    }
  }

  const STAT_CARDS = [
    { key: 'pending', label: 'Pending', sub: 'Awaiting your review', icon: '⏳', tint: 'rgba(255,144,102,0.10)' },
    { key: 'accepted', label: 'Accepted', sub: 'Affiliated organizations', icon: '✅', tint: 'rgba(207,207,207,0.10)' },
    { key: 'total', label: 'Total requests', sub: 'All-time', icon: '📊', tint: 'rgba(255,144,102,0.10)' },
  ];

  const sel = selected ? detailsOf(selected) : null;
  const selBusy = selected && busy && busy.startsWith(`${selected.id}:`);

  return (
    <div className="acct-wrap">
      <div className="acct-stats">
        {STAT_CARDS.map((c) => (
          <div className="acct-stat" key={c.key}>
            <div className="acct-stat-icon" style={{ background: c.tint }}>
              {c.icon}
            </div>
            <div className="acct-stat-texts">
              <div className="acct-stat-value">{stats[c.key]}</div>
              <div className="acct-stat-label">{c.label}</div>
              <div className="acct-stat-sub">{c.sub}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="acct-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`acct-tab${tab === t.key ? ' active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="acct-cols">
        {/* list */}
        <section className="acct-listpanel">
          <div className="acct-panel-head">
            <div className="acct-panel-title">Affiliate requests</div>
            <div className="acct-panel-sub">
              {loading ? 'Loading…' : `${filtered.length} organization${filtered.length === 1 ? '' : 's'}`}
            </div>
          </div>
          <div className="acct-list">
            {error && <div className="acct-empty">{error}</div>}
            {!loading && !error && filtered.length === 0 && (
              <div className="acct-empty">No requests in this category.</div>
            )}
            {filtered.map((r) => {
              const ag = agencyOf(r.agency_type);
              const st = statusOf(r.status);
              const d = detailsOf(r);
              const active = r.id === selectedId;
              return (
                <button
                  key={r.id}
                  className={`acct-card${active ? ' active' : ''}`}
                  onClick={() => setSelectedId(r.id)}
                >
                  <span
                    className="acct-card-icon"
                    style={{ background: `${ag.color}22`, color: ag.color }}
                  >
                    🏢
                  </span>
                  <span className="acct-card-body">
                    <span className="acct-card-name">{r.organization_name}</span>
                    <span className="acct-card-sub">
                      {d.roster.length} personnel · {d.equipment.length} units
                    </span>
                    <span className="acct-badges">
                      <span
                        className="acct-badge"
                        style={{
                          color: ag.color,
                          borderColor: `${ag.color}48`,
                          background: `${ag.color}1f`,
                        }}
                      >
                        {ag.label}
                      </span>
                      <span
                        className="acct-badge"
                        style={{
                          color: st.color,
                          borderColor: `${st.color}48`,
                          background: `${st.color}1f`,
                        }}
                      >
                        {st.label}
                      </span>
                      {d.sec ? (
                        <span className="acct-badge muted">SEC Submitted</span>
                      ) : (
                        <span
                          className="acct-badge"
                          style={{
                            color: '#FF544E',
                            borderColor: 'rgba(255,84,78,0.28)',
                            background: 'rgba(255,84,78,0.12)',
                          }}
                        >
                          SEC Missing
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* detail */}
        <section className="acct-detailpanel">
          {!selected ? (
            <div className="acct-detail-empty">
              {loading ? 'Loading…' : 'Select a request to review.'}
            </div>
          ) : (
            <>
              <div className="acct-detail-head">
                <div>
                  <div className="acct-detail-title">{selected.organization_name}</div>
                  <div className="acct-detail-sub">
                    {agencyOf(selected.agency_type).label} · Submitted{' '}
                    {fmtDate(selected.created_at)} · Request {shortId(selected.id)}
                  </div>
                </div>
                <span
                  className="acct-detail-icon"
                  style={{
                    background: `${agencyOf(selected.agency_type).color}22`,
                    color: agencyOf(selected.agency_type).color,
                  }}
                >
                  🏢
                </span>
              </div>

              <div className="acct-detail-body">
                {/* primary contact */}
                <div className="acct-section">
                  <div className="acct-section-title">Primary contact</div>
                  <div className="acct-fields">
                    <div className="acct-field">
                      <div className="acct-field-l">Contact person</div>
                      <div className="acct-field-v">{selected.contact_name || '—'}</div>
                    </div>
                    <div className="acct-field">
                      <div className="acct-field-l">Email</div>
                      <div className="acct-field-v">{selected.contact_email || '—'}</div>
                    </div>
                    <div className="acct-field">
                      <div className="acct-field-l">Phone</div>
                      <div className="acct-field-v">{selected.contact_phone || '—'}</div>
                    </div>
                    <div className="acct-field">
                      <div className="acct-field-l">Address</div>
                      <div className="acct-field-v">{selected.address || '—'}</div>
                    </div>
                  </div>
                </div>

                {/* SEC certificate */}
                <div className="acct-section">
                  <div className="acct-section-row">
                    <div className="acct-section-title">SEC Certificate</div>
                    {sel.sec ? (
                      <span className="acct-pill muted">Submitted</span>
                    ) : (
                      <span
                        className="acct-pill"
                        style={{
                          color: '#FF544E',
                          borderColor: 'rgba(255,84,78,0.28)',
                          background: 'rgba(255,84,78,0.12)',
                        }}
                      >
                        Required
                      </span>
                    )}
                  </div>
                  {sel.sec ? (
                    <>
                      <div className="acct-file">
                        <span className="acct-file-icon">📄</span>
                        <div className="acct-file-texts">
                          <div className="acct-file-name">{sel.sec}</div>
                          <div className="acct-file-sub">
                            Filename on record — file upload not yet wired
                          </div>
                        </div>
                      </div>
                      <div className="acct-fields">
                        <div className="acct-subcard">
                          <div className="acct-subcard-l">File type</div>
                          <div className="acct-subcard-v">{fileExt(sel.sec)}</div>
                        </div>
                        <div className="acct-subcard">
                          <div className="acct-subcard-l">Stored file</div>
                          <div className="acct-subcard-v">Not uploaded</div>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="acct-empty acct-empty-left">
                      No SEC certificate was declared on this request.
                    </div>
                  )}
                </div>

                {/* roster */}
                <div className="acct-section">
                  <div className="acct-section-row">
                    <div className="acct-section-title">Declared roster</div>
                    <div className="acct-section-count">{sel.roster.length} personnel</div>
                  </div>
                  {sel.roster.length === 0 ? (
                    <div className="acct-empty acct-empty-left">No roster declared.</div>
                  ) : (
                    <div className="acct-grid2">
                      {sel.roster.map((m, i) => (
                        <div className="acct-member" key={i}>
                          <span
                            className="acct-avatar"
                            style={{
                              background: `${agencyOf(selected.agency_type).color}22`,
                              color: agencyOf(selected.agency_type).color,
                            }}
                          >
                            {initialOf(m.full_name)}
                          </span>
                          <div className="acct-member-texts">
                            <div className="acct-member-name">{m.full_name || 'Unnamed'}</div>
                            <div className="acct-member-role">{m.role || '—'}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* equipment */}
                <div className="acct-section">
                  <div className="acct-section-row">
                    <div className="acct-section-title">Declared equipment</div>
                    <div className="acct-section-count">{sel.equipment.length} units</div>
                  </div>
                  {sel.equipment.length === 0 ? (
                    <div className="acct-empty acct-empty-left">No equipment declared.</div>
                  ) : (
                    <div className="acct-grid2">
                      {sel.equipment.map((e, i) => (
                        <div className="acct-eq" key={i}>
                          <div className="acct-eq-top">
                            <span className="acct-eq-name">{e.name}</span>
                            <span className="acct-pill orange">Declared</span>
                          </div>
                          <div className="acct-eq-sub">{e.type || 'Equipment'}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {selected.status !== 'pending' && (
                  <div className="acct-reviewed">
                    <span
                      className="acct-pill"
                      style={{
                        color: statusOf(selected.status).color,
                        borderColor: `${statusOf(selected.status).color}48`,
                        background: `${statusOf(selected.status).color}1f`,
                      }}
                    >
                      {statusOf(selected.status).label}
                    </span>
                    {selected.status === 'approved' && selected.organization_id && (
                      <span className="acct-reviewed-note">Organization created ✓</span>
                    )}
                    {selected.review_notes && (
                      <span className="acct-reviewed-note">“{selected.review_notes}”</span>
                    )}
                  </div>
                )}
              </div>

              {selected.status === 'pending' && (
                <div className="acct-actions">
                  <div className="acct-foot-note">
                    Accepting creates a sub-admin login
                    {selected.contact_email ? ` on ${selected.contact_email}` : ''} and emails a
                    password-setup link for the mobile dashboard.
                  </div>
                  <div className="acct-btn-row">
                    <button
                      className="acct-accept"
                      disabled={selBusy}
                      onClick={() => review(selected.id, 'accept')}
                    >
                      {busy === `${selected.id}:accept` ? 'Accepting…' : '✓ Accept organization'}
                    </button>
                    <button
                      className="acct-reject"
                      disabled={selBusy}
                      onClick={() => review(selected.id, 'reject')}
                    >
                      {busy === `${selected.id}:reject` ? 'Rejecting…' : '✕ Reject'}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {toast && (
        <div className={`acct-toast${toast.kind === 'err' ? ' err' : ''}`}>{toast.msg}</div>
      )}
    </div>
  );
}
