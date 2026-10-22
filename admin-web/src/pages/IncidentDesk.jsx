import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import IncidentDetail from '../components/incidents/IncidentDetail.jsx';
import IncidentTable, { degrees } from '../components/incidents/IncidentTable.jsx';
import OverlapReview from '../components/incidents/OverlapReview.jsx';
import Icon from '../components/ui/Icon.jsx';
import { EmptyState, PageHeader, StatePanel } from '../components/ui/index.js';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import { AGENCY_LABEL } from '../lib/status.js';

/* Incidents (REPLIT (MAIN) 10 · A22 865:2061, A23–A28, A80–A82, A84).
 *
 * The list: every active Area, searchable and filtered by status, agency and
 * confidence, a page at a time. Opening one shows it in full (IncidentDetail)
 * where this Admin may acknowledge it.
 *
 * Two of the design's pieces wait on the server. "Routed to you" needs the
 * server to route an Area to an Admin's organisation; today every Admin may
 * act on every Area, so the tab is not drawn. And an Admin no longer rejects
 * an Area (PRD v13 §4.5.2: Reject is the Coordinator's, before anyone goes),
 * so the console's old Reject is gone. */

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
    <label className="ad-select">
      <span className="ad-select-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
    </label>
  );
}

export default function IncidentDesk({ focusId = null }) {
  const { incidents: live, loaded, failed, loadedAt, refresh: refreshFeed, acknowledge } = useLiveFeed();
  const { org } = useConsole();
  const lastViewed = useSurfaceVisit('incidents');

  const [tab, setTab] = useState('active');
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
  const rows = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (source ?? []).filter((inc) => {
      if (tab === 'active' && status !== 'all' && status !== 'post_incident_report' && inc.status !== status) return false;
      if (agency !== 'any' && !(inc.requested_agencies ?? []).includes(agency)) return false;
      if (band !== 'any' && inc.confidence_band !== band) return false;
      if (term && !`${inc.designation} ${degrees(inc.centroid_lat, inc.centroid_lng)}`.toLowerCase().includes(term)) return false;
      return true;
    });
  }, [source, tab, status, agency, band, query]);
  useEffect(() => { setPage(0); }, [tab, status, agency, band, query]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);

  const loadDetail = useCallback(async (id) => {
    if (!id) { setDetail(null); setDetailState('idle'); return; }
    setDetailState((s) => (s === 'ready' ? 'ready' : 'loading'));
    try {
      const [d, r, x, q] = await Promise.all([
        api.incident(id),
        api.incidentReports(id).catch(() => []),
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
      setNotice(`${detail.designation} acknowledged${org?.name ? ` for ${org.name}` : ''}`);
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
        <div className="ad-page">
          <button type="button" className="ad-text-button ad-back" onClick={() => setSelectedId(null)}>← All incidents</button>
          <StatePanel kind="error" title="This incident couldn’t load" description={error} onRetry={() => loadDetail(selectedId)} />
        </div>
      );
    }
    if (!detail || detail.id !== selectedId) {
      return <div className="ad-page"><StatePanel kind="loading" title="Loading the incident…" /></div>;
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

  const listLoading = needs ? fetched[needs] == null && !fetchError : !loaded;
  const emptyMessage = query || agency !== 'any' || band !== 'any' || status !== 'all'
    ? 'Nothing matches these filters.'
    : tab === 'closed' ? 'Nothing closed yet.' : 'No active incidents. A new Area appears here the moment its first report is clustered.';

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={org?.name ?? 'Operations'}
        title="Incidents"
        description="Every active incident in Pasay. Open one to see it in full and acknowledge it."
      />

      {overlaps.map((o) => (
        <div className="ad-overlap-alert" key={o.id} role="status">
          <span className="ad-overlap-alert-mark" aria-hidden="true">!</span>
          <span className="ad-overlap-alert-text">
            <span className="ad-cell-title">{o.area_a_designation} and {o.area_b_designation} may be the same fire</span>
            <span className="ad-cell-meta">{Math.round(o.distance_m)} m apart · decide in the next two minutes, or they stay separate</span>
          </span>
          <button type="button" className="ad-button ad-button--secondary ad-button--compact" onClick={() => setReviewing(o)}>
            Review
          </button>
        </div>
      ))}

      {notice && (
        <div className="ad-toast" role="status">
          <span aria-hidden="true">✓</span>
          {notice}
        </div>
      )}

      <div className="ad-tabs ad-tabs--page" role="tablist" aria-label="Incident lists">
        {[{ key: 'active', label: 'All active' }, { key: 'closed', label: 'Closed' }].map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`ad-tab${tab === t.key ? ' is-active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="ad-filters">
        <label className="ad-search">
          <Icon name="search" />
          <span className="web-sr-only">Search incidents</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search areas and coordinates"
          />
        </label>
        {tab === 'active' && (
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
        <div className="ad-alert ad-alert--danger" role="alert">
          <span className="ad-alert-mark" aria-hidden="true">!</span>
          <div className="ad-alert-text">
            <p className="ad-alert-title">Couldn’t load incidents</p>
            <p className="ad-alert-body">
              {fetchError
                ? `${fetchError} Check your connection, then try again.`
                : 'Check your connection. Alerts with sound start again when the console reconnects.'}
            </p>
            <button
              type="button"
              className="ad-text-button"
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
        <EmptyState icon="requests" title={tab === 'closed' ? 'Nothing closed yet' : 'No active incidents in Pasay'}>
          {tab === 'closed'
            ? 'An Area lands here once its post-incident report is filed.'
            : 'New reports appear here with a sound. Closed incidents are under Closed.'}
        </EmptyState>
      ) : (rows.length > 0 || !(fetchError || failed)) ? (
        <>
          <IncidentTable
            incidents={shown}
            lastViewed={tab === 'active' ? lastViewed : null}
            onOpen={open}
            emptyMessage={emptyMessage}
            staleAt={!needs && failed ? loadedAt : null}
          />
          <div className="ad-pager">
            <span className="ad-pager-range">
              {rows.length === 0 ? 'Showing 0 of 0' : `Showing ${page * PAGE + 1}–${Math.min(rows.length, page * PAGE + PAGE)} of ${rows.length}`}
            </span>
            {pages > 1 && (
              <nav className="ad-pager-pages" aria-label="Pages">
                <button type="button" className="ad-page-button" onClick={() => setPage((p) => p - 1)} disabled={page === 0} aria-label="Previous page">‹</button>
                {Array.from({ length: pages }, (_, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`ad-page-button${i === page ? ' is-current' : ''}`}
                    onClick={() => setPage(i)}
                    aria-current={i === page ? 'page' : undefined}
                  >
                    {i + 1}
                  </button>
                ))}
                <button type="button" className="ad-page-button" onClick={() => setPage((p) => p + 1)} disabled={page >= pages - 1} aria-label="Next page">›</button>
              </nav>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
