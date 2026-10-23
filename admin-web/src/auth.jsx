import { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { api, getToken, setToken } from './api/client.js';

// Exported for the development previews in docs/, which supply a fictional
// signed-in Admin without touching the stored session.
export const AuthContext = createContext(null);

/// Roles admitted to this console.
///
/// Each surface has one audience (PRD v14 §4.6.1): the Admin Console is the
/// Admins'; every organisation's Coordinators and Responders work from the
/// mobile app. There is no Observer Console any more.
const CONSOLE_ROLES = ['admin'];

export function isConsoleRole(role) {
  return CONSOLE_ROLES.includes(role);
}

/// Why someone was turned away, in terms of where they should go instead.
function refusalFor(me) {
  if (me?.role === 'sub_admin') {
    return 'Coordinators work from the RepLiT mobile app. This console is for Admins.';
  }
  return 'This console is for Admins. Response Teams and residents use the mobile app.';
}

/// Agencies that coordinate the fire response. Mirrors COORDINATING_AGENCIES in
/// app/services/incident.py — keep the two in step.
const COORDINATING_AGENCIES = ['fire_volunteer', 'bfp'];

/// Police, medical and barangay organisations acknowledge the incidents that
/// asked for them and follow them; the server leaves rejecting, going, fire
/// out and the report to the fire agencies. Mirrors OBSERVER_AGENCIES in
/// app/services/incident.py (a name the server keeps for now).
const ACKNOWLEDGING_AGENCIES = ['police', 'medical', 'barangay'];

/// Standing of an agency itself, independent of any one account. The directory
/// screens list organisations and personnel side by side, and a police station
/// is indistinguishable from a fire brigade in that table unless the authority
/// it carries is spelled out.
export function agencyAuthority(agency) {
  if (COORDINATING_AGENCIES.includes(agency)) {
    return {
      key: 'responds',
      label: 'Runs the response',
      color: '#FF9066',
      note: 'Acknowledges, goes to the scene, marks fire out and files the report.',
    };
  }
  if (ACKNOWLEDGING_AGENCIES.includes(agency)) {
    return {
      key: 'acknowledges',
      label: 'Acknowledges',
      color: '#6098D6',
      note: 'Acknowledges the incidents that asked for this agency, and follows them.',
    };
  }
  return { key: 'unknown', label: '—', color: '#8a8a8a', note: null };
}

/// Human label for an agency, used where the console explains someone's standing.
export function agencyLabel(agency) {
  return {
    fire_volunteer: 'Fire Volunteers',
    bfp: 'Bureau of Fire Protection',
    police: 'Police',
    medical: 'Medical',
    barangay: 'Barangay',
  }[agency] ?? agency ?? '—';
}

/// Holds the signed-in console user (Admin).
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // Why the stored session could not be checked on load (server unreachable,
  // slow to wake, an error page), with the session kept so Retry can resume
  // it. Only a refused session (401/403) or a non-console role signs out.
  const [startupError, setStartupError] = useState(null);

  const resume = useCallback(async () => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setStartupError(null);
    try {
      const me = await api.me();
      if (isConsoleRole(me.role)) setUser(me);
      else setToken(null);
    } catch (e) {
      if (e?.status === 401 || e?.status === 403) setToken(null);
      else setStartupError(e?.message || 'Could not reach the server.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { resume(); }, [resume]);

  async function login(email, password) {
    const res = await api.login(email, password);
    setToken(res.access_token);
    const me = await api.me();
    if (!isConsoleRole(me.role)) {
      await api.logout();
      setToken(null);
      throw new Error(refusalFor(me));
    }
    setUser(me);
    return me;
  }

  async function logout() {
    await api.logout();
    setToken(null);
    setUser(null);
    setStartupError(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, startupError, retry: resume, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
