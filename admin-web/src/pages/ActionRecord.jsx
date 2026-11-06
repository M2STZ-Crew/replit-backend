import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import { EmptyState, Icon, PageHeader, StatePanel } from '../components/ui/index.js';
import { t } from '../i18n/i18n.jsx';

/* Audit log (REPLIT (MAIN) 10 · A64 879:8852; Section 2.5 audit trail): the
 * append-only record of consequential actions, newest first.
 *
 * Each entry keeps the actor's role and agency as they were at the time.
 * The server stores no actor name, so the actor column names the role and
 * agency instead. The design's correction entries (A65) wait on server
 * support. An earlier design showed a hash-chained digest; audit_logs has
 * no hash or chain, so no such property is claimed. */

const CLOCK = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit', second: '2-digit',
});
const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short' });

/* Categories come from the action's "<entity>.<verb>" prefix, the naming
 * convention the migration documents. Anything unrecognised is "Other"
 * rather than dropped. */
const CATEGORY = {
  get incident() { return t('Incident'); },
  get area() { return t('Incident'); },
  get alarm() { return t('Alarm'); },
  get kyc() { return t('Identity'); },
  get hydrant() { return t('Water'); },
  get map_layer() { return t('Map layer'); },
  get user() { return t('Account'); },
  get report() { return t('Report'); },
  get dispatch() { return t('Dispatch'); },
};
const categoryOf = (action = '') => CATEGORY[action.split('.')[0]] ?? t('Other');

const VERB = {
  get 'incident.route'() { return t('Routed to agencies'); },
  get 'incident.accept'() { return t('Acknowledged'); },
  get 'incident.verify'() { return t('Acknowledged'); },
  get 'incident.post_incident_report'() { return t('Filed post-incident report'); },
};
function labelOf(action = '') {
  if (VERB[action]) return VERB[action];
  const words = (action.split('.').slice(1).join(' ') || action).replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const ROLE = { get admin() { return t('Admin'); }, get sub_admin() { return t('Coordinator'); }, get response_team() { return t('Responder'); }, get general_user() { return t('Citizen'); } };

function detailOf(r) {
  if (r.action === 'incident.route' && Array.isArray(r.metadata?.routes)) {
    return r.metadata.routes
      .map((x) => `${agencyLabel(x.agency)}${x.organization_name ? ` (${x.organization_name})` : ''}`)
      .join(', ');
  }
  if (r.metadata?.notes) return r.metadata.notes;
  return null;
}

const shortId = (id) => (id ? String(id).slice(0, 8) : '—');

function timeOf(iso) {
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? CLOCK.format(d) : `${DAY.format(d)}, ${CLOCK.format(d)}`;
}

export default function ActionRecord() {
  const { org } = useConsole();
  const [rows, setRows] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [area, setArea] = useState('all');
  const [category, setCategory] = useState('all');

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      const list = await api.auditLogs({ limit: 200 });
      setRows(Array.isArray(list) ? list : []);
      setPhase('ready');
    } catch (e) {
      setError(e.message || t('The audit log could not be loaded.'));
      setPhase('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const areas = useMemo(() => [...new Set(rows.map((r) => r.area_designation).filter(Boolean))].sort(), [rows]);
  const categories = useMemo(() => [...new Set(rows.map((r) => categoryOf(r.action)))].sort(), [rows]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (area !== 'all' && r.area_designation !== area) return false;
      if (category !== 'all' && categoryOf(r.action) !== category) return false;
      if (!q) return true;
      return [r.action, labelOf(r.action), r.actor_role, r.actor_agency, r.entity_type, r.area_designation, detailOf(r)]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [rows, query, area, category]);

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? t('Records')}
        title={t('Audit log')}
        description={t('Append-only. Each entry keeps the actor’s role and agency as they were at the time.')}
        actions={(
          <button type="button" className="rpl-button rpl-button--secondary" onClick={load} disabled={phase === 'loading'}>{t('Refresh')}</button>
        )}
      />

      <div className="rpl-filters">
        <label className="rpl-search">
          <Icon name="search" />
          <span className="web-sr-only">{t('Search the audit log')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search actions, areas, agencies')} />
        </label>
        <label className="rpl-select">
          <span className="rpl-select-label">{t('Area')}</span>
          <select value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="all">{t('All areas')}</option>
            {areas.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="rpl-select">
          <span className="rpl-select-label">{t('Action')}</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="all">{t('All actions')}</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" title={t('Loading the audit log…')} busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title={t('The audit log couldn’t load')} description={error} onRetry={load} />
      ) : rows.length === 0 ? (
        <EmptyState icon="audit" title={t('Nothing recorded yet')}>{t('Entries appear as incidents are acknowledged, reports are filed and requests are decided.')}</EmptyState>
      ) : (
        <>
          <div className="web-table-wrap">
            <table className="web-table rpl-audit">
              <caption className="web-sr-only">{t('Audit log, newest first')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('Time (PHT)')}</th>
                  <th scope="col">{t('Actor at the time')}</th>
                  <th scope="col">{t('Action')}</th>
                  <th scope="col">{t('Target')}</th>
                  <th scope="col">{t('Detail')}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className="web-table-row">
                    <td className="rpl-cell-strong rpl-audit-time">
                      <time dateTime={r.created_at}>{timeOf(r.created_at)}</time>
                    </td>
                    <td>
                      <span className="rpl-cell-text">
                        <span className="rpl-cell-title">{r.actor_role ? (ROLE[r.actor_role] ?? r.actor_role) : t('System')}</span>
                        <span className="rpl-cell-meta">{r.actor_agency ? agencyLabel(r.actor_agency) : r.actor_user_id ? t('Account {shortId}', { shortId: shortId(r.actor_user_id) }) : t('Automatic')}</span>
                      </span>
                    </td>
                    <th scope="row">
                      <span className="rpl-cell-text">
                        <span className="rpl-cell-title">{labelOf(r.action)}</span>
                        <span className="rpl-cell-meta">{r.action}</span>
                      </span>
                    </th>
                    <td className="rpl-cell-strong">
                      {r.area_designation || (r.entity_type ? `${r.entity_type.replace(/_/g, ' ')} ${shortId(r.entity_id ?? r.area_id)}` : '—')}
                    </td>
                    <td className="rpl-audit-detail">{detailOf(r) ?? '—'}</td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr><td className="web-table-empty" colSpan={5}>{t('No entries match these filters.')}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="rpl-table-foot">{t('Showing {shown} of the latest {total} entries', { shown: shown.length, total: rows.length })}</p>
        </>
      )}
    </div>
  );
}
