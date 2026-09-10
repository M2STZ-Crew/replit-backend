import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel, useAuth } from '../auth.jsx';

/* Kinds of entry an observer sees. The server returns only entries tied to an
   incident their agency can see, with device details withheld. */
const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'accept', label: 'Accepts', match: (a) => a === 'incident.accept' },
  { key: 'route', label: 'Routing', match: (a) => a === 'incident.route' },
  {
    key: 'lifecycle', label: 'Lifecycle',
    match: (a) => a.startsWith('incident.') && a !== 'incident.accept' && a !== 'incident.route',
  },
];

const VERB = {
  'incident.verify': 'verified',
  'incident.reject': 'rejected',
  'incident.resolve': 'declared fire out',
  'incident.dispatch': 'dispatched a responder',
  'incident.self_dispatch': 'self-dispatched',
  'incident.en_route': 'marked en route',
  'incident.arrived': 'marked on scene',
  'incident.route': 'routed to agencies',
  'incident.accept': 'accepted',
  'incident.post_incident_report': 'filed the Post-Incident Report',
};

function verbOf(action) {
  return VERB[action] ?? action.split('.').slice(1).join(' ').replace(/_/g, ' ');
}

function when(iso) {
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

/// Audit log (History) — the append-only record, as far as it concerns
/// incidents involving this agency (v10 Section 2.6.1). Each entry keeps the
/// actor's role and agency as they were at the time.
export default function HistoryPage() {
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [mineOnly, setMineOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.auditLogs({ limit: 200 }));
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter);
    return rows.filter((r) =>
      (!f?.match || f.match(r.action)) && (!mineOnly || r.actor_user_id === user.id));
  }, [rows, filter, mineOnly, user.id]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="os-eyebrow">History</span>
          <h1 className="page-title">Audit log</h1>
          <p className="page-sub">
            Every consequential action on incidents involving {agencyLabel(user.agency_type)}, newest
            first. Append-only; nothing here can be edited.
          </p>
        </div>
        <button className="btn-ghost" onClick={load} disabled={loading}>Refresh</button>
      </header>

      <div className="filters">
        {FILTERS.map((f) => (
          <button key={f.key} className={`layer-chip${filter === f.key ? ' is-on' : ''}`}
                  onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}>
            {f.label}
          </button>
        ))}
        <label className="check">
          <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
          Only my actions
        </label>
      </div>

      {error && <div className="note is-error">{error}</div>}

      <section className="panel table-panel">
        <div className="table-scroll">
          <table className="log">
            <thead>
              <tr><th>Time</th><th>Incident</th><th>Who</th><th>Action</th></tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id}>
                  <td className="log-time">{when(r.created_at)}</td>
                  <td>{r.area_designation || '—'}</td>
                  <td>
                    <span className="log-role">{(r.actor_role || 'system').replace(/_/g, ' ')}</span>
                    {r.actor_agency && <span className="log-agency">{agencyLabel(r.actor_agency)}</span>}
                  </td>
                  <td>
                    {verbOf(r.action)}
                    {r.action === 'incident.route' && Array.isArray(r.metadata?.routes) && (
                      <span className="log-detail">
                        {' '}· {r.metadata.routes.map((x) => agencyLabel(x.agency)).join(', ')}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && shown.length === 0 && (
            <p className="empty">
              {rows.length === 0
                ? 'Nothing recorded yet for incidents involving your agency.'
                : 'No entries match that filter.'}
            </p>
          )}
          {loading && <p className="empty">Loading…</p>}
        </div>
      </section>
    </div>
  );
}
