/* Which units share one marker at the current zoom — the mobile app's rule
 * (lib/widgets/unit_groups.dart, v1.12.7), so a truck reads the same on every
 * screen.
 *
 * Grouped by where they are on the screen, not by road: trucks in convoy merge,
 * and as the Admin zooms in, or the trucks spread out, they split back into
 * their own markers. A group never grows wider than the merge radius around its
 * centre, so the merged marker sits where its trucks are rather than between
 * two far-apart ones. */

/// How close, in screen pixels, two units' centres may be before their
/// markers merge: a marker is 38 px across, so "they would touch or overlap"
/// with a little air.
export const UNIT_MERGE_RADIUS = 44;

/// [points] are screen positions ({x, y}) in a stable order; returns groups of
/// indices into it, each in that same order.
export function groupOnScreen(points, radius = UNIT_MERGE_RADIUS) {
  const groups = [];
  const centres = [];
  points.forEach((p, i) => {
    let best = -1;
    let bestDistance = Infinity;
    centres.forEach((c, g) => {
      const d = Math.hypot(p.x - c.x, p.y - c.y);
      if (d <= radius && d < bestDistance) {
        best = g;
        bestDistance = d;
      }
    });
    if (best < 0) {
      groups.push([i]);
      centres.push({ x: p.x, y: p.y });
    } else {
      const members = groups[best];
      members.push(i);
      const c = centres[best];
      c.x += (p.x - c.x) / members.length;
      c.y += (p.y - c.y) / members.length;
    }
  });
  return groups;
}

/// The count on a merged marker: "2" … "9", then "9+".
export function groupCount(n) {
  return n > 9 ? '9+' : String(n);
}
