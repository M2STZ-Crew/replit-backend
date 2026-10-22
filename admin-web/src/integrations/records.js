import { api } from '../api/client.js';

/* The production readers behind Requests (A40, A41) and Reports & CIAR
 * (A60, A61). Both pages take their data through callbacks (documented at
 * the top of each page, so docs/console-ready.html can hand them empty and
 * failing readers); these supply them from endpoints the server already
 * serves an Admin. Every one is a read: nothing here sends, accepts,
 * executes, generates or regenerates.
 *
 * Module-level functions, so their identity is stable across renders. */

/* Requests: the alarm-escalation records. An Admin may read every one
 * (GET /alarm-requests); raising and deciding them happen on mobile. */
export async function readRequests({ status }) {
  return api.alarmRequests(status && status !== 'all' ? status : undefined);
}

/* Reports: filed Post-Incident Reports, newest first. The list endpoint
 * returns a plain page, so one extra row tells whether another page exists. */
export async function readReports({ areaId, offset, pageSize }) {
  const rows = areaId
    ? await api.postIncidentReports(areaId)
    : await api.postIncidentReportList({ limit: pageSize + 1, offset });
  const list = Array.isArray(rows) ? rows : [];
  if (areaId) {
    return { items: list.slice(offset, offset + pageSize), hasMore: list.length > offset + pageSize };
  }
  return { items: list.slice(0, pageSize), hasMore: list.length > pageSize };
}

export async function readIncidentReports({ areaId }) {
  const rows = await api.postIncidentReports(areaId);
  return Array.isArray(rows) ? rows : [];
}

/* The newest stored AI summary of an incident. GET /incidents/{id}/summaries
 * only reads what was stored; it never starts a generation, so whether one
 * is being written is unknown here and `state` stays null. */
export async function readSummary({ areaId }) {
  const rows = await api.incidentSummaries(areaId);
  const list = Array.isArray(rows) ? rows : [];
  const latest = list.reduce(
    (best, row) => (!best || new Date(row.generated_at) > new Date(best.generated_at) ? row : best),
    null,
  );
  return {
    state: null,
    summary: latest ? { summary_text: latest.summary_text, generated_at: latest.generated_at } : null,
  };
}

export function downloadIncidentPdf({ areaId, designation }) {
  return api.incidentReportPdf(areaId, designation);
}
