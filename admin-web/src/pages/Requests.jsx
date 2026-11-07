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
import { t } from '../i18n/i18n.jsx';

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
  pending: { get label() { return t('Pending'); }, tone: 'warn' },
  approved: { get label() { return t('Approved'); }, tone: 'ok' },
  rejected: { get label() { return t('Rejected'); }, tone: 'neutral' },
  cancelled: { get label() { return t('Cancelled'); }, tone: 'neutral' },
};

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const CLOCK_S = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit', second: '2-digit',
});

const clock = (iso) => (iso ? CLOCK.format(new Date(iso)) : '—');
const requestStatus = (s) => REQUEST_STATUS[s] ?? { label: (s || '—').replace(/_/g, ' '), tone: 'neutral' };
const areaOf = (r) => r.area_designation || t('Area not recorded');
const askedBy = (r) => r.requested_by_name || t('A Coordinator');

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
        if (!Array.isArray(list)) throw new Error(t('The requests could not be read. Try again.'));
        setRows(list);
        setPhase('ready');
      })
      .catch((e) => {
        if (!alive) return;
        setError(e?.message || t('The requests could not be loaded.'));
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
          <div className="rpl-toast" role="status">
            <span aria-hidden="true">✓</span>
            {notice}
          </div>
        )}
      </>
    );
  }

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? t('Requests')}
        title={t('Requests')}
        description={decides
          ? t('Alarm escalations from the organizations on scene. You set the alarm level or decline.')
          : asks
            ? t('Alarm escalations raised on scene, and BFP’s answers. Ask BFP to raise the alarm on an Area routed to you.')
            : t('Alarm escalations raised on scene. BFP sets the alarm level; you follow each request and its answer here.')}
        actions={(
          <>
            <button type="button" className="rpl-button rpl-button--secondary" onClick={refresh} disabled={phase === 'loading'}>{t('Refresh')}</button>
            {asks && (
              <button
                type="button"
                className="rpl-button rpl-button--primary"
                onClick={() => setAsking(true)}
                disabled={askable.length === 0}
                title={askable.length === 0 ? t('No acknowledged Area is routed to you right now') : undefined}
              >{t('New request')}</button>
            )}
          </>
        )}
      />

      {notice && (
        <div className="rpl-toast" role="status">
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
          setNotice(t('Asked BFP for {level} on {area}', { level: alarmLabel(level), area: areaById.get(areaId)?.designation ?? t('the Area') }));
          refresh();
        }}
      />

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label={t('Requests')}>
          {[
            { key: 'inbox', label: t('Inbox'), count: pending.length },
            { key: 'history', label: t('History') },
          ].map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={tab === item.key}
              className={`rpl-tab${tab === item.key ? ' is-active' : ''}`}
              onClick={() => setTab(item.key)}
            >
              {item.label}
              {item.count > 0 && <span className="web-count-badge" aria-label={t('{count} pending', { count: item.count })}>{item.count}</span>}
            </button>
          ))}
        </div>
        <label className="rpl-search">
          <Icon name="search" />
          <span className="web-sr-only">{t('Search requests')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search areas and names')} />
        </label>
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" title={t('Loading requests…')} busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title={t('The requests couldn’t load')} description={error} onRetry={refresh} />
      ) : shown.length === 0 && !query.trim() ? (
        <EmptyState icon="requests" title={tab === 'inbox' ? t('Nothing waiting') : t('No answered requests yet')}>
          {tab === 'inbox'
            ? t('An alarm escalation appears here when someone on scene asks BFP to raise the alarm.')
            : t('Requests move here once BFP approves or rejects them, or they are cancelled.')}
        </EmptyState>
      ) : (
        <>
          <div className="web-table-wrap">
            <table className="web-table rpl-requests">
              <caption className="web-sr-only">{tab === 'inbox' ? t('Pending requests') : t('Answered requests')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('Request')}</th>
                  <th scope="col">{t('From → To')}</th>
                  <th scope="col">{t('Status')}</th>
                  <th scope="col">{t('Received')}</th>
                  <th scope="col"><span className="web-sr-only">{t('Open')}</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const area = areaById.get(r.area_id);
                  return (
                    <tr key={r.id} className={`web-table-row${r.status === 'pending' ? ' is-unread' : ''}`}>
                      <th scope="row">
                        <span className="rpl-cell-resource">
                          <span className="rpl-plate rpl-plate--request" aria-hidden="true"><Icon name="escalate" /></span>
                          <span className="rpl-cell-text">
                            <span className="rpl-cell-title">{t('Alarm escalation ·')}{' '}{alarmLabel(r.requested_alarm_level)}</span>
                            <span className="rpl-cell-meta">
                              {areaOf(r)}{area ? ` · ${statusOf(area.status).label}` : ''}
                            </span>
                          </span>
                        </span>
                      </th>
                      <td className="rpl-cell-strong">{askedBy(r)}{' '}{t('→ BFP')}</td>
                      <td><StatusChip {...requestStatus(r.status)} /></td>
                      <td className="rpl-cell-quiet">{received(r.created_at)}</td>
                      <td className="web-table-action-cell">
                        <button type="button" className="web-table-row-action" onClick={() => setSelectedId(r.id)}>{t('Open')}<span className="web-sr-only">{' '}{t('the request for')}{' '}{areaOf(r)}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {shown.length === 0 && (
                  <tr><td className="web-table-empty" colSpan={5}>{t('Nothing matches “{query}”.', { query })}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="rpl-table-foot">{t('Showing {shown} of {total}', { shown: shown.length, total: tab === 'inbox' ? pending.length : rows.length - pending.length })}</p>
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
    [t('Area'), `${areaOf(r)}${area ? ` · ${statusOf(area.status).label}` : ''}`],
    ...(area?.alarm_level ? [[t('Current level'), alarmLabel(area.alarm_level)]] : []),
    [t('Proposed level'), level],
    [t('Asked by'), askedBy(r)],
    [t('Reason'), r.justification || t('No reason given')],
  ];
  const history = [
    { at: r.created_at, title: t('{level} requested', { level }), sub: askedBy(r), tone: 'accent' },
    r.reviewed_at && {
      at: r.reviewed_at,
      title: r.status === 'approved'
        ? t('Approved by BFP')
        : r.status === 'rejected'
          ? t('Rejected by BFP')
          : r.status === 'cancelled' ? t('Cancelled before BFP answered') : t('Reviewed by BFP'),
      sub: r.review_notes || null,
      tone: r.status === 'approved' ? 'ok' : 'quiet',
    },
    r.executed_at && { at: r.executed_at, title: t('Alarm set to {level}', { level }), sub: t('For every organization on this Area'), tone: 'live' },
  ].filter(Boolean);
  const status = requestStatus(r.status);

  return (
    <div className="rpl-page rpl-incident">
      <button type="button" className="rpl-text-button rpl-back" onClick={onBack}>{t('← All requests')}</button>
      <PageHeader
        eyebrow={t('From {askedBy} · {clock}', { askedBy: askedBy(r), clock: clock(r.created_at) })}
        title={t('Alarm escalation · {level}', { level })}
        description={area?.alarm_level
          ? t('For {area} · now {alarm}', { area: areaOf(r), alarm: alarmLabel(area.alarm_level) })
          : t('For {area}', { area: areaOf(r) })}
      />

      <div className="rpl-incident-grid">
        <section className="rpl-panel rpl-request-card" aria-labelledby="rpl-request-title">
          <div className="rpl-decision-head">
            <h2 className="rpl-decision-title" id="rpl-request-title">{t('Request')}</h2>
            <StatusChip {...status} />
          </div>
          <dl className="rpl-facts rpl-facts--wide">
            {facts.map(([t, v]) => (
              <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <h3 className="rpl-decision-title rpl-request-history">{t('History')}</h3>
          <ol className="rpl-timeline">
            {history.map((h) => (
              <li key={`${h.title}-${h.at}`} className={`rpl-timeline-item is-${h.tone}`}>
                <span className="rpl-timeline-time">{CLOCK_S.format(new Date(h.at))}</span>
                <span className="rpl-timeline-title">{h.title}</span>
                {h.sub && <span className="rpl-timeline-sub">{h.sub}</span>}
              </li>
            ))}
          </ol>
        </section>

        <section className="rpl-panel rpl-decision" aria-labelledby="rpl-reply-title">
          <h2 className="rpl-decision-title" id="rpl-reply-title">{decides && r.status === 'pending' ? t('Your reply') : t('Answer')}</h2>
          {r.status === 'pending' && decides ? (
            <div className="rpl-reply-actions">
              <button type="button" className="rpl-button rpl-button--primary rpl-button--run" onClick={() => { setNote(''); setConfirm('set'); }}>{t('Set {level}', { level })}
              </button>
              <div className="rpl-reply-row">
                <button type="button" className="rpl-button rpl-button--secondary" onClick={() => { setNote(''); setConfirm('decline'); }}>{t('Decline')}</button>
              </div>
              <div className="rpl-alert rpl-alert--info">
                <span className="rpl-alert-mark" aria-hidden="true">i</span>
                <p className="rpl-alert-body">{t('Only {org} sets the alarm level. Setting it updates {area} for every organization.', { org: orgName, area: areaOf(r) })}</p>
              </div>
            </div>
          ) : r.status === 'pending' ? (
            <div className="rpl-alert rpl-alert--info">
              <Icon name="visibility" />
              <div className="rpl-alert-text">
                <p className="rpl-alert-title">{t('Waiting on BFP')}</p>
                <p className="rpl-alert-body">{t('Only BFP sets the alarm level: a BFP Coordinator on the mobile app, or the BFP Admin here. Setting it updates {area} for every organization.', { area: areaOf(r) })}</p>
              </div>
            </div>
          ) : r.status === 'cancelled' ? (
            <div className="rpl-alert">
              <span className="rpl-alert-mark" aria-hidden="true">⦸</span>
              <div className="rpl-alert-text">
                <p className="rpl-alert-title">{t('Cancelled')}{r.reviewed_at ? ` · ${clock(r.reviewed_at)}` : ''}</p>
                <p className="rpl-alert-body">
                  {r.review_notes || t('Taken back before BFP answered. The alarm level was not changed.')}
                </p>
              </div>
            </div>
          ) : (
            <div className={`rpl-alert ${r.status === 'approved' ? 'rpl-alert--ok' : ''}`}>
              <span className="rpl-alert-mark" aria-hidden="true">{r.status === 'approved' ? '✓' : '⦸'}</span>
              <div className="rpl-alert-text">
                <p className="rpl-alert-title">
                  {status.label}{' '}{t('by BFP')}{r.reviewed_at ? ` · ${clock(r.reviewed_at)}` : ''}
                </p>
                <p className="rpl-alert-body">
                  {r.review_notes || (r.status === 'approved' ? t('{area} is at {level}.', { area: areaOf(r), level }) : t('The alarm level was not changed.'))}
                </p>
              </div>
            </div>
          )}
          {withdraws && r.status !== 'approved' && (
            <div className="rpl-reply-row">
              {r.status === 'pending' && (
                <button type="button" className="rpl-button rpl-button--secondary" onClick={() => { setNote(''); setConfirm('cancel'); }}>{t('Cancel request')}</button>
              )}
              <button type="button" className="rpl-button rpl-button--danger" onClick={() => setConfirm('delete')}>{t('Delete request')}</button>
            </div>
          )}
          {onOpenIncident && area && (
            <button type="button" className="rpl-button rpl-button--secondary" onClick={() => onOpenIncident(r.area_id)}>{t('Open')}{' '}{areaOf(r)}
            </button>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={confirm === 'set'}
        eyebrow={t('{areaOf} · requested by {askedBy}', { areaOf: areaOf(r), askedBy: askedBy(r) })}
        title={t('Set {areaOf} to {level}?', { areaOf: areaOf(r), level })}
        description={t('Every organization sees the new level at once.')}
        confirmLabel={t('Set {level}', { level })}
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestExecute(r.id, null);
          setConfirm(null);
          onDecided?.(t('{area} is now at {level}', { area: areaOf(r), level }));
        }}
      />
      <ConfirmDialog
        open={confirm === 'decline'}
        eyebrow={t('{areaOf} · requested by {askedBy}', { areaOf: areaOf(r), askedBy: askedBy(r) })}
        title={t('Decline {level} for {areaOf}?', { level, areaOf: areaOf(r) })}
        description={t('The alarm level stays as it is. Say why, so the organization on scene knows.')}
        confirmLabel={t('Decline')}
        destructive
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestReject(r.id, note.trim() || null);
          setConfirm(null);
          onDecided?.(t('Declined {level} for {area}', { level, area: areaOf(r) }));
        }}
      >
        <label className="rpl-field">
          <span className="rpl-field-label">{t('Reason (optional)')}</span>
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'cancel'}
        eyebrow={t('{areaOf} · requested by {askedBy}', { areaOf: areaOf(r), askedBy: askedBy(r) })}
        title={t('Cancel the request for {level}?', { level })}
        description={t('BFP stops seeing it as waiting. It stays in History as Cancelled.')}
        confirmLabel={t('Cancel request')}
        cancelLabel={t('Keep it')}
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestCancel(r.id, note.trim() || null);
          setConfirm(null);
          onDecided?.(t('Cancelled the request for {level} on {area}', { level, area: areaOf(r) }));
        }}
      >
        <label className="rpl-field">
          <span className="rpl-field-label">{t('Reason (optional)')}</span>
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'delete'}
        eyebrow={t('{areaOf} · requested by {askedBy}', { areaOf: areaOf(r), askedBy: askedBy(r) })}
        title={t('Delete the request for {level}?', { level })}
        description={t('It is removed for every organization and cannot be brought back.')}
        confirmLabel={t('Delete request')}
        cancelLabel={t('Keep it')}
        destructive
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          await api.alarmRequestDelete(r.id);
          setConfirm(null);
          onDeleted?.(t('Deleted the request for {level} on {area}', { level, area: areaOf(r) }));
        }}
      />
    </div>
  );
}
