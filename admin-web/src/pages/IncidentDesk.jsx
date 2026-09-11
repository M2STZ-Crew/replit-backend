import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import {
  AGENCY_LABEL,
  routableAgencies,
  since,
  statusOf,
  when,
} from '../lib/status.js';

// Confidence bands from the backend's generated column (Section 2.3).
const BAND = {
  high: { label: 'High confidence', color: '#22C55E' },
  medium: { label: 'Medium confidence', color: '#EAB308' },
  low: { label: 'Low confidence', color: '#FF544E' },
};

// Reporter credibility badges (Section 2.1) — advisory, never gating.
function badgeOf(pct) {
  if (pct >= 100) return { label: '100% verified', color: '#22C55E' };
  if (pct >= 90) return { label: 'High credibility', color: '#22C55E' };
  if (pct >= 50) return { label: 'Partly verified', color: '#EAB308' };
  return { label: 'Low credibility', color: '#EAB308' };
}

const OBSERVERS = ['police', 'medical', 'barangay'];

const TABS = [
  { key: 'incoming', label: 'Incoming', hint: 'Live and not yet routed' },
  { key: 'live', label: 'Live', hint: 'Every open incident' },
  { key: 'report', label: 'Report due', hint: 'Fire out; Post-Incident Report owed' },
  { key: 'closed', label: 'Closed', hint: 'Report filed' },
];

/// Admin's incident desk (Master Context v10, Section 2.6.2).
///
/// Admin accepts an incoming report and routes it to the agencies the reporter
/// asked for — several at once when the fire needs it — choosing which teams
/// within each to alert. Routing does not verify: the Fire Volunteer coordinator
/// still owns that, from the mobile app. Once routed, an observer agency's
/// Accept shows here. After fire out the same screen shows the Post-Incident
/// Report once the team captain has filed it.
export default function IncidentDesk({ focusId = null }) {
  const { incidents: live, refresh: refreshFeed } = useLiveFeed();
  const lastViewed = useSurfaceVisit('incidents');

  const [tab, setTab] = useState(focusId ? 'live' : 'incoming');
  const [fetched, setFetched] = useState({ report: null, closed: null });
  const [selectedId, setSelectedId] = useState(focusId);
  const [detail, setDetail] = useState(null);
  const [evidence, setEvidence] = useState([]);
  const [report, setReport] = useState(null);
  const [orgs, setOrgs] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');

  useEffect(() => {
    api.organizations().then(setOrgs).catch(() => setOrgs([]));
  }, []);

  const loadTab = useCallback(async (key) => {
    if (key !== 'report' && key !== 'closed') return;
    const status = key === 'report' ? 'post_incident_report' : 'closed';
    const rows = await api.incidents({ activeOnly: false, status, limit: 100 }).catch(() => []);
    setFetched((f) => ({ ...f, [key]: rows }));
  }, []);

  useEffect(() => { loadTab(tab); }, [tab, loadTab]);

  const lists = useMemo(() => ({
    incoming: live.filter((i) => (i.routed_agencies ?? []).length === 0),
    live,
    // Longest-waiting first: a report that has been owed for a day matters
    // more than one owed for ten minutes (§10.2).
    report: [...(fetched.report ?? [])].sort(
      (a, b) => new Date(a.resolved_at ?? 0) - new Date(b.resolved_at ?? 0),
    ),
    closed: fetched.closed ?? [],
  }), [live, fetched]);
  const rows = lists[tab];

  // Keep a selection on screen: the focused/last-picked incident while it is in
  // the current list, otherwise the first one.
  useEffect(() => {
    if (rows.length === 0) return;
    if (!selectedId || !rows.some((r) => r.id === selectedId)) setSelectedId(rows[0].id);
  }, [rows, selectedId]);

  const loadDetail = useCallback(async (id) => {
    if (!id) { setDetail(null); setEvidence([]); setReport(null); return; }
    const [d, r] = await Promise.all([
      api.incident(id).catch(() => null),
      api.incidentReports(id).catch(() => []),
    ]);
    setDetail(d);
    setEvidence(r);
    setReport(d?.has_post_incident_report
      ? await api.postIncidentReport(id).catch(() => null)
      : null);
  }, []);

  useEffect(() => {
    setRejecting(false);
    setReason('');
    setError(null);
    loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  // The feed polls every 12 s; when the selected incident's summary changes
  // (a new report, a status move, an observer's Accept) re-read its detail.
  const liveSig = useMemo(() => {
    const s = live.find((i) => i.id === selectedId);
    return s ? JSON.stringify([s.updated_at, s.status, s.routed_agencies, s.accepted_agencies]) : '';
  }, [live, selectedId]);
  useEffect(() => {
    if (liveSig) loadDetail(selectedId);
  }, [liveSig]); // selectedId is folded into liveSig

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await Promise.all([refreshFeed(), loadDetail(selectedId), loadTab(tab)]);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const isNew = (inc) =>
    tab !== 'report' && tab !== 'closed' &&
    new Date(inc.reported_at).getTime() > (lastViewed ? new Date(lastViewed).getTime() : 0);
  const band = detail?.confidence_band ? BAND[detail.confidence_band] : null;
  const st = detail ? statusOf(detail.status) : null;
  const isLive = detail && !['resolved', 'post_incident_report', 'closed', 'rejected', 'merged'].includes(detail.status);

  return (
    <div className="vq dk">
      <div className="dk-tabs" role="tablist" aria-label="Incident lists">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`dk-tab${tab === t.key ? ' is-on' : ''}`}
            onClick={() => { setTab(t.key); setSelectedId(null); }}
            title={t.hint}
          >
            {t.label}
            {(t.key === 'incoming' || t.key === 'live' || fetched[t.key]) && (
              <span className="dk-tab-n">{lists[t.key].length}</span>
            )}
          </button>
        ))}
        <button className="vq-refresh dk-refresh" onClick={() => { refreshFeed(); loadTab(tab); }}>
          Refresh
        </button>
      </div>

      {error && <div className="vq-error">{error}</div>}

      <div className="vq-cols">
        <div className="vq-list">
          {rows.length === 0 && (
            <div className="vq-empty">
              {tab === 'incoming' ? 'Nothing waiting to be routed.' :
               tab === 'live' ? 'No live incidents.' :
               tab === 'report' ? 'No Post-Incident Reports owed.' : 'Nothing closed yet.'}
            </div>
          )}
          {rows.map((inc) => {
            const s = statusOf(inc.status);
            return (
              <button
                key={inc.id}
                className={`vq-item${inc.id === selectedId ? ' is-active' : ''}`}
                onClick={() => setSelectedId(inc.id)}
              >
                <div className="vq-item-top">
                  <span className="vq-item-name">
                    {isNew(inc) && <span className="dk-new" aria-label="New">NEW</span>}
                    {inc.designation}
                  </span>
                  <span className="dk-status" style={{ color: s.color }}>{s.label}</span>
                </div>
                <div className="vq-item-sub">
                  {tab === 'report'
                    ? `Fire out ${since(inc.resolved_at)} ago · report owed`
                    : tab === 'closed'
                      ? `Closed ${since(inc.closed_at)} ago`
                      : `${inc.report_count} report${inc.report_count === 1 ? '' : 's'} · ${since(inc.reported_at)} ago`}
                </div>
                <div className="dk-agencies">
                  {(inc.requested_agencies ?? []).map((a) => (
                    <span
                      key={a}
                      className={`dk-ag${(inc.routed_agencies ?? []).includes(a) ? ' is-routed' : ''}`}
                    >
                      {AGENCY_LABEL[a] ?? a}
                    </span>
                  ))}
                </div>
              </button>
            );
          })}
        </div>

        <div className="vq-detail">
          {!detail && <div className="vq-empty">Select an incident.</div>}
          {detail && (
            <>
              <div className="vq-detail-head">
                <div>
                  <h3 className="vq-detail-title">{detail.designation}</h3>
                  <div className="vq-detail-sub">
                    <span style={{ color: st.color, fontWeight: 700 }}>{st.label}</span>
                    {' · '}Reported {when(detail.reported_at)} · {detail.centroid_lat?.toFixed(5)}, {detail.centroid_lng?.toFixed(5)}
                  </div>
                </div>
                {band && (
                  <span className="vq-band" style={{ color: band.color, borderColor: band.color }}>
                    {band.label} · {Math.round((detail.confidence_score ?? 0) * 100)}%
                  </span>
                )}
              </div>

              <Timeline d={detail} />

              {isLive && (
                <RoutePanel
                  key={`${detail.id}:${detail.routes?.length ?? 0}`}
                  detail={detail}
                  orgs={orgs}
                  busy={busy}
                  onRoute={(routes, notes) => act(() => api.routeIncident(detail.id, routes, notes))}
                />
              )}

              {detail.routes?.length > 0 && <RouteList routes={detail.routes} />}

              {detail.status === 'post_incident_report' && (
                <div className="vq-note">
                  Fire out {since(detail.resolved_at)} ago. Waiting on the responding team
                  captain&apos;s Post-Incident Report — the incident closes when they file it.
                </div>
              )}
              {report && <ReportView report={report} />}

              <div className="vq-scores">
                <div className="vq-score">
                  <span className="vq-score-v">{detail.report_count}</span>
                  <span className="vq-score-l">reports</span>
                </div>
                <div className="vq-score">
                  <span className="vq-score-v">{Math.round((detail.s_score ?? 0) * 100)}%</span>
                  <span className="vq-score-l">spatial agreement</span>
                </div>
                <div className="vq-score">
                  <span className="vq-score-v">{Math.round((detail.v_score ?? 0) * 100)}%</span>
                  <span className="vq-score-l">reporter credibility</span>
                </div>
              </div>

              <h4 className="vq-section">Evidence ({evidence.length})</h4>
              <div className="vq-reports">
                {evidence.map((r) => {
                  const b = badgeOf(r.user_verified_percent ?? 0);
                  return (
                    <div key={r.id} className="vq-report">
                      {r.photo_url
                        ? <img className="vq-photo" src={r.photo_url} alt="Reported scene" />
                        : <div className="vq-photo vq-photo-missing">No photo</div>}
                      <div className="vq-report-meta">
                        <div className="vq-reporter">{r.reporter_name || 'Unnamed reporter'}</div>
                        <div className="vq-badge" style={{ color: b.color }}>
                          {r.user_verified_percent ?? 0}% · {b.label}
                        </div>
                        {r.gps_discrepancy_flag && (
                          <div className="vq-flag">Photo GPS disagrees with device GPS — possible spoofing</div>
                        )}
                        {!r.has_exif && <div className="vq-muted">No photo GPS</div>}
                        {r.notes && <div className="vq-muted">“{r.notes}”</div>}
                      </div>
                    </div>
                  );
                })}
                {evidence.length === 0 && <div className="vq-empty">No member reports.</div>}
              </div>

              {(detail.status === 'pending' || detail.status === 'verified') && (
                <div className="vq-actions">
                  {rejecting ? (
                    <>
                      <input
                        className="vq-reason"
                        placeholder="Why is this being rejected? (required)"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        autoFocus
                      />
                      <button
                        className="vq-btn vq-btn-reject"
                        disabled={busy || reason.trim().length === 0}
                        onClick={async () => {
                          if (await act(() => api.incidentReject(detail.id, reason.trim()))) {
                            setRejecting(false);
                          }
                        }}
                      >
                        {busy ? 'Rejecting…' : 'Confirm reject'}
                      </button>
                      <button className="vq-btn" onClick={() => setRejecting(false)} disabled={busy}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="vq-btn vq-btn-reject" disabled={busy} onClick={() => setRejecting(true)}>
                        Reject as false report
                      </button>
                      {detail.status === 'pending' && (
                        <span className="vq-muted">
                          Verification is the Fire Volunteer coordinator&apos;s, on mobile.
                        </span>
                      )}
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Timeline({ d }) {
  const steps = [
    ['Reported', d.reported_at],
    ['Verified', d.verified_at],
    ['Dispatched', d.dispatched_at],
    ['En route', d.en_route_at],
    ['On scene', d.arrived_at],
    ['Fire out', d.resolved_at],
    ['Closed', d.closed_at],
  ];
  if (d.rejected_at) steps.splice(1, steps.length, ['Rejected', d.rejected_at]);
  if (d.merged_at) steps.splice(1, steps.length, ['Merged', d.merged_at]);
  return (
    <ol className="dk-timeline" aria-label="Lifecycle">
      {steps.map(([label, at]) => (
        <li key={label} className={at ? 'is-done' : ''}>
          <span className="dk-tl-dot" />
          <span className="dk-tl-label">{label}</span>
          <span className="dk-tl-time">
            {at ? new Date(at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : '—'}
          </span>
        </li>
      ))}
    </ol>
  );
}

/// Choose agencies (only those the report asked for) and, within each, whole
/// agency or specific teams. Already-routed teams are shown but cannot be
/// picked again; routing more later is allowed.
function RoutePanel({ detail, orgs, busy, onRoute }) {
  const routable = routableAgencies(detail.requested_agencies);
  const requested = new Set(detail.requested_agencies ?? []);
  const routed = new Set((detail.routes ?? []).map((r) => `${r.agency}:${r.organization_id ?? ''}`));
  const firstTime = (detail.routes ?? []).length === 0;

  const [picked, setPicked] = useState(() =>
    Object.fromEntries(
      routable.map((a) => [a, { on: firstTime && requested.has(a), teams: [] }]),
    ),
  );
  const [notes, setNotes] = useState('');

  const teamsOf = (agency) => orgs.filter((o) => o.agency_type === agency && o.is_active);
  const choice = routable
    .filter((a) => picked[a]?.on)
    .map((a) => ({ agency: a, organization_ids: picked[a].teams }))
    // Drop a choice that would only repeat what is already routed.
    .filter((c) => (c.organization_ids.length === 0
      ? !routed.has(`${c.agency}:`)
      : c.organization_ids.some((id) => !routed.has(`${c.agency}:${id}`))));

  function toggleAgency(a) {
    setPicked((p) => ({ ...p, [a]: { ...p[a], on: !p[a].on } }));
  }
  function toggleTeam(a, id) {
    setPicked((p) => {
      const teams = p[a].teams.includes(id) ? p[a].teams.filter((t) => t !== id) : [...p[a].teams, id];
      return { ...p, [a]: { on: true, teams } };
    });
  }

  if (routable.length === 0) {
    return <div className="vq-note">The reports on this incident did not ask for any agency.</div>;
  }

  return (
    <section className="dk-route">
      <div className="dk-route-head">
        <span className="dc-eyebrow">{firstTime ? 'Accept & route' : 'Route to more teams'}</span>
        <span className="vq-muted">Only agencies the reporter asked for can be routed.</span>
      </div>

      {routable.map((a) => {
        const on = picked[a]?.on;
        const teams = teamsOf(a);
        const wholeRouted = routed.has(`${a}:`);
        return (
          <div className={`dk-route-row${on ? ' is-on' : ''}`} key={a}>
            <label className="dk-route-agency">
              <input type="checkbox" checked={!!on} onChange={() => toggleAgency(a)} disabled={busy} />
              <span>{AGENCY_LABEL[a]}</span>
              {!requested.has(a) && <span className="dk-hint">with Fire</span>}
              {OBSERVERS.includes(a) && <span className="dk-hint">observer · will Accept</span>}
            </label>
            {on && (
              <div className="dk-teams">
                <button
                  className={`dk-team${picked[a].teams.length === 0 ? ' is-on' : ''}`}
                  onClick={() => setPicked((p) => ({ ...p, [a]: { on: true, teams: [] } }))}
                  disabled={busy || wholeRouted}
                >
                  {wholeRouted ? '✓ Whole agency' : 'Whole agency'}
                </button>
                {teams.map((o) => {
                  const done = routed.has(`${a}:${o.id}`);
                  return (
                    <button
                      key={o.id}
                      className={`dk-team${picked[a].teams.includes(o.id) ? ' is-on' : ''}`}
                      onClick={() => toggleTeam(a, o.id)}
                      disabled={busy || done}
                    >
                      {done ? `✓ ${o.name}` : o.name}
                    </button>
                  );
                })}
                {teams.length === 0 && <span className="vq-muted">No accredited teams yet — routes to the agency.</span>}
              </div>
            )}
          </div>
        );
      })}

      <div className="dk-route-foot">
        <input
          className="vq-reason"
          placeholder="Note for the record (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={1000}
        />
        <button
          className="vq-btn vq-btn-verify"
          disabled={busy || choice.length === 0}
          onClick={() => onRoute(choice, notes.trim())}
        >
          {busy ? 'Routing…' : firstTime ? 'Accept & route' : 'Route'}
        </button>
      </div>
    </section>
  );
}

function RouteList({ routes }) {
  return (
    <section className="dk-routes">
      <span className="dc-eyebrow">Routed</span>
      {routes.map((r) => (
        <div className="dk-routed" key={r.id}>
          <span className="dk-routed-who">
            {AGENCY_LABEL[r.agency] ?? r.agency}
            <span className="vq-muted"> · {r.organization_name || 'whole agency'}</span>
          </span>
          <span className="vq-muted">{when(r.routed_at)}{r.routed_by_name ? ` by ${r.routed_by_name}` : ''}</span>
          {OBSERVERS.includes(r.agency) ? (
            r.accepted_at ? (
              <span className="dk-accepted">✓ Accepted{r.accepted_by_name ? ` by ${r.accepted_by_name}` : ''} · {when(r.accepted_at)}</span>
            ) : (
              <span className="dk-awaiting">Awaiting Accept</span>
            )
          ) : (
            <span className="vq-muted">Coordinator — verifies &amp; dispatches</span>
          )}
        </div>
      ))}
    </section>
  );
}

function ReportView({ report }) {
  const mins = report.resolved_at
    ? Math.max(0, Math.round((new Date(report.submitted_at) - new Date(report.resolved_at)) / 60000))
    : null;
  return (
    <section className="dk-pir">
      <div className="dk-route-head">
        <span className="dc-eyebrow">Post-Incident Report</span>
        <span className="vq-muted">
          Filed {when(report.submitted_at)} by {report.filed_by_name || 'the team captain'}
          {report.organization_name ? ` · ${report.organization_name}` : ''}
          {mins != null ? ` · ${mins} min after fire out` : ''}
        </span>
      </div>
      <dl className="dk-pir-grid">
        <dt>Unit</dt><dd>{report.truck_label} <span className="vq-muted">· {report.truck_type}</span></dd>
        <dt>Driver</dt><dd>{report.driver_name}</dd>
        <dt>Roster</dt>
        <dd>
          {report.roster.map((m, i) => (
            <span className="dk-chip" key={`${m.name}-${i}`}>{m.name}{m.role ? ` · ${m.role}` : ''}</span>
          ))}
        </dd>
        <dt>Equipment</dt>
        <dd>{report.equipment_taken.map((e) => <span className="dk-chip" key={e}>{e}</span>)}</dd>
        {report.notes && (<><dt>Notes</dt><dd className="dk-pir-notes">{report.notes}</dd></>)}
      </dl>
    </section>
  );
}
