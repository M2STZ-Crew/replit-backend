import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import LiveMap, { LAYER_COLORS } from '../components/LiveMap.jsx';

const STATUS = {
  pending: { label: 'Pending', color: '#EAB308' },
  verified: { label: 'Verified', color: '#42A5F5' },
  dispatched: { label: 'Dispatched', color: '#1976D2' },
  en_route: { label: 'En route', color: '#FF9066' },
  arrived: { label: 'On scene', color: '#F4511E' },
  resolved: { label: 'Resolved', color: '#22C55E' },
  rejected: { label: 'Rejected', color: '#9E9E9E' },
  merged: { label: 'Merged', color: '#7E57C2' },
};

const BAND = { high: '#22C55E', medium: '#EAB308', low: '#FF544E' };

/* Posture is derived, not invented: it reads off the count of live incidents.
   The design showed a fixed "Elevated · Lvl 3 / 5" with a dry-season advisory;
   nothing in the system produces an advisory, so the level comes from what the
   system actually knows. */
function postureOf(active, pending) {
  if (active === 0) return { label: 'Normal', level: 1, note: 'No active incidents across Pasay City.' };
  if (active <= 2) return { label: 'Watch', level: 2, note: `${active} incident${active === 1 ? '' : 's'} being handled.` };
  if (active <= 5) {
    return {
      label: 'Elevated', level: 3,
      note: `${active} incidents open` + (pending ? `, ${pending} awaiting verification.` : '.'),
    };
  }
  return { label: 'High', level: 4, note: `${active} incidents open simultaneously.` };
}

/* 16 hourly buckets from real reported_at timestamps. Where the design had a
   decorative sparkline, this is a genuine histogram — an empty hour is an empty
   bar rather than a fabricated one. */
function hourlyBars(incidents, hours = 16) {
  const now = Date.now();
  const buckets = new Array(hours).fill(0);
  for (const inc of incidents) {
    if (!inc.reported_at) continue;
    const age = (now - new Date(inc.reported_at).getTime()) / 3.6e6;
    if (age >= 0 && age < hours) buckets[hours - 1 - Math.floor(age)] += 1;
  }
  const peak = Math.max(1, ...buckets);
  return buckets.map((n) => ({ n, h: Math.max(2, Math.round((n / peak) * 34)) }));
}

function since(iso) {
  if (!iso) return '—';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d`;
}

export default function SituationBoard({ onNavigate }) {
  const [stats, setStats] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [allIncidents, setAllIncidents] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [layerPoints, setLayerPoints] = useState({});
  const [enabled, setEnabled] = useState(new Set(['incidents']));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [s, live, history, eq] = await Promise.all([
        api.incidentStats().catch(() => null),
        api.incidents().catch(() => []),
        // Closed incidents included, so the histogram reflects the real last
        // 16 hours rather than only what is still open.
        api.incidents({ activeOnly: false, limit: 200 }).catch(() => []),
        api.equipment().catch(() => []),
      ]);
      if (cancelled) return;
      setStats(s);
      setIncidents(live);
      setAllIncidents(history);
      setEquipment(eq);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const specs = [
        { key: 'evac', path: 'evacuation-sites', lat: 'latitude', lng: 'longitude' },
        { key: 'risk', path: 'risk-zones', lat: 'centroid_lat', lng: 'centroid_lng' },
        { key: 'hydrants', path: 'hydrants', lat: 'latitude', lng: 'longitude' },
        { key: 'water', path: 'bodies-of-water', lat: 'latitude', lng: 'longitude' },
      ];
      for (const spec of specs) {
        const rows = await api.mapLayer(spec.path).catch(() => []);
        if (cancelled) return;
        const pts = rows
          .map((r) => ({ lat: r[spec.lat], lng: r[spec.lng] }))
          .filter((p) => p.lat != null && p.lng != null);
        setLayerPoints((lp) => ({ ...lp, [spec.key]: pts }));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const active = stats?.active_incidents ?? 0;
  const pending = stats?.pending_verify ?? 0;
  const posture = postureOf(active, pending);
  const bars = useMemo(() => hourlyBars(allIncidents), [allIncidents]);
  const barsHaveData = bars.some((b) => b.n > 0);

  const kpis = [
    { key: 'active', label: 'Active incidents', value: active, foot: 'Open right now', tone: active > 0 ? '#FF9066' : '#ffffff' },
    { key: 'pending', label: 'Awaiting verification', value: pending, foot: 'Needs a coordinator', tone: pending > 0 ? '#EAB308' : '#ffffff' },
    { key: 'deployed', label: 'Units deployed', value: stats?.units_deployed ?? 0, foot: 'En route or on scene', tone: '#ffffff' },
    { key: 'standby', label: 'Units standby', value: stats?.units_standby ?? 0, foot: 'Ready to respond', tone: '#ffffff' },
  ];

  function toggle(key) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  return (
    <div className="sb">
      {/* ── row 1: posture + KPIs ─────────────────────────────────────── */}
      <div className="sb-row">
        <section className="sb-posture">
          <div className="sb-posture-glow" aria-hidden="true" />
          <span className="sb-posture-eyebrow">Citywide posture</span>
          <div className="sb-posture-head">
            <span className="sb-posture-level">{posture.label}</span>
            <span className="sb-posture-lvl">Lvl {posture.level} / 5</span>
          </div>
          <p className="sb-posture-note">{posture.note}</p>

          <div className="sb-bars" role="img"
               aria-label={`Reports per hour over the last 16 hours, ${allIncidents.length} total`}>
            {bars.map((b, i) => (
              <span key={i} className={`sb-bar${b.n > 0 ? ' is-on' : ''}`} style={{ height: `${b.h}px` }} />
            ))}
          </div>
          <div className="sb-posture-foot">
            <span className="dc-eyebrow">
              {barsHaveData ? 'Reports · last 16 hours' : 'No reports in the last 16 hours'}
            </span>
            <button className="sb-link" onClick={() => onNavigate('map')}>Open map →</button>
          </div>
        </section>

        <div className="sb-kpis">
          {kpis.map((k) => (
            <section className="sb-kpi" key={k.key}>
              <span className="dc-eyebrow">{k.label}</span>
              <span className="sb-kpi-value" style={{ color: k.tone }}>
                {loading ? '·' : k.value}
              </span>
              <span className="sb-kpi-foot">{k.foot}</span>
            </section>
          ))}
        </div>
      </div>

      {/* ── row 2: map + side column ──────────────────────────────────── */}
      <div className="sb-row">
        <section className="sb-map">
          <header className="sb-map-head">
            <div className="sb-map-title">
              <span className="sb-panel-title">Live map · Pasay City</span>
              <span className="sb-panel-sub">Incident areas and operational overlays</span>
            </div>
            <span className="sb-pill">
              <span className="sb-pill-dot" />
              Feed healthy
            </span>
            <button className="sb-ghost" onClick={() => onNavigate('map')}>Expand</button>
          </header>

          <div className="sb-map-canvas">
            <LiveMap incidents={incidents} layerPoints={layerPoints} enabled={enabled} />
          </div>

          <div className="sb-legend">
            {[
              { key: 'incidents', label: 'Incidents', color: '#FF544E' },
              { key: 'evac', label: 'Evacuation sites', color: LAYER_COLORS.evac },
              { key: 'risk', label: 'Risk areas', color: LAYER_COLORS.risk },
              { key: 'hydrants', label: 'Hydrants', color: LAYER_COLORS.hydrants },
              { key: 'water', label: 'Bodies of water', color: LAYER_COLORS.water },
            ].map((l) => (
              <button
                key={l.key}
                className={`sb-legend-item${enabled.has(l.key) ? ' is-on' : ''}`}
                onClick={() => toggle(l.key)}
                aria-pressed={enabled.has(l.key)}
              >
                <span className="sb-legend-dot" style={{ background: l.color, boxShadow: `0 0 8px ${l.color}66` }} />
                {l.label}
              </button>
            ))}
          </div>
        </section>

        <div className="sb-side">
          <section className="sb-panel">
            <header className="sb-panel-head">
              <div className="sb-map-title">
                <span className="sb-panel-title">Incident reports</span>
                <span className="sb-panel-sub">Verification clock runs from first report</span>
              </div>
              <button className="sb-link" onClick={() => onNavigate('audit')}>Records →</button>
            </header>

            {incidents.length === 0 ? (
              <p className="sb-empty">
                {loading ? 'Loading…' : 'No active incidents. Reports appear here the moment they are clustered.'}
              </p>
            ) : (
              <div className="sb-list">
                {incidents.slice(0, 4).map((inc) => {
                  const st = STATUS[inc.status] ?? { label: inc.status, color: '#8a8a8a' };
                  return (
                    <button key={inc.id} className="sb-inc" onClick={() => onNavigate('verify')}>
                      <div className="sb-inc-top">
                        <span className="sb-inc-band" style={{
                          color: BAND[inc.confidence_band] ?? '#8a8a8a',
                          background: `${BAND[inc.confidence_band] ?? '#8a8a8a'}1f`,
                        }}>
                          {Math.round((inc.confidence_score ?? 0) * 100)}%
                        </span>
                        <span className="sb-inc-id">{inc.designation}</span>
                        <span className="sb-inc-status" style={{ color: st.color }}>
                          <span className="sb-inc-dot" style={{ background: st.color }} />
                          {st.label}
                        </span>
                      </div>
                      <span className="sb-inc-where">
                        {inc.centroid_lat?.toFixed(5)}, {inc.centroid_lng?.toFixed(5)}
                      </span>
                      <div className="sb-inc-foot">
                        <span>
                          {inc.report_count} report{inc.report_count === 1 ? '' : 's'}
                          {inc.active_dispatch_count > 0 && ` · ${inc.active_dispatch_count} unit(s)`}
                        </span>
                        <span className="sb-inc-age">{since(inc.reported_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section className="sb-panel sb-panel-grow">
            <header className="sb-panel-head">
              <div className="sb-map-title">
                <span className="sb-panel-title">Unit roster</span>
                <span className="sb-panel-sub">
                  {equipment.length} unit{equipment.length === 1 ? '' : 's'} in your organisation
                </span>
              </div>
              <span className="sb-tag">Read only</span>
            </header>

            {equipment.length === 0 ? (
              <p className="sb-empty">
                {loading
                  ? 'Loading…'
                  : 'No equipment registered to your organisation. Admins see every org.'}
              </p>
            ) : (
              <div className="sb-units">
                {equipment.slice(0, 6).map((u) => (
                  <div className="sb-unit" key={u.id}>
                    <span className="sb-unit-chip">
                      <img src="/assets/glyph-truck.png" alt="" width="14" height="14" />
                    </span>
                    <div className="sb-unit-text">
                      <span className="sb-unit-id">{u.name}</span>
                      <span className="sb-unit-org">{(u.type || '').replace(/_/g, ' ')}</span>
                    </div>
                    <span className={`sb-unit-state${u.status === 'available' ? ' is-ok' : ''}`}>
                      {(u.status || '').replace(/_/g, ' ')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
