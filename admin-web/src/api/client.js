// Thin fetch wrapper around the RepLiT FastAPI backend.
//
// The trailing slash is stripped deliberately. Paths below all start with "/",
// so a base of "https://host/" builds "https://host//auth/login" — a double
// slash the router does not match. FastAPI answers that with a 404 whose
// message is the literal "Not Found", which the UI then shows on the login
// form. Pasting a URL with its trailing slash into VITE_API_BASE is the easiest
// mistake to make in a hosting dashboard, and the symptom points nowhere near
// the cause.
const BASE = (import.meta.env.VITE_API_BASE || 'http://localhost:8000').replace(/\/+$/, '');
const TOKEN_KEY = 'replit_admin_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
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
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    throw new Error(data.message || `Request failed (${resp.status}).`);
  }
  return data;
}

/// Fetch a file the API serves (the incident report PDF) and hand it to the
/// browser as a download. It needs the bearer token, so a plain link will not do.
async function download(path, filename) {
  let resp;
  try {
    resp = await fetch(`${BASE}${path}`, {
      headers: { Authorization: `Bearer ${getToken() ?? ''}` },
    });
  } catch {
    throw new Error('Cannot reach the server. Is the API running?');
  }
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.message || `Download failed (${resp.status}).`);
  }
  const url = URL.createObjectURL(await resp.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  login: (email, password) =>
    request('/auth/login', { method: 'POST', auth: false, body: { email, password } }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }).catch(() => {}),
  // Public affiliate registration (no account required).
  registerAffiliate: (payload) =>
    request('/affiliates/register', { method: 'POST', auth: false, body: payload }),

  // Dashboard data (admin = staff, sees everything).
  incidentStats: () => request('/incidents/stats'),
  incidents: (opts = {}) => {
    const q = new URLSearchParams();
    if (opts.activeOnly === false) q.set('active_only', 'false');
    if (opts.status) q.set('status', opts.status);
    if (opts.limit) q.set('limit', String(opts.limit));
    const qs = q.toString();
    return request(`/incidents${qs ? `?${qs}` : ''}`);
  },
  incident: (id) => request(`/incidents/${id}`),
  incidentDispatches: (id) => request(`/incidents/${id}/dispatches`),

  // Verification workflow (Section 2.5, stage 3). incidentReports returns the
  // member reports with the reporter's name and a signed photo URL — the
  // evidence a Sub-Admin reviews before deciding.
  incidentReports: (id) => request(`/incidents/${id}/reports`),

  // Accept (v12 Section 2.5.1) verifies: the first moves the incident Reported
  // -> Verified and sends nobody; it goes On the way when someone responds.
  // Admin pressing this is the
  // safety net for an incident no agency has picked up. There is no separate
  // verify call any more, and no routing: the reporter already said which
  // agencies they wanted, and each of those sees its own Accept.
  incidentAccept: (id) => request(`/incidents/${id}/accept`, { method: 'POST' }),
  incidentReject: (id, reason) =>
    request(`/incidents/${id}/reject`, { method: 'POST', body: { reason } }),

  // The Post-Incident Report a team captain filed after fire out (§2.5.3).
  postIncidentReport: (id) => request(`/incidents/${id}/post-incident-report`),
  // Every responding team's report, in the order they were filed.
  postIncidentReports: (id) => request(`/incidents/${id}/post-incident-reports`),
  // The incident report PDF: timeline, every team's report, and the AI summary.
  incidentReportPdf: (id, designation) =>
    download(
      `/incidents/${id}/report.pdf`,
      `${(designation || 'incident').replace(/[^\w.-]+/g, '-')}-report.pdf`,
    ),
  equipment: () => request('/equipment'),
  mapLayer: (name) => request(`/map/${name}`),

  // Immutable action record (Admin sees all of it).
  auditLogs: (opts = {}) => {
    const q = new URLSearchParams();
    if (opts.limit) q.set('limit', String(opts.limit));
    if (opts.action) q.set('action', opts.action);
    const qs = q.toString();
    return request(`/audit-logs${qs ? `?${qs}` : ''}`);
  },

  // National ID review (admin only — Section 2.6). The pending list already
  // carries short-lived signed URLs for the ID and selfie images, which live in
  // a private bucket.
  pendingVerifications: () => request('/admin/verifications/pending'),
  approveVerification: (id) =>
    request(`/admin/verifications/${id}/approve`, { method: 'POST' }),
  rejectVerification: (id, notes) =>
    request(`/admin/verifications/${id}/reject`, {
      method: 'POST',
      body: { notes: notes || null },
    }),

  // Affiliate organization review (admin).
  affiliates: (statusFilter) =>
    request(`/affiliates${statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''}`),
  affiliateAccept: (id, notes) =>
    request(`/affiliates/${id}/accept`, { method: 'POST', body: { notes: notes || null } }),
  affiliateReject: (id, notes) =>
    request(`/affiliates/${id}/reject`, { method: 'POST', body: { notes: notes || null } }),

  // Affiliate organization directory (admin).
  organizations: () => request('/organizations'),
  orgPersonnel: (id) => request(`/organizations/${id}/personnel`),
  orgEquipment: (id) => request(`/equipment?organization_id=${id}`),

  // Map-layer management (admin create/update/delete; `path` e.g. 'risk-zones').
  mapLayerCreate: (path, body) => request(`/map/${path}`, { method: 'POST', body }),
  mapLayerUpdate: (path, id, body) =>
    request(`/map/${path}/${id}`, { method: 'PATCH', body }),
  mapLayerDelete: (path, id) => request(`/map/${path}/${id}`, { method: 'DELETE' }),
};

export { BASE };
