import { createContext, useContext, useEffect, useState } from 'react';

import { api, getToken, setToken } from './api/client.js';

const AuthContext = createContext(null);

/// Agencies that take part for situational awareness only (Master Context v10,
/// Section 2.6.1). Mirrors OBSERVER_AGENCIES in app/services/incident.py and
/// admin-web/src/auth.jsx — keep the three in step. The UI mirror is a
/// courtesy; the server is the authority.
export const OBSERVER_AGENCIES = ['police', 'medical', 'barangay'];

/// This console's one audience: an observer team captain.
export function isObserver(user) {
  return user?.role === 'sub_admin' && OBSERVER_AGENCIES.includes(user?.agency_type);
}

/// Accept is the only action here, and only an observer has it. Mirrors
/// assert_can_accept() in app/services/incident.py.
export function canAccept(user) {
  return isObserver(user);
}

export function agencyLabel(agency) {
  return {
    fire_volunteer: 'Fire Volunteers',
    bfp: 'Bureau of Fire Protection',
    police: 'Police',
    medical: 'Medical',
    barangay: 'Barangay',
  }[agency] ?? agency ?? '—';
}

/// Where someone who is not an observer should go instead.
function refusalFor(me) {
  if (me?.role === 'admin') return 'Admins use the Admin Console.';
  if (me?.role === 'sub_admin') {
    return 'Fire Volunteer and BFP team captains coordinate from the RepLiT mobile app.';
  }
  return (
    'The Observer Console is for Police, Medical and Barangay team captains. ' +
    'Response Teams and residents use the mobile app.'
  );
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      if (getToken()) {
        try {
          const me = await api.me();
          if (isObserver(me)) setUser(me);
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
    if (!isObserver(me)) {
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
