import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';

import { api } from '../api/client.js';
import {
  CATCH_UP_MS,
  isAcknowledged,
  notifyDesktop,
  recordAcknowledged,
  useAlarmSettings,
} from '../sound/alarm.js';
import { announce } from '../sound/cues.js';

/// The live incident feed behind the console's red badges and sounds
/// (Master Context v10, Sections 2.8 and 2.9).
///
/// Polls /incidents on the Section 6 cadence (10–15 s). An incident this session
/// has not seen before plays its category's cue, and then keeps ringing on the
/// repeat interval until it is acknowledged (sound/alarm.js). The first load
/// does not ring for everything open: only for incidents reported in the last
/// half hour that this browser never acknowledged, so a reload cannot silence
/// an alarm nobody answered.
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
  // Incidents ringing until acknowledged, newest first.
  const [alarmIds, setAlarmIds] = useState([]);
  const known = useRef(null);

  const refresh = useCallback(async () => {
    const [list, s] = await Promise.all([
      api.incidents({ limit: 200 }).catch(() => null),
      api.incidentStats().catch(() => null),
    ]);
    if (list) {
      let ring;
      if (known.current) {
        const fresh = list.filter((inc) => !known.current.has(inc.id));
        if (fresh.length) announce(fresh);
        ring = fresh.filter((inc) => !isAcknowledged(inc.id));
        notifyDesktop(ring);
      } else {
        known.current = new Set();
        const now = Date.now();
        ring = list.filter((inc) => !isAcknowledged(inc.id)
          && now - new Date(inc.reported_at).getTime() < CATCH_UP_MS);
        if (ring.length) announce(ring);
      }
      list.forEach((inc) => known.current.add(inc.id));
      // An incident that has left the feed (closed, rejected, merged) stops ringing.
      const live = new Set(list.map((inc) => inc.id));
      setAlarmIds((prev) => {
        const added = ring.map((inc) => inc.id).filter((id) => !prev.includes(id));
        const next = [...added, ...prev].filter((id) => live.has(id));
        return next.length === prev.length && next.every((id, i) => id === prev[i]) ? prev : next;
      });
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

  const alarms = useMemo(
    () => alarmIds.map((id) => incidents.find((inc) => inc.id === id)).filter(Boolean),
    [alarmIds, incidents],
  );

  const acknowledge = useCallback((ids) => {
    const list = Array.isArray(ids) ? ids : [ids];
    recordAcknowledged(list);
    setAlarmIds((prev) => {
      const next = prev.filter((id) => !list.includes(id));
      return next.length === prev.length ? prev : next;
    });
  }, []);

  // Ring again on the repeat interval while anything is unanswered. The timer
  // reads the alarms through a ref: restarting it on every 12 s poll would
  // keep pushing a 30 s repeat back so that it never fired.
  const { repeat, everySec } = useAlarmSettings();
  const ringing = useRef(alarms);
  ringing.current = alarms;
  const anyRinging = alarms.length > 0;
  useEffect(() => {
    if (!anyRinging || !repeat) return undefined;
    const timer = setInterval(() => {
      announce(ringing.current);
      notifyDesktop(ringing.current, { again: true });
    }, everySec * 1000);
    return () => clearInterval(timer);
  }, [anyRinging, repeat, everySec]);

  const newSince = useCallback(
    (iso) => {
      const t = iso ? new Date(iso).getTime() : 0;
      return incidents.filter((inc) => new Date(inc.reported_at).getTime() > t);
    },
    [incidents],
  );

  return (
    <LiveFeedContext.Provider
      value={{
        incidents, stats, loaded, seenAt, markSeen, newSince, refresh, alarms, acknowledge,
      }}
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
