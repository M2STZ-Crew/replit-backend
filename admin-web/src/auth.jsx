import { createContext, useContext, useEffect, useState } from 'react';

import { api, getToken, setToken } from './api/client.js';

const AuthContext = createContext(null);

/// Roles admitted to this console.
///
/// Master Context v10 (Sections 2.6 and 3.1) gives each surface one audience:
/// the Admin Console is Admin's; coordinators (Fire Volunteer and BFP team
/// captains) run the response from the mobile app, where verification now
/// happens; observers (Police, Medical, Barangay) have the Observer Console.
const CONSOLE_ROLES = ['admin'];

export function isConsoleRole(role) {
  return CONSOLE_ROLES.includes(role);
}

/// Where the Observer Console lives, for the message shown to an observer who
/// signs in here. Set VITE_OBSERVER_URL in admin-web/.env once it is deployed.
const OBSERVER_URL = import.meta.env.VITE_OBSERVER_URL || 'http://localhost:5174';

/// Why someone was turned away, in terms of where they should go instead.
function refusalFor(me) {
  if (me?.role === 'sub_admin' && OBSERVER_AGENCIES.includes(me?.agency_type)) {
    return (
      `${agencyLabel(me.agency_type)} team captains use the Observer Console at ` +
      `${OBSERVER_URL}.`
    );
  }
  if (me?.role === 'sub_admin') {
    return 'Fire Volunteer and BFP team captains coordinate from the RepLiT mobile app.';
  }
  return 'This console is for Admins. Response Teams and residents use the mobile app.';
}

/// Agencies that coordinate the fire response. Mirrors COORDINATING_AGENCIES in
/// app/services/incident.py — keep the two in step.
const COORDINATING_AGENCIES = ['fire_volunteer', 'bfp'];

/// Police, medical and barangay take part for situational awareness only
/// (Section 2.6.1). Their team captains work from the Observer Console, where
/// the one action they have is Accept. Mirrors OBSERVER_AGENCIES in
/// app/services/incident.py and observer-web/src/auth.jsx.
const OBSERVER_AGENCIES = ['police', 'medical', 'barangay'];

/// Standing of an agency itself, independent of any one account. The directory
/// screens list organisations and personnel side by side, and a police station
/// is indistinguishable from a fire brigade in that table unless the authority
/// it carries is spelled out.
export function agencyAuthority(agency) {
  if (COORDINATING_AGENCIES.includes(agency)) {
    return { key: 'coordinator', label: 'Coordinator', color: '#FF9066' };
  }
  if (OBSERVER_AGENCIES.includes(agency)) {
    return { key: 'observer', label: 'Observer', color: '#6098D6' };
  }
  return { key: 'unknown', label: '—', color: '#8a8a8a' };
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

  useEffect(() => {
    (async () => {
      if (getToken()) {
        try {
          const me = await api.me();
          if (isConsoleRole(me.role)) setUser(me);
          else setToken(null);
        } catch {
          setToken(null);
        }
      }
      setLoading(false);
    })();
  }, []);

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
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
