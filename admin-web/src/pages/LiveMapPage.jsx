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
import { PERM, can } from '../lib/access.js';
import { AGENCY_LABEL, statusOf } from '../lib/status.js';
import BaseTiles from '../map/BaseTiles.jsx';
import { groupOnScreen } from '../map/unitGroups.js';

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
  { key: 'incidents', label: 'Incidents', tone: 'accent' },
  { key: 'water', label: 'Water', tone: 'info' },
  { key: 'shelters', label: 'Shelters', tone: 'ok' },
  { key: 'risk', label: 'Risk zones', tone: 'danger' },
];

const SOURCES = [
  { key: 'hydrant', path: 'hydrants', layer: 'water', lat: 'latitude', lng: 'longitude', name: (r) => r.code || 'Hydrant' },
  { key: 'water', path: 'bodies-of-water', layer: 'water', lat: 'latitude', lng: 'longitude', name: (r) => r.name || 'Body of water' },
  { key: 'cistern', path: 'underground-cisterns', layer: 'water', lat: 'latitude', lng: 'longitude', name: (r) => r.name || r.code || 'Cistern' },
  { key: 'shelter', path: 'evacuation-sites', layer: 'shelters', lat: 'latitude', lng: 'longitude', name: (r) => r.name || 'Evacuation site' },
  { key: 'risk', path: 'risk-zones', layer: 'risk', lat: 'centroid_lat', lng: 'centroid_lng', name: (r) => r.name || r.barangay || 'Risk zone' },
];

const AGO = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

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
      ? `${names[0]}, to ${members[0].designation}`
      : `${members.length} units: ${names.join(', ')}`;
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
            <span className="ad-unit-tip" key={u.key}>
              <strong>{u.label}</strong>
              {` · ${u.designation} · ${u.stale ? `last seen ${seen(u.at)}` : 'live'}`}
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
    ['Location', <Place lat={inc.centroid_lat} lng={inc.centroid_lng} stacked />],
    ['Acknowledged', inc.verified_at ? `${first.join(' · ') || 'Yes'} · ${CLOCK.format(new Date(inc.verified_at))}` : 'Not yet'],
    ['Requested', agenciesOf(inc)],
    ['Reports', `${inc.report_count} · ${confidenceOf(inc)}`],
  ];
  return (
    <aside className="ad-map-panel" aria-labelledby="ad-map-panel-title">
      <div className="ad-detail-head">
        <div>
          <p className="ad-eyebrow">{inc.designation} · {statusOf(inc.status).label}</p>
          <h2 className="ad-detail-title" id="ad-map-panel-title">{inc.designation}</h2>
        </div>
        <button type="button" className="ad-icon-button" onClick={onClose} aria-label="Close">
          <span aria-hidden="true">✕</span>
        </button>
      </div>
      <LifecycleChip status={inc.status} />
      <dl className="ad-facts">
        {facts.map(([t, v]) => (
          <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <button type="button" className="ad-button ad-button--primary" onClick={onOpen}>Open incident</button>
    </aside>
  );
}

export default function LiveMapPage({ onOpenIncident, onManage }) {
  const { incidents } = useLiveFeed();
  const { console: access } = useConsole();
  const managesMap = can(access, PERM.MANAGE_MAP);
  const [on, setOn] = useState(() => new Set(LAYERS.map((l) => l.key)));
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

  const selected = useMemo(() => incidents.find((i) => i.id === selectedId) ?? null, [incidents, selectedId]);
  const units = useLiveUnits(incidents);

  const toggle = (key) => setOn((prev) => {
    const next = new Set(prev);
    if (!next.delete(key)) next.add(key);
    return next;
  });

  return (
    <div className="ad-map">
      <MapContainer
        center={PASAY}
        zoom={15}
        zoomControl={false}
        attributionControl={false}
        style={{ height: '100%', width: '100%' }}
      >
        <BaseTiles />
        <ZoomControl position="bottomright" />
        {SOURCES.filter((s) => on.has(s.layer)).flatMap((s) => (points[s.key] ?? [])
          .filter((r) => r[s.lat] != null && r[s.lng] != null)
          .flatMap((r) => [
            // A risk zone is its icon inside the circle the Admin set.
            s.key === 'risk' && (
              <Circle
                key={`zone-${r.id}`}
                center={[r[s.lat], r[s.lng]]}
                radius={riskRadius(r)}
                pathOptions={RISK_CIRCLE_STYLE}
                interactive={false}
              />
            ),
            <Marker key={`${s.key}-${r.id}`} position={[r[s.lat], r[s.lng]]} icon={markerIcon(s.key)}>
              <Tooltip direction="top" offset={[0, -18]}>
                {`${MARKER_KINDS[s.key].label} · ${s.name(r)}${s.key === 'risk' ? ` · ${Math.round(riskRadius(r))} m` : ''}`}
              </Tooltip>
            </Marker>,
          ].filter(Boolean)))}
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
            <Marker
              key={`i-${i.id}`}
              position={[i.centroid_lat, i.centroid_lng]}
              icon={markerIcon('incident', i.id === selectedId)}
              eventHandlers={{ click: () => setSelectedId(i.id) }}
              title={`${i.designation}, ${statusOf(i.status).label}`}
            />,
          ])}
        <UnitsLayer units={units} onSelect={setSelectedId} />
      </MapContainer>

      <div className="ad-map-chips" role="group" aria-label="Map layers">
        {LAYERS.map((l) => {
          const active = on.has(l.key);
          return (
            <button
              key={l.key}
              type="button"
              className={`ad-map-chip ad-map-chip--${l.tone}${active ? ' is-on' : ''}`}
              onClick={() => toggle(l.key)}
              aria-pressed={active}
            >
              {active ? <span aria-hidden="true">✓</span> : <span className="ad-map-chip-dot" aria-hidden="true" />}
              {l.label}
            </button>
          );
        })}
      </div>

      <div className="ad-map-tools">
        <button
          type="button"
          className="ad-map-tool"
          onClick={() => setLegend((v) => !v)}
          aria-pressed={legend}
          aria-label={legend ? 'Hide the legend' : 'Show the legend'}
          title="Legend"
        >
          <Icon name="map" />
        </button>
        {managesMap && (
          <button
            type="button"
            className="ad-map-tool"
            onClick={onManage}
            aria-label="Map settings"
            title="Map settings"
          >
            <Icon name="settings" />
          </button>
        )}
      </div>

      {legend && (
        <section className="ad-map-legend" aria-label="Legend">
          <p className="ad-eyebrow ad-eyebrow--quiet">Legend</p>
          <ul>
            {['incident', 'unit', 'hydrant', 'water', 'cistern', 'shelter', 'risk'].map((k) => (
              <li key={k}>
                <span className={`ad-legend-mark ad-marker-disc--${MARKER_KINDS[k].tone}`} aria-hidden="true">
                  <img src={`/icons/map/${k}.svg`} alt="" width="12" height="12" />
                </span>
                {k === 'unit' && access?.variant === 'system' ? 'Responding unit' : MARKER_KINDS[k].label}
              </li>
            ))}
          </ul>
          {access?.variant !== 'system' && (
            <p className="ad-map-legend-note">Other organizations’ vehicles are never shown.</p>
          )}
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
