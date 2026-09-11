import 'leaflet/dist/leaflet.css';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
  ZoomControl,
} from 'react-leaflet';

import { api } from '../api/client.js';
import { agencyLabel, canAccept, useAuth } from '../auth.jsx';
import { awaitingAccept, routesForMe, useLiveFeed } from '../live/LiveFeed.jsx';
import { AGENCY_LABEL, OFF_FEED, since, statusOf, when } from '../lib/status.js';
import { TILE_ATTRIBUTION, TILE_MAX_ZOOM, TILE_URL } from '../map/tiles.js';

const PASAY = [14.5378, 121.0014];
const EVAC = '#22C55E';
const RISK = '#FF9066';

/// Pans the map to the selected incident.
///
/// Leaflet's flyTo divides by the map's pixel size, so on a map with no size —
/// a background tab, a collapsed layout — it throws "Invalid LatLng (NaN, NaN)",
/// and with no error boundary that would blank the console. A sizeless map
/// jumps instead of flying, and a failed camera move is never fatal.
function FlyTo({ point }) {
  const map = useMap();
  useEffect(() => {
    if (!point || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) return;
    const zoom = Math.max(map.getZoom(), 15);
    const size = map.getSize();
    try {
      if (size.x > 0 && size.y > 0) map.flyTo(point, zoom, { duration: 0.6 });
      else map.setView(point, zoom, { animate: false });
    } catch {
      /* the selection still opens in the side panel */
    }
  }, [point, map]);
  return null;
}

/// Map (Monitoring) — where an observer watches and, when Admin has routed an
/// incident to them, presses Accept (v10 Section 2.6.1).
///
/// Accept acknowledges receipt — yes, we see it; yes, we are on it. It is
/// recorded in the audit log and changes no lifecycle status. There is no
/// Reject here, and no verify, dispatch or resolve: those belong to the Fire
/// Volunteer and BFP coordinators.
export default function MonitoringPage({ focusId = null }) {
  const { user } = useAuth();
  const { incidents, refresh } = useLiveFeed();
  const agency = user.agency_type;

  const [selectedId, setSelectedId] = useState(focusId);
  const [detail, setDetail] = useState(null);
  const [evidence, setEvidence] = useState([]);
  const [layers, setLayers] = useState({ evac: [], risk: [] });
  const [enabled, setEnabled] = useState(() => new Set(['incidents', 'evac']));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      const [evac, risk] = await Promise.all([
        api.mapLayer('evacuation-sites').catch(() => []),
        api.mapLayer('risk-zones').catch(() => []),
      ]);
      setLayers({ evac, risk });
    })();
  }, []);

  const loadDetail = useCallback(async (id) => {
    if (!id) { setDetail(null); setEvidence([]); return; }
    const [d, r] = await Promise.all([
      api.incident(id).catch(() => null),
      api.incidentReports(id).catch(() => []),
    ]);
    setDetail(d);
    setEvidence(r);
  }, []);

  useEffect(() => { setError(null); loadDetail(selectedId); }, [selectedId, loadDetail]);

  // Re-read the open incident when the 12 s feed shows it changed.
  const sig = useMemo(() => {
    const s = incidents.find((i) => i.id === selectedId);
    return s ? JSON.stringify([s.updated_at, s.status, s.routed_agencies, s.accepted_agencies]) : '';
  }, [incidents, selectedId]);
  useEffect(() => { if (sig) loadDetail(selectedId); }, [sig]); // selectedId is folded into sig

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.accept(detail.id));
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function toggle(key) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  // Keyed on the id, not the object: a refreshed detail of the same incident
  // (after Accept, or a poll) must not yank the map back to it.
  const focusPoint = useMemo(
    () => (detail ? [detail.centroid_lat, detail.centroid_lng] : null),
    [detail?.id],
  );

  const mine = detail ? routesForMe(detail, user) : [];
  const live = detail && !OFF_FEED.includes(detail.status);
  const acceptedRoute = mine.find((r) => r.accepted_at);
  const canPress = canAccept(user) && live && mine.some((r) => !r.accepted_at);
  const routedElsewhere = detail && mine.length === 0 &&
    (detail.routes ?? []).some((r) => r.agency === agency);

  return (
    <div className="mon">
      <div className="mon-map">
        <MapContainer center={PASAY} zoom={13} zoomControl={false} attributionControl={false}
                      style={{ height: '100%', width: '100%', background: '#0B0B0B' }}>
          <TileLayer url={TILE_URL} maxZoom={TILE_MAX_ZOOM} />
          <ZoomControl position="bottomleft" />
          <FlyTo point={focusPoint} />

          {enabled.has('risk') && layers.risk.map((z) => (
            z.centroid_lat != null && (
              <CircleMarker key={`r-${z.id}`} center={[z.centroid_lat, z.centroid_lng]} radius={6}
                            pathOptions={{ color: '#fff', weight: 1, fillColor: RISK, fillOpacity: 0.9 }}>
                <Tooltip>{z.name || `Risk area · ${z.barangay}`}</Tooltip>
              </CircleMarker>
            )
          ))}

          {enabled.has('evac') && layers.evac.map((s) => (
            // Section 2.4: a shelter outside Pasay is a dashed ring, not a dot.
            <CircleMarker
              key={`e-${s.id}`}
              center={[s.latitude, s.longitude]}
              radius={s.outside_pasay ? 8 : 6}
              pathOptions={s.outside_pasay
                ? { color: EVAC, weight: 2.5, dashArray: '3 3', fillColor: '#0B0B0B', fillOpacity: 0.85 }
                : { color: '#fff', weight: 1, fillColor: EVAC, fillOpacity: 0.9 }}
            >
              <Tooltip>{s.name}{s.outside_pasay ? ` · ${s.city} (outside Pasay)` : ''}</Tooltip>
            </CircleMarker>
          ))}

          {enabled.has('incidents') && incidents.map((inc) => {
            const st = statusOf(inc.status);
            const waiting = awaitingAccept(inc, agency);
            return (
              // Leaflet applies className only when a marker is created, so the
              // key carries the waiting state: accepting remounts the marker and
              // its pulse stops.
              <CircleMarker
                key={`${inc.id}:${waiting ? 'awaiting' : 'quiet'}`}
                center={[inc.centroid_lat, inc.centroid_lng]}
                radius={inc.id === selectedId ? 12 : 9}
                pathOptions={{
                  color: waiting ? '#FF544E' : '#fff',
                  weight: waiting ? 3 : 1.5,
                  fillColor: st.color,
                  fillOpacity: 0.95,
                  className: waiting ? 'marker-awaiting' : undefined,
                }}
                eventHandlers={{ click: () => setSelectedId(inc.id) }}
              >
                <Tooltip>{inc.designation} · {st.label}{waiting ? ' · awaiting your Accept' : ''}</Tooltip>
              </CircleMarker>
            );
          })}
          <div className="map-attribution">{TILE_ATTRIBUTION}</div>
        </MapContainer>

        <div className="mon-layers" role="group" aria-label="Map layers">
          {[
            { key: 'incidents', label: 'Incidents', color: '#FF544E' },
            { key: 'evac', label: 'Evacuation sites', color: EVAC },
            { key: 'risk', label: 'Risk areas', color: RISK },
          ].map((l) => (
            <button key={l.key} className={`layer-chip${enabled.has(l.key) ? ' is-on' : ''}`}
                    onClick={() => toggle(l.key)} aria-pressed={enabled.has(l.key)}>
              <span className="dot" style={{ background: l.color }} />
              {l.label}
            </button>
          ))}
          {enabled.has('evac') && layers.evac.some((s) => s.outside_pasay) && (
            <span className="layer-chip is-on is-static">
              <span className="ring" style={{ borderColor: EVAC }} />
              Shelter outside Pasay
            </span>
          )}
        </div>
      </div>

      <aside className="mon-side">
        {!detail ? (
          <>
            <header className="panel-head">
              <span className="panel-title">Incidents</span>
              <span className="os-eyebrow">Select one on the map or below</span>
            </header>
            {incidents.length === 0 && (
              <p className="empty">No live incidents involve {agencyLabel(agency)}.</p>
            )}
            <div className="mon-list">
              {incidents.map((inc) => {
                const st = statusOf(inc.status);
                const waiting = awaitingAccept(inc, agency);
                return (
                  <button key={inc.id} className={`row${waiting ? ' is-urgent' : ''}`}
                          onClick={() => setSelectedId(inc.id)}>
                    <span className="row-name">{inc.designation}</span>
                    <span className="row-status" style={{ color: st.color }}>{st.label}</span>
                    <span className="row-sub">
                      {waiting ? 'Awaiting your Accept' : `${since(inc.reported_at)} ago`}
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        ) : (
          <div className="detail">
            <button className="btn-ghost detail-back" onClick={() => setSelectedId(null)}>← All incidents</button>

            <header className="detail-head">
              <h2 className="detail-title">{detail.designation}</h2>
              <span className="pill" style={{ color: statusOf(detail.status).color }}>
                {statusOf(detail.status).label}
              </span>
            </header>
            <p className="detail-sub">
              Reported {when(detail.reported_at)} · {detail.report_count} report
              {detail.report_count === 1 ? '' : 's'} ·{' '}
              {Math.round((detail.confidence_score ?? 0) * 100)}% confidence
            </p>

            <div className="card-agencies">
              {(detail.requested_agencies ?? []).map((a) => (
                <span key={a} className={`chip${a === agency ? ' is-mine' : ''}`}>{AGENCY_LABEL[a] ?? a}</span>
              ))}
            </div>

            {error && <div className="note is-error">{error}</div>}

            <section className="accept">
              {/* An unanswered route wins over an earlier Accept: Admin may add
                  your team after your agency already acknowledged. */}
              {canPress ? (
                <>
                  <p className="accept-copy">
                    Admin routed this to{' '}
                    {mine.find((r) => !r.accepted_at)?.organization_name || agencyLabel(agency)}.
                    Accept to confirm your agency has it.
                  </p>
                  <button className="btn-accent" onClick={accept} disabled={busy}>
                    {busy ? 'Accepting…' : 'Accept'}
                  </button>
                  <span className="accept-meta">An acknowledgement only — it does not change the incident&apos;s status.</span>
                </>
              ) : acceptedRoute ? (
                <div className="accept-done">
                  <span className="accept-check">✓</span>
                  <div>
                    <strong>Accepted</strong>
                    <span className="accept-meta">
                      {acceptedRoute.accepted_by_name ? `by ${acceptedRoute.accepted_by_name} · ` : ''}
                      {when(acceptedRoute.accepted_at)}
                    </span>
                  </div>
                </div>
              ) : routedElsewhere ? (
                <p className="accept-copy">
                  Routed to{' '}
                  {(detail.routes ?? []).filter((r) => r.agency === agency).map((r) => r.organization_name).filter(Boolean).join(', ') || 'another team'}
                  , not to your team.
                </p>
              ) : live ? (
                <p className="accept-copy">
                  Not routed to {agencyLabel(agency)} yet. Accept appears once Admin routes it to you.
                </p>
              ) : (
                <p className="accept-copy">This incident is no longer live.</p>
              )}
            </section>

            <dl className="facts">
              <dt>Verified</dt><dd>{detail.verified_at ? `${when(detail.verified_at)}${detail.verified_by_name ? ` · ${detail.verified_by_name}` : ''}` : 'Not yet'}</dd>
              <dt>Units</dt><dd>{detail.active_dispatch_count} responding</dd>
              <dt>On scene</dt><dd>{detail.arrived_at ? when(detail.arrived_at) : '—'}</dd>
              <dt>Fire out</dt><dd>{detail.resolved_at ? when(detail.resolved_at) : '—'}</dd>
            </dl>

            {evidence.length > 0 && (
              <>
                <span className="os-eyebrow">Evidence</span>
                <div className="thumbs">
                  {evidence.map((r) => (
                    r.photo_url
                      ? <a key={r.id} href={r.photo_url} target="_blank" rel="noreferrer"><img src={r.photo_url} alt="Reported scene" /></a>
                      : <span key={r.id} className="thumb-missing">No photo</span>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
