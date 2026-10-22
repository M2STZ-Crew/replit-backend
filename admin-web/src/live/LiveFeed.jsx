import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';

import { api } from '../api/client.js';
import {
  CATCH_UP_MS,
  isAcknowledged,
  notifyDesktop,
  recordAcknowledged,
} from '../sound/alarm.js';
import { announce, stopCues } from '../sound/cues.js';

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

/// How often a still-unanswered alarm's desktop alert is shown again.
const DESKTOP_AGAIN_MS = 30 * 1000;

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
  // Whether the latest poll failed, and when the feed last arrived. A failed
  // poll keeps the last list on screen but must say so (10 · A82): a stale
  // list read as a live one is worse than an error.
  const [failed, setFailed] = useState(false);
  const [loadedAt, setLoadedAt] = useState(null);
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
        ring = fresh.filter((inc) => !isAcknowledged(inc.id));
        notifyDesktop(ring);
      } else {
        known.current = new Set();
        const now = Date.now();
        ring = list.filter((inc) => !isAcknowledged(inc.id)
          && now - new Date(inc.reported_at).getTime() < CATCH_UP_MS);
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
      setFailed(false);
      setLoadedAt(new Date().toISOString());
    } else {
      setFailed(true);
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
    stopCues();
    setAlarmIds((prev) => {
      const next = prev.filter((id) => !list.includes(id));
      return next.length === prev.length ? prev : next;
    });
  }, []);

  // PRD v14 §4.13.1: a true loop. While anything is unanswered its sounds play
  // back to back, with no gap to miss them in, until an admin answers it
  // (acknowledge stops the sound at once). The loop reads the alarms through a
  // ref, so an alarm that joins is heard on the next pass, and a 12 s poll
  // does not restart it. A desktop alert is shown again every 30 s.
  const ringing = useRef(alarms);
  ringing.current = alarms;
  const anyRinging = alarms.length > 0;
  useEffect(() => {
    if (!anyRinging) return undefined;
    let alive = true;
    let timer = null;
    let desktopAt = Date.now();
    const ring = async () => {
      const seconds = await announce(ringing.current);
      if (!alive) return;
      if (Date.now() - desktopAt >= DESKTOP_AGAIN_MS) {
        notifyDesktop(ringing.current, { again: true });
        desktopAt = Date.now();
      }
      // Nothing could sound (muted, or audio not unlocked yet): look again soon.
      timer = setTimeout(ring, seconds > 0 ? seconds * 1000 : 1000);
    };
    ring();
    return () => {
      alive = false;
      clearTimeout(timer);
      stopCues();
    };
  }, [anyRinging]);

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
        incidents, stats, loaded, failed, loadedAt, seenAt, markSeen, newSince, refresh, alarms, acknowledge,
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
