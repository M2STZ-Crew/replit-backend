import { degrees, useAddress } from '../lib/place.js';

/* A point, in words and in numbers: "F. Victor Street, Barangay 76, Pasay ·
 * 14.5378° N, 121.0014° E". `address` is one the record already carries (a
 * hydrant's); without it the street is looked up (lib/place.js) and appears
 * when it is known. `stacked` puts the coordinates on their own line, for a
 * detail panel; inline, the whole line is in the title for when it is cut. */
export default function Place({ lat, lng, address = null, stacked = false }) {
  const looked = useAddress(address ? null : lat, address ? null : lng);
  const street = address || looked;
  const coords = degrees(lat, lng);
  if (stacked) {
    return (
      <span className="ad-place is-stacked">
        {street && <span className="ad-place-street">{street}</span>}
        <span className="ad-place-coords">{coords}</span>
      </span>
    );
  }
  return (
    <span className="ad-place" title={street ? `${street} · ${coords}` : coords}>
      {street && <span className="ad-place-street">{street} · </span>}
      <span className="ad-place-coords">{coords}</span>
    </span>
  );
}
