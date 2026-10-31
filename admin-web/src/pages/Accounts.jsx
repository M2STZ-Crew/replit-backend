import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel, useAuth } from '../auth.jsx';
import CreateCoordinatorDialog from '../components/accounts/CreateCoordinatorDialog.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import Icon from '../components/ui/Icon.jsx';
import {
  ConfirmDialog, EmptyState, PageHeader, StatePanel, StatusChip,
} from '../components/ui/index.js';
import { PERM, can } from '../lib/access.js';

/* Accounts (REPLIT (MAIN) 10 · A48 875:7204, A49 875:7435, A49b 875:7722;
 * PRD v13 §4.6.4: Tier 1 creates Tier 2).
 *
 * An organisation's Admin sees its own people: the Coordinators it creates
 * and turns off and on, and — view only — the Responders its Coordinators
 * created on the mobile app. A new Coordinator is emailed a link to set their
 * password (POST /admin/coordinators). The system Admin, which belongs to no
 * organisation, sees every organisation's and names the organisation when it
 * creates one. */

const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short', year: 'numeric' });
const SHORT = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short' });

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

function created(p, myName) {
  const by = p.created_by_name ? (p.created_by_name === myName ? 'By you' : `By ${p.created_by_name}`) : null;
  const on = p.created_at ? DAY.format(new Date(p.created_at)) : null;
  const off = !p.is_active && p.deactivated_at ? `turned off ${SHORT.format(new Date(p.deactivated_at))}` : null;
  return [by, on, off].filter(Boolean).join(' · ') || '—';
}

export default function Accounts() {
  const { org, console: access } = useConsole();
  const { user } = useAuth();
  const everyOrg = access?.variant === 'system';
  const manages = can(access, PERM.CREATE_COORDINATORS) && (everyOrg || Boolean(org?.id));

  const [people, setPeople] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('sub_admin');
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const [turningOff, setTurningOff] = useState(null);
  const [notice, setNotice] = useState(null);
  const [warning, setWarning] = useState(null);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (everyOrg) {
        const orgList = (await api.organizations()) ?? [];
        setOrgs(orgList);
        const rosters = await Promise.all(
          orgList.map((o) => api.orgPersonnel(o.id)
            .then((rows) => (rows ?? []).map((r) => ({ ...r, org: o.name, orgId: o.id })))
            .catch(() => [])),
        );
        setPeople(rosters.flat());
      } else if (org?.id) {
        const rows = await api.orgPersonnel(org.id);
        setPeople((rows ?? []).map((r) => ({ ...r, org: org.name, orgId: org.id })));
      } else {
        setPeople([]);
      }
    } catch (e) {
      setError(e.message || 'The accounts could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [everyOrg, org?.id, org?.name]);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people
      .filter((p) => p.role === tab)
      .filter((p) => !q || [p.full_name, p.email, p.title, p.org].filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)));
  }, [people, tab, query]);
  const counts = useMemo(() => ({
    sub_admin: people.filter((p) => p.role === 'sub_admin').length,
    response_team: people.filter((p) => p.role === 'response_team').length,
  }), [people]);

  async function create({ fullName, email, title, organizationId }) {
    const result = await api.createCoordinator({ fullName, email, title, organizationId });
    setCreating(false);
    setTab('sub_admin');
    setNotice(`Coordinator account created for ${result.coordinator?.full_name ?? fullName}`);
    setWarning(result.invite_email_sent ? null : (result.detail || 'The email with their password link was not sent.'));
    await load();
  }

  async function turnOff(person) {
    await api.deactivateCoordinator(person.id);
    setTurningOff(null);
    setNotice(`${person.full_name}’s account is turned off`);
    await load();
  }

  async function turnOn(person) {
    setError(null);
    try {
      await api.reactivateCoordinator(person.id);
      setNotice(`${person.full_name}’s account is turned on`);
      await load();
    } catch (e) {
      setError(e.message || 'The account could not be turned on.');
    }
  }

  const coordinators = tab === 'sub_admin';
  const myName = user?.full_name ?? null;

  if (!everyOrg && !org?.id) {
    return (
      <div className="rpl-page">
        <PageHeader eyebrow="Organization" title="Accounts" />
        <EmptyState icon="accounts" title="No organization on this account">
          Your Admin account isn’t attached to an organization, so there are no accounts to manage here.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? 'Organization'}
        title="Accounts"
        description={everyOrg
          ? 'Coordinators of every accredited organization. Responder accounts are created by Coordinators.'
          : 'You create and turn off Coordinator accounts. Responder accounts are created by Coordinators.'}
        actions={manages && (
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => setCreating(true)}>
            Create Coordinator
          </button>
        )}
      />

      {warning && (
        <div className="rpl-alert rpl-alert--warn" role="status">
          <span className="rpl-alert-mark" aria-hidden="true">!</span>
          <div className="rpl-alert-text">
            <p className="rpl-alert-title">The account is ready, but its email didn’t go out</p>
            <p className="rpl-alert-body">{warning}</p>
            <button type="button" className="rpl-text-button" onClick={() => setWarning(null)}>Dismiss</button>
          </div>
        </div>
      )}

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label="Accounts">
          {[
            { key: 'sub_admin', label: 'Coordinators' },
            { key: 'response_team', label: 'Responders · view only' },
          ].map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={`rpl-tab${tab === t.key ? ' is-active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {!loading && <span className="rpl-tab-count">{counts[t.key]}</span>}
            </button>
          ))}
        </div>
        <label className="rpl-search">
          <Icon name="search" />
          <span className="web-sr-only">Search accounts</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search names, emails and titles" />
        </label>
      </div>

      {loading ? (
        <StatePanel kind="loading" title="Loading accounts…" />
      ) : error ? (
        <StatePanel kind="error" title="The accounts couldn’t load" description={error} onRetry={load} />
      ) : counts[tab] === 0 ? (
        <EmptyState icon="accounts" title={coordinators ? 'No Coordinators yet' : 'No Responders yet'}>
          {coordinators
            ? (manages ? 'Create the first one: they get an email with a link to set their password.' : 'A Coordinator account is created when an affiliate application is accepted.')
            : 'Coordinators create Responder accounts for their team on the mobile app.'}
        </EmptyState>
      ) : (
        <div className="web-table-wrap">
          <table className="web-table">
            <caption className="web-sr-only">{coordinators ? 'Coordinators' : 'Responders'}</caption>
            <thead>
              <tr>
                <th scope="col">{coordinators ? 'Coordinator' : 'Responder'}</th>
                {everyOrg && <th scope="col">Organization</th>}
                <th scope="col">Title</th>
                <th scope="col">Status</th>
                <th scope="col">Created</th>
                {coordinators && manages && <th scope="col"><span className="web-sr-only">Actions</span></th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className={`web-table-row${p.is_active === false ? ' is-disabled' : ''}`}>
                  <th scope="row">
                    <span className="rpl-cell-resource">
                      <span className="rpl-avatar" aria-hidden="true">{initials(p.full_name)}</span>
                      <span className="rpl-cell-text">
                        <span className="rpl-cell-title">{p.full_name || 'Unnamed account'}</span>
                        <span className="rpl-cell-meta">{p.email || (p.agency_type ? agencyLabel(p.agency_type) : '—')}</span>
                      </span>
                    </span>
                  </th>
                  {everyOrg && <td>{p.org}</td>}
                  <td>{p.title || '—'}</td>
                  <td>
                    <StatusChip
                      label={p.is_active === false ? 'Disabled' : 'Active'}
                      tone={p.is_active === false ? 'neutral' : 'ok'}
                    />
                  </td>
                  <td className="rpl-cell-quiet">{created(p, myName)}</td>
                  {coordinators && manages && (
                    <td className="web-table-action-cell">
                      <span className="rpl-account-actions">
                        {p.is_active === false ? (
                          <button type="button" className="web-table-row-action" onClick={() => turnOn(p)}>
                            Turn on<span className="web-sr-only"> {p.full_name}’s account</span>
                          </button>
                        ) : (
                          <button type="button" className="web-table-row-action" onClick={() => setTurningOff(p)}>
                            Turn off<span className="web-sr-only"> {p.full_name}’s account</span>
                          </button>
                        )}
                      </span>
                    </td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td className="web-table-empty" colSpan={6}>Nobody matches “{query}”.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {notice && (
        <div className="rpl-toast" role="status">
          <span aria-hidden="true">✓</span>
          {notice}
        </div>
      )}

      <CreateCoordinatorDialog
        open={creating}
        organization={org?.name ?? 'your organization'}
        organizations={everyOrg ? orgs.filter((o) => o.is_active) : null}
        onCreate={create}
        onClose={() => setCreating(false)}
      />

      <ConfirmDialog
        open={Boolean(turningOff)}
        eyebrow={turningOff ? `Coordinator · ${turningOff.org ?? org?.name ?? ''}` : ''}
        title={turningOff ? `Turn off ${turningOff.full_name}’s account?` : ''}
        description="They can’t sign in until you turn it back on. Their history stays, and any response they’re on is released."
        confirmLabel="Turn off"
        destructive
        onClose={() => setTurningOff(null)}
        onConfirm={() => turnOff(turningOff)}
      />
    </div>
  );
}
