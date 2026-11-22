import { Circle, CircleMarker } from 'react-leaflet';

/* A live fire's pulse on every console map (v1.12.48; 22 Nov 2026: "make the
 * animation of the pulsing incident in the web too"; answered "Ring + marker
 * halo"): the true 100 m ring, as on the app, and a halo around the marker
 * that still shows zoomed out, where 100 m is smaller than the marker. Under
 * reduced motion both stand still (styles/pass6-map.css).
 *
 * `className` is a prop of its own, never inside pathOptions: react-leaflet
 * applies pathOptions with setStyle once the path exists, and Leaflet only
 * reads a class as it creates the path. The v1.12.46 ripple had it there, so
 * it moved on the dev server (StrictMode mounts twice) and never in
 * production. */

const RIPPLE_M = 100; // as far as the residents it alerts
const HALO_PX = 38; // the marker is about 40 px across

// Deeper than the brand's coral, which is lost on light map tiles.
const EDGE = '#ee5a24';
const GLOW = '#ff7943';
const RING = { color: EDGE, weight: 2, fillColor: GLOW, fillOpacity: 0.1 };
const HALO = { color: EDGE, weight: 3, fillColor: GLOW, fillOpacity: 0.25 };

export default function FirePulse({ lat, lng }) {
  const at = [lat, lng];
  return (
    <>
      <Circle center={at} radius={RIPPLE_M} className="rpl-ripple" interactive={false} pathOptions={RING} />
      <CircleMarker center={at} radius={HALO_PX} className="rpl-halo" interactive={false} pathOptions={HALO} />
    </>
  );
}
