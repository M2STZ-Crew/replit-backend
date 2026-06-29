import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';

const AGENCY = {
  fire_volunteer: { label: 'Fire Volunteer', color: '#FF9066' },
  bfp: { label: 'BFP', color: '#FF9066' },
  barangay: { label: 'Barangay', color: '#CFCFCF' },
  medical: { label: 'Medical', color: '#CFCFCF' },
  police: { label: 'Police', color: '#CFCFCF' },
};

const ROLE = {
  sub_admin: 'Coordinator',
  response_team: 'Responder',
  admin: 'Admin',
  general_user: 'Member',
};

const EQ_STATUS = {
  available: { label: 'Ready', color: '#FF9066' },
  in_use: { label: 'Deployed', color: '#FF544E' },
  maintenance: { label: 'Maintenance', color: '#EAB308' },
  out_of_service: { label: 'Out of Service', color: '#767575' },
};

function agencyOf(t) {
  return AGENCY[t] || { label: prettify(t), color: '#767575' };
}

function roleOf(r) {
  return ROLE[r] || prettify(r);
}

function eqStatusOf(s) {
  return EQ_STATUS[s] || { label: prettify(s), color: '#767575' };
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

function eqSubtitle(e) {
  const cat = e.category ? prettify(e.category) : 'Equipment';
  if (e.capacity_liters) return `${cat} · ${Number(e.capacity_liters).toLocaleString()} L`;
  return cat;
}

export default function OrgDirectory({ query = '', onQuery }) {
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(null);

  const [personnel, setPersonnel] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const rows = await api.organizations();
        if (!alive) return;
        setOrgs(Array.isArray(rows) ? rows : []);
      } catch (e) {
        if (alive) setError(e.message || 'Failed to load organizations.');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return orgs;
    return orgs.filter((o) => (o.name || '').toLowerCase().includes(q));
  }, [orgs, query]);

  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !filtered.some((o) => o.id === selectedId)) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setPersonnel([]);
      setEquipment([]);
      return;
    }
    let alive = true;
    (async () => {
      setDetailLoading(true);
      const [p, e] = await Promise.all([
        api.orgPersonnel(selectedId).catch(() => []),
        api.orgEquipment(selectedId).catch(() => []),
      ]);
      if (!alive) return;
      setPersonnel(Array.isArray(p) ? p : []);
      setEquipment(Array.isArray(e) ? e : []);
      setDetailLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [selectedId]);

  const selected = useMemo(
    () => orgs.find((o) => o.id === selectedId) || null,
    [orgs, selectedId],
  );

  return (
    <div className="org-wrap">
      <div className="org-search">
        🔍
        <input
          value={query}
          onChange={(e) => onQuery?.(e.target.value)}
          placeholder="Find an organization…"
        />
      </div>

      <div className="org-cols">
        {/* org list */}
        <div className="org-listpanel">
          {loading && <div className="org-empty">Loading…</div>}
          {error && <div className="org-empty">{error}</div>}
          {!loading && !error && filtered.length === 0 && (
            <div className="org-empty">No affiliate organizations yet.</div>
          )}
          {filtered.map((o) => {
            const ag = agencyOf(o.agency_type);
            const active = o.id === selectedId;
            return (
              <button
                key={o.id}
                className={`org-card${active ? ' active' : ''}`}
                onClick={() => setSelectedId(o.id)}
              >
                <span
                  className="org-card-icon"
                  style={{ background: `${ag.color}22`, color: ag.color }}
                >
                  🏢
                </span>
                <span className="org-card-texts">
                  <span className="org-card-name">{o.name}</span>
                  <span className="org-card-sub">
                    {o.personnel_count} personnel · {o.equipment_count} units
                  </span>
                </span>
                <span
                  className="org-badge"
                  style={{
                    color: ag.color,
                    borderColor: `${ag.color}48`,
                    background: `${ag.color}1f`,
                  }}
                >
                  {ag.label}
                </span>
              </button>
            );
          })}
        </div>

        {/* org detail */}
        <div className="org-detailpanel">
          {!selected ? (
            <div className="org-detail-empty">
              {loading ? 'Loading…' : 'Select an organization to view its roster.'}
            </div>
          ) : (
            <>
              <div className="org-detail-head">
                <div>
                  <div className="org-detail-title">{selected.name}</div>
                  <div className="org-detail-sub">
                    {agencyOf(selected.agency_type).label} · {selected.personnel_count}{' '}
                    personnel · {selected.equipment_count}{' '}
                    {selected.equipment_count === 1 ? 'piece' : 'pieces'} of equipment
                  </div>
                </div>
                <span
                  className="org-detail-icon"
                  style={{
                    background: `${agencyOf(selected.agency_type).color}22`,
                    color: agencyOf(selected.agency_type).color,
                  }}
                >
                  🏢
                </span>
              </div>

              <div className="org-detail-body">
                {/* roster */}
                <section className="org-col">
                  <div className="org-col-head">
                    <div className="org-col-title">👥 Roster</div>
                    <div className="org-col-count">{personnel.length} people</div>
                  </div>
                  <div className="org-col-list">
                    {detailLoading && <div className="org-empty">Loading…</div>}
                    {!detailLoading && personnel.length === 0 && (
                      <div className="org-empty">No personnel on record.</div>
                    )}
                    {!detailLoading &&
                      personnel.map((m) => {
                        const ag = agencyOf(m.agency_type || selected.agency_type);
                        return (
                          <div className="org-member" key={m.id}>
                            <span
                              className="org-avatar"
                              style={{ background: `${ag.color}22`, color: ag.color }}
                            >
                              {initialOf(m.full_name)}
                            </span>
                            <div className="org-member-texts">
                              <div className="org-member-name">
                                {m.full_name || 'Unnamed'}
                              </div>
                              <div className="org-member-role">{roleOf(m.role)}</div>
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </section>

                {/* equipment */}
                <section className="org-col">
                  <div className="org-col-head">
                    <div className="org-col-title">🧰 Equipment</div>
                    <div className="org-col-count">{equipment.length} units</div>
                  </div>
                  <div className="org-col-list">
                    {detailLoading && <div className="org-empty">Loading…</div>}
                    {!detailLoading && equipment.length === 0 && (
                      <div className="org-empty">No equipment on record.</div>
                    )}
                    {!detailLoading &&
                      equipment.map((e) => {
                        const st = eqStatusOf(e.status);
                        return (
                          <div className="org-eq" key={e.id}>
                            <div className="org-eq-top">
                              <span className="org-eq-name">{e.name}</span>
                              <span
                                className="org-eq-pill"
                                style={{
                                  color: st.color,
                                  borderColor: `${st.color}48`,
                                  background: `${st.color}1f`,
                                }}
                              >
                                {st.label}
                              </span>
                            </div>
                            <div className="org-eq-sub">{eqSubtitle(e)}</div>
                          </div>
                        );
                      })}
                  </div>
                </section>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
