import 'leaflet/dist/leaflet.css';

import L from 'leaflet';
import { Circle, MapContainer, Marker, TileLayer } from 'react-leaflet';

import { TILE_MAX_ZOOM, TILE_URL } from '../../map/tiles.js';

/* One or more Areas on the map (REPLIT (MAIN) 10 · A23, A27; 04 · Map
 * marker, Area radius): the incident marker — the brand's solid step with a
 * white flame, white edge — inside its radius. The radius is the server's
 * clustering radius (app/services/clustering.py, 300 m); the design draws
 * v13's 100 m, which the server does not use yet, so the circle shows what
 * actually joins reports. A second Area is drawn smaller, as the one that
 * would be merged away. */

export const CLUSTER_RADIUS_M = 300;

function markerIcon(small) {
  const size = small ? 36 : 44;
  return L.divIcon({
    className: 'ad-area-marker',
    html: `<span class="ad-area-marker-plate${small ? ' is-small' : ''}"><img src="/icons/flame.svg" alt="" width="${small ? 16 : 20}" height="${small ? 16 : 20}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

export default function AreaMap({ lat, lng, label, areas, height }) {
  const list = (areas ?? [{ lat, lng, label }]).filter((a) => a.lat != null && a.lng != null);
  if (list.length === 0) {
    return <div className="ad-area-map is-empty">No location recorded for this Area.</div>;
  }
  const centre = [
    list.reduce((s, a) => s + a.lat, 0) / list.length,
    list.reduce((s, a) => s + a.lng, 0) / list.length,
  ];
  return (
    <div
      className="ad-area-map"
      style={height ? { height } : undefined}
      role="img"
      aria-label={`Map of ${list.map((a) => a.label).join(' and ')}`}
    >
      <MapContainer
        center={centre}
        zoom={list.length > 1 ? 16 : 15}
        zoomControl={false}
        attributionControl={false}
        scrollWheelZoom={false}
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer url={TILE_URL} maxZoom={TILE_MAX_ZOOM} />
        {list.map((a, i) => (
          <Circle
            key={`r-${i}`}
            center={[a.lat, a.lng]}
            radius={CLUSTER_RADIUS_M}
            pathOptions={{ color: '#ff9066', weight: 1.5, fillColor: '#ff9066', fillOpacity: 0.12 }}
          />
        ))}
        {list.map((a, i) => (
          <Marker key={`m-${i}`} position={[a.lat, a.lng]} icon={markerIcon(i > 0)} interactive={false} keyboard={false} />
        ))}
      </MapContainer>
    </div>
  );
}
