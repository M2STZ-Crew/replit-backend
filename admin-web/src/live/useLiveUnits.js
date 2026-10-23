import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';

/* The units on the way to, or at, the fires on the live map (REPLIT (MAIN)
 * 10 · A30: "Your organisation's unit").
 *
 * For every Area with someone going (en route or on scene), its dispatches and
 * the latest fix of each responder on it, every few seconds. The server sends
 * an organisation's Admin only its own people's fixes — "Other organisations'
 * vehicles are never shown" — and the system Admin everyone's; a dispatch
 * with no fix is simply not drawn. As for a resident following the trucks
 * (app/services/tracking.py), the crew of one truck each stream from their
 * own phone and are one unit, at the freshest of their fixes. */

export const TRACKED = ['en_route', 'arrived'];
const EVERY_MS = 6000;
// A fix older than this is drawn dimmed: the server's own tracking_stale_after_seconds.
export const STALE_AFTER_MS = 60_000;

async function unitsOf(incident) {
  const [dispatches, fixes] = await Promise.all([
    api.incidentDispatches(incident.id),
    api.responderLocations(incident.id),
  ]);
  const latest = new Map();
  for (const f of Array.isArray(fixes) ? fixes : []) {
    const prev = latest.get(f.responder_id);
    if (!prev || new Date(f.captured_at) > new Date(prev.captured_at)) latest.set(f.responder_id, f);
  }
  const groups = new Map();
  for (const d of Array.isArray(dispatches) ? dispatches : []) {
    if (d.status !== 'active') continue;
    const vehicle = (d.vehicle_name || '').trim();
    const key = vehicle ? `v:${vehicle.toLowerCase()}` : `r:${d.responder_id}`;
    if (!groups.has(key)) groups.set(key, { vehicle, crew: [] });
    groups.get(key).crew.push(d);
  }
  const units = [];
  for (const [key, { vehicle, crew }] of groups) {
    const withFix = crew.map((d) => latest.get(d.responder_id)).filter(Boolean);
    if (withFix.length === 0) continue;
    const best = withFix.reduce((a, b) => (new Date(b.captured_at) > new Date(a.captured_at) ? b : a));
    units.push({
      key: `${incident.id}:${key}`,
      incidentId: incident.id,
      designation: incident.designation,
      label: vehicle || crew[0].responder_name || 'Unit',
      crew: crew.map((d) => d.responder_name).filter(Boolean),
      lat: best.lat,
      lng: best.lng,
      at: best.captured_at,
    });
  }
  return units;
}

/// The live units for [incidents], refreshed every few seconds while the
/// page is visible. Keeps the last good picture through a failed refresh.
export function useLiveUnits(incidents) {
  const tracked = useMemo(
    () => (incidents ?? []).filter((i) => TRACKED.includes(i.status)),
    [incidents],
  );
  // Refetch when the set of Areas changes, not on every feed tick.
  const ids = tracked.map((i) => i.id).sort().join(',');
  const [units, setUnits] = useState([]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!ids) {
      setUnits([]);
      return undefined;
    }
    let alive = true;
    let timer = null;
    const load = async () => {
      if (document.visibilityState !== 'hidden') {
        const results = await Promise.all(tracked.map((i) => unitsOf(i).catch(() => null)));
        if (!alive) return;
        setUnits((prev) => {
          // An Area whose read failed keeps its last units.
          const kept = prev.filter((u) => results[tracked.findIndex((i) => i.id === u.incidentId)] === null);
          return [...kept, ...results.filter(Boolean).flat()];
        });
        setNow(Date.now());
      }
      if (alive) timer = setTimeout(load, EVERY_MS);
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // `tracked` follows `ids`; re-running on its identity would refetch on every tick.
  }, [ids]);

  return useMemo(
    () => units.map((u) => ({ ...u, stale: now - new Date(u.at).getTime() > STALE_AFTER_MS })),
    [units, now],
  );
}
