import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { useAuth } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import AlarmEscalationDialog from '../components/requests/AlarmEscalationDialog.jsx';
import {
  ConfirmDialog, EmptyState, Icon, PageHeader, StatePanel, StatusChip,
} from '../components/ui/index.js';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import { PERM, actsOn, can, mayWithdraw } from '../lib/access.js';
import { ago, alarmLabel, statusOf } from '../lib/status.js';

/* Requests (REPLIT (MAIN) 10 · A40 873:5264, A41 873:5578, A45 874:6513,
 * A46 874:6933, A46b 874:7126).
 *
 * The server carries one kind of request today: an alarm escalation, raised
 * on scene by a Fire Volunteer or BFP Coordinator or a Fire Volunteer
 * responder — or, here, by a Fire Volunteer organisation's Admin (A45) — and
 * decided by BFP: a BFP Coordinator on the mobile app, or the BFP Admin here
 * (A46, A46b; PRD v14 §3.4). Every other Admin follows them, read only.
 *
 * Whoever asked, an Admin of their organisation or the system Admin can take
 * a request back: cancel one still waiting (it moves to History as
 * Cancelled), or delete one BFP did not approve. An approved request stays,
 * as the record of why the alarm level changed.
 *
 * The design's water, backup and equipment requests between Admins (A43,
 * A44), the Sent folder (A42) and Admin replies wait on server support; see
 * docs/FRONTEND_INTEGRATION_HANDOFF.md. The host supplies
 * readRequests({ status }) -> Promise<AlarmRequest[]>. */

const REQUEST_STATUS = {
  pending: { label: 'Pending', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
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
  const { org, console: access } = useConsole();
  const me = useAuth()?.user ?? null;
  const decides = can(access, PERM.DECIDE_ALARM);
  const asks = can(access, PERM.REQUEST_ALARM);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState(null);
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
  // Where a Fire Volunteer Admin may ask for a higher alarm: live Areas
  // routed to it that someone has acknowledged.
  const askable = useMemo(
    () => incidents.filter((i) => ['verified', 'en_route', 'arrived'].includes(i.status) && actsOn(access, i)),
    [incidents, access],
  );
  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

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
      <>
        <RequestDetail
          request={selected}
          area={areaById.get(selected.area_id) ?? null}
          decides={decides}
          withdraws={mayWithdraw(access, me, selected)}
          orgName={org?.name ?? 'BFP'}
          onBack={() => setSelectedId(null)}
          onOpenIncident={onOpenIncident}
          onDecided={(message) => { setNotice(message); refresh(); }}
          onDeleted={(message) => { setSelectedId(null); setNotice(message); refresh(); }}
        />
        {notice && (
          <div className="ad-toast" role="status">
            <span aria-hidden="true">✓</span>
            {notice}
          </div>
        )}
      </>
    );
  }

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={org?.name ?? 'Requests'}
        title="Requests"
        description={decides
          ? 'Alarm escalations from the organisations on scene. You set the alarm level or decline.'
          : asks
            ? 'Alarm escalations raised on scene, and BFP\u2019s answers. Ask BFP to raise the alarm on an Area routed to you.'
            : 'Alarm escalations raised on scene. BFP sets the alarm level; you follow each request and its answer here.'}
        actions={(
          <>
            <button type="button" className="ad-button ad-button--secondary" onClick={refresh} disabled={phase === 'loading'}>
              Refresh
            </button>
            {asks && (
              <button
                type="button"
                className="ad-button ad-button--primary"
                onClick={() => setAsking(true)}
                disabled={askable.length === 0}
                title={askable.length === 0 ? 'No acknowledged Area is routed to you right now' : undefined}
              >
                New request
              </button>
            )}
          </>
        )}
      />

      {notice && (
        <div className="ad-toast" role="status">
          <span aria-hidden="true">✓</span>
          {notice}
        </div>
      )}

      <AlarmEscalationDialog
        open={asking}
        areas={askable}
        bfpName="BFP"
        onClose={() => setAsking(false)}
        onSend={async ({ areaId, level, justification }) => {
          await api.alarmRequestCreate({ areaId, level, justification });
          setAsking(false);
          setNotice(`Asked BFP for ${alarmLabel(level)} on ${areaById.get(areaId)?.designation ?? 'the Area'}`);
          refresh();
        }}
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
            : 'Requests move here once BFP approves or rejects them, or they are cancelled.'}
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

/* One request (A41, A46, A46b): what was asked, by whom, and what happened
 * to it. The BFP Admin answers it here: set the level (confirmed first —
 * every organisation sees it at once) or decline. Everyone else is told who
 * decides instead of being offered buttons their account would be refused. */
function RequestDetail({
  request: r, area, decides, withdraws, orgName, onBack, onOpenIncident, onDecided, onDeleted,
}) {
  const [confirm, setConfirm] = useState(null);
  const [note, setNote] = useState('');
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
      title: r.status === 'approved'
        ? 'Approved by BFP'
        : r.status === 'rejected'
          ? 'Rejected by BFP'
          : r.status === 'cancelled' ? 'Cancelled before BFP answered' : 'Reviewed by BFP',
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
          <h2 className="ad-decision-title" id="ad-reply-title">{decides && r.status === 'pending' ? 'Your reply' : 'Answer'}</h2>
          {r.status === 'pending' && decides ? (
            <div className="ad-reply-actions">
              <button type="button" className="ad-button ad-button--primary ad-button--run" onClick={() => { setNote(''); setConfirm('set'); }}>
                Set {level}
              </button>
              <div className="ad-reply-row">
                <button type="button" className="ad-button ad-button--secondary" onClick={() => { setNote(''); setConfirm('decline'); }}>
                  Decline
                </button>
              </div>
              <div className="ad-alert ad-alert--info">
                <span className="ad-alert-mark" aria-hidden="true">i</span>
                <p className="ad-alert-body">
                  Only {orgName} sets the alarm level. Setting it updates {areaOf(r)} for every organisation.
                </p>
              </div>
            </div>
          ) : r.status === 'pending' ? (
            <div className="ad-alert ad-alert--info">
              <Icon name="visibility" />
              <div className="ad-alert-text">
                <p className="ad-alert-title">Waiting on BFP</p>
                <p className="ad-alert-body">Only BFP sets the alarm level: a BFP Coordinator on the mobile app, or the BFP Admin here. Setting it updates {areaOf(r)} for every organisation.</p>
              </div>
            </div>
          ) : r.status === 'cancelled' ? (
            <div className="ad-alert">
              <span className="ad-alert-mark" aria-hidden="true">⦸</span>
              <div className="ad-alert-text">
                <p className="ad-alert-title">Cancelled{r.reviewed_at ? ` · ${clock(r.reviewed_at)}` : ''}</p>
                <p className="ad-alert-body">
                  {r.review_notes || 'Taken back before BFP answered. The alarm level was not changed.'}
                </p>
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
          {withdraws && r.status !== 'approved' && (
            <div className="ad-reply-row">
              {r.status === 'pending' && (
                <button type="button" className="ad-button ad-button--secondary" onClick={() => { setNote(''); setConfirm('cancel'); }}>
                  Cancel request
                </button>
              )}
              <button type="button" className="ad-button ad-button--danger" onClick={() => setConfirm('delete')}>
                Delete request
              </button>
            </div>
          )}
          {onOpenIncident && area && (
            <button type="button" className="ad-button ad-button--secondary" onClick={() => onOpenIncident(r.area_id)}>
              Open {areaOf(r)}
            </button>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={confirm === 'set'}
        eyebrow={`${areaOf(r)} · requested by ${askedBy(r)}`}
        title={`Set ${areaOf(r)} to ${level}?`}
        description="Every organisation sees the new level at once."
        confirmLabel={`Set ${level}`}
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestExecute(r.id, null);
          setConfirm(null);
          onDecided?.(`${areaOf(r)} is now at ${level}`);
        }}
      />
      <ConfirmDialog
        open={confirm === 'decline'}
        eyebrow={`${areaOf(r)} · requested by ${askedBy(r)}`}
        title={`Decline ${level} for ${areaOf(r)}?`}
        description="The alarm level stays as it is. Say why, so the organisation on scene knows."
        confirmLabel="Decline"
        destructive
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestReject(r.id, note.trim() || null);
          setConfirm(null);
          onDecided?.(`Declined ${level} for ${areaOf(r)}`);
        }}
      >
        <label className="ad-field">
          <span className="ad-field-label">Reason (optional)</span>
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'cancel'}
        eyebrow={`${areaOf(r)} · requested by ${askedBy(r)}`}
        title={`Cancel the request for ${level}?`}
        description="BFP stops seeing it as waiting. It stays in History as Cancelled."
        confirmLabel="Cancel request"
        cancelLabel="Keep it"
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestCancel(r.id, note.trim() || null);
          setConfirm(null);
          onDecided?.(`Cancelled the request for ${level} on ${areaOf(r)}`);
        }}
      >
        <label className="ad-field">
          <span className="ad-field-label">Reason (optional)</span>
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'delete'}
        eyebrow={`${areaOf(r)} · requested by ${askedBy(r)}`}
        title={`Delete the request for ${level}?`}
        description="It is removed for every organisation and cannot be brought back."
        confirmLabel="Delete request"
        cancelLabel="Keep it"
        destructive
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestDelete(r.id);
          setConfirm(null);
          onDeleted?.(`Deleted the request for ${level} on ${areaOf(r)}`);
        }}
      />
    </div>
  );
}
