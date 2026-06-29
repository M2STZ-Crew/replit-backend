import { createContext, useContext, useEffect, useState } from 'react';

import { api, getToken, setToken } from './api/client.js';

const AuthContext = createContext(null);

/// Holds the signed-in admin. The dashboard is admin-only: a non-admin login is
/// rejected (citizens/staff use the mobile app).
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      if (getToken()) {
        try {
          const me = await api.me();
          if (me.role === 'admin') setUser(me);
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
    if (me.role !== 'admin') {
      setToken(null);
      throw new Error('This dashboard is for administrators only.');
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
