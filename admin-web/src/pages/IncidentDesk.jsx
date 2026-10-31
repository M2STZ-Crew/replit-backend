import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import IncidentDetail from '../components/incidents/IncidentDetail.jsx';
import IncidentTable from '../components/incidents/IncidentTable.jsx';
import OverlapReview from '../components/incidents/OverlapReview.jsx';
import AlarmEscalationDialog from '../components/requests/AlarmEscalationDialog.jsx';
import Icon from '../components/ui/Icon.jsx';
import { EmptyState, PageHeader, StatePanel } from '../components/ui/index.js';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import { actsOn, splitsIncidents, yourOrg } from '../lib/access.js';
import { degrees, knownAddress } from '../lib/place.js';
import { AGENCY_LABEL } from '../lib/status.js';

/* Incidents (REPLIT (MAIN) 10 · A22 865:2061, A23–A28, A80–A82, A84).
 *
 * The list: every active Area, searchable and filtered by status, agency and
 * confidence, a page at a time. Opening one shows it in full (IncidentDetail)
 * where this Admin may acknowledge it.
 *
 * An Admin that acts on some Areas only gets "Routed to you" — the Areas that
 * asked for its agency — and the "Your org" column (lib/access.js). Every
 * other Area it can open and follow, view only (A25). An Admin never rejects
 * an Area (PRD v13 §4.5.2: Reject is the Coordinator's, before anyone goes). */

const PAGE = 10;

const STATUSES = [
  { key: 'all', label: 'All active' },
  { key: 'reported', label: 'Reported' },
  { key: 'verified', label: 'Acknowledged' },
  { key: 'en_route', label: 'En route' },
  { key: 'arrived', label: 'Arrived' },
  { key: 'post_incident_report', label: 'Report due' },
];
const CONFIDENCE = [
  { key: 'any', label: 'Any' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
];
const AGENCIES = ['any', 'fire_volunteer', 'bfp', 'police', 'medical', 'barangay'];

function Select({ label, value, onChange, options }) {
  return (
    <label className="rpl-select">
      <span className="rpl-select-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
    </label>
  );
}

export default function IncidentDesk({ focusId = null, initialTab = null }) {
  const { incidents: live, loaded, failed, loadedAt, refresh: refreshFeed, acknowledge } = useLiveFeed();
  const { org, console: access } = useConsole();
  const lastViewed = useSurfaceVisit('incidents');
  const split = splitsIncidents(access);
  const orgStatus = split ? (inc) => yourOrg(access, inc) : null;
  // Read by loadDetail through refs, so a 12 s poll does not reload the open
  // incident (that is what liveSig below is for).
  const liveRef = useRef(live);
  liveRef.current = live;
  const accessRef = useRef(access);
  accessRef.current = access;

  const [tab, setTab] = useState(split && initialTab === 'routed' ? 'routed' : 'active');
  const [status, setStatus] = useState('all');
  const [agency, setAgency] = useState('any');
  const [band, setBand] = useState('any');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [fetched, setFetched] = useState({ post_incident_report: null, closed: null });
  const [fetchError, setFetchError] = useState(null);

  const [selectedId, setSelectedId] = useState(focusId);
  const [detail, setDetail] = useState(null);
  const [detailState, setDetailState] = useState('idle');
  const [evidence, setEvidence] = useState([]);
  const [dispatches, setDispatches] = useState([]);
  const [requests, setRequests] = useState([]);
  const [reports, setReports] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState(null);
  const [overlaps, setOverlaps] = useState([]);
  const [reviewing, setReviewing] = useState(null);
  const [askingAlarm, setAskingAlarm] = useState(false);
  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  // Arriving on an incident from the alarm, a desktop alert, the board or the
  // map is seeing it: its alarm stops. So does opening it from the list.
  useEffect(() => {
    if (focusId) acknowledge(focusId);
  }, [focusId, acknowledge]);

  // Pending overlaps (A27) come and go within two minutes, so they are read
  // again whenever the live feed moves.
  const loadOverlaps = useCallback(() => {
    api.pendingOverlaps()
      .then((rows) => setOverlaps(Array.isArray(rows) ? rows : []))
      .catch(() => setOverlaps([]));
  }, []);
  const feedSig = live.map((i) => `${i.id}:${i.updated_at}`).join('|');
  useEffect(() => { loadOverlaps(); }, [feedSig, loadOverlaps]);

  const needs = tab === 'closed' ? 'closed' : status === 'post_incident_report' ? 'post_incident_report' : null;
  const loadList = useCallback(async (key) => {
    if (!key) return;
    setFetchError(null);
    try {
      const rows = await api.incidents({ activeOnly: false, status: key, limit: 200 });
      setFetched((f) => ({ ...f, [key]: Array.isArray(rows) ? rows : [] }));
    } catch (e) {
      setFetchError(e.message || 'The incidents could not be loaded.');
    }
  }, []);
  useEffect(() => { loadList(needs); }, [needs, loadList]);

  const source = needs ? fetched[needs] : live;
  const routedCount = useMemo(() => live.filter((inc) => actsOn(access, inc)).length, [live, access]);
  const rows = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (source ?? []).filter((inc) => {
      if (tab === 'routed' && !actsOn(access, inc)) return false;
      if (tab !== 'closed' && status !== 'all' && status !== 'post_incident_report' && inc.status !== status) return false;
      if (agency !== 'any' && !(inc.requested_agencies ?? []).includes(agency)) return false;
      if (band !== 'any' && inc.confidence_band !== band) return false;
      if (term && !`${inc.designation} ${knownAddress(inc.centroid_lat, inc.centroid_lng) ?? ''} ${degrees(inc.centroid_lat, inc.centroid_lng)}`.toLowerCase().includes(term)) return false;
      return true;
    });
  }, [source, tab, status, agency, band, query, access]);
  useEffect(() => { setPage(0); }, [tab, status, agency, band, query]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);

  const loadDetail = useCallback(async (id) => {
    if (!id) { setDetail(null); setDetailState('idle'); return; }
    setDetailState((s) => (s === 'ready' ? 'ready' : 'loading'));
    try {
      // Who reported is for the organisations the Area asked for (A25): an
      // Area routed elsewhere is opened without it.
      const summary = liveRef.current.find((i) => i.id === id);
      const routed = !summary || actsOn(accessRef.current, summary);
      const [d, r, x, q] = await Promise.all([
        api.incident(id),
        routed ? api.incidentReports(id).catch(() => []) : Promise.resolve([]),
        api.incidentDispatches(id).catch(() => []),
        api.alarmRequests().catch(() => []),
      ]);
      setDetail(d);
      setEvidence(Array.isArray(r) ? [...r].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)) : []);
      setDispatches(Array.isArray(x) ? x : []);
      setRequests(Array.isArray(q) ? q.filter((row) => row.area_id === id) : []);
      // One per responding team. An API from before that returns a single one.
      setReports(d?.has_post_incident_report
        ? await api.postIncidentReports(id)
            .catch(() => api.postIncidentReport(id).then((one) => [one]).catch(() => []))
        : []);
      setDetailState('ready');
    } catch (e) {
      setDetailState('error');
      setError(e.message || 'This incident could not be loaded.');
    }
  }, []);

  useEffect(() => {
    setError(null);
    setConfirming(false);
    loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  // The feed polls; when the open incident's summary changes (a new report, a
  // status move, another Accept) read its detail again.
  const liveSig = useMemo(() => {
    const s = live.find((i) => i.id === selectedId);
    return s ? JSON.stringify([s.updated_at, s.status, s.accepted_agencies]) : '';
  }, [live, selectedId]);
  useEffect(() => {
    if (liveSig) loadDetail(selectedId);
  }, [liveSig]); // selectedId is folded into liveSig

  function open(inc) {
    setNotice(null);
    setSelectedId(inc.id);
    acknowledge(inc.id);
  }

  async function confirmAcknowledge() {
    setBusy(true);
    setError(null);
    try {
      await api.incidentAccept(detail.id);
      await Promise.all([refreshFeed(), loadDetail(detail.id)]);
      setConfirming(false);
      setNotice(`${detail.designation} acknowledged${org?.id && org?.name ? ` for ${org.name}` : ''}`);
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    setBusy(true);
    setError(null);
    try {
      await api.incidentReportPdf(detail.id, detail.designation);
    } catch (e) {
      setError(e.message || 'The report could not be downloaded.');
    } finally {
      setBusy(false);
    }
  }

  if (reviewing) {
    return (
      <>
        <OverlapReview
          overlap={reviewing}
          onBack={() => setReviewing(null)}
          onDone={async (message) => {
            setReviewing(null);
            setNotice(message);
            await refreshFeed();
            loadOverlaps();
          }}
        />
      </>
    );
  }

  if (selectedId) {
    if (detailState === 'error' && !detail) {
      return (
        <div className="rpl-page">
          <button type="button" className="rpl-text-button rpl-back" onClick={() => setSelectedId(null)}>← All incidents</button>
          <StatePanel kind="error" title="This incident couldn’t load" description={error} onRetry={() => loadDetail(selectedId)} />
        </div>
      );
    }
    if (!detail || detail.id !== selectedId) {
      return <div className="rpl-page"><StatePanel kind="loading" title="Loading the incident…" /></div>;
    }
    return (
      <>
        <IncidentDetail
          detail={detail}
          evidence={evidence}
          dispatches={dispatches}
          requests={requests}
          reports={reports}
          busy={busy}
          error={error}
          confirming={confirming}
          acknowledgedNow={!!notice}
          onAskAcknowledge={() => setConfirming(true)}
          onCancelAcknowledge={() => setConfirming(false)}
          onConfirmAcknowledge={confirmAcknowledge}
          onBack={() => { setSelectedId(null); setNotice(null); }}
          onPdf={downloadPdf}
          access={access}
          orgName={org?.name ?? 'your organization'}
          onAskAlarm={() => setAskingAlarm(true)}
        />
        <AlarmEscalationDialog
          open={askingAlarm}
          areas={[detail]}
          bfpName="BFP"
          onClose={() => setAskingAlarm(false)}
          onSend={async ({ areaId, level, justification }) => {
            await api.alarmRequestCreate({ areaId, level, justification });
            setAskingAlarm(false);
            setNotice(`Asked BFP to raise ${detail.designation} to ${level.replace(/_/g, ' ')}`);
            await loadDetail(detail.id);
          }}
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

  const listLoading = needs ? fetched[needs] == null && !fetchError : !loaded;
  const emptyMessage = query || agency !== 'any' || band !== 'any' || status !== 'all'
    ? 'Nothing matches these filters.'
    : tab === 'closed'
      ? 'Nothing closed yet.'
      : tab === 'routed'
        ? 'Nothing is routed to you right now. An Area that asks for your agency appears here, with its sound.'
        : 'No active incidents. A new Area appears here the moment its first report is clustered.';

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? 'Operations'}
        title="Incidents"
        description={split
          ? 'Every active incident in Pasay. You can act on the ones routed to you.'
          : 'Every active incident in Pasay. Open one to see it in full and acknowledge it.'}
      />

      {overlaps.map((o) => (
        <div className="rpl-overlap-alert" key={o.id} role="status">
          <span className="rpl-overlap-alert-mark" aria-hidden="true">!</span>
          <span className="rpl-overlap-alert-text">
            <span className="rpl-cell-title">{o.area_a_designation} and {o.area_b_designation} may be the same fire</span>
            <span className="rpl-cell-meta">{Math.round(o.distance_m)} m apart · decide in the next two minutes, or they stay separate</span>
          </span>
          <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" onClick={() => setReviewing(o)}>
            Review
          </button>
        </div>
      ))}

      {notice && (
        <div className="rpl-toast" role="status">
          <span aria-hidden="true">✓</span>
          {notice}
        </div>
      )}

      <div className="rpl-tabs rpl-tabs--page" role="tablist" aria-label="Incident lists">
        {[
          { key: 'active', label: 'All active' },
          ...(split ? [{ key: 'routed', label: 'Routed to you', count: routedCount }] : []),
          { key: 'closed', label: 'Closed' },
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
            {t.count > 0 && <span className="web-count-badge" aria-label={`${t.count} routed to you`}>{t.count}</span>}
          </button>
        ))}
      </div>

      <div className="rpl-filters">
        <label className="rpl-search">
          <Icon name="search" />
          <span className="web-sr-only">Search incidents</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search areas and coordinates"
          />
        </label>
        {tab !== 'closed' && (
          <Select label="Status" value={status} onChange={setStatus} options={STATUSES} />
        )}
        <Select
          label="Agency"
          value={agency}
          onChange={setAgency}
          options={AGENCIES.map((a) => ({ key: a, label: a === 'any' ? 'Any' : AGENCY_LABEL[a] ?? a }))}
        />
        <Select label="Confidence" value={band} onChange={setBand} options={CONFIDENCE} />
      </div>

      {(fetchError || (!needs && failed)) && (
        <div className="rpl-alert rpl-alert--danger" role="alert">
          <span className="rpl-alert-mark" aria-hidden="true">!</span>
          <div className="rpl-alert-text">
            <p className="rpl-alert-title">Couldn’t load incidents</p>
            <p className="rpl-alert-body">
              {fetchError
                ? `${fetchError} Check your connection, then try again.`
                : 'Check your connection. Alerts with sound start again when the console reconnects.'}
            </p>
            <button
              type="button"
              className="rpl-text-button"
              onClick={() => (fetchError ? loadList(needs) : refreshFeed())}
            >
              Try again
            </button>
          </div>
        </div>
      )}

      {listLoading && !failed ? (
        <StatePanel kind="loading" title="Loading incidents…" />
      ) : rows.length === 0 && !(query || agency !== 'any' || band !== 'any' || status !== 'all') && !(fetchError || failed) ? (
        <EmptyState
          icon="requests"
          title={tab === 'closed' ? 'Nothing closed yet' : tab === 'routed' ? 'Nothing routed to you' : 'No active incidents in Pasay'}
        >
          {tab === 'closed'
            ? 'An Area lands here once its post-incident report is filed.'
            : tab === 'routed'
              ? 'An Area that asks for your agency appears here, with its sound. Every other one is under All active.'
              : 'New reports appear here with a sound. Closed incidents are under Closed.'}
        </EmptyState>
      ) : (rows.length > 0 || !(fetchError || failed)) ? (
        <>
          <IncidentTable
            incidents={shown}
            lastViewed={tab !== 'closed' ? lastViewed : null}
            onOpen={open}
            emptyMessage={emptyMessage}
            staleAt={!needs && failed ? loadedAt : null}
            yourOrg={orgStatus}
          />
          <div className="rpl-pager">
            <span className="rpl-pager-range">
              {rows.length === 0 ? 'Showing 0 of 0' : `Showing ${page * PAGE + 1}–${Math.min(rows.length, page * PAGE + PAGE)} of ${rows.length}`}
            </span>
            {pages > 1 && (
              <nav className="rpl-pager-pages" aria-label="Pages">
                <button type="button" className="rpl-page-button" onClick={() => setPage((p) => p - 1)} disabled={page === 0} aria-label="Previous page">‹</button>
                {Array.from({ length: pages }, (_, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`rpl-page-button${i === page ? ' is-current' : ''}`}
                    onClick={() => setPage(i)}
                    aria-current={i === page ? 'page' : undefined}
                  >
                    {i + 1}
                  </button>
                ))}
                <button type="button" className="rpl-page-button" onClick={() => setPage((p) => p + 1)} disabled={page >= pages - 1} aria-label="Next page">›</button>
              </nav>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
