import L from 'leaflet';
import { useMemo } from 'react';
import { GeoJSON } from 'react-leaflet';

import { t } from '../i18n/i18n.jsx';

/* The barangay layer (v1.12.45; 19 Nov 2026: "barangay map outline refers to
 * the exact geographic boundary lines (polygons) of each barangay, displayed
 * as a clean layer so you can color-code and highlight fire risk zones").
 *
 * `rows` are GET /map/barangays: Metro Manila's 1,712 PSA/NAMRIA outlines,
 * and on the 86 of Pasay's eight High zones a `risk`. Two switches:
 * `outlines` draws every barangay's border; `risk` fills the High fire-risk
 * zones, "research-based", never a BFP designation. The admin-drawn Risk
 * Areas are their own layer. Drawn on a canvas: 50,000 points as SVG would
 * slow the map. */

// A dashed slate line reads as a boundary on light and dark tiles alike.
const OUTLINE = { color: '#5f6f8f', weight: 1.5, opacity: 0.95, dashArray: '5 4', fill: true, fillOpacity: 0 };
const HIGH = { color: '#ff5a4e', weight: 1.5, opacity: 0.9, fillColor: '#ff5a4e', fillOpacity: 0.16 };

export const BARANGAY_ATTRIBUTION = 'Barangay boundaries: PSA/NAMRIA via UN OCHA (CC BY-IGO)';

/* "Barangay 76 Zone 10, Pasay", "Barangay 70 Zone 6, Tondo, Manila",
 * "Bel-Air, Makati": the full form a fire's place uses. */
export function barangayPlace(b) {
  const name = b.kind === 'numbered' && b.zone != null ? `${b.name} Zone ${b.zone}` : b.name;
  return [name, b.district, b.city].filter(Boolean).join(', ');
}

function feature(row) {
  try {
    return { type: 'Feature', geometry: JSON.parse(row.area_geojson), properties: row };
  } catch {
    return null;
  }
}

export default function BarangayLayer({ rows, outlines, risk }) {
  const renderer = useMemo(() => L.canvas({ padding: 0.3 }), []);
  const data = useMemo(() => ({
    type: 'FeatureCollection',
    features: (rows ?? [])
      .filter((r) => r.area_geojson && (outlines || (risk && r.risk)))
      .map(feature)
      .filter(Boolean),
  }), [rows, outlines, risk]);

  if (data.features.length === 0) return null;
  return (
    <GeoJSON
      // A new layer when what is drawn changes: GeoJSON keeps its first data.
      key={`${outlines ? 'o' : ''}${risk ? 'r' : ''}${data.features.length}`}
      data={data}
      renderer={renderer}
      style={(f) => (risk && f.properties.risk ? HIGH : OUTLINE)}
      onEachFeature={(f, layer) => {
        const b = f.properties;
        const tip = risk && b.risk
          ? `${barangayPlace(b)} · ${t('High fire-risk zone (research-based)')}`
          : barangayPlace(b);
        layer.bindTooltip(tip, { sticky: true, direction: 'top' });
      }}
    />
  );
}
