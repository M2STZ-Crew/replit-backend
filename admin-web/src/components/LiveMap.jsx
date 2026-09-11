import 'leaflet/dist/leaflet.css';
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet';

import { statusOf } from '../lib/status.js';
import { TILE_ATTRIBUTION, TILE_MAX_ZOOM, TILE_URL } from '../map/tiles.js';

const PASAY = [14.5378, 121.0014];

// Colour for GIS layer points (only the layers we have backend data for).
export const LAYER_COLORS = {
  evac: '#22C55E',
  risk: '#FF9066',
  hydrants: '#767575',
  water: '#767575',
};

/// A shelter outside Pasay (v10 Section 2.4) is drawn as a dashed ring rather
/// than a filled dot, so an operator sees at a glance that the destination is
/// in another city.
export const OUTSIDE_PASAY_STYLE = {
  color: LAYER_COLORS.evac,
  weight: 2.5,
  dashArray: '3 3',
  fillColor: '#0b0b0b',
  fillOpacity: 0.85,
};

function dot(color, weight = 1.5) {
  return { color: '#ffffff', weight, fillColor: color, fillOpacity: 0.95 };
}

/// The dark basemap with incident markers and toggleable GIS layer points.
/// `enabled` is a Set of layer keys; `layerPoints[key]` is an array of
/// { lat, lng, outside?, label? }. `onSelectIncident`, when given, makes the
/// incident markers open the incident. The tile source lives in map/tiles.js.
export default function LiveMap({ incidents = [], layerPoints = {}, enabled, onSelectIncident }) {
  return (
    <MapContainer
      center={PASAY}
      zoom={13}
      style={{ height: '100%', width: '100%', background: '#0b0b0b' }}
      zoomControl={false}
      attributionControl={false}
    >
      <TileLayer url={TILE_URL} maxZoom={TILE_MAX_ZOOM} />

      {Object.entries(LAYER_COLORS).flatMap(([key, color]) =>
        enabled.has(key)
          ? (layerPoints[key] || []).map((p, i) => (
              <CircleMarker
                key={`${key}-${i}`}
                center={[p.lat, p.lng]}
                radius={p.outside ? 8 : 6}
                pathOptions={p.outside ? OUTSIDE_PASAY_STYLE : dot(color, 1)}
              >
                {p.label && <Tooltip>{p.outside ? `${p.label} (outside Pasay)` : p.label}</Tooltip>}
              </CircleMarker>
            ))
          : [],
      )}

      {enabled.has('incidents') &&
        incidents.map((inc) => {
          const lat = inc.centroid_lat;
          const lng = inc.centroid_lng;
          if (lat == null || lng == null) return null;
          const st = statusOf(inc.status);
          return (
            <CircleMarker
              key={inc.id}
              center={[lat, lng]}
              radius={9}
              pathOptions={dot(st.color)}
              eventHandlers={onSelectIncident ? { click: () => onSelectIncident(inc) } : undefined}
            >
              <Tooltip>
                {(inc.designation || 'Incident')} · {st.label}
              </Tooltip>
            </CircleMarker>
          );
        })}

      {/* Attribution is a licence condition for both tile providers.
          Leaflet's own control is off so it can be styled to the design. */}
      <div className="lm-attribution">{TILE_ATTRIBUTION}</div>
    </MapContainer>
  );
}
