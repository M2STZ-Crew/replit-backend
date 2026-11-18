import { useState } from 'react';
import { useMap, useMapEvents } from 'react-leaflet';

import { t } from '../i18n/i18n.jsx';

/* The zoom from which a map draws its layers' points: shelters, hydrants,
 * cisterns, bodies of water (v1.12.38, 18 Nov 2026: Metro Manila's layers went
 * from about 40 points to about 3,100, and "Only nearby, when zoomed in"). The
 * same as the app's (lib/widgets/map_layer_gate.dart). Incidents are drawn at
 * every zoom. */
export const LAYER_MIN_ZOOM = 14;

/* How far past the map's edges its points are still drawn, as a share of the
 * view, so a short pan finds them already there. */
const NEARBY_PAD = 0.25;

function viewOf(map) {
  return { zoom: map.getZoom(), bounds: map.getBounds().pad(NEARBY_PAD) };
}

/* Inside a MapContainer. From LAYER_MIN_ZOOM in, it renders [children], a
 * function of `near(lat, lng)`: true for a point on the screen or just off it,
 * so a page draws only the points nearby. Leaflet would otherwise build every
 * point in Metro Manila; the app's map leaves the off-screen ones out on its
 * own. Below that zoom, while [active] (a layer with points is on), it shows a
 * note to zoom in; [className] places it on a page with a panel over the map. */
export default function ZoomGate({ children, active = true, className }) {
  const map = useMap();
  const [view, setView] = useState(() => viewOf(map));
  // `moveend` follows every pan and every zoom; `resize` a map that changed size.
  useMapEvents({ moveend: () => setView(viewOf(map)), resize: () => setView(viewOf(map)) });
  if (view.zoom >= LAYER_MIN_ZOOM) {
    return children((lat, lng) => view.bounds.contains([lat, lng]));
  }
  if (!active) return null;
  return (
    <div className={className ? `lm-zoom-hint ${className}` : 'lm-zoom-hint'} role="status">
      {t('Zoom in to see the places you turned on')}
    </div>
  );
}
