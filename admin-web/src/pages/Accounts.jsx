import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel, useAuth } from '../auth.jsx';
import CreateCoordinatorDialog from '../components/accounts/CreateCoordinatorDialog.jsx';
import { ManageAccountDialog, PasswordLinkDialog, accountEyebrow } from '../components/accounts/ResponderDialogs.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import Pager, { usePager } from '../components/ui/Pager.jsx';
import {
  ConfirmDialog, EmptyState, PageHeader, StatePanel, StatusChip,
} from '../components/ui/index.js';
import { PERM, can, governsAll } from '../lib/access.js';
import { fireAt, fireName } from '../lib/place.js';
import { t } from '../i18n/i18n.jsx';
import SearchBox from '../components/ui/SearchBox.jsx';

/* Accounts (REPLIT (MAIN) 10 · A48 875:7204, A49 875:7435, A49b 875:7722;
 * PRD v13 §4.6.4: Tier 1 creates Tier 2).
 *
 * An organisation's Admin manages its own Coordinators and Responders the
 * same way (22 Nov 2026: "admin can manage responders too"; 23 Nov 2026:
 * "make the account management in coordinator and responder the same"):
 * create, edit, send a password link, turn off and on, and see who is on a
 * fire. Dispatching stays with the Coordinators. A new account is emailed a
 * link to set its password. The system Admin and the central hub see every
 * organisation's, name the organisation when they create one, and move an
 * account within an agency. */

const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short', year: 'numeric' });
const SHORT = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short' });
// How often a tab asks again who is on a fire.
const REFRESH_MS = 30000;

// Each kind's calls: the same set, whichever tab.
const CALLS = {
  sub_admin: {
    list: api.adminCoordinators,
    save: api.updateCoordinator,
    link: api.coordinatorPasswordLink,
    off: api.deactivateCoordinator,
    on: api.reactivateCoordinator,
  },
  response_team: {
    list: api.adminResponders,
    save: api.updateResponder,
    link: api.responderPasswordLink,
    off: api.deactivateResponder,
    on: api.reactivateResponder,
  },
};
const asRows = (role, list) => (list ?? []).map((p) => ({
  ...p, role, org: p.organization_name, orgId: p.organization_id,
}));

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

export default function Accounts({ onOpenIncident }) {
  const { org, console: access } = useConsole();
  const { user } = useAuth();
  // The system Admin and the central hub manage every organisation's.
  const everyOrg = governsAll(access);
  const manages = can(access, PERM.CREATE_COORDINATORS) && (everyOrg || Boolean(org?.id));
  const managesResponders = can(access, PERM.MANAGE_RESPONDERS) && (everyOrg || Boolean(org?.id));

  const [people, setPeople] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('sub_admin');
  const [query, setQuery] = useState('');
  // Which account is being created: a 'sub_admin' or a 'response_team' one.
  const [creating, setCreating] = useState(null);
  const [turningOff, setTurningOff] = useState(null);
  const [editing, setEditing] = useState(null);
  const [linking, setLinking] = useState(null);
  const [notice, setNotice] = useState(null);
  const [warning, setWarning] = useState(null);
  const [failed, setFailed] = useState(null);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Each kind this Admin manages, with its fire; one it only looks at
      // comes from its organization's roster.
      const lists = { sub_admin: manages, response_team: managesResponders };
      const [orgList, roster, ...managed] = await Promise.all([
        everyOrg ? api.organizations() : null,
        (!manages || !managesResponders) && org?.id ? api.orgPersonnel(org.id) : null,
        ...Object.entries(lists).map(async ([role, mine]) => (mine ? asRows(role, await CALLS[role].list()) : [])),
      ]);
      setOrgs(orgList ?? []);
      const looked = (roster ?? [])
        .filter((p) => p.role in lists && !lists[p.role])
        .map((p) => ({ ...p, org: org.name, orgId: org.id }));
      setPeople([...managed.flat(), ...looked]);
    } catch (e) {
      setError(e.message || t('The accounts could not be loaded.'));
    } finally {
      setLoading(false);
    }
  }, [everyOrg, manages, managesResponders, org?.id, org?.name]);
  useEffect(() => { load(); }, [load]);

  // Who is on a fire changes while the tab is open.
  useEffect(() => {
    const mine = tab === 'sub_admin' ? manages : managesResponders;
    if (!mine || loading) return undefined;
    let left = false;
    const timer = setInterval(async () => {
      if (document.visibilityState === 'hidden') return;
      try {
        const fresh = asRows(tab, await CALLS[tab].list());
        if (!left) setPeople((all) => all.filter((p) => p.role !== tab).concat(fresh));
      } catch {
        // The next refresh asks again; the list on screen stays.
      }
    }, REFRESH_MS);
    return () => { left = true; clearInterval(timer); };
  }, [tab, manages, managesResponders, loading]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people
      .filter((p) => p.role === tab)
      .filter((p) => !q || [p.full_name, p.email, p.title, p.org, p.mobile, p.responding_to].filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)));
  }, [people, tab, query]);
  const counts = useMemo(() => ({
    sub_admin: people.filter((p) => p.role === 'sub_admin').length,
    response_team: people.filter((p) => p.role === 'response_team').length,
  }), [people]);
  const { shown, pager } = usePager(rows, { key: 'accounts', reset: [tab, query] });

  async function create({ firstName, lastName, personalEmail, title, mobile, organizationId }) {
    if (creating === 'response_team') {
      const made = await api.createResponder({ firstName, lastName, personalEmail, title, mobile, organizationId });
      setCreating(null);
      setTab('response_team');
      setNotice(t('Responder account created: {name} signs in as {address}', {
        name: made.responder?.full_name ?? `${firstName} ${lastName}`,
        address: made.responder?.email ?? '—',
      }));
      setWarning(made.invite_email_sent ? null : (made.detail || t('The email with their password link was not sent.')));
      await load();
      return;
    }
    const result = await api.createCoordinator({ firstName, lastName, personalEmail, title, mobile, organizationId });
    setCreating(null);
    setTab('sub_admin');
    setNotice(t('Coordinator account created: {name} signs in as {address}', {
      name: result.coordinator?.full_name ?? `${firstName} ${lastName}`,
      address: result.coordinator?.email ?? '—',
    }));
    setWarning(result.invite_email_sent ? null : (result.detail || t('The email with their password link was not sent.')));
    await load();
  }

  async function turnOff(person) {
    await CALLS[person.role].off(person.id);
    setTurningOff(null);
    setNotice(t('{full_name}’s account is turned off', { full_name: person.full_name || person.email }));
    await load();
  }

  async function turnOn(person) {
    setFailed(null);
    try {
      await CALLS[person.role].on(person.id);
      setNotice(t('{full_name}’s account is turned on', { full_name: person.full_name || person.email }));
      await load();
    } catch (e) {
      setFailed(e.message || t('The account could not be turned on.'));
    }
  }

  async function saveEdit(person, changes) {
    const saved = await CALLS[person.role].save(person.id, changes);
    setEditing(null);
    setNotice(changes.organization_id
      ? t('{name} moved to {org}', { name: saved.full_name ?? person.email, org: saved.organization_name ?? '—' })
      : t('{name}’s account is saved', { name: saved.full_name ?? person.email }));
    await load();
  }

  async function sendLink(person, personalEmail) {
    const { sent_to: address } = await CALLS[person.role].link(person.id, personalEmail);
    setLinking(null);
    setNotice(t('Password link sent to {address}', { address }));
    await load();
  }

  const coordinators = tab === 'sub_admin';
  const actsHere = coordinators ? manages : managesResponders;
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
        description={managesResponders
          ? (everyOrg
            ? t('Coordinators and Responders of every organization. Dispatching stays with Coordinators.')
            : t('You manage your organization’s Coordinator and Responder accounts. Dispatching stays with Coordinators.'))
          : t('Responder accounts are created by Coordinators.')}
        actions={actsHere && (
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => setCreating(tab)}>
            {coordinators ? t('Create Coordinator') : t('Create Responder')}
          </button>
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

      {failed && (
        <div className="rpl-alert rpl-alert--danger" role="alert">
          <span className="rpl-alert-mark" aria-hidden="true">!</span>
          <div className="rpl-alert-text">
            <p className="rpl-alert-title">{t('The account is still off')}</p>
            <p className="rpl-alert-body">{failed}</p>
            <button type="button" className="rpl-text-button" onClick={() => setFailed(null)}>{t('Dismiss')}</button>
          </div>
        </div>
      )}

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label={t('Accounts')}>
          {[
            { key: 'sub_admin', label: t('Coordinators') },
            { key: 'response_team', label: managesResponders ? t('Responders') : t('Responders · view only') },
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
        <SearchBox label={t('Search accounts')} placeholder={t('Search names, emails and titles')} value={query} onChange={setQuery} />
      </div>

      {loading ? (
        <StatePanel kind="loading" title={t('Loading accounts…')} />
      ) : error ? (
        <StatePanel kind="error" title={t('The accounts couldn’t load')} description={error} onRetry={load} />
      ) : counts[tab] === 0 ? (
        <EmptyState icon="accounts" title={coordinators ? t('No Coordinators yet') : t('No Responders yet')}>
          {coordinators
            ? (manages ? t('Create the first one: they get an email with a link to set their password.') : t('A Coordinator account is created when an affiliate application is accepted.'))
            : managesResponders
              ? t('Create the first one here, or their Coordinator can on the mobile app.')
              : t('Coordinators create Responder accounts for their team on the mobile app.')}
        </EmptyState>
      ) : (
        <>
          <div className="web-table-wrap">
            <table className="web-table">
              <caption className="web-sr-only">{coordinators ? t('Coordinators') : t('Responders')}</caption>
              <thead>
                <tr>
                  <th scope="col">{coordinators ? t('Coordinator') : t('Responder')}</th>
                  {everyOrg && <th scope="col">{t('Organization')}</th>}
                  <th scope="col">{t('Title and mobile')}</th>
                  <th scope="col">{t('Status')}</th>
                  <th scope="col">{t('Created')}</th>
                  {actsHere && <th scope="col"><span className="web-sr-only">{t('Actions')}</span></th>}
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => (
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
                    {everyOrg && <td data-label={t('Organization')}>{p.org || t('No organization')}</td>}
                    <td data-label={t('Title and mobile')}>
                      <span className="rpl-account-detail">
                        <span>{p.title || '—'}</span>
                        {p.mobile && <span className="rpl-cell-meta">{p.mobile}</span>}
                      </span>
                    </td>
                    <td>
                      <span className="rpl-account-detail">
                        <StatusChip
                          label={p.is_active === false ? t('Disabled') : p.responding ? t('On a fire') : t('Active')}
                          tone={p.is_active === false ? 'neutral' : p.responding ? 'danger' : 'ok'}
                        />
                        {p.responding && p.responding_area_id && onOpenIncident && (
                          <button type="button" className="rpl-text-button rpl-account-fire" onClick={() => onOpenIncident(p.responding_area_id)}>
                            {fireName(p.responding_to) || t('Open the incident')}
                          </button>
                        )}
                      </span>
                    </td>
                    <td className="rpl-cell-quiet" data-label={t('Created')}>{created(p, myName)}</td>
                    {actsHere && (
                      <td className="web-table-action-cell">
                        <span className="rpl-account-actions">
                          <button type="button" className="web-table-row-action" onClick={() => setEditing(p)}>{t('Manage')}<span className="web-sr-only">{t(' {name}’s account', { name: p.full_name || p.email })}</span>
                          </button>
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
          <Pager {...pager} />
        </>
      )}

      {notice && (
        <div className="rpl-toast" role="status">
          <span aria-hidden="true">✓</span>
          {notice}
        </div>
      )}

      <CreateCoordinatorDialog
        open={Boolean(creating)}
        responder={creating === 'response_team'}
        organization={org?.name ?? t('your organization')}
        organizations={everyOrg ? orgs.filter((o) => o.is_active) : null}
        onCreate={create}
        onClose={() => setCreating(null)}
      />
      <ManageAccountDialog
        person={editing}
        organizations={everyOrg ? orgs : null}
        onSave={saveEdit}
        onLink={(person) => { setEditing(null); setLinking(person); }}
        onTurnOff={(person) => { setEditing(null); setTurningOff(person); }}
        onTurnOn={(person) => { setEditing(null); turnOn(person); }}
        onClose={() => setEditing(null)}
      />
      <PasswordLinkDialog person={linking} onSend={sendLink} onClose={() => setLinking(null)} />

      <ConfirmDialog
        open={Boolean(turningOff)}
        eyebrow={accountEyebrow(turningOff)}
        title={turningOff ? t('Turn off {full_name}’s account?', { full_name: turningOff.full_name || turningOff.email }) : ''}
        description={turningOff?.responding
          ? t('They’re responding to {fire} now and will be taken off it. They can’t sign in until you turn it back on. Their history stays.', { fire: fireAt(turningOff.responding_to) })
          : t('They can’t sign in until you turn it back on. Their history stays, and any response they’re on is released.')}
        confirmLabel={t('Turn off')}
        destructive
        onClose={() => setTurningOff(null)}
        onConfirm={() => turnOff(turningOff)}
      />
    </div>
  );
}
