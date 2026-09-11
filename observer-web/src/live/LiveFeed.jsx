import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { announce } from '../sound/cues.js';

/// The Observer Console's live incident feed (Master Context v10, Section 2.6.1).
///
/// Polls /incidents on the Section 6 cadence. The server returns only the
/// incidents a reporter asked this agency for. The moment Admin routes one to
/// this observer — their agency as a whole, or their own team — the agency's cue
/// plays (Section 2.8) and a banner offers to open it, since that is when there
/// is something to Accept.
///
/// Routing is per team, and the summary only says which agencies an incident is
/// routed to. So the feed keeps each incident's route_count and re-reads the
/// detail whenever it changes, alerting only for route rows that are this
/// observer's and have not been seen before. The first load alerts nothing, or
/// signing in would sound every open incident at once.

const POLL_MS = 12_000;

const LiveFeedContext = createContext(null);

/// The route rows on an incident that this observer's Accept would answer:
/// routed to their agency as a whole, or to their own team. Mirrors the
/// predicate in POST /incidents/{id}/accept.
export function routesForMe(detail, user) {
  return (detail?.routes ?? []).filter(
    (r) =>
      r.agency === user?.agency_type &&
      (r.organization_id == null || r.organization_id === user?.primary_org_id),
  );
}

/// From a summary alone: routed to this agency and nobody in it has accepted.
export function awaitingAccept(inc, agency) {
  return (
    (inc.routed_agencies ?? []).includes(agency) &&
    !(inc.accepted_agencies ?? []).includes(agency)
  );
}

export function LiveFeedProvider({ user, children }) {
  const agency = user.agency_type;
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [alert, setAlert] = useState(null);
  const routeCounts = useRef(new Map()); // incident id -> route_count last checked
  const seenRoutes = useRef(new Set()); // ids of route rows for me already known
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

    const routedToAgency = list.filter((inc) => (inc.routed_agencies ?? []).includes(agency));
    for (const inc of routedToAgency) {
      if (routeCounts.current.get(inc.id) === inc.route_count) continue;
      const detail = await api.incident(inc.id).catch(() => null);
      if (!detail) continue;
      routeCounts.current.set(inc.id, inc.route_count);
      const fresh = routesForMe(detail, user).filter((r) => !seenRoutes.current.has(r.id));
      fresh.forEach((r) => seenRoutes.current.add(r.id));
      if (primed.current && fresh.length > 0) {
        announce([inc], [agency]);
        setAlert({ id: inc.id, designation: inc.designation, at: Date.now() });
      }
    }
    primed.current = true;
    setIncidents(list);
    setLoaded(true);
  }, [agency, user]);

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
