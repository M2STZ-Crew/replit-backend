import 'leaflet/dist/leaflet.css';
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet';

const PASAY = [14.5378, 121.0014];

// Colour for GIS layer points (only the layers we have backend data for).
export const LAYER_COLORS = {
  evac: '#22C55E',
  risk: '#FF9066',
  hydrants: '#767575',
  water: '#767575',
};

function incidentColor(status) {
  switch (status) {
    case 'verified':
      return '#3B82F6';
    case 'dispatched':
    case 'en_route':
      return '#FF9066';
    case 'arrived':
    case 'resolved':
      return '#22C55E';
    case 'rejected':
      return '#FF544E';
    default:
      return '#EAB308'; // pending
  }
}

function dot(color, weight = 1.5) {
  return { color: '#ffffff', weight, fillColor: color, fillOpacity: 0.95 };
}

/// CARTO dark-tile map (free, no key) with incident markers + toggleable GIS
/// layer points. `enabled` is a Set of layer keys; `layerPoints[key]` is an
/// array of { lat, lng }.
export default function LiveMap({ incidents = [], layerPoints = {}, enabled }) {
  return (
    <MapContainer
      center={PASAY}
      zoom={13}
      style={{ height: '100%', width: '100%', background: '#0b0b0b' }}
      zoomControl={false}
      attributionControl={false}
    >
      <TileLayer url="https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png" />

      {Object.entries(LAYER_COLORS).flatMap(([key, color]) =>
        enabled.has(key)
          ? (layerPoints[key] || []).map((p, i) => (
              <CircleMarker
                key={`${key}-${i}`}
                center={[p.lat, p.lng]}
                radius={6}
                pathOptions={dot(color, 1)}
              />
            ))
          : [],
      )}

      {enabled.has('incidents') &&
        incidents.map((inc) => {
          const lat = inc.centroid_lat;
          const lng = inc.centroid_lng;
          if (lat == null || lng == null) return null;
          return (
            <CircleMarker
              key={inc.id}
              center={[lat, lng]}
              radius={9}
              pathOptions={dot(incidentColor(inc.status))}
            >
              <Tooltip>
                {(inc.designation || 'Incident')} · {inc.status}
              </Tooltip>
            </CircleMarker>
          );
        })}
    </MapContainer>
  );
}
