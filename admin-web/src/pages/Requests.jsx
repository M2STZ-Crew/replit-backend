import { useCallback, useEffect, useMemo, useState } from 'react';

import { useConsole } from '../components/ConsoleShell.jsx';
import { EmptyState, Icon, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import { ago, alarmLabel, statusOf } from '../lib/status.js';

/* Requests (REPLIT (MAIN) 10 · A40 873:5264, A41 873:5578, A46 874:6933).
 *
 * The server carries one kind of request today: an alarm escalation, raised
 * on scene by a Fire Volunteer or BFP Coordinator or a Fire Volunteer
 * responder, and decided by a BFP Coordinator on the mobile app. An Admin
 * can read every one (GET /alarm-requests) but neither raises nor decides
 * them, so this destination is the inbox and its history, read only.
 *
 * The design's water, backup and equipment requests between Admins (A43,
 * A44), the Sent folder (A42) and Admin replies wait on server support; see
 * docs/FRONTEND_INTEGRATION_HANDOFF.md. The host supplies
 * readRequests({ status }) -> Promise<AlarmRequest[]>. */

const REQUEST_STATUS = {
  pending: { label: 'Pending', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'neutral' },
};

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const CLOCK_S = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit', second: '2-digit',
});

const clock = (iso) => (iso ? CLOCK.format(new Date(iso)) : '—');
const requestStatus = (s) => REQUEST_STATUS[s] ?? { label: (s || '—').replace(/_/g, ' '), tone: 'neutral' };
const areaOf = (r) => r.area_designation || 'Area not recorded';
const askedBy = (r) => r.requested_by_name || 'A Coordinator';

function received(iso) {
  if (!iso) return '—';
  const hours = (Date.now() - new Date(iso).getTime()) / 3600000;
  return hours < 12 ? clock(iso) : ago(iso);
}

export default function Requests({ readRequests, onOpenIncident }) {
  const { org } = useConsole();
  // The live feed names each request's Area status; without it (an isolated
  // preview) the rows simply leave the status out.
  const incidents = useLiveFeed()?.incidents ?? [];
  const [rows, setRows] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('inbox');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let alive = true;
    setPhase('loading');
    setError(null);
    Promise.resolve()
      .then(() => readRequests({ status: 'all' }))
      .then((list) => {
        if (!alive) return;
        if (!Array.isArray(list)) throw new Error('The requests could not be read. Try again.');
        setRows(list);
        setPhase('ready');
      })
      .catch((e) => {
        if (!alive) return;
        setError(e?.message || 'The requests could not be loaded.');
        setPhase('error');
      });
    return () => { alive = false; };
  }, [readRequests, refreshKey]);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  const areaById = useMemo(() => new Map(incidents.map((i) => [i.id, i])), [incidents]);

  const pending = rows.filter((r) => r.status === 'pending');
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows
      .filter((r) => (tab === 'inbox' ? r.status === 'pending' : r.status !== 'pending'))
      .filter((r) => !q || [r.area_designation, r.requested_by_name, alarmLabel(r.requested_alarm_level), r.justification]
        .some((v) => v != null && String(v).toLowerCase().includes(q)));
  }, [rows, tab, query]);

  const selected = rows.find((r) => r.id === selectedId) ?? null;
  if (selected) {
    return (
      <RequestDetail
        request={selected}
        area={areaById.get(selected.area_id) ?? null}
        onBack={() => setSelectedId(null)}
        onOpenIncident={onOpenIncident}
      />
    );
  }

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={org?.name ?? 'Requests'}
        title="Requests"
        description="Alarm escalations raised on scene. A BFP Coordinator sets the alarm level on the mobile app; you follow each request and its answer here."
        actions={(
          <button type="button" className="ad-button ad-button--secondary" onClick={refresh} disabled={phase === 'loading'}>
            Refresh
          </button>
        )}
      />

      <div className="ad-toolbar">
        <div className="ad-tabs" role="tablist" aria-label="Requests">
          {[
            { key: 'inbox', label: 'Inbox', count: pending.length },
            { key: 'history', label: 'History' },
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
              {t.count > 0 && <span className="web-count-badge" aria-label={`${t.count} pending`}>{t.count}</span>}
            </button>
          ))}
        </div>
        <label className="ad-search">
          <Icon name="search" />
          <span className="web-sr-only">Search requests</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search areas and names" />
        </label>
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" title="Loading requests…" busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title="The requests couldn’t load" description={error} onRetry={refresh} />
      ) : shown.length === 0 && !query.trim() ? (
        <EmptyState icon="requests" title={tab === 'inbox' ? 'Nothing waiting' : 'No answered requests yet'}>
          {tab === 'inbox'
            ? 'An alarm escalation appears here when someone on scene asks BFP to raise the alarm.'
            : 'Requests move here once BFP approves or rejects them.'}
        </EmptyState>
      ) : (
        <>
          <div className="web-table-wrap">
            <table className="web-table ad-requests">
              <caption className="web-sr-only">{tab === 'inbox' ? 'Pending requests' : 'Answered requests'}</caption>
              <thead>
                <tr>
                  <th scope="col">Request</th>
                  <th scope="col">From → To</th>
                  <th scope="col">Status</th>
                  <th scope="col">Received</th>
                  <th scope="col"><span className="web-sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const area = areaById.get(r.area_id);
                  return (
                    <tr key={r.id} className={`web-table-row${r.status === 'pending' ? ' is-unread' : ''}`}>
                      <th scope="row">
                        <span className="ad-cell-resource">
                          <span className="ad-plate ad-plate--request" aria-hidden="true"><Icon name="escalate" /></span>
                          <span className="ad-cell-text">
                            <span className="ad-cell-title">Alarm escalation · {alarmLabel(r.requested_alarm_level)}</span>
                            <span className="ad-cell-meta">
                              {areaOf(r)}{area ? ` · ${statusOf(area.status).label}` : ''}
                            </span>
                          </span>
                        </span>
                      </th>
                      <td className="ad-cell-strong">{askedBy(r)} → BFP</td>
                      <td><StatusChip {...requestStatus(r.status)} /></td>
                      <td className="ad-cell-quiet">{received(r.created_at)}</td>
                      <td className="web-table-action-cell">
                        <button type="button" className="web-table-row-action" onClick={() => setSelectedId(r.id)}>
                          Open<span className="web-sr-only"> the request for {areaOf(r)}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {shown.length === 0 && (
                  <tr><td className="web-table-empty" colSpan={5}>Nothing matches “{query}”.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="ad-table-foot">Showing {shown.length} of {tab === 'inbox' ? pending.length : rows.length - pending.length}</p>
        </>
      )}
    </div>
  );
}

/* One request (A41, A46): what was asked, by whom, and what happened to it.
 * The reply card says who decides instead of offering buttons an Admin's
 * account would be refused. */
function RequestDetail({ request: r, area, onBack, onOpenIncident }) {
  const level = alarmLabel(r.requested_alarm_level);
  const facts = [
    ['Area', `${areaOf(r)}${area ? ` · ${statusOf(area.status).label}` : ''}`],
    ...(area?.alarm_level ? [['Current level', alarmLabel(area.alarm_level)]] : []),
    ['Proposed level', level],
    ['Asked by', askedBy(r)],
    ['Reason', r.justification || 'No reason given'],
  ];
  const history = [
    { at: r.created_at, title: `${level} requested`, sub: askedBy(r), tone: 'accent' },
    r.reviewed_at && {
      at: r.reviewed_at,
      title: r.status === 'approved' ? 'Approved by BFP' : r.status === 'rejected' ? 'Rejected by BFP' : 'Reviewed by BFP',
      sub: r.review_notes || null,
      tone: r.status === 'approved' ? 'ok' : 'quiet',
    },
    r.executed_at && { at: r.executed_at, title: `Alarm set to ${level}`, sub: 'For every organisation on this Area', tone: 'live' },
  ].filter(Boolean);
  const status = requestStatus(r.status);

  return (
    <div className="ad-page ad-incident">
      <button type="button" className="ad-text-button ad-back" onClick={onBack}>← All requests</button>
      <PageHeader
        eyebrow={`From ${askedBy(r)} · ${clock(r.created_at)}`}
        title={`Alarm escalation · ${level}`}
        description={`For ${areaOf(r)}${area?.alarm_level ? ` · now ${alarmLabel(area.alarm_level)}` : ''}`}
      />

      <div className="ad-incident-grid">
        <section className="ad-panel ad-request-card" aria-labelledby="ad-request-title">
          <div className="ad-decision-head">
            <h2 className="ad-decision-title" id="ad-request-title">Request</h2>
            <StatusChip {...status} />
          </div>
          <dl className="ad-facts ad-facts--wide">
            {facts.map(([t, v]) => (
              <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <h3 className="ad-decision-title ad-request-history">History</h3>
          <ol className="ad-timeline">
            {history.map((h) => (
              <li key={`${h.title}-${h.at}`} className={`ad-timeline-item is-${h.tone}`}>
                <span className="ad-timeline-time">{CLOCK_S.format(new Date(h.at))}</span>
                <span className="ad-timeline-title">{h.title}</span>
                {h.sub && <span className="ad-timeline-sub">{h.sub}</span>}
              </li>
            ))}
          </ol>
        </section>

        <section className="ad-panel ad-decision" aria-labelledby="ad-reply-title">
          <h2 className="ad-decision-title" id="ad-reply-title">Answer</h2>
          {r.status === 'pending' ? (
            <div className="ad-alert ad-alert--info">
              <Icon name="visibility" />
              <div className="ad-alert-text">
                <p className="ad-alert-title">Waiting on BFP</p>
                <p className="ad-alert-body">Only a BFP Coordinator sets the alarm level, from the mobile app. Setting it updates {areaOf(r)} for every organisation.</p>
              </div>
            </div>
          ) : (
            <div className={`ad-alert ${r.status === 'approved' ? 'ad-alert--ok' : ''}`}>
              <span className="ad-alert-mark" aria-hidden="true">{r.status === 'approved' ? '✓' : '⦸'}</span>
              <div className="ad-alert-text">
                <p className="ad-alert-title">
                  {status.label} by BFP{r.reviewed_at ? ` · ${clock(r.reviewed_at)}` : ''}
                </p>
                <p className="ad-alert-body">
                  {r.review_notes || (r.status === 'approved' ? `${areaOf(r)} is at ${level}.` : 'The alarm level was not changed.')}
                </p>
              </div>
            </div>
          )}
          {onOpenIncident && area && (
            <button type="button" className="ad-button ad-button--secondary" onClick={() => onOpenIncident(r.area_id)}>
              Open {areaOf(r)}
            </button>
          )}
        </section>
      </div>
    </div>
  );
}
