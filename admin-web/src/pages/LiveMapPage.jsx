import 'leaflet/dist/leaflet.css';

import { useEffect, useMemo, useState } from 'react';
import {
  Circle, MapContainer, Marker, Tooltip, ZoomControl, useMap, useMapEvents,
} from 'react-leaflet';

import { api } from '../api/client.js';
import { CLUSTER_RADIUS_M } from '../components/incidents/AreaMap.jsx';
import { agenciesOf, confidenceOf } from '../components/incidents/IncidentTable.jsx';
import LifecycleChip from '../components/incidents/LifecycleChip.jsx';
import {
  MARKER_KINDS, RISK_CIRCLE_STYLE, markerIcon, riskRadius, unitIcon,
} from '../components/map/markers.js';
import Place from '../components/Place.jsx';
import Icon from '../components/ui/Icon.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import { useLiveUnits } from '../live/useLiveUnits.js';
import { PERM, can, governsAll } from '../lib/access.js';
import { AGENCY_LABEL, statusOf } from '../lib/status.js';
import BarangayLayer, { BARANGAY_ATTRIBUTION } from '../map/BarangayLayer.jsx';
import BaseTiles from '../map/BaseTiles.jsx';
import ZoomGate from '../map/ZoomGate.jsx';
import { groupOnScreen } from '../map/unitGroups.js';
import { t } from '../i18n/i18n.jsx';
import { fireAt, fireName } from '../lib/place.js';

/* Live map (REPLIT (MAIN) 10 · A30 869:3563, A31 869:3858; PRD v13 §4.4):
 * every active Area on the shared map with the water sources, shelters and
 * risk zones; select an Area to see it beside the map and open it.
 *
 * The units on their way to a fire, or at it: an organisation's Admin sees
 * its own (the server sends nothing else — "Other organisations' vehicles are
 * never shown"), the system Admin everyone's. Trucks that would overlap on
 * screen share one marker with their count, and split as the map zooms in,
 * as on the mobile app (src/live/useLiveUnits.js, src/map/unitGroups.js).
 *
 * The gear opens Map settings, the editor for every map element, for the Admin
 * the server lets change map layers (`map.manage`: Fire Volunteer, BFP and
 * central hub Admins, and the system Admin where one exists). */

const PASAY = [14.5378, 121.0014];
const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });

const LAYERS = [
  { key: 'incidents', get label() { return t('Incidents'); }, tone: 'accent' },
  { key: 'water', get label() { return t('Water'); }, tone: 'info' },
  { key: 'shelters', get label() { return t('Shelters'); }, tone: 'ok' },
  { key: 'risk', get label() { return t('Risk zones'); }, tone: 'danger' },
  // v1.12.45: PSA/NAMRIA's barangay outlines, and Pasay's High fire-risk
  // zones (research-based) filled.
  { key: 'barangays', get label() { return t('Barangays'); }, tone: 'info' },
  { key: 'fireRisk', get label() { return t('High fire risk'); }, tone: 'danger' },
];

// Off until switched on: 1,712 outlines are a lot of lines over a busy map.
const OFF_AT_FIRST = ['barangays'];

const SOURCES = [
  { key: 'hydrant', path: 'hydrants', layer: 'water', lat: 'latitude', lng: 'longitude', name: (r) => r.code || t('Hydrant') },
  { key: 'water', path: 'bodies-of-water', layer: 'water', lat: 'latitude', lng: 'longitude', name: (r) => r.name || t('Body of water') },
  { key: 'cistern', path: 'underground-cisterns', layer: 'water', lat: 'latitude', lng: 'longitude', name: (r) => r.name || r.code || t('Cistern') },
  { key: 'shelter', path: 'evacuation-sites', layer: 'shelters', lat: 'latitude', lng: 'longitude', name: (r) => r.name || t('Evacuation site') },
  { key: 'risk', path: 'risk-zones', layer: 'risk', lat: 'centroid_lat', lng: 'centroid_lng', name: (r) => r.name || r.barangay || t('Risk zone') },
];

const AGO = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

/* A hydrant is gray until checked on the ground in the last 6 months
 * (v1.12.46). */
const kindOf = (key, r) => (key === 'hydrant' && !r.verified ? 'hydrantUnverified' : key);

// The fire's ripple reaches as far as the residents it alerts (v1.12.46).
const RIPPLE_M = 100;

function seen(iso) {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  return AGO.format(-Math.round(s / 60), 'minute');
}

/* The units on the map, merged where they would overlap at this zoom. */
function UnitsLayer({ units, onSelect }) {
  const map = useMap();
  const [, setView] = useState(0);
  useMapEvents({ zoomend: () => setView((v) => v + 1), moveend: () => setView((v) => v + 1) });
  const groups = groupOnScreen(units.map((u) => map.latLngToLayerPoint([u.lat, u.lng])));
  return groups.map((g) => {
    const members = g.map((i) => units[i]);
    const lat = members.reduce((s, u) => s + u.lat, 0) / members.length;
    const lng = members.reduce((s, u) => s + u.lng, 0) / members.length;
    const stale = members.every((u) => u.stale);
    const names = members.map((u) => u.label);
    const title = members.length === 1
      ? t('{name}, to {fire}', { name: names[0], fire: fireAt(members[0].designation) })
      : t('{count} units: {names}', { count: members.length, names: names.join(', ') });
    return (
      <Marker
        key={members.map((u) => u.key).join('|')}
        position={[lat, lng]}
        icon={unitIcon(members.length, stale)}
        title={title}
        zIndexOffset={500}
        eventHandlers={{ click: () => onSelect(members[0].incidentId) }}
      >
        <Tooltip direction="top" offset={[0, -18]}>
          {members.map((u) => (
            <span className="rpl-unit-tip" key={u.key}>
              <strong>{u.label}</strong>
              {` · ${fireName(u.designation)} · ${u.stale ? t('last seen {seen}', { seen: seen(u.at) }) : 'live'}`}
            </span>
          ))}
        </Tooltip>
      </Marker>
    );
  });
}

function Selected({ inc, onClose, onOpen }) {
  const first = (inc.accepted_agencies ?? []).map((a) => AGENCY_LABEL[a] ?? a);
  const facts = [
    [t('Location'), <Place lat={inc.centroid_lat} lng={inc.centroid_lng} stacked />],
    [t('Acknowledged'), inc.verified_at ? `${first.join(' · ') || t('Yes')} · ${CLOCK.format(new Date(inc.verified_at))}` : t('Not yet')],
    [t('Requested'), agenciesOf(inc)],
    [t('Reports'), `${inc.report_count} · ${confidenceOf(inc)}`],
  ];
  return (
    <aside className="rpl-map-panel" aria-labelledby="rpl-map-panel-title">
      <div className="rpl-detail-head">
        <div>
          <p className="rpl-eyebrow">{fireName(inc.designation)} · {statusOf(inc.status).label}</p>
          <h2 className="rpl-detail-title" id="rpl-map-panel-title">{fireName(inc.place_line || inc.designation)}</h2>
        </div>
        <button type="button" className="rpl-icon-button" onClick={onClose} aria-label={t('Close')}>
          <span aria-hidden="true">✕</span>
        </button>
      </div>
      <LifecycleChip status={inc.status} />
      <dl className="rpl-facts">
        {facts.map(([t, v]) => (
          <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <button type="button" className="rpl-button rpl-button--primary" onClick={onOpen}>{t('Open incident')}</button>
    </aside>
  );
}

export default function LiveMapPage({ onOpenIncident, onManage }) {
  const { incidents } = useLiveFeed();
  const { console: access } = useConsole();
  const managesMap = can(access, PERM.MANAGE_MAP);
  const [on, setOn] = useState(() => new Set(LAYERS.map((l) => l.key).filter((k) => !OFF_AT_FIRST.includes(k))));
  const [barangays, setBarangays] = useState(null);
  const [legend, setLegend] = useState(true);
  const [points, setPoints] = useState({});
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all(SOURCES.map((s) => api.mapLayer(s.path).catch(() => [])))
      .then((results) => {
        if (!alive) return;
        const next = {};
        SOURCES.forEach((s, i) => { next[s.key] = Array.isArray(results[i]) ? results[i] : []; });
        setPoints(next);
      });
    return () => { alive = false; };
  }, []);

  // The barangay layer, read once either of its switches is on.
  const wantsBarangays = on.has('barangays') || on.has('fireRisk');
  useEffect(() => {
    if (!wantsBarangays || barangays) return undefined;
    let alive = true;
    api.mapLayer('barangays')
      .then((rows) => { if (alive) setBarangays(Array.isArray(rows) ? rows : []); })
      .catch(() => { if (alive) setBarangays([]); });
    return () => { alive = false; };
  }, [wantsBarangays, barangays]);

  const selected = useMemo(() => incidents.find((i) => i.id === selectedId) ?? null, [incidents, selectedId]);
  const units = useLiveUnits(incidents);

  const toggle = (key) => setOn((prev) => {
    const next = new Set(prev);
    if (!next.delete(key)) next.add(key);
    return next;
  });

  return (
    <div className="rpl-map">
      <MapContainer
        center={PASAY}
        zoom={15}
        zoomControl={false}
        attributionControl={false}
        style={{ height: '100%', width: '100%' }}
      >
        <BaseTiles />
        <ZoomControl position="bottomright" />
        {wantsBarangays && (
          <BarangayLayer rows={barangays} outlines={on.has('barangays')} risk={on.has('fireRisk')} />
        )}
        {/* A risk zone is its icon inside the circle the Admin set. The circle
            is the zone, so it shows at every zoom, as on the app. */}
        {on.has('risk') && (points.risk ?? [])
          .filter((r) => r.centroid_lat != null && r.centroid_lng != null)
          .map((r) => (
            <Circle
              key={`zone-${r.id}`}
              center={[r.centroid_lat, r.centroid_lng]}
              radius={riskRadius(r)}
              pathOptions={RISK_CIRCLE_STYLE}
              interactive={false}
            />
          ))}
        {/* The layers' points nearby, from street level in (v1.12.39). */}
        <ZoomGate active={SOURCES.some((s) => on.has(s.layer) && (points[s.key] ?? []).length > 0)}>
        {(near) => SOURCES.filter((s) => on.has(s.layer)).flatMap((s) => (points[s.key] ?? [])
          .filter((r) => r[s.lat] != null && r[s.lng] != null && near(r[s.lat], r[s.lng]))
          .map((r) => (
            <Marker key={`${s.key}-${r.id}`} position={[r[s.lat], r[s.lng]]} icon={markerIcon(kindOf(s.key, r))}>
              <Tooltip direction="top" offset={[0, -18]}>
                {`${MARKER_KINDS[kindOf(s.key, r)].label} · ${s.name(r)}${s.key === 'risk' ? ` · ${Math.round(riskRadius(r))} m` : ''}`}
              </Tooltip>
            </Marker>
          )))}
        </ZoomGate>
        {on.has('incidents') && incidents
          .filter((i) => i.centroid_lat != null && i.centroid_lng != null)
          .flatMap((i) => [
            <Circle
              key={`r-${i.id}`}
              center={[i.centroid_lat, i.centroid_lng]}
              radius={CLUSTER_RADIUS_M}
              pathOptions={{ color: '#ff9066', weight: 1.5, fillColor: '#ff9066', fillOpacity: 0.12 }}
              interactive={false}
            />,
            <Circle
              key={`p-${i.id}`}
              center={[i.centroid_lat, i.centroid_lng]}
              radius={RIPPLE_M}
              pathOptions={{ className: 'rpl-ripple', color: '#ff9066', weight: 2, fillColor: '#ff9066', fillOpacity: 0.08 }}
              interactive={false}
            />,
            <Marker
              key={`i-${i.id}`}
              position={[i.centroid_lat, i.centroid_lng]}
              icon={markerIcon('incident', i.id === selectedId)}
              eventHandlers={{ click: () => setSelectedId(i.id) }}
              title={`${fireName(i.designation)}, ${statusOf(i.status).label}`}
            />,
          ])}
        <UnitsLayer units={units} onSelect={setSelectedId} />
      </MapContainer>

      <div className="rpl-map-chips" role="group" aria-label={t('Map layers')}>
        {LAYERS.map((l) => {
          const active = on.has(l.key);
          return (
            <button
              key={l.key}
              type="button"
              className={`rpl-map-chip rpl-map-chip--${l.tone}${active ? ' is-on' : ''}`}
              onClick={() => toggle(l.key)}
              aria-pressed={active}
            >
              {active ? <span aria-hidden="true">✓</span> : <span className="rpl-map-chip-dot" aria-hidden="true" />}
              {l.label}
            </button>
          );
        })}
      </div>

      <div className="rpl-map-tools">
        <button
          type="button"
          className="rpl-map-tool"
          onClick={() => setLegend((v) => !v)}
          aria-pressed={legend}
          aria-label={legend ? t('Hide the legend') : t('Show the legend')}
          title={t('Legend')}
        >
          <Icon name="map" />
        </button>
        {managesMap && (
          <button
            type="button"
            className="rpl-map-tool"
            onClick={onManage}
            aria-label={t('Map settings')}
            title={t('Map settings')}
          >
            <Icon name="settings" />
          </button>
        )}
      </div>

      {legend && (
        <section className="rpl-map-legend" aria-label={t('Legend')}>
          <p className="rpl-eyebrow rpl-eyebrow--quiet">{t('Legend')}</p>
          <ul>
            {['incident', 'unit', 'hydrant', 'hydrantUnverified', 'water', 'cistern', 'shelter', 'risk'].map((k) => (
              <li key={k}>
                <span className={`rpl-legend-mark rpl-marker-disc--${MARKER_KINDS[k].tone}`} aria-hidden="true">
                  <img src={`/icons/map/${MARKER_KINDS[k].icon ?? k}.svg`} alt="" width="12" height="12" />
                </span>
                {k === 'unit' && governsAll(access) ? t('Responding unit') : MARKER_KINDS[k].label}
              </li>
            ))}
          </ul>
          {on.has('fireRisk') && (
            <p className="rpl-map-legend-note">
              <span className="rpl-legend-swatch rpl-legend-swatch--risk" aria-hidden="true" />
              {t('High fire-risk zone (research-based)')}
            </p>
          )}
          {!governsAll(access) && (
            <p className="rpl-map-legend-note">{t('Other organizations’ vehicles are never shown.')}</p>
          )}
          {wantsBarangays && <p className="rpl-map-legend-note">{BARANGAY_ATTRIBUTION}</p>}
        </section>
      )}

      {selected && (
        <Selected
          inc={selected}
          onClose={() => setSelectedId(null)}
          onOpen={() => onOpenIncident(selected.id)}
        />
      )}
    </div>
  );
}
