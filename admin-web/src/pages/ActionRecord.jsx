import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import {
  EmptyState, Icon, PageHeader, Pager, Select, StatePanel, usePager,
} from '../components/ui/index.js';
import { t } from '../i18n/i18n.jsx';
import { fireName } from '../lib/place.js';
import SearchBox from '../components/ui/SearchBox.jsx';

/* Audit log (REPLIT (MAIN) 10 · A64 879:8852; Section 2.5 audit trail): the
 * append-only record of consequential actions.
 *
 * Each entry keeps the actor's role and agency as they were at the time, and
 * a staff member's name and organisation (a resident's name is never sent).
 * The design's correction entries (A65) wait on server support. An earlier
 * design showed a hash-chained digest; audit_logs has no hash or chain, so no
 * such property is claimed.
 *
 * v1.12.47 (20 Nov 2026: "in the audit logs, make it per incident and put
 * some sorting to it (alphabethical and recent)"; answered "Grouped by
 * incident"): the entries are grouped by the incident they are about, each
 * group's timeline inside it, oldest first, as the incident unfolded. The
 * groups are sorted by their latest entry (Most recent) or by the fire's name
 * (A–Z), and paged like every list. Entries about no incident (accounts, map
 * layers, identity checks) are a group of their own, newest first. */

const LOADED = 500; // the most the server lists at once

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
  get 'incident.under_control'() { return t('Declared under control'); },
  get 'incident.under_control_withdrawn'() { return t('Withdrew Under control'); },
  get 'user.responder_created'() { return t('Created a Responder account'); },
  get 'user.responder_updated'() { return t('Edited a Responder account'); },
  get 'user.responder_moved'() { return t('Moved a Responder'); },
  get 'user.responder_email_set'() { return t('Set a Responder’s email'); },
  get 'user.responder_password_link'() { return t('Sent a Responder a password link'); },
  get 'user.responder_password_reset'() { return t('Reset a Responder’s password'); },
  get 'user.responder_deactivated'() { return t('Turned off a Responder account'); },
  get 'user.responder_reactivated'() { return t('Turned on a Responder account'); },
};
// What an edit changed, named on its entry.
const FIELD = {
  get full_name() { return t('name'); },
  get title() { return t('title'); },
  get mobile() { return t('mobile'); },
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
  if (r.metadata?.responder) {
    const changed = (r.metadata.changed ?? []).map((key) => FIELD[key] ?? key).join(', ');
    const to = r.metadata.moved_to ? t('to {org}', { org: r.metadata.moved_to }) : null;
    return [r.metadata.responder, to, changed].filter(Boolean).join(' · ');
  }
  return null;
}

const shortId = (id) => (id ? String(id).slice(0, 8) : '—');

function timeOf(iso) {
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? CLOCK.format(d) : `${DAY.format(d)}, ${CLOCK.format(d)}`;
}

/* Who acted: a staff member by name and organisation, with their role then;
 * otherwise the role and agency, or the system. */
function actorOf(r) {
  const role = r.actor_role ? (ROLE[r.actor_role] ?? r.actor_role) : t('System');
  if (r.actor_name) {
    const org = r.actor_organization || (r.actor_agency ? agencyLabel(r.actor_agency) : null);
    return [r.actor_name, org, role].filter(Boolean).join(' · ');
  }
  const who = r.actor_agency
    ? agencyLabel(r.actor_agency)
    : r.actor_user_id ? t('Account {shortId}', { shortId: shortId(r.actor_user_id) }) : t('Automatic');
  return `${role} · ${who}`;
}

/* What an entry about no incident was about: "map layer 1a2b3c4d". */
const targetOf = (r) => (r.entity_type ? `${r.entity_type.replace(/_/g, ' ')} ${shortId(r.entity_id)}` : null);

const OTHER = 'other';
const at = (iso) => new Date(iso).getTime();

/* The entries by incident: each group's entries oldest first (newest first
 * for the group about no incident), its latest time, and its name. */
function groupsOf(rows) {
  const byKey = new Map();
  for (const r of rows) {
    const key = r.area_id ?? OTHER;
    if (!byKey.has(key)) {
      byKey.set(key, {
        key,
        areaId: r.area_id ?? null,
        name: r.area_id
          ? fireName(r.area_designation) || t('Incident {shortId}', { shortId: shortId(r.area_id) })
          : t('Not about an incident'),
        entries: [],
      });
    }
    byKey.get(key).entries.push(r);
  }
  return [...byKey.values()].map((g) => {
    const newestFirst = g.key === OTHER;
    const entries = [...g.entries].sort((a, b) => (newestFirst ? at(b.created_at) - at(a.created_at) : at(a.created_at) - at(b.created_at)));
    const latest = entries.reduce((m, r) => Math.max(m, at(r.created_at)), 0);
    const last = entries.find((r) => at(r.created_at) === latest);
    return { ...g, entries, newestFirst, latest, last };
  });
}

const SORTS = {
  recent: { get label() { return t('Most recent'); }, compare: (a, b) => b.latest - a.latest },
  az: {
    get label() { return t('A–Z'); },
    // By the fire's name; the group about no incident comes last.
    compare: (a, b) => (a.key === OTHER) - (b.key === OTHER)
      || a.name.localeCompare(b.name, 'en', { numeric: true, sensitivity: 'base' }),
  },
};

const SHOWN_AT_FIRST = 20;

function Timeline({ group, matched }) {
  const [all, setAll] = useState(false);
  const entries = matched;
  const hidden = all ? 0 : Math.max(0, entries.length - SHOWN_AT_FIRST);
  let visible = entries;
  if (hidden > 0) visible = group.newestFirst ? entries.slice(0, SHOWN_AT_FIRST) : entries.slice(-SHOWN_AT_FIRST);
  const more = hidden > 0 && (
    <li className="rpl-audit-more">
      <button type="button" className="rpl-text-button" onClick={() => setAll(true)}>
        {group.newestFirst
          ? t('Show {count} older entries', { count: hidden })
          : t('Show {count} earlier entries', { count: hidden })}
      </button>
    </li>
  );
  return (
    <ol className="rpl-audit-timeline" id={`rpl-audit-${group.key}`}>
      {!group.newestFirst && more}
      {visible.map((r) => {
        const detail = detailOf(r);
        const target = group.key === OTHER ? targetOf(r) : null;
        return (
          <li key={r.id} className="rpl-audit-entry">
            <time className="rpl-audit-time" dateTime={r.created_at}>{timeOf(r.created_at)}</time>
            <div className="rpl-audit-what">
              <span className="rpl-cell-title">{labelOf(r.action)}</span>
              <span className="rpl-cell-meta">{actorOf(r)}</span>
              {(detail || target) && (
                <span className="rpl-audit-detail">{[target, detail].filter(Boolean).join(' · ')}</span>
              )}
            </div>
            <span className="rpl-audit-code">{r.action}</span>
          </li>
        );
      })}
      {group.newestFirst && more}
    </ol>
  );
}

function Group({ group, matched, open, onToggle, onOpenIncident }) {
  const last = group.last;
  return (
    <section className={`rpl-panel rpl-audit-group${open ? ' is-open' : ''}`} aria-labelledby={`rpl-audit-head-${group.key}`}>
      <div className="rpl-audit-group-head">
        <button
          type="button"
          className="rpl-audit-toggle"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={`rpl-audit-${group.key}`}
          id={`rpl-audit-head-${group.key}`}
        >
          <span className="rpl-audit-chevron" aria-hidden="true"><Icon name="chevron-right" /></span>
          <span className="rpl-cell-text">
            <span className="rpl-cell-title">{group.name}</span>
            <span className="rpl-cell-meta">
              {t('{count} entries · latest {when}', { count: matched.length, when: timeOf(last.created_at) })}
              {' · '}
              {labelOf(last.action)}
            </span>
          </span>
        </button>
        {group.areaId && onOpenIncident && (
          <button type="button" className="web-table-row-action" onClick={() => onOpenIncident(group.areaId)}>
            {t('Open incident')}
            <span className="web-sr-only">{' '}{group.name}</span>
          </button>
        )}
      </div>
      {open && <Timeline group={group} matched={matched} />}
    </section>
  );
}

export default function ActionRecord({ onOpenIncident }) {
  const { org } = useConsole();
  const [rows, setRows] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [sort, setSort] = useState('recent');
  const [opened, setOpened] = useState(() => new Set());

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      const list = await api.auditLogs({ limit: LOADED });
      setRows(Array.isArray(list) ? list : []);
      setPhase('ready');
    } catch (e) {
      setError(e.message || t('The audit log could not be loaded.'));
      setPhase('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const categories = useMemo(() => [...new Set(rows.map((r) => categoryOf(r.action)))].sort(), [rows]);
  const groups = useMemo(() => groupsOf(rows), [rows]);

  // Each group with the entries that match the search and the action filter;
  // a search that names the incident keeps all of its entries.
  const q = query.trim().toLowerCase();
  const matching = useMemo(() => groups
    .map((g) => {
      const named = q && g.name.toLowerCase().includes(q);
      const matched = g.entries.filter((r) => {
        if (category !== 'all' && categoryOf(r.action) !== category) return false;
        if (!q || named) return true;
        return [r.action, labelOf(r.action), actorOf(r), r.entity_type, detailOf(r)]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(q));
      });
      return { group: g, matched };
    })
    .filter((m) => m.matched.length > 0)
    .sort((a, b) => SORTS[sort].compare(a.group, b.group)), [groups, q, category, sort]);

  const { shown, pager } = usePager(matching, { key: 'audit', reset: [q, category, sort] });

  // Groups open when clicked; while searching, every group with a match is
  // open until it is folded.
  const [folded, setFolded] = useState(() => new Set());
  useEffect(() => { setFolded(new Set()); }, [q]);
  const isOpen = (key) => (q ? !folded.has(key) : opened.has(key));
  const toggle = (key) => (q ? setFolded : setOpened)((prev) => {
    const next = new Set(prev);
    if (!next.delete(key)) next.add(key);
    return next;
  });

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? t('Records')}
        title={t('Audit log')}
        description={t('Append-only, grouped by incident. Each entry keeps the actor’s role and agency as they were at the time.')}
        actions={(
          <button type="button" className="rpl-button rpl-button--secondary" onClick={load} disabled={phase === 'loading'}>{t('Refresh')}</button>
        )}
      />

      <div className="rpl-filters">
        <SearchBox label={t('Search the audit log')} placeholder={t('Search actions, incidents, agencies')} value={query} onChange={setQuery} />
        <Select
          label={t('Action')}
          value={category}
          onChange={setCategory}
          options={[{ key: 'all', label: t('All actions') }, ...categories.map((c) => ({ key: c, label: c }))]}
        />
        <Select
          label={t('Sort')}
          value={sort}
          onChange={setSort}
          options={Object.entries(SORTS).map(([key, s]) => ({ key, label: s.label }))}
        />
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" title={t('Loading the audit log…')} busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title={t('The audit log couldn’t load')} description={error} onRetry={load} />
      ) : rows.length === 0 ? (
        <EmptyState icon="audit" title={t('Nothing recorded yet')}>{t('Entries appear as incidents are acknowledged, reports are filed and requests are decided.')}</EmptyState>
      ) : (
        <>
          <p className="rpl-table-foot">
            {t('The latest {count} entries, in {groups} groups.', { count: rows.length, groups: groups.length })}
          </p>
          {matching.length === 0 ? (
            <p className="rpl-empty-line">{t('No entries match these filters.')}</p>
          ) : (
            <div className="rpl-audit-groups">
              {shown.map(({ group, matched }) => (
                <Group
                  key={group.key}
                  group={group}
                  matched={matched}
                  open={isOpen(group.key)}
                  onToggle={() => toggle(group.key)}
                  onOpenIncident={onOpenIncident}
                />
              ))}
            </div>
          )}
          <Pager {...pager} />
        </>
      )}
    </div>
  );
}
