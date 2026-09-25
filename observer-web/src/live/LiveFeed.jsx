import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { OFF_FEED } from '../lib/status.js';
import { announce } from '../sound/cues.js';

/// The Observer Console's live incident feed (Master Context v11, Section 2.6.1).
///
/// Polls /incidents on the Section 6 cadence. The server returns only the
/// incidents a reporter asked this agency for, and each of those is this
/// observer's to Accept (v11 Section 2.5.1) — there is no routing step to wait
/// for any more. So the moment a new one appears that nobody in the agency has
/// accepted, the agency's cue plays (Section 2.8) and a banner offers to open
/// it. The first load alerts nothing, or signing in would sound every open
/// incident at once.

const POLL_MS = 12_000;

const LiveFeedContext = createContext(null);

/// From a summary alone: live, asked for this agency, and nobody in the agency
/// has accepted it yet.
export function awaitingAccept(inc, agency) {
  return (
    !OFF_FEED.includes(inc.status) &&
    (inc.requested_agencies ?? []).includes(agency) &&
    !(inc.accepted_agencies ?? []).includes(agency)
  );
}

/// This agency's Accept on an incident detail, if anyone in it has pressed it.
export function ourAcceptance(detail, agency) {
  return (detail?.acceptances ?? []).find((a) => a.agency === agency) ?? null;
}

export function LiveFeedProvider({ user, children }) {
  const agency = user.agency_type;
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [alert, setAlert] = useState(null);
  const seen = useRef(new Set()); // incidents already announced (or there at sign-in)
  const primed = useRef(false);

  const refresh = useCallback(async () => {
    let list;
    try {
      list = await api.incidents({ limit: 200 });
      setError(null);
    } catch (e) {
      setError(e.message);
      return;
    }
    const s = await api.incidentStats().catch(() => null);
    if (s) setStats(s);

    const fresh = list.filter(
      (inc) => awaitingAccept(inc, agency) && !seen.current.has(inc.id),
    );
    fresh.forEach((inc) => seen.current.add(inc.id));
    if (primed.current && fresh.length > 0) {
      announce(fresh, [agency]);
      setAlert({ id: fresh[0].id, designation: fresh[0].designation, at: Date.now() });
    }
    primed.current = true;
    setIncidents(list);
    setLoaded(true);
  }, [agency]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <LiveFeedContext.Provider
      value={{
        incidents,
        stats,
        loaded,
        error,
        refresh,
        alert,
        dismissAlert: () => setAlert(null),
      }}
    >
      {children}
    </LiveFeedContext.Provider>
  );
}

export function useLiveFeed() {
  return useContext(LiveFeedContext);
}
