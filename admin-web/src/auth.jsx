import { createContext, useContext, useEffect, useState } from 'react';

import { api, getToken, setToken } from './api/client.js';

const AuthContext = createContext(null);

/// Roles admitted to this console.
///
/// Section 2.6 gives the Fire Volunteer Sub-Admin "Mobile + Web" access and
/// exclusive incident-verification authority, so locking the dashboard to admin
/// shut the verifier out of the only screen where verification happens.
/// Response Team and General User remain mobile-only.
const CONSOLE_ROLES = ['admin', 'sub_admin'];

export function isConsoleRole(role) {
  return CONSOLE_ROLES.includes(role);
}

/// Only a Fire Volunteer sub-admin may verify an incident — the backend pins
/// this in both the route and a database trigger (Section 6). The UI mirrors it
/// so the action is not offered to someone who would be refused.
export function canVerifyIncidents(user) {
  return user?.role === 'sub_admin' && user?.agency_type === 'fire_volunteer';
}

/// Rejecting is broader: any sub-admin, or an admin.
export function canRejectIncidents(user) {
  return user?.role === 'sub_admin' || user?.role === 'admin';
}

/// Holds the signed-in console user (Admin or Sub-Admin).
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
      setToken(null);
      throw new Error(
        'This console is for Admins and Sub-Admins. Response Teams and ' +
          'citizens use the mobile app.',
      );
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
