import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel, useAuth } from '../auth.jsx';

/* Categories are derived from the action's "<entity>.<verb>" prefix, which the
   migration documents as the naming convention. Anything unrecognised falls
   through to "Other" rather than being dropped. */
const CATEGORY = {
  incident: { label: 'Incident', color: '#FF9066' },
  alarm: { label: 'Alarm', color: '#FF544E' },
  kyc: { label: 'Identity', color: '#22C55E' },
  hydrant: { label: 'Hydrant', color: '#6098D6' },
  map_layer: { label: 'Map layer', color: '#6098D6' },
  user: { label: 'Account', color: '#EAB308' },
  report: { label: 'Report', color: '#FF9066' },
  dispatch: { label: 'Dispatch', color: '#7E57C2' },
};

function categoryOf(action = '') {
  const key = action.split('.')[0];
  return { key, ...(CATEGORY[key] ?? { label: 'Other', color: '#8a8a8a' }) };
}

function verbOf(action = '') {
  const verb = action.split('.').slice(1).join(' ') || action;
  return verb.replace(/_/g, ' ');
}

function when(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

function shortId(id) {
  return id ? String(id).slice(0, 8) : '—';
}

/* The immutable action record (Section 2.5 audit trail).
 *
 * The design showed a "Digest" column with "hash-chained · retained 7 years"
 * and "Chain verified · no gaps detected". public.audit_logs has no hash, chain
 * or digest column and no retention policy, so none of that is claimed here —
 * it would be a fabricated security property. What the table does record is
 * genuinely strong provenance (actor role and agency at the time, before/after
 * state, IP, request id) and that is what the footer states instead. */
export default function ActionRecord() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.auditLogs({ limit: 200 }));
      setError(null);
    } catch (e) {
      setError(e.message);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (isAdmin) load(); else setLoading(false); }, [isAdmin, load]);

  const categories = useMemo(() => {
    const seen = new Map();
    for (const r of rows) {
      const c = categoryOf(r.action);
      seen.set(c.key, c);
    }
    return [...seen.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (category !== 'all' && categoryOf(r.action).key !== category) return false;
      if (!q) return true;
      return [r.action, r.actor_role, r.actor_agency, r.entity_type, r.request_id]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [rows, query, category]);

  const stats = useMemo(() => {
    const actors = new Set(rows.map((r) => r.actor_user_id).filter(Boolean));
    const day = Date.now() - 864e5;
    const recent = rows.filter((r) => r.created_at && new Date(r.created_at).getTime() > day);
    return [
      { k: 'Entries held', v: rows.length, foot: 'Most recent 200', color: '#ffffff' },
      { k: 'Last 24 hours', v: recent.length, foot: 'Actions recorded', color: '#FF9066' },
      { k: 'Distinct actors', v: actors.size, foot: 'Accounts represented', color: '#ffffff' },
      { k: 'Categories', v: categories.length, foot: 'Kinds of action', color: '#ffffff' },
    ];
  }, [rows, categories]);

  if (!isAdmin) {
    return (
      <div className="ar">
        <section className="ar-locked">
          <h2 className="sb-panel-title">Action record</h2>
          <p className="sb-empty">
            The full action record is available to Admin accounts only. Your
            incident history is on the {' '}
            <strong>{user?.role === 'sub_admin' ? 'Verification' : 'Incidents'}</strong> screen.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="ar">
      <div className="ar-stats">
        {stats.map((s) => (
          <section className="ar-stat" key={s.k}>
            <span className="dc-eyebrow">{s.k}</span>
            <span className="ar-stat-v" style={{ color: s.color }}>{loading ? '·' : s.v}</span>
            <span className="sb-kpi-foot">{s.foot}</span>
          </section>
        ))}
      </div>

      <section className="ar-panel">
        <header className="ar-head">
          <div className="sb-map-title">
            <span className="sb-panel-title">Immutable action record</span>
            <span className="sb-panel-sub">
              {loading ? 'Loading…' : `${filtered.length} of ${rows.length} entries`}
              {' · append-only · actor, role and agency captured at the time'}
            </span>
          </div>

          <label className="ar-search">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--faint)"
                 strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by actor, action, target…"
              aria-label="Filter the action record"
            />
          </label>

          {categories.length > 0 && (
            <div className="ar-chips">
              <button
                className={`ar-chip${category === 'all' ? ' is-on' : ''}`}
                onClick={() => setCategory('all')}
              >
                All
              </button>
              {categories.map((c) => (
                <button
                  key={c.key}
                  className={`ar-chip${category === c.key ? ' is-on' : ''}`}
                  style={{ color: category === c.key ? c.color : undefined }}
                  onClick={() => setCategory(c.key)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}
        </header>

        {error && <div className="vq-error" style={{ margin: '16px 22px' }}>{error}</div>}

        <div className="ar-scroll">
          <div className="ar-cols">
            <span className="ar-c-time">Time</span>
            <span className="ar-c-cat">Category</span>
            <span className="ar-c-actor">Actor</span>
            <span className="ar-c-action">Action</span>
            <span className="ar-c-target">Target</span>
          </div>

          {!loading && filtered.length === 0 && (
            <p className="sb-empty" style={{ padding: '20px 22px' }}>
              {rows.length === 0
                ? 'Nothing recorded yet. Entries appear as verifications, dispatches and approvals happen.'
                : 'No entries match that filter.'}
            </p>
          )}

          {filtered.map((r) => {
            const cat = categoryOf(r.action);
            return (
              <div className="ar-row" key={r.id}>
                <span className="ar-c-time ar-time">{when(r.created_at)}</span>
                <span className="ar-c-cat">
                  <span className="ar-tag" style={{ color: cat.color, background: `${cat.color}1f` }}>
                    {cat.label}
                  </span>
                </span>
                <span className="ar-c-actor ar-actor">
                  <span className="ar-actor-role">{(r.actor_role || 'system').replace(/_/g, ' ')}</span>
                  <span className="ar-actor-sub">
                    {r.actor_agency ? agencyLabel(r.actor_agency) : shortId(r.actor_user_id)}
                  </span>
                </span>
                <span className="ar-c-action ar-action">{verbOf(r.action)}</span>
                <span className="ar-c-target ar-target">
                  {r.entity_type ? `${r.entity_type} ${shortId(r.entity_id ?? r.area_id)}` : '—'}
                </span>
              </div>
            );
          })}
        </div>

        <footer className="ar-foot">
          <span className="sb-kpi-foot">
            Append-only. Each entry keeps the actor&apos;s role and agency as they were at
            the time, plus before and after state where the change was diffable.
          </span>
          <button className="sb-ghost" onClick={load} disabled={loading}>Refresh</button>
        </footer>
      </section>
    </div>
  );
}
