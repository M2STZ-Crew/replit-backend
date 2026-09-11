import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import LiveMap, { LAYER_COLORS } from '../components/LiveMap.jsx';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import { formatMinutes, formatShare, responseMetrics } from '../lib/metrics.js';
import { AGENCY_LABEL, since, statusOf } from '../lib/status.js';

const BAND = { high: '#22C55E', medium: '#EAB308', low: '#FF544E' };

const HISTORY_LIMIT = 500;
const METRICS_DAYS = 30;

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

export default function SituationBoard({ onNavigate }) {
  // Live incidents and counters come from the console-wide feed, so this board
  // updates on the same 12 s poll that drives the badges and sounds.
  const { incidents, stats, loaded } = useLiveFeed();
  const lastViewed = useSurfaceVisit('dashboard');
  const [allIncidents, setAllIncidents] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [layerPoints, setLayerPoints] = useState({});
  const [enabled, setEnabled] = useState(new Set(['incidents']));
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const loading = !loaded || !historyLoaded;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [history, eq] = await Promise.all([
        // Closed incidents included, so the histogram reflects the real last
        // 16 hours and the §11.2 metrics cover finished incidents. 500 is the
        // most the feed returns in one page.
        api.incidents({ activeOnly: false, limit: HISTORY_LIMIT }).catch(() => []),
        api.equipment().catch(() => []),
      ]);
      if (cancelled) return;
      setAllIncidents(history);
      setEquipment(eq);
      setHistoryLoaded(true);
    })();
    return () => { cancelled = true; };
  }, []);

  const lastViewedMs = lastViewed ? new Date(lastViewed).getTime() : 0;
  const isNew = (inc) => new Date(inc.reported_at).getTime() > lastViewedMs;
  const newCount = incidents.filter(isNew).length;

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
          .map((r) => ({
            lat: r[spec.lat],
            lng: r[spec.lng],
            // Section 2.4: a shelter outside Pasay gets a distinct marker.
            outside: !!r.outside_pasay,
            label: r.name ? `${r.name}${r.outside_pasay ? ` · ${r.city}` : ''}` : null,
          }))
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
  const metrics = useMemo(
    () => responseMetrics(allIncidents, { days: METRICS_DAYS }),
    [allIncidents],
  );
  // If a full page came back and even its oldest incident is inside the
  // window, older ones in the window were cut off — say so.
  const metricsTruncated =
    allIncidents.length >= HISTORY_LIMIT &&
    Date.now() - new Date(allIncidents[allIncidents.length - 1]?.reported_at).getTime() <
      METRICS_DAYS * 864e5;
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
            <LiveMap
              incidents={incidents}
              layerPoints={layerPoints}
              enabled={enabled}
              onSelectIncident={(inc) => onNavigate('incidents', { incidentId: inc.id })}
            />
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
            {enabled.has('evac') && (layerPoints.evac || []).some((p) => p.outside) && (
              <span className="sb-legend-item is-on sb-legend-static">
                <span className="sb-legend-ring" style={{ borderColor: LAYER_COLORS.evac }} />
                Shelter outside Pasay
              </span>
            )}
          </div>
        </section>

        <div className="sb-side">
          <section className="sb-panel">
            <header className="sb-panel-head">
              <div className="sb-map-title">
                <span className="sb-panel-title">
                  Incident reports
                  {newCount > 0 && (
                    <span className="sb-new-count" aria-label={`${newCount} new since you last looked`}>
                      {newCount} new
                    </span>
                  )}
                </span>
                <span className="sb-panel-sub">Click a card to open it</span>
              </div>
              <button className="sb-link" onClick={() => onNavigate('incidents')}>All incidents →</button>
            </header>

            {incidents.length === 0 ? (
              <p className="sb-empty">
                {loading ? 'Loading…' : 'No active incidents. Reports appear here the moment they are clustered.'}
              </p>
            ) : (
              <div className="sb-list">
                {incidents.slice(0, 4).map((inc) => {
                  const st = statusOf(inc.status);
                  const routed = (inc.routed_agencies ?? []).length > 0;
                  return (
                    <button
                      key={inc.id}
                      className={`sb-inc${isNew(inc) ? ' is-new' : ''}`}
                      onClick={() => onNavigate('incidents', { incidentId: inc.id })}
                      title={`Open ${inc.designation}`}
                    >
                      <div className="sb-inc-top">
                        {isNew(inc) && <span className="sb-inc-new">NEW</span>}
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
                        {(inc.requested_agencies ?? []).map((a) => AGENCY_LABEL[a] ?? a).join(' · ') ||
                          `${inc.centroid_lat?.toFixed(5)}, ${inc.centroid_lng?.toFixed(5)}`}
                      </span>
                      <div className="sb-inc-foot">
                        <span>
                          {inc.report_count} report{inc.report_count === 1 ? '' : 's'}
                          {inc.active_dispatch_count > 0 && ` · ${inc.active_dispatch_count} unit(s)`}
                          {routed ? '' : ' · not routed'}
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

      {/* ── row 3: the §11.2 operational metrics ─────────────────────── */}
      <section className="sb-panel sb-metrics">
        <header className="sb-panel-head">
          <div className="sb-map-title">
            <span className="sb-panel-title">Response metrics · last {METRICS_DAYS} days</span>
            <span className="sb-panel-sub">
              {historyLoaded
                ? `${metrics.count} incident${metrics.count === 1 ? '' : 's'}` +
                  `${metricsTruncated ? ` (the latest ${HISTORY_LIMIT})` : ''}` +
                  ' · medians over incidents that reached both steps'
                : 'Loading…'}
            </span>
          </div>
        </header>
        <div className="sb-metric-grid">
          {[
            { label: 'Report → verified', m: metrics.reportToVerify, fmt: 'time' },
            { label: 'Verified → on scene', m: metrics.verifyToScene, fmt: 'time' },
            { label: 'Fire out → report filed', m: metrics.fireOutToReport, fmt: 'time' },
            { label: 'Reached high confidence', m: metrics.highConfidence, fmt: 'share' },
            { label: 'False alarms', m: metrics.falseAlarm, fmt: 'share' },
          ].map(({ label, m, fmt }) => (
            <div className="sb-metric" key={label}>
              <span className="dc-eyebrow">{label}</span>
              <span className="sb-metric-value">
                {historyLoaded ? (fmt === 'time' ? formatMinutes(m.median) : formatShare(m.share)) : '·'}
              </span>
              <span className="sb-kpi-foot">
                {m.n === 0 ? 'None yet' : `over ${m.n} incident${m.n === 1 ? '' : 's'}`}
              </span>
            </div>
          ))}
        </div>
        {historyLoaded && metrics.count > 0 && metrics.highConfidence.share === 0 && (
          <p className="sb-metric-note">
            No incident has reached high confidence. With phone verification (+40%)
            blocked until an SMS provider is chosen (§10.3), reporter credibility tops out
            at 60%, so the high band (0.7) takes about six or more tightly grouped
            reports even from otherwise fully verified residents.
          </p>
        )}
      </section>
    </div>
  );
}
