import { useEffect } from 'react';
import { TileLayer, useMap } from 'react-leaflet';

import { TILE_MAX_ZOOM, TILE_URL } from './tiles.js';

/* The console's base map tiles, for every map.
 *
 * Leaflet measures its box once. When the page around a map changes size —
 * an alarm banner comes or goes above it, the sidebar or the window resizes —
 * it would go on drawing tiles for the old box and leave the rest of the map
 * black. So whenever the box changes, Leaflet is told to measure again. */
export default function BaseTiles() {
  const map = useMap();
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return <TileLayer url={TILE_URL} maxZoom={TILE_MAX_ZOOM} />;
}
