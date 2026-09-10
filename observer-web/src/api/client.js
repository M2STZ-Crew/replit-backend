// Thin fetch wrapper around the RepLiT FastAPI backend.
const BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

// Its own key, so signing in to the Observer Console on the same machine as the
// Admin Console does not sign either one out.
const TOKEN_KEY = 'replit_observer_token';

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable — the session lasts until the tab closes */
  }
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth) {
    const t = getToken();
    if (t) headers.Authorization = `Bearer ${t}`;
  }
  let resp;
  try {
    resp = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error('Cannot reach the server. Is the API running?');
  }
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {};
  }
  if (!resp.ok) {
    const err = new Error(data.message || `Request failed (${resp.status}).`);
    err.status = resp.status;
    throw err;
  }
  return data;
}

/// Only what an observer may do: read the incidents that involve their agency,
/// read the part of the action record about them, and press Accept.
export const api = {
  login: (email, password) =>
    request('/auth/login', { method: 'POST', auth: false, body: { email, password } }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }).catch(() => {}),

  // Incidents where a reporter asked for the caller's agency (server-scoped).
  incidents: (opts = {}) => {
    const q = new URLSearchParams();
    if (opts.activeOnly === false) q.set('active_only', 'false');
    if (opts.status) q.set('status', opts.status);
    if (opts.limit) q.set('limit', String(opts.limit));
    const qs = q.toString();
    return request(`/incidents${qs ? `?${qs}` : ''}`);
  },
  incidentStats: () => request('/incidents/stats'),
  incident: (id) => request(`/incidents/${id}`),
  incidentReports: (id) => request(`/incidents/${id}/reports`),

  // The observer-side action (v10 Section 2.6.1). An acknowledgement only —
  // the incident's status does not change.
  accept: (id) => request(`/incidents/${id}/accept`, { method: 'POST' }),

  // The action record, scoped by the server to incidents the agency can see.
  auditLogs: (opts = {}) => {
    const q = new URLSearchParams();
    if (opts.limit) q.set('limit', String(opts.limit));
    if (opts.action) q.set('action', opts.action);
    const qs = q.toString();
    return request(`/audit-logs${qs ? `?${qs}` : ''}`);
  },

  mapLayer: (name) => request(`/map/${name}`),
};

export { BASE };
