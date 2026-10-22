import L from 'leaflet';

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
  unit: { tone: 'unit', label: 'Your organisation’s unit' },
};

export const MARKER_KINDS = KINDS;

const cache = new Map();

export function markerIcon(kind, selected = false) {
  const key = `${kind}:${selected}`;
  if (cache.has(key)) return cache.get(key);
  const { tone } = KINDS[kind] ?? KINDS.incident;
  const size = 48;
  const icon = L.divIcon({
    className: 'ad-marker',
    html:
      `<span class="ad-marker-backing${selected ? ' is-selected' : ''}"></span>` +
      `<span class="ad-marker-disc ad-marker-disc--${tone}${selected ? ' is-selected' : ''}">` +
      `<img src="/icons/map/${kind}.svg" alt="" width="${selected ? 24 : 20}" height="${selected ? 24 : 20}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
  cache.set(key, icon);
  return icon;
}
