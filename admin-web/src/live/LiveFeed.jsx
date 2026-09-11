import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { announce } from '../sound/cues.js';

/// The live incident feed behind the console's red badges and sounds
/// (Master Context v10, Sections 2.8 and 2.9).
///
/// Polls /incidents on the Section 6 cadence (10–15 s). An incident this session
/// has not seen before plays its category's cue; the very first load plays
/// nothing, or signing in would sound every open incident at once.
///
/// "New since you last looked" is per surface: each screen records when it was
/// last viewed, in localStorage so it survives a reload.

const POLL_MS = 12_000;
const SEEN_KEY = 'replit.seen.v1';

const LiveFeedContext = createContext(null);

function readSeen() {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) || '{}');
  } catch {
    return {};
  }
}

export function LiveFeedProvider({ children }) {
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [seenAt, setSeenAt] = useState(readSeen);
  const known = useRef(null);

  const refresh = useCallback(async () => {
    const [list, s] = await Promise.all([
      api.incidents({ limit: 200 }).catch(() => null),
      api.incidentStats().catch(() => null),
    ]);
    if (list) {
      if (known.current) {
        const fresh = list.filter((inc) => !known.current.has(inc.id));
        if (fresh.length) announce(fresh);
      } else {
        known.current = new Set();
      }
      list.forEach((inc) => known.current.add(inc.id));
      setIncidents(list);
      setLoaded(true);
    }
    if (s) setStats(s);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const markSeen = useCallback((surface) => {
    setSeenAt((prev) => {
      const next = { ...prev, [surface]: new Date().toISOString() };
      try {
        localStorage.setItem(SEEN_KEY, JSON.stringify(next));
      } catch {
        /* ignore — badges just reset on reload */
      }
      return next;
    });
  }, []);

  const newSince = useCallback(
    (iso) => {
      const t = iso ? new Date(iso).getTime() : 0;
      return incidents.filter((inc) => new Date(inc.reported_at).getTime() > t);
    },
    [incidents],
  );

  return (
    <LiveFeedContext.Provider
      value={{ incidents, stats, loaded, seenAt, markSeen, newSince, refresh }}
    >
      {children}
    </LiveFeedContext.Provider>
  );
}

export function useLiveFeed() {
  return useContext(LiveFeedContext);
}

/// For a screen that counts as "viewing" a surface. Returns when the surface
/// was last viewed *before* this visit — cards newer than that are drawn as new
/// — and records this visit on entry and again on leaving, so anything that
/// arrived while the operator was looking is not counted against them later.
export function useSurfaceVisit(surface) {
  const { seenAt, markSeen } = useLiveFeed();
  const [previous] = useState(() => seenAt[surface] ?? null);
  useEffect(() => {
    markSeen(surface);
    return () => markSeen(surface);
  }, [surface, markSeen]);
  return previous;
}
