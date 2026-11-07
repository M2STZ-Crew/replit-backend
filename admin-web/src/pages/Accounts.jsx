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
import { t } from '../i18n/i18n.jsx';

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
  const by = p.created_by_name ? (p.created_by_name === myName ? t('By you') : t('By {created_by_name}', { created_by_name: p.created_by_name })) : null;
  const on = p.created_at ? DAY.format(new Date(p.created_at)) : null;
  const off = !p.is_active && p.deactivated_at ? t('turned off {date}', { date: SHORT.format(new Date(p.deactivated_at)) }) : null;
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
      setError(e.message || t('The accounts could not be loaded.'));
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

  async function create({ firstName, lastName, personalEmail, title, organizationId }) {
    const result = await api.createCoordinator({ firstName, lastName, personalEmail, title, organizationId });
    setCreating(false);
    setTab('sub_admin');
    setNotice(t('Coordinator account created: {name} signs in as {address}', {
      name: result.coordinator?.full_name ?? `${firstName} ${lastName}`,
      address: result.coordinator?.email ?? '—',
    }));
    setWarning(result.invite_email_sent ? null : (result.detail || t('The email with their password link was not sent.')));
    await load();
  }

  async function turnOff(person) {
    await api.deactivateCoordinator(person.id);
    setTurningOff(null);
    setNotice(t('{full_name}’s account is turned off', { full_name: person.full_name }));
    await load();
  }

  async function turnOn(person) {
    setError(null);
    try {
      await api.reactivateCoordinator(person.id);
      setNotice(t('{full_name}’s account is turned on', { full_name: person.full_name }));
      await load();
    } catch (e) {
      setError(e.message || t('The account could not be turned on.'));
    }
  }

  const coordinators = tab === 'sub_admin';
  const myName = user?.full_name ?? null;

  if (!everyOrg && !org?.id) {
    return (
      <div className="rpl-page">
        <PageHeader eyebrow={t('Organization')} title={t('Accounts')} />
        <EmptyState icon="accounts" title={t('No organization on this account')}>{t('Your Admin account isn’t attached to an organization, so there are no accounts to manage here.')}</EmptyState>
      </div>
    );
  }

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? t('Organization')}
        title={t('Accounts')}
        description={everyOrg
          ? t('Coordinators of every accredited organization. Responder accounts are created by Coordinators.')
          : t('You create and turn off Coordinator accounts. Responder accounts are created by Coordinators.')}
        actions={manages && (
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => setCreating(true)}>{t('Create Coordinator')}</button>
        )}
      />

      {warning && (
        <div className="rpl-alert rpl-alert--warn" role="status">
          <span className="rpl-alert-mark" aria-hidden="true">!</span>
          <div className="rpl-alert-text">
            <p className="rpl-alert-title">{t('The account is ready, but its email didn’t go out')}</p>
            <p className="rpl-alert-body">{warning}</p>
            <button type="button" className="rpl-text-button" onClick={() => setWarning(null)}>{t('Dismiss')}</button>
          </div>
        </div>
      )}

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label={t('Accounts')}>
          {[
            { key: 'sub_admin', label: t('Coordinators') },
            { key: 'response_team', label: t('Responders · view only') },
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
          <span className="web-sr-only">{t('Search accounts')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search names, emails and titles')} />
        </label>
      </div>

      {loading ? (
        <StatePanel kind="loading" title={t('Loading accounts…')} />
      ) : error ? (
        <StatePanel kind="error" title={t('The accounts couldn’t load')} description={error} onRetry={load} />
      ) : counts[tab] === 0 ? (
        <EmptyState icon="accounts" title={coordinators ? t('No Coordinators yet') : t('No Responders yet')}>
          {coordinators
            ? (manages ? t('Create the first one: they get an email with a link to set their password.') : t('A Coordinator account is created when an affiliate application is accepted.'))
            : t('Coordinators create Responder accounts for their team on the mobile app.')}
        </EmptyState>
      ) : (
        <div className="web-table-wrap">
          <table className="web-table">
            <caption className="web-sr-only">{coordinators ? t('Coordinators') : t('Responders')}</caption>
            <thead>
              <tr>
                <th scope="col">{coordinators ? t('Coordinator') : t('Responder')}</th>
                {everyOrg && <th scope="col">{t('Organization')}</th>}
                <th scope="col">{t('Title')}</th>
                <th scope="col">{t('Status')}</th>
                <th scope="col">{t('Created')}</th>
                {coordinators && manages && <th scope="col"><span className="web-sr-only">{t('Actions')}</span></th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className={`web-table-row${p.is_active === false ? ' is-disabled' : ''}`}>
                  <th scope="row">
                    <span className="rpl-cell-resource">
                      <span className="rpl-avatar" aria-hidden="true">{initials(p.full_name)}</span>
                      <span className="rpl-cell-text">
                        <span className="rpl-cell-title">{p.full_name || t('Unnamed account')}</span>
                        <span className="rpl-cell-meta">{p.email || (p.agency_type ? agencyLabel(p.agency_type) : '—')}</span>
                      </span>
                    </span>
                  </th>
                  {everyOrg && <td>{p.org}</td>}
                  <td>{p.title || '—'}</td>
                  <td>
                    <StatusChip
                      label={p.is_active === false ? t('Disabled') : t('Active')}
                      tone={p.is_active === false ? 'neutral' : 'ok'}
                    />
                  </td>
                  <td className="rpl-cell-quiet">{created(p, myName)}</td>
                  {coordinators && manages && (
                    <td className="web-table-action-cell">
                      <span className="rpl-account-actions">
                        {p.is_active === false ? (
                          <button type="button" className="web-table-row-action" onClick={() => turnOn(p)}>{t('Turn on')}<span className="web-sr-only">{t(' {name}’s account', { name: p.full_name })}</span>
                          </button>
                        ) : (
                          <button type="button" className="web-table-row-action" onClick={() => setTurningOff(p)}>{t('Turn off')}<span className="web-sr-only">{t(' {name}’s account', { name: p.full_name })}</span>
                          </button>
                        )}
                      </span>
                    </td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td className="web-table-empty" colSpan={6}>{t('Nobody matches “{query}”.', { query })}</td></tr>
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
        organization={org?.name ?? t('your organization')}
        organizations={everyOrg ? orgs.filter((o) => o.is_active) : null}
        onCreate={create}
        onClose={() => setCreating(false)}
      />

      <ConfirmDialog
        open={Boolean(turningOff)}
        eyebrow={turningOff ? t('Coordinator · {org}', { org: turningOff.org ?? org?.name ?? '' }) : ''}
        title={turningOff ? t('Turn off {full_name}’s account?', { full_name: turningOff.full_name }) : ''}
        description={t('They can’t sign in until you turn it back on. Their history stays, and any response they’re on is released.')}
        confirmLabel={t('Turn off')}
        destructive
        onClose={() => setTurningOff(null)}
        onConfirm={() => turnOff(turningOff)}
      />
    </div>
  );
}
