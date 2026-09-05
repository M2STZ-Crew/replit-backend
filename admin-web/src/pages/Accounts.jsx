import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyAuthority, agencyLabel } from '../auth.jsx';

const ROLE = {
  admin: { label: 'Admin', color: '#FF544E' },
  sub_admin: { label: 'Sub-Admin', color: '#FF9066' },
  response_team: { label: 'Response Team', color: '#6098D6' },
  general_user: { label: 'Citizen', color: '#8a8a8a' },
};

const BADGE = {
  green_check: { label: '100%', color: '#22C55E' },
  green: { label: 'High', color: '#22C55E' },
  light_green: { label: 'Partial', color: '#EAB308' },
  yellow: { label: 'Low', color: '#EAB308' },
};

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

/* What this account may actually do. Authority is a Sub-Admin question — a
 * Response Team member acts on the dispatches they are given regardless of
 * which agency they belong to, so labelling them "Coordinator" because their
 * organisation is a fire brigade would be wrong. */
function authorityOf(person) {
  if (person.role === 'sub_admin') {
    const { label, color, key } = agencyAuthority(person.agency_type);
    return {
      label,
      color,
      hint: key === 'observer'
        ? 'Sees incidents that requested this agency; cannot verify, reject or dispatch.'
        : 'Verifies, rejects and dispatches on incidents.',
    };
  }
  if (person.role === 'response_team') {
    return { label: 'Responder', color: '#8a8a8a', hint: 'Acts on dispatches; no console authority.' };
  }
  if (person.role === 'admin') {
    return { label: 'Full access', color: '#FF544E', hint: 'Every action, citywide.' };
  }
  return { label: '—', color: '#8a8a8a', hint: '' };
}

/* Personnel accounts (Section 2.6 — Admin: user approval and oversight).
 *
 * There is no endpoint that lists every user; the only roster available is
 * per-organisation, so the table is assembled from /organizations and each
 * org's personnel. That has a real consequence worth stating on screen: a
 * citizen has no organisation, so citizens do not appear here.
 *
 * The design's table also had "Last active" and "Session" columns. The
 * personnel endpoint returns neither, and no session state is exposed at all,
 * so verification standing takes their place — which is the more useful signal
 * anyway, since it is what dispatchers weigh. */
export default function Accounts() {
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const orgList = await api.organizations();
      const rosters = await Promise.all(
        orgList.map((o) =>
          api.orgPersonnel(o.id)
            .then((rows) => rows.map((r) => ({ ...r, org: o.name, orgId: o.id })))
            .catch(() => []),
        ),
      );
      setPeople(rosters.flat());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return people;
    return people.filter((p) =>
      [p.full_name, p.role, p.org, p.agency_type]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)),
    );
  }, [people, query]);

  const subAdmins = people.filter((p) => p.role === 'sub_admin');
  const observers = subAdmins.filter(
    (p) => agencyAuthority(p.agency_type).key === 'observer',
  ).length;
  const coordinators = subAdmins.length - observers;

  const split = useMemo(() => {
    const counts = new Map();
    for (const p of people) counts.set(p.role, (counts.get(p.role) ?? 0) + 1);
    const total = people.length || 1;
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([role, n]) => ({
        role,
        n,
        pct: Math.round((n / total) * 100),
        ...(ROLE[role] ?? { label: role, color: '#8a8a8a' }),
      }));
  }, [people]);

  return (
    <div className="ar">
      <div className="ar-stats">
        <section className="ar-stat">
          <span className="dc-eyebrow">Personnel</span>
          <span className="ar-stat-v">{loading ? '·' : people.length}</span>
          <span className="sb-kpi-foot">Attached to an organisation</span>
        </section>
        {/* Sub-Admins are split rather than counted together: five of them with
            only two able to act on an incident is the sort of number that gets
            misread in a meeting. */}
        <section className="ar-stat">
          <span className="dc-eyebrow">Coordinators</span>
          <span className="ar-stat-v" style={{ color: '#FF9066' }}>
            {loading ? '·' : coordinators}
          </span>
          <span className="sb-kpi-foot">Sub-Admins who can act</span>
        </section>
        <section className="ar-stat">
          <span className="dc-eyebrow">Observers</span>
          <span className="ar-stat-v" style={{ color: '#6098D6' }}>
            {loading ? '·' : observers}
          </span>
          <span className="sb-kpi-foot">Situational awareness only</span>
        </section>
        <section className="ar-stat">
          <span className="dc-eyebrow">Responders</span>
          <span className="ar-stat-v">
            {loading ? '·' : people.filter((p) => p.role === 'response_team').length}
          </span>
          <span className="sb-kpi-foot">Response Team accounts</span>
        </section>
      </div>

      {error && <div className="vq-error">{error}</div>}

      {split.length > 0 && (
        <section className="ar-panel" style={{ padding: '20px 22px', gap: 14 }}>
          <div className="sb-map-title">
            <span className="sb-panel-title">Role distribution</span>
            <span className="sb-panel-sub">Across every accredited organisation</span>
          </div>
          <div className="ac-split">
            {split.map((s) => (
              <div className="ac-split-row" key={s.role}>
                <span className="ac-split-name">{s.label}</span>
                <span className="ac-split-track">
                  <span className="ac-split-fill" style={{ width: `${s.pct}%`, background: s.color }} />
                </span>
                <span className="ac-split-n">{s.n}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="ar-panel">
        <header className="ar-head">
          <div className="sb-map-title">
            <span className="sb-panel-title">Personnel accounts</span>
            <span className="sb-panel-sub">
              {loading ? 'Loading…' : `${filtered.length} of ${people.length}`}
              {' · citizens have no organisation, so they are not listed here'}
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
              placeholder="Filter by name, role, organisation…"
              aria-label="Filter personnel"
            />
          </label>
        </header>

        <div className="ar-scroll">
          <div className="ar-cols ac-cols">
            <span className="ac-c-person">Person</span>
            <span className="ac-c-role">Role</span>
            <span className="ac-c-org">Organisation</span>
            <span className="ac-c-auth">Authority</span>
            <span className="ac-c-ver">Verification</span>
          </div>

          {!loading && filtered.length === 0 && (
            <p className="sb-empty" style={{ padding: '20px 22px' }}>
              {people.length === 0
                ? 'No personnel accounts yet. They are created when an affiliate application is approved.'
                : 'Nobody matches that filter.'}
            </p>
          )}

          {filtered.map((p) => {
            const role = ROLE[p.role] ?? { label: p.role, color: '#8a8a8a' };
            const badge = BADGE[p.badge] ?? { label: '—', color: '#8a8a8a' };
            const auth = authorityOf(p);
            return (
              <div className="ar-row ac-cols" key={p.id}>
                <div className="ac-c-person af-org">
                  <span className="ac-avatar">{initials(p.full_name)}</span>
                  <div className="af-org-text">
                    <span className="af-org-name">{p.full_name || 'Unnamed account'}</span>
                    <span className="ar-actor-sub">
                      {p.agency_type ? agencyLabel(p.agency_type) : 'No agency'}
                    </span>
                  </div>
                </div>
                <span className="ac-c-role">
                  <span className="ar-tag" style={{ color: role.color, background: `${role.color}1f` }}>
                    {role.label}
                  </span>
                </span>
                <span className="ac-c-org af-sector">{p.org}</span>
                <span className="ac-c-auth">
                  <span className="ar-tag" title={auth.hint}
                        style={{ color: auth.color, background: `${auth.color}1f` }}>
                    {auth.label}
                  </span>
                </span>
                <span className="ac-c-ver ac-ver">
                  <span className="ac-ver-pct" style={{ color: badge.color }}>
                    {p.verified_percent ?? 0}%
                  </span>
                  <span className="ar-actor-sub">{badge.label}</span>
                </span>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
