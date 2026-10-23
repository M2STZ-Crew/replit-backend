import { useEffect, useState } from 'react';

import { mapboxToken } from '../map/tiles.js';

/* Where a point is, in words: the street and barangay beside its coordinates.
 *
 * PRD v13 §4.10 has the server store a resolved address on each report; it
 * does not yet, so the console looks the street up itself with Mapbox reverse
 * geocoding and the public token it already uses for map tiles. Each point is
 * asked about once per browser — answers are kept, keyed to about a metre —
 * and at most four lookups run at a time, so a long list does not flood the
 * service. Without a token, or when a lookup fails, the coordinates stand on
 * their own; nothing is guessed. */

const STORE = 'replit.places.v1';
const KEEP = 500;
const AT_ONCE = 4;

const keyOf = (lat, lng) => `${lat.toFixed(5)},${lng.toFixed(5)}`;

/// "14.5378° N, 121.0014° E".
export function degrees(lat, lng) {
  if (lat == null || lng == null) return 'Location unknown';
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lng).toFixed(4)}° ${lng >= 0 ? 'E' : 'W'}`;
}

function loadSaved() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) || '[]');
    return new Map(Array.isArray(saved) ? saved : []);
  } catch {
    return new Map();
  }
}

const known = loadSaved();
const asking = new Map();
const waiting = [];
let running = 0;

function remember(key, address) {
  known.delete(key);
  known.set(key, address);
  while (known.size > KEEP) known.delete(known.keys().next().value);
  try {
    localStorage.setItem(STORE, JSON.stringify([...known]));
  } catch {
    /* storage full or blocked — the answer still holds for this session */
  }
}

/// "12 F. Victor Street, Barangay 76, Pasay" from a Mapbox reverse-geocoding
/// answer: the most specific place found, then its neighbourhood (or
/// locality) and city. Null when the answer names nothing useful.
export function placeName(json) {
  const feature = json?.features?.[0];
  if (!feature) return null;
  const context = Array.isArray(feature.context) ? feature.context : [];
  const part = (kind) => context.find((c) => String(c.id ?? '').startsWith(`${kind}.`))?.text;
  const types = feature.place_type ?? [];
  const head = types.includes('address') && feature.address
    ? `${feature.address} ${feature.text}`
    : feature.text;
  const parts = [head, part('neighborhood') ?? part('locality'), part('place')]
    .filter((p) => typeof p === 'string' && p.trim());
  const unique = parts.filter((p, i) => parts.indexOf(p) === i);
  return unique.length ? unique.join(', ') : null;
}

async function ask(lat, lng) {
  const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${lng},${lat}.json`
    + `?language=en&access_token=${encodeURIComponent(mapboxToken)}`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`geocoding ${resp.status}`);
  return placeName(await resp.json());
}

function pump() {
  while (running < AT_ONCE && waiting.length) {
    const job = waiting.shift();
    running += 1;
    ask(job.lat, job.lng)
      .then((address) => {
        remember(job.key, address);
        job.resolve(address);
      })
      .catch(() => job.resolve(null))
      .finally(() => {
        running -= 1;
        asking.delete(job.key);
        pump();
      });
  }
}

/// The address already known for a point, without asking (undefined when it
/// has not been looked up; null when the lookup found nothing).
export function knownAddress(lat, lng) {
  if (lat == null || lng == null) return undefined;
  return known.get(keyOf(lat, lng));
}

/// The street address of a point, or null.
export function addressFor(lat, lng) {
  if (lat == null || lng == null || !mapboxToken) return Promise.resolve(null);
  const key = keyOf(lat, lng);
  if (known.has(key)) return Promise.resolve(known.get(key));
  if (!asking.has(key)) {
    asking.set(key, new Promise((resolve) => {
      waiting.push({ key, lat, lng, resolve });
      pump();
    }));
  }
  return asking.get(key);
}

/// The address of a point once it is known; null until then or without one.
export function useAddress(lat, lng) {
  const [address, setAddress] = useState(() => knownAddress(lat, lng) ?? null);
  useEffect(() => {
    let alive = true;
    setAddress(knownAddress(lat, lng) ?? null);
    addressFor(lat, lng).then((a) => { if (alive) setAddress(a); });
    return () => { alive = false; };
  }, [lat, lng]);
  return address;
}
