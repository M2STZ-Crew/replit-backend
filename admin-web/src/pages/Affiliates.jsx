import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyAuthority, agencyLabel } from '../auth.jsx';
import OrgDialog from '../components/OrgDialog.jsx';

const GLYPH = {
  fire_volunteer: 'glyph-firefighter',
  bfp: 'glyph-fire',
  police: 'glyph-police',
  medical: 'glyph-hospital',
  barangay: 'glyph-people',
};

const SECTOR_COLOR = {
  fire_volunteer: '#FF9066',
  bfp: '#FF544E',
  police: '#6098D6',
  medical: '#22C55E',
  barangay: '#8a8a8a',
};

function when(iso, opts = { day: 'numeric', month: 'short', year: 'numeric' }) {
  return iso ? new Date(iso).toLocaleDateString(undefined, opts) : '—';
}

function ChevronIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

function ago(iso) {
  if (!iso) return '';
  const hrs = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (hrs < 1) return 'just now';
  if (hrs < 24) return `${Math.floor(hrs)}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/* Affiliate governance (Section 2.6 — Admin: organization management).
 *
 * The design's table carried an "Acceptance" percentage and Suspend/Revoke
 * buttons. There is no acceptance metric anywhere in the system and no endpoint
 * that changes an organisation's standing, so neither is shown — a button that
 * cannot work is worse than no button. Its application cards also had a
 * document-completion bar; affiliate_requests stores no documents, so the
 * contact details that are actually submitted are shown instead.
 *
 * An approved application leaves the queue, but what it said stays useful: a
 * row in the accredited table opens the organisation with its application,
 * matched on the organisation the approval created. */
export default function Affiliates() {
  const [orgs, setOrgs] = useState([]);
  const [requests, setRequests] = useState([]);
  const [approved, setApproved] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [rejecting, setRejecting] = useState(null);
  const [notes, setNotes] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, r, a] = await Promise.all([
        api.organizations().catch(() => []),
        api.affiliates('pending').catch(() => []),
        api.affiliates('approved').catch(() => []),
      ]);
      setOrgs(o);
      setRequests(r);
      setApproved(a);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function decide(id, action) {
    setBusyId(id);
    setError(null);
    try {
      if (action === 'accept') await api.affiliateAccept(id, '');
      else await api.affiliateReject(id, notes.trim());
      setRejecting(null);
      setNotes('');
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  }

  // The application that created each organisation, newest first so a
  // re-application would win over an older one.
  const applicationOf = useMemo(() => {
    const byOrg = new Map();
    for (const req of approved) {
      if (req.organization_id && !byOrg.has(req.organization_id)) {
        byOrg.set(req.organization_id, req);
      }
    }
    return byOrg;
  }, [approved]);

  const openOrg = orgs.find((o) => o.id === openId) ?? null;
  const closeOrg = useCallback(() => setOpenId(null), []);

  const stats = useMemo(() => {
    const personnel = orgs.reduce((n, o) => n + (o.personnel_count ?? 0), 0);
    const units = orgs.reduce((n, o) => n + (o.equipment_count ?? 0), 0);
    return [
      { k: 'Accredited', v: orgs.length, foot: 'Organisations on the network', color: 'var(--text)' },
      { k: 'Awaiting decision', v: requests.length, foot: 'Applications pending', color: requests.length ? 'var(--accent)' : 'var(--text)' },
      { k: 'Personnel', v: personnel, foot: 'Across all organisations', color: 'var(--text)' },
      { k: 'Units', v: units, foot: 'Equipment registered', color: 'var(--text)' },
    ];
  }, [orgs, requests]);

  return (
    <div className="ar">
      <div className="ar-stats">
        {stats.map((s) => (
          <section className="ar-stat" key={s.k}>
            <span className="dc-eyebrow">{s.k}</span>
            <span className="ar-stat-v" style={{ color: s.color }}>{loading ? '·' : s.v}</span>
            <span className="sb-kpi-foot">{s.foot}</span>
          </section>
        ))}
      </div>

      {error && <div className="vq-error">{error}</div>}

      {/* Applications ------------------------------------------------------ */}
      <section className="af-apps">
        <header className="af-apps-head">
          <span className="af-apps-dot" />
          <span className="sb-panel-title">Applications awaiting your decision</span>
          <span className="af-authority">Admin authority</span>
        </header>

        {requests.length === 0 ? (
          <p className="sb-empty">
            {loading ? 'Loading…' : 'No applications pending. New submissions appear here.'}
          </p>
        ) : (
          <div className="af-app-grid">
            {requests.map((r) => (
              <article className="af-app" key={r.id}>
                <div className="af-app-top">
                  <span className="ar-tag" style={{
                    color: SECTOR_COLOR[r.agency_type] ?? '#8a8a8a',
                    background: `${SECTOR_COLOR[r.agency_type] ?? '#8a8a8a'}1f`,
                  }}>
                    {agencyLabel(r.agency_type)}
                  </span>
                  <span className="af-app-when">{ago(r.created_at)}</span>
                </div>

                <div className="af-app-id">
                  <span className="af-app-name">{r.organization_name}</span>
                  <span className="sb-panel-sub">{r.address || 'No address given'}</span>
                </div>

                <dl className="af-app-facts">
                  <div><dt>Contact</dt><dd>{r.contact_name || '—'}</dd></div>
                  <div><dt>Email</dt><dd>{r.contact_email || '—'}</dd></div>
                  <div><dt>Phone</dt><dd>{r.contact_phone || '—'}</dd></div>
                </dl>

                {r.message && <p className="af-app-msg">“{r.message}”</p>}

                {rejecting === r.id ? (
                  <div className="af-app-actions">
                    <input
                      className="vq-reason"
                      placeholder="Reason for rejection"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      autoFocus
                    />
                    <button
                      className="vq-btn vq-btn-reject"
                      disabled={busyId === r.id || notes.trim().length === 0}
                      onClick={() => decide(r.id, 'reject')}
                    >
                      {busyId === r.id ? 'Rejecting…' : 'Confirm'}
                    </button>
                    <button className="vq-btn" onClick={() => { setRejecting(null); setNotes(''); }}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    {/* Approving is not just a status flip — it creates the
                        organisation and a sub-admin account for the contact. */}
                    <p className="af-app-effect">
                      Approving creates the organisation and a Sub-Admin account for the contact.
                    </p>
                    <div className="af-app-actions">
                      <button
                        className="vq-btn vq-btn-verify"
                        disabled={busyId === r.id}
                        onClick={() => decide(r.id, 'accept')}
                      >
                        {busyId === r.id ? 'Working…' : 'Approve'}
                      </button>
                      <button
                        className="vq-btn vq-btn-reject"
                        disabled={busyId === r.id}
                        onClick={() => { setRejecting(r.id); setNotes(''); }}
                      >
                        Reject
                      </button>
                    </div>
                  </>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Accredited organisations ------------------------------------------ */}
      <section className="ar-panel">
        <header className="ar-head">
          <div className="sb-map-title">
            <span className="sb-panel-title">Accredited organisations</span>
            <span className="sb-panel-sub">
              {orgs.length} on the network. Select one to see its contact details, people,
              equipment and the application it joined with. Fire Volunteer and BFP
              organisations coordinate the response; police, medical and barangay take part
              for situational awareness only.
            </span>
          </div>
        </header>

        <div className="ar-scroll">
          <div className="ar-cols af-cols">
            <span className="af-c-org">Organisation</span>
            <span className="af-c-sector">Sector</span>
            <span className="af-c-auth">Authority</span>
            <span className="af-c-num">Units</span>
            <span className="af-c-num">Personnel</span>
            <span className="af-c-status">Status</span>
            <span className="af-c-go" />
          </div>

          {!loading && orgs.length === 0 && (
            <p className="sb-empty" style={{ padding: '20px 22px' }}>
              No accredited organisations yet.
            </p>
          )}

          {orgs.map((o) => {
            const auth = agencyAuthority(o.agency_type);
            return (
            <button
              type="button"
              className="ar-row af-cols af-row"
              key={o.id}
              onClick={() => setOpenId(o.id)}
              aria-haspopup="dialog"
              aria-label={`${o.name}: view details`}
            >
              <div className="af-c-org af-org">
                <span className="af-org-chip" style={{ background: `${SECTOR_COLOR[o.agency_type] ?? '#8a8a8a'}1f` }}>
                  <img src={`/assets/${GLYPH[o.agency_type] ?? 'glyph-people'}.png`} alt="" width="15" height="15" />
                </span>
                <div className="af-org-text">
                  <span className="af-org-name">{o.name}</span>
                  <span className="ar-actor-sub">
                    Accredited {when(applicationOf.get(o.id)?.reviewed_at || o.created_at)}
                    {(o.address || applicationOf.get(o.id)?.address)
                      ? ` · ${o.address || applicationOf.get(o.id).address}`
                      : ''}
                  </span>
                </div>
              </div>
              <span className="af-c-sector af-sector">{agencyLabel(o.agency_type)}</span>
              <span className="af-c-auth">
                <span className="ar-tag" style={{ color: auth.color, background: `${auth.color}1f` }}
                      title={auth.key === 'observer'
                        ? 'Sees incidents that requested this agency; cannot verify, reject or dispatch.'
                        : 'Verifies, rejects and dispatches on incidents.'}>
                  {auth.label}
                </span>
              </span>
              {/* data-label names the count on a phone, where the header row is hidden. */}
              <span className="af-c-num af-num" data-label="Units">{o.equipment_count ?? 0}</span>
              <span className="af-c-num af-num" data-label="Personnel">{o.personnel_count ?? 0}</span>
              <span className="af-c-status">
                <span className={`af-status${o.is_active ? ' is-on' : ''}`}>
                  <span className="af-status-dot" />
                  {o.is_active ? 'Active' : 'Inactive'}
                </span>
              </span>
              <span className="af-c-go" aria-hidden="true"><ChevronIcon /></span>
            </button>
            );
          })}
        </div>
      </section>

      {openOrg && (
        <OrgDialog
          org={openOrg}
          application={applicationOf.get(openOrg.id) ?? null}
          glyph={GLYPH[openOrg.agency_type] ?? 'glyph-people'}
          color={SECTOR_COLOR[openOrg.agency_type] ?? '#8a8a8a'}
          onClose={closeOrg}
        />
      )}
    </div>
  );
}
