import L from 'leaflet';

import { groupCount } from '../../map/unitGroups.js';

/* Map markers (REPLIT (MAIN) 04 · Map marker, pass 3): a rounded square in
 * the category's 700 step with a white outline and a white filled glyph, on
 * a ground-coloured backing plate so the edge holds on light fallback tiles.
 * Selected grows from 32 to 40 px with a 2 px outline. The glyphs in
 * public/icons/map are the Figma exports. */

const KINDS = {
  incident: { tone: 'incident', label: 'Active incident Area' },
  hydrant: { tone: 'water', label: 'Hydrant' },
  water: { tone: 'water', label: 'Body of water' },
  cistern: { tone: 'water', label: 'Cistern' },
  shelter: { tone: 'shelter', label: 'Evacuation site' },
  risk: { tone: 'risk', label: 'Risk zone' },
  unit: { tone: 'unit', label: 'Your organization’s unit' },
};

export const MARKER_KINDS = KINDS;

/// A unit on the live map, or several that would overlap merged into one
/// (the mobile app's UnitGroupMarker): the truck, a second plate peeking out
/// behind it when there are more, and the count at its top right. Dimmed
/// when every truck in it has stopped sending its position.
export function unitIcon(count = 1, stale = false) {
  const key = `unit-group:${count > 9 ? 10 : count}:${stale}`;
  if (cache.has(key)) return cache.get(key);
  const size = 48;
  const many = count > 1;
  const icon = L.divIcon({
    className: `rpl-marker rpl-unit${stale ? ' is-stale' : ''}`,
    html:
      (many ? '<span class="rpl-marker-backing rpl-unit-behind"></span>' : '')
      + (many ? '<span class="rpl-marker-disc rpl-marker-disc--unit rpl-unit-behind"></span>' : '')
      + '<span class="rpl-marker-backing"></span>'
      + '<span class="rpl-marker-disc rpl-marker-disc--unit">'
      + '<img src="/icons/map/unit.svg" alt="" width="20" height="20"></span>'
      + (many ? `<span class="rpl-unit-count">${groupCount(count)}</span>` : ''),
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
  cache.set(key, icon);
  return icon;
}

/// A risk zone's circle until the Admin sets one (risk_zones.radius_m), and
/// how far the editor lets it go (the server's own bounds).
export const RISK_RADIUS_M = 150;
export const RISK_RADIUS_MIN_M = 10;
export const RISK_RADIUS_MAX_M = 5000;

/// The circle a risk zone is drawn in, on every map.
export const RISK_CIRCLE_STYLE = { color: '#e5675f', weight: 1.5, fillColor: '#e5675f', fillOpacity: 0.12 };

export function riskRadius(zone) {
  const r = Number(zone?.radius_m);
  return Number.isFinite(r) && r > 0 ? r : RISK_RADIUS_M;
}

const cache = new Map();

export function markerIcon(kind, selected = false) {
  const key = `${kind}:${selected}`;
  if (cache.has(key)) return cache.get(key);
  const { tone } = KINDS[kind] ?? KINDS.incident;
  const size = 48;
  const icon = L.divIcon({
    className: 'rpl-marker',
    html:
      `<span class="rpl-marker-backing${selected ? ' is-selected' : ''}"></span>` +
      `<span class="rpl-marker-disc rpl-marker-disc--${tone}${selected ? ' is-selected' : ''}">` +
      `<img src="/icons/map/${kind}.svg" alt="" width="${selected ? 24 : 20}" height="${selected ? 24 : 20}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
  cache.set(key, icon);
  return icon;
}
