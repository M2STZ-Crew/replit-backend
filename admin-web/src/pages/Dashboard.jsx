import { useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { isObserver, useAuth } from '../auth.jsx';
import ConsoleShell from '../components/ConsoleShell.jsx';
import LiveMap, { LAYER_COLORS } from '../components/LiveMap.jsx';
import AccountManagement from './AccountManagement.jsx';
import AffiliatesPanel from './AffiliatesPanel.jsx';
import AuditLog from './AuditLog.jsx';
import MapManagement from './MapManagement.jsx';
import IdReview from './IdReview.jsx';
import VerificationQueue from './VerificationQueue.jsx';

// Per-section topbar heading (dashboard uses the personalised welcome).
const HEAD = {
  map: {
    title: 'Map Management',
    sub: 'Update risk zones, evacuation sites, hydrants, water sources, and cisterns.',
  },
  audit: { title: 'Audit Log', sub: 'Every incident, every timestamp — fully traceable.' },
  affiliates: {
    title: 'Affiliate Organizations',
    sub: 'Rosters, roles, and equipment for partner response teams.',
  },
  accounts: {
    title: 'Account Management',
    sub: 'Review and approve affiliate access requests.',
  },
};

// Section-aware placeholder for the shared topbar search.
const SEARCH_PH = {
  dashboard: 'Search incidents, units…',
  map: 'Find a marker…',
  audit: 'Search incidents…',
  affiliates: 'Find an organization…',
  accounts: 'Search requests…',
};

const NAV = [
  { key: 'dashboard', label: 'Dashboard', sub: 'Live operations', icon: '▦' },
  { key: 'verify', label: 'Verification', sub: 'Awaiting review', icon: '✓' },
  { key: 'map', label: 'Map', sub: 'Geo overlays', icon: '🗺' },
  { key: 'audit', label: 'Audit Log', sub: 'Incident records', icon: '🗂' },
  { key: 'affiliates', label: 'Affiliates', sub: 'Partner orgs', icon: '🤝',
    adminOnly: true },
  { key: 'accounts', label: 'Accounts', sub: 'Access requests', icon: '👤',
    adminOnly: true },
  { key: 'idreview', label: 'ID Review', sub: 'National ID approvals', icon: '🪪',
    adminOnly: true },
];

function navFor(user) {
  const observer = isObserver(user);
  return NAV.filter((n) => !n.adminOnly || user?.role === 'admin').map((n) =>
    n.key === 'verify' && observer
      ? { ...n, label: 'Incidents', sub: 'Involving your agency' }
      : n,
  );
}

// Map layers: which have backend data + how to read their coordinates.
const LAYERS = [
  { key: 'incidents', label: 'Incidents', color: '#FF544E' },
  { key: 'evac', label: 'Evacuation Sites', color: LAYER_COLORS.evac, path: 'evacuation-sites', lat: 'latitude', lng: 'longitude' },
  { key: 'risk', label: 'Risk Areas', color: LAYER_COLORS.risk, path: 'risk-zones', lat: 'centroid_lat', lng: 'centroid_lng' },
  { key: 'teams', label: 'Response Teams', color: '#FF9066' },
  { key: 'hydrants', label: 'Fire Hydrants', color: '#767575', path: 'hydrants', lat: 'latitude', lng: 'longitude' },
  { key: 'water', label: 'Bodies of Water', color: '#767575', path: 'bodies-of-water', lat: 'latitude', lng: 'longitude' },
  { key: 'fire', label: 'Fire Department', color: '#767575' },
  { key: 'police', label: 'Police Department', color: '#767575' },
  { key: 'hospital', label: 'Hospital', color: '#767575' },
  { key: 'barangay', label: 'Barangay Hall', color: '#767575' },
];

const STAT_CARDS = [
  { key: 'active_incidents', label: 'Active Incidents', sub: 'In progress now', tint: 'rgba(255,84,78,0.10)', icon: '🔥' },
  { key: 'pending_verify', label: 'Pending Verify', sub: 'Needs ops review', tint: 'rgba(255,144,102,0.10)', icon: '🪪' },
  { key: 'units_deployed', label: 'Units Deployed', sub: 'On the way or on-site', tint: 'rgba(255,144,102,0.10)', icon: '🚒' },
  { key: 'units_standby', label: 'Units Standby', sub: 'Ready to respond', tint: 'rgba(118,117,117,0.15)', icon: '✓' },
];

function reportStatus(status) {
  switch (status) {
    case 'verified':
    case 'dispatched':
    case 'en_route':
      return { label: 'Responding', color: '#FF9066' };
    case 'arrived':
      return { label: 'Active', color: '#FF544E' };
    case 'resolved':
      return { label: 'Resolved', color: '#22C55E' };
    case 'rejected':
      return { label: 'Rejected', color: '#FF544E' };
    default:
      return { label: 'Pending', color: '#CFCFCF' };
  }
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    let h = d.getHours();
    const ampm = h < 12 ? 'AM' : 'PM';
    h = h % 12 === 0 ? 12 : h % 12;
    return `${h}:${String(d.getMinutes()).padStart(2, '0')} ${ampm}`;
  } catch {
    return '';
  }
}

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [active, setActive] = useState('dashboard');
  const [query, setQuery] = useState('');

  const [stats, setStats] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [enabled, setEnabled] = useState(new Set(['incidents']));
  const [layerPoints, setLayerPoints] = useState({});

  // Switch sections and clear the search so it doesn't carry across views.
  function go(key) {
    setActive(key);
    setQuery('');
  }

  // Dashboard-home filtering driven by the shared search.
  const q = query.trim().toLowerCase();
  const shownIncidents =
    active === 'dashboard' && q
      ? incidents.filter((inc) =>
          `${inc.designation || ''} ${inc.status || ''}`.toLowerCase().includes(q),
        )
      : incidents;
  const shownEquipment =
    active === 'dashboard' && q
      ? equipment.filter((u) =>
          `${u.name || ''} ${u.category || ''}`.toLowerCase().includes(q),
        )
      : equipment;

  const name = user?.full_name || user?.email || 'Admin';
  const initials = name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const [s, inc, eq] = await Promise.all([
          api.incidentStats().catch(() => null),
          api.incidents().catch(() => []),
          api.equipment().catch(() => []),
        ]);
        if (!alive) return;
        if (s) setStats(s);
        setIncidents(Array.isArray(inc) ? inc : []);
        setEquipment(Array.isArray(eq) ? eq : []);
      } catch {
        /* keep last */
      }
    }
    load();
    const t = setInterval(load, 12000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  async function toggleLayer(layer) {
    const next = new Set(enabled);
    if (next.has(layer.key)) {
      next.delete(layer.key);
      setEnabled(next);
      return;
    }
    next.add(layer.key);
    setEnabled(next);
    if (layer.path && !layerPoints[layer.key]) {
      try {
        const raw = await api.mapLayer(layer.path);
        const pts = (Array.isArray(raw) ? raw : [])
          .map((r) => ({ lat: r[layer.lat], lng: r[layer.lng] }))
          .filter((p) => p.lat != null && p.lng != null);
        setLayerPoints((lp) => ({ ...lp, [layer.key]: pts }));
      } catch {
        /* layer just shows nothing */
      }
    }
  }

  return (
    <ConsoleShell active={active} onNavigate={go}>
      <div className="db-main">
        <header className="db-topbar">
          <div>
            <div className="db-hello">
              {HEAD[active]?.title || `Welcome back, ${name.split(/\s+/)[0]}`}
            </div>
            <div className="db-hello-sub">
              {HEAD[active]?.sub || "Here's what's happening across Pasay City right now."}
            </div>
          </div>
          <div className="db-search">
            <span className="db-search-icon">🔍</span>
            <input
              className="db-search-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={SEARCH_PH[active] || 'Search…'}
            />
          </div>
        </header>

        <div className={`db-scroll${active === 'map' ? ' db-scroll-flush' : ''}`}>
          {active === 'dashboard' ? (
            <>
              <div className="db-stats">
                {STAT_CARDS.map((c) => (
                  <div className="db-stat" key={c.key}>
                    <div className="db-stat-icon" style={{ background: c.tint }}>{c.icon}</div>
                    <div className="db-stat-value">{stats ? (stats[c.key] ?? 0) : '–'}</div>
                    <div className="db-stat-label">{c.label}</div>
                    <div className="db-stat-sub">{c.sub}</div>
                  </div>
                ))}
              </div>

              <div className="db-cols">
                <section className="db-panel db-mappanel">
                  <div className="db-panel-head">
                    <div>
                      <div className="db-panel-title">Live Map</div>
                      <div className="db-panel-sub">
                        Real-time positions across Pasay City. Toggle layers to focus.
                      </div>
                    </div>
                    <div className="db-live"><span className="db-live-dot" />Updating live</div>
                  </div>
                  <div className="db-chips">
                    {LAYERS.map((l) => {
                      const on = enabled.has(l.key);
                      return (
                        <button
                          key={l.key}
                          className={`db-chip${on ? ' on' : ''}`}
                          onClick={() => toggleLayer(l)}
                          style={on ? { borderColor: l.color } : undefined}
                        >
                          <span className="db-chip-dot" style={{ background: l.color }} />
                          {l.label}
                        </button>
                      );
                    })}
                  </div>
                  <div className="db-map">
                    <LiveMap incidents={shownIncidents} layerPoints={layerPoints} enabled={enabled} />
                  </div>
                </section>

                <div className="db-right">
                  <section className="db-panel">
                    <div className="db-panel-head">
                      <div>
                        <div className="db-panel-title">Incident Reports</div>
                        <div className="db-panel-sub">
                          {shownIncidents.length} {q ? 'matching' : 'active'} reports
                        </div>
                      </div>
                      <span className="db-link" onClick={() => go('audit')}>View all ›</span>
                    </div>
                    <div className="db-list">
                      {shownIncidents.length === 0 && <div className="db-empty">No active incidents.</div>}
                      {shownIncidents.slice(0, 8).map((inc) => {
                        const st = reportStatus(inc.status);
                        return (
                          <div className="db-inccard" key={inc.id}>
                            <div className="db-inccard-top">
                              <span className="db-tag">FIRE</span>
                              <span className="db-dot-status" style={{ color: st.color }}>● {st.label}</span>
                            </div>
                            <div className="db-inccard-addr">{inc.designation || 'Incident'}</div>
                            <div className="db-inccard-meta">
                              <span>Reported {fmtTime(inc.reported_at)}</span>
                              <span>{(inc.report_count ?? 0)} report(s)</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>

                  <section className="db-panel">
                    <div className="db-panel-head">
                      <div>
                        <div className="db-panel-title">Units</div>
                        <div className="db-panel-sub">Fleet status snapshot</div>
                      </div>
                    </div>
                    <div className="db-units">
                      {shownEquipment.length === 0 && <div className="db-empty">No units registered.</div>}
                      {shownEquipment.slice(0, 10).map((u) => {
                        const deployed = u.status === 'in_use';
                        return (
                          <div className="db-unit" key={u.id}>
                            <span className="db-unit-dot" style={{ background: deployed ? '#FF9066' : '#CFCFCF' }} />
                            <div className="db-unit-texts">
                              <div className="db-unit-name">{u.name}</div>
                              <div className="db-unit-sub">{u.category || '—'}</div>
                            </div>
                            <span className={`db-unit-pill${deployed ? ' deployed' : ''}`}>
                              {deployed ? 'Deployed' : 'Standby'}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                </div>
              </div>
            </>
          ) : active === 'map' ? (
            <MapManagement query={query} />
          ) : active === 'affiliates' ? (
            <AffiliatesPanel query={query} onQuery={setQuery} />
          ) : active === 'idreview' ? (
            <IdReview />
          ) : active === 'verify' ? (
            <VerificationQueue />
          ) : active === 'audit' ? (
            <AuditLog query={query} onQuery={setQuery} />
          ) : active === 'accounts' ? (
            <AccountManagement query={query} />
          ) : (
            <div className="db-placeholder">
              <div className="db-placeholder-icon">{NAV.find((n) => n.key === active)?.icon}</div>
              <h2>{NAV.find((n) => n.key === active)?.label}</h2>
              <p className="muted">This section is coming next.</p>
            </div>
          )}
        </div>
      </div>
    </ConsoleShell>
  );
}
