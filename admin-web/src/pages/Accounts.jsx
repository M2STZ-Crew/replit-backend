import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import Icon from '../components/ui/Icon.jsx';
import { EmptyState, PageHeader, StatePanel } from '../components/ui/index.js';

/* Accounts (REPLIT (MAIN) 10 · A48 875:7204): the Coordinators of every
 * accredited organisation, and — view only — the Responders they created.
 *
 * The roster comes from each organisation's personnel (there is no list of
 * every user, so citizens, who have no organisation, are not here). It
 * carries each person's name, role, agency and verification; the design's
 * email, title, Active/Disabled and Created columns are not returned yet,
 * and Create Coordinator (A49) waits on a matching server contract — see
 * components/accounts/CreateCoordinatorDialog.jsx. */

const BADGE = {
  green_check: 'Fully verified',
  green: 'High',
  light_green: 'Partial',
  yellow: 'Low',
};

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

export default function Accounts({ renderCreate = null }) {
  const { org } = useConsole();
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('sub_admin');
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const orgList = await api.organizations();
      const rosters = await Promise.all(
        (orgList ?? []).map((o) => api.orgPersonnel(o.id)
          .then((rows) => (rows ?? []).map((r) => ({ ...r, org: o.name, orgId: o.id })))
          .catch(() => [])),
      );
      setPeople(rosters.flat());
    } catch (e) {
      setError(e.message || 'The accounts could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people
      .filter((p) => p.role === tab)
      .filter((p) => !q || [p.full_name, p.org, p.agency_type].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)));
  }, [people, tab, query]);
  const counts = useMemo(() => ({
    sub_admin: people.filter((p) => p.role === 'sub_admin').length,
    response_team: people.filter((p) => p.role === 'response_team').length,
  }), [people]);

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={org?.name ?? 'Organization'}
        title="Accounts"
        description="Coordinators of every accredited organisation. Coordinators create their Responders’ accounts on the mobile app."
        actions={renderCreate}
      />

      <div className="ad-toolbar">
        <div className="ad-tabs" role="tablist" aria-label="Accounts">
          {[
            { key: 'sub_admin', label: 'Coordinators' },
            { key: 'response_team', label: 'Responders · view only' },
          ].map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={`ad-tab${tab === t.key ? ' is-active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {!loading && <span className="ad-tab-count">{counts[t.key]}</span>}
            </button>
          ))}
        </div>
        <label className="ad-search">
          <Icon name="search" />
          <span className="web-sr-only">Search accounts</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search names and organisations" />
        </label>
      </div>

      {loading ? (
        <StatePanel kind="loading" title="Loading accounts…" />
      ) : error ? (
        <StatePanel kind="error" title="The accounts couldn’t load" description={error} onRetry={load} />
      ) : counts[tab] === 0 ? (
        <EmptyState icon="accounts" title={tab === 'sub_admin' ? 'No Coordinators yet' : 'No Responders yet'}>
          {tab === 'sub_admin'
            ? 'A Coordinator account is created when an affiliate application is accepted.'
            : 'Coordinators create Responder accounts for their team on the mobile app.'}
        </EmptyState>
      ) : (
        <div className="web-table-wrap">
          <table className="web-table">
            <caption className="web-sr-only">{tab === 'sub_admin' ? 'Coordinators' : 'Responders'}</caption>
            <thead>
              <tr>
                <th scope="col">{tab === 'sub_admin' ? 'Coordinator' : 'Responder'}</th>
                <th scope="col">Organisation</th>
                <th scope="col">Verification</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="web-table-row">
                  <th scope="row">
                    <span className="ad-cell-resource">
                      <span className="ad-avatar" aria-hidden="true">{initials(p.full_name)}</span>
                      <span className="ad-cell-text">
                        <span className="ad-cell-title">{p.full_name || 'Unnamed account'}</span>
                        <span className="ad-cell-meta">{p.agency_type ? agencyLabel(p.agency_type) : 'No agency'}</span>
                      </span>
                    </span>
                  </th>
                  <td>{p.org}</td>
                  <td>
                    <span className="ad-cell-text">
                      <span className="ad-cell-value">{p.verified_percent ?? 0}%</span>
                      <span className="ad-cell-meta">{BADGE[p.badge] ?? '—'}</span>
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td className="web-table-empty" colSpan={3}>Nobody matches “{query}”.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
