import { useEffect, useState } from 'react';
import { TileLayer, useMap } from 'react-leaflet';

import { TILE_MAX_ZOOM, tileUrl } from './tiles.js';

/* The console's ground, as theme.js last set it on <html>. */
function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

/* The ground, kept current: Settings flips data-theme on <html>, and every map
 * on screen follows without a reload. */
export function useConsoleTheme() {
  const [theme, setTheme] = useState(currentTheme);
  useEffect(() => {
    if (typeof MutationObserver === 'undefined') return undefined;
    const observer = new MutationObserver(() => setTheme(currentTheme()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    return () => observer.disconnect();
  }, []);
  return theme;
}

/* The console's base map tiles, for every map.
 *
 * Leaflet measures its box once. When the page around a map changes size —
 * an alarm banner comes or goes above it, the sidebar or the window resizes —
 * it would go on drawing tiles for the old box and leave the rest of the map
 * black. So whenever the box changes, Leaflet is told to measure again.
 *
 * The map's style follows the console's ground: Mapbox's dark map on the dark
 * ground, its light map on the light one. */
export default function BaseTiles() {
  const map = useMap();
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  const theme = useConsoleTheme();
  return <TileLayer key={theme} url={tileUrl(theme)} maxZoom={TILE_MAX_ZOOM} />;
}
