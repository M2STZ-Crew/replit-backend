import { useEffect, useMemo, useState } from 'react';

import FiledReport from '../components/reports/FiledReport.jsx';
import IncidentSummary from '../components/reports/IncidentSummary.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import { EmptyState, Icon, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';

/* Reports & CIAR (REPLIT (MAIN) 10 · A60 878:8055, A61 878:8354).
 *
 * Every filed Post-Incident Report, newest first; open one to read it, the
 * Area's stored AI summary, and download the Area's PDF. Everything here is
 * a read. The design's six-part CIAR (A62), its generating and failed
 * states (A63, A63b) and correction entries (A65, A66) wait on server
 * support; the AI summary the server writes automatically is shown as it is.
 *
 * The host supplies the readers (src/integrations/records.js):
 *   readReports({ areaId, offset, pageSize }) -> { items, hasMore }
 *   readIncidentReports({ areaId }) -> report[]
 *   readSummary({ areaId }) -> { state, summary }
 *   downloadIncidentPdf({ areaId, designation }) */

const PAGE_SIZE = 25;
const CLOCK = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
});
const time = (iso) => (iso ? CLOCK.format(new Date(iso)) : '—');
const message = (e, fallback) => (e instanceof Error && e.message ? e.message : fallback);

function outcome(r) {
  return r.false_alarm ? { label: 'False alarm', tone: 'warn' } : { label: 'Filed', tone: 'ok' };
}

function ReportView({ report, readIncidentReports, readSummary, downloadIncidentPdf, onBack }) {
  const [view, setView] = useState('report');
  const [team, setTeam] = useState({ phase: 'loading', count: 0 });
  const [pdf, setPdf] = useState({ busy: false, error: null });

  useEffect(() => {
    let alive = true;
    Promise.resolve()
      .then(() => readIncidentReports({ areaId: report.area_id }))
      .then((rows) => { if (alive) setTeam({ phase: 'ready', count: Array.isArray(rows) ? rows.length : 0 }); })
      .catch(() => { if (alive) setTeam({ phase: 'error', count: 0 }); });
    return () => { alive = false; };
  }, [report.area_id, readIncidentReports]);

  async function download() {
    setPdf({ busy: true, error: null });
    try {
      await downloadIncidentPdf({ areaId: report.area_id, designation: report.area_designation });
      setPdf({ busy: false, error: null });
    } catch (e) {
      setPdf({ busy: false, error: message(e, 'The PDF could not be downloaded. Try again.') });
    }
  }

  const sub = [
    `Fire out ${time(report.fire_out_at || report.resolved_at)}`,
    `report sent ${time(report.submitted_at)} by ${report.filed_by_name || 'the team captain'}`,
    report.organization_name,
  ].filter(Boolean).join(' · ');

  return (
    <div className="ad-page">
      <button type="button" className="ad-text-button ad-back" onClick={onBack}>← All reports</button>
      <PageHeader
        eyebrow={`${report.area_designation}${report.organization_name ? ` · ${report.organization_name}` : ''}`}
        title={report.area_designation}
        description={sub}
        actions={(
          <button type="button" className="ad-button ad-button--secondary" onClick={download} disabled={pdf.busy}>
            {pdf.busy ? 'Preparing PDF…' : 'Download PDF'}
          </button>
        )}
      />
      {pdf.error && <p className="ad-inline-error" role="alert">{pdf.error}</p>}

      <div className="ad-toolbar">
        <div className="ad-tabs" role="tablist" aria-label="Report">
          {[{ key: 'report', label: 'Post-incident report' }, { key: 'summary', label: 'AI summary' }].map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={view === t.key}
              className={`ad-tab${view === t.key ? ' is-active' : ''}`}
              onClick={() => setView(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {team.phase === 'ready' && team.count > 1 && (
          <p className="ad-table-foot">{team.count} teams filed for {report.area_designation}; the PDF has every one.</p>
        )}
      </div>

      {view === 'report' ? (
        <>
          <FiledReport report={report} />
          <div className="ad-alert ad-alert--info">
            <span className="ad-alert-mark" aria-hidden="true">i</span>
            <p className="ad-alert-body">Reports can’t be edited after they’re sent.</p>
          </div>
        </>
      ) : (
        <section className="ad-panel">
          <IncidentSummary areaId={report.area_id} readSummary={readSummary} />
        </section>
      )}
    </div>
  );
}

export default function Reports({ readReports, readIncidentReports, readSummary, downloadIncidentPdf }) {
  const { org } = useConsole();
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ phase: 'loading', rows: [], hasMore: false, error: null });
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, phase: 'loading', error: null }));
    Promise.resolve()
      .then(() => readReports({ areaId: null, offset, pageSize: PAGE_SIZE }))
      .then((page) => {
        if (!alive) return;
        if (!Array.isArray(page?.items)) throw new Error('The reports could not be read. Try again.');
        setState({ phase: 'ready', rows: page.items, hasMore: page.hasMore === true, error: null });
      })
      .catch((e) => { if (alive) setState({ phase: 'error', rows: [], hasMore: false, error: message(e, 'The reports could not be loaded.') }); });
    return () => { alive = false; };
  }, [readReports, offset, attempt]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return state.rows;
    return state.rows.filter((r) => [r.area_designation, r.organization_name, r.filed_by_name, r.driver_name]
      .some((v) => String(v || '').toLowerCase().includes(q)));
  }, [state.rows, query]);

  if (selected) {
    return (
      <ReportView
        report={selected}
        readIncidentReports={readIncidentReports}
        readSummary={readSummary}
        downloadIncidentPdf={downloadIncidentPdf}
        onBack={() => setSelected(null)}
      />
    );
  }

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={org?.name ?? 'Records'}
        title="Reports & CIAR"
        description="Post-incident reports filed by the teams that responded, and each incident’s AI summary."
        actions={(
          <button type="button" className="ad-button ad-button--secondary" onClick={() => setAttempt((a) => a + 1)} disabled={state.phase === 'loading'}>
            Refresh
          </button>
        )}
      />

      <div className="ad-toolbar ad-toolbar--plain">
        <label className="ad-search">
          <Icon name="search" />
          <span className="web-sr-only">Search reports on this page</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search areas, organisations, names" />
        </label>
      </div>

      {state.phase === 'loading' ? (
        <StatePanel kind="loading" title="Loading reports…" busy />
      ) : state.phase === 'error' ? (
        <StatePanel kind="error" title="The reports couldn’t load" description={state.error} onRetry={() => setAttempt((a) => a + 1)} />
      ) : state.rows.length === 0 ? (
        <EmptyState icon="reports" title={offset > 0 ? 'No more reports' : 'No reports filed yet'}>
          A team captain files a post-incident report on the mobile app after the fire is out.
        </EmptyState>
      ) : (
        <>
          <div className="web-table-wrap">
            <table className="web-table">
              <caption className="web-sr-only">Filed post-incident reports</caption>
              <thead>
                <tr>
                  <th scope="col">Incident</th>
                  <th scope="col">Filed</th>
                  <th scope="col">Organisation</th>
                  <th scope="col">Outcome</th>
                  <th scope="col"><span className="web-sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className="web-table-row">
                    <th scope="row">
                      <span className="ad-cell-text">
                        <span className="ad-cell-title">{r.area_designation}</span>
                        <span className="ad-cell-meta">By {r.filed_by_name || 'the team captain'}{r.driver_name ? ` · driver ${r.driver_name}` : ''}</span>
                      </span>
                    </th>
                    <td className="ad-cell-quiet">{time(r.submitted_at)}</td>
                    <td className="ad-cell-strong">{r.organization_name || 'Not recorded'}</td>
                    <td><StatusChip {...outcome(r)} /></td>
                    <td className="web-table-action-cell">
                      <button type="button" className="web-table-row-action" onClick={() => setSelected(r)}>
                        Open<span className="web-sr-only"> the report for {r.area_designation}</span>
                      </button>
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr><td className="web-table-empty" colSpan={5}>Nothing on this page matches “{query}”.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <nav className="ad-pager" aria-label="Report pages">
            <p className="ad-table-foot">Showing {offset + 1}–{offset + state.rows.length}</p>
            <div className="ad-pager-buttons">
              <button type="button" className="ad-button ad-button--secondary ad-button--compact" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE_SIZE)); setQuery(''); }}>
                Previous
              </button>
              <button type="button" className="ad-button ad-button--secondary ad-button--compact" disabled={!state.hasMore} onClick={() => { setOffset(offset + PAGE_SIZE); setQuery(''); }}>
                Next
              </button>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
