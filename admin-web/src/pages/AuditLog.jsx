import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';

// Status filter tabs (lifecycle-based — incidents are not agency-typed at the
// area level, so we filter on the real `status` field rather than agency).
const TABS = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'rejected', label: 'Rejected' },
];

const STATUS = {
  pending: { label: 'Pending', color: '#EAB308' },
  clustered: { label: 'Clustered', color: '#EAB308' },
  verified: { label: 'Verified', color: '#3B82F6' },
  dispatched: { label: 'Dispatched', color: '#FF9066' },
  en_route: { label: 'En Route', color: '#FF9066' },
  arrived: { label: 'Arrived', color: '#22C55E' },
  resolved: { label: 'Resolved', color: '#22C55E' },
  rejected: { label: 'Rejected', color: '#FF544E' },
};

// The lifecycle timeline (the 7-stage incident progression). Each step maps to a
// real `*_at` timestamp on the incident; `rejected_at` is a terminal branch.
const STEPS = [
  { key: 'reported_at', label: 'Reported' },
  { key: 'verified_at', label: 'Verified' },
  { key: 'dispatched_at', label: 'Dispatched' },
  { key: 'en_route_at', label: 'En Route' },
  { key: 'arrived_at', label: 'Arrived' },
  { key: 'resolved_at', label: 'Resolved' },
];

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

function shortId(id) {
  return id ? `#${String(id).slice(0, 8)}` : '';
}

function fmtTime(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return null;
  }
}

function fmtDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return '';
  }
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = fmtDate(iso);
  const t = fmtTime(iso);
  return t ? `${d} · ${t}` : d;
}

// Local YYYY-MM-DD for the date filter (compared against an <input type=date>).
function localDay(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

export default function AuditLog({ query = '', onQuery }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('all');
  const [day, setDay] = useState('');
  const [selectedId, setSelectedId] = useState(null);

  const [detail, setDetail] = useState(null);
  const [dispatches, setDispatches] = useState([]);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const rows = await api.incidents({ activeOnly: false, limit: 200 });
        if (!alive) return;
        setList(Array.isArray(rows) ? rows : []);
      } catch (e) {
        if (alive) setError(e.message || 'Failed to load incidents.');
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
    return list.filter((inc) => {
      if (tab === 'active' && (inc.status === 'resolved' || inc.status === 'rejected'))
        return false;
      if (tab === 'resolved' && inc.status !== 'resolved') return false;
      if (tab === 'rejected' && inc.status !== 'rejected') return false;
      if (day && localDay(inc.reported_at) !== day) return false;
      if (q) {
        const hay = `${inc.designation || ''} ${inc.id}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [list, tab, query, day]);

  // Keep a valid selection as filters change.
  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !filtered.some((i) => i.id === selectedId)) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  // Load the detail + dispatches for the selected incident.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDispatches([]);
      return;
    }
    let alive = true;
    (async () => {
      setDetailLoading(true);
      const [d, disp] = await Promise.all([
        api.incident(selectedId).catch(() => null),
        api.incidentDispatches(selectedId).catch(() => []),
      ]);
      if (!alive) return;
      setDetail(d);
      setDispatches(Array.isArray(disp) ? disp : []);
      setDetailLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [selectedId]);

  const lead = useMemo(
    () => dispatches.find((d) => d.status === 'active') || dispatches[0] || null,
    [dispatches],
  );

  const steps = useMemo(() => {
    const base = STEPS.map((s) => ({ ...s, at: detail?.[s.key] || null }));
    if (detail?.rejected_at) {
      base.push({ key: 'rejected_at', label: 'Rejected', at: detail.rejected_at, danger: true });
    }
    return base;
  }, [detail]);

  return (
    <div className="al-wrap">
      <div className="al-toolbar">
        <div className="al-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`al-tab${tab === t.key ? ' active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="al-tools">
          <div className="al-search">
            🔍
            <input
              value={query}
              onChange={(e) => onQuery?.(e.target.value)}
              placeholder="Search incidents…"
            />
          </div>
          <input
            className="al-date"
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
          />
          {day && (
            <button className="al-clear" onClick={() => setDay('')} title="Clear date">
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="al-cols">
        {/* list */}
        <section className="al-listpanel">
          <div className="al-panel-head">
            <div className="al-panel-title">Incidents</div>
            <div className="al-panel-sub">
              {loading ? 'Loading…' : `${filtered.length} matching record${filtered.length === 1 ? '' : 's'}`}
            </div>
          </div>
          <div className="al-list">
            {error && <div className="al-empty">{error}</div>}
            {!loading && !error && filtered.length === 0 && (
              <div className="al-empty">No incidents match these filters.</div>
            )}
            {filtered.map((inc) => {
              const st = statusOf(inc.status);
              const active = inc.id === selectedId;
              return (
                <button
                  key={inc.id}
                  className={`al-card${active ? ' active' : ''}`}
                  onClick={() => setSelectedId(inc.id)}
                >
                  <div className="al-card-top">
                    <span
                      className="al-badge"
                      style={{
                        color: st.color,
                        borderColor: `${st.color}40`,
                        background: `${st.color}1f`,
                      }}
                    >
                      {st.label}
                    </span>
                    <span className="al-code">{shortId(inc.id)}</span>
                  </div>
                  <div className="al-card-title">{inc.designation || 'Incident'}</div>
                  <div className="al-card-org">
                    {inc.report_count} report{inc.report_count === 1 ? '' : 's'} ·{' '}
                    {prettify(inc.confidence_band)} confidence
                  </div>
                  <div className="al-card-addr">Reported {fmtDateTime(inc.reported_at)}</div>
                </button>
              );
            })}
          </div>
        </section>

        {/* detail */}
        <section className="al-detailpanel">
          {!detail ? (
            <div className="al-detail-empty">
              {detailLoading ? 'Loading…' : 'Select an incident to view its record.'}
            </div>
          ) : (
            <>
              <div className="al-detail-head">
                <div>
                  <div className="al-detail-title">
                    Incident · {detail.designation || shortId(detail.id)}
                  </div>
                  <div className="al-detail-sub">
                    {lead
                      ? `${lead.vehicle_name || 'Unit'}${lead.responder_name ? ` — ${lead.responder_name}` : ''}`
                      : 'No units dispatched'}
                  </div>
                </div>
                <span
                  className="al-detail-icon"
                  style={{
                    color: statusOf(detail.status).color,
                    background: `${statusOf(detail.status).color}1f`,
                  }}
                >
                  ●
                </span>
              </div>

              <div className="al-detail-body">
                <div className="al-info">
                  <div className="al-infocard">
                    <div className="al-info-l">Status</div>
                    <div className="al-info-v">{statusOf(detail.status).label}</div>
                  </div>
                  <div className="al-infocard">
                    <div className="al-info-l">Reports</div>
                    <div className="al-info-v">{detail.report_count}</div>
                  </div>
                  <div className="al-infocard">
                    <div className="al-info-l">Confidence</div>
                    <div className="al-info-v">
                      {prettify(detail.confidence_band)} · {Number(detail.confidence_score).toFixed(2)}
                    </div>
                  </div>
                  <div className="al-infocard">
                    <div className="al-info-l">Lead Unit</div>
                    <div className="al-info-v">
                      {lead ? lead.vehicle_name || lead.responder_name || '—' : 'None'}
                    </div>
                  </div>
                  <div className="al-infocard">
                    <div className="al-info-l">Alarm Level</div>
                    <div className="al-info-v">{prettify(detail.alarm_level)}</div>
                  </div>
                  <div className="al-infocard">
                    <div className="al-info-l">Coordinates</div>
                    <div className="al-info-v">
                      {Number(detail.centroid_lat).toFixed(5)}, {Number(detail.centroid_lng).toFixed(5)}
                    </div>
                  </div>
                </div>

                {(detail.verified_by_name ||
                  detail.resolved_by_name ||
                  detail.rejected_by_name) && (
                  <div className="al-accts">
                    {detail.verified_by_name && (
                      <span className="al-acct">Verified by {detail.verified_by_name}</span>
                    )}
                    {detail.resolved_by_name && (
                      <span className="al-acct">Resolved by {detail.resolved_by_name}</span>
                    )}
                    {detail.rejected_by_name && (
                      <span className="al-acct danger">
                        Rejected by {detail.rejected_by_name}
                        {detail.rejection_reason ? ` — ${detail.rejection_reason}` : ''}
                      </span>
                    )}
                  </div>
                )}

                <div className="al-tl-title">Response Timeline</div>
                <div className="al-timeline">
                  {steps.map((s, i) => {
                    const done = !!s.at;
                    const color = s.danger ? '#FF544E' : done ? '#FF9066' : '#3A3A3A';
                    return (
                      <div className="al-step" key={s.key}>
                        <div className="al-step-rail">
                          <span
                            className={`al-step-dot${done ? ' done' : ''}`}
                            style={done ? { background: color, borderColor: color } : undefined}
                          />
                          {i < steps.length - 1 && <span className="al-step-line" />}
                        </div>
                        <div className="al-step-row">
                          <div className="al-step-body">
                            <div className="al-step-label">{s.label}</div>
                            <div className="al-step-meta">
                              Step {i + 1} of {steps.length}
                            </div>
                          </div>
                          <div
                            className="al-step-time"
                            style={done ? { color } : undefined}
                          >
                            {s.at ? fmtTime(s.at) : 'Pending'}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="al-tl-title">Units Dispatched</div>
                <div className="al-units">
                  {dispatches.length === 0 && (
                    <div className="al-empty">No units dispatched.</div>
                  )}
                  {dispatches.map((d) => {
                    const st = statusOf(d.status);
                    return (
                      <div className="al-unit" key={d.id}>
                        <div className="al-unit-l">
                          <div className="al-unit-name">
                            {d.vehicle_name || d.responder_name || 'Unit'}
                          </div>
                          <div className="al-unit-sub">
                            {[d.responder_name, d.crew_role].filter(Boolean).join(' · ') || '—'}
                          </div>
                        </div>
                        <div className="al-unit-r">
                          <span
                            className="al-unit-pill"
                            style={{ color: st.color, borderColor: `${st.color}40` }}
                          >
                            {prettify(d.status)}
                          </span>
                          <span className="al-unit-time">{fmtTime(d.dispatched_at)}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
