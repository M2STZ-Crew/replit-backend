import { useEffect, useMemo, useState } from 'react';

import FiledReport from '../components/reports/FiledReport.jsx';
import IncidentSummary from '../components/reports/IncidentSummary.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import { EmptyState, Icon, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';
import { t } from '../i18n/i18n.jsx';

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
  return r.false_alarm ? { label: t('False alarm'), tone: 'warn' } : { label: t('Filed'), tone: 'ok' };
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
      setPdf({ busy: false, error: message(e, t('The PDF could not be downloaded. Try again.')) });
    }
  }

  const sub = [
    t('Fire out {time}', { time: time(report.fire_out_at || report.resolved_at) }),
    report.filed_by_name
      ? t('report sent {time} by {name}', { time: time(report.submitted_at), name: report.filed_by_name })
      : t('report sent {time} by the team captain', { time: time(report.submitted_at) }),
    report.organization_name,
  ].filter(Boolean).join(' · ');

  return (
    <div className="rpl-page">
      <button type="button" className="rpl-text-button rpl-back" onClick={onBack}>{t('← All reports')}</button>
      <PageHeader
        eyebrow={`${report.area_designation}${report.organization_name ? ` · ${report.organization_name}` : ''}`}
        title={report.area_designation}
        description={sub}
        actions={(
          <button type="button" className="rpl-button rpl-button--secondary" onClick={download} disabled={pdf.busy}>
            {pdf.busy ? t('Preparing PDF…') : t('Download PDF')}
          </button>
        )}
      />
      {pdf.error && <p className="rpl-inline-error" role="alert">{pdf.error}</p>}

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label={t('Report')}>
          {[{ key: 'report', label: t('Post-incident report') }, { key: 'summary', label: t('AI summary') }].map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={view === t.key}
              className={`rpl-tab${view === t.key ? ' is-active' : ''}`}
              onClick={() => setView(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {team.phase === 'ready' && team.count > 1 && (
          <p className="rpl-table-foot">{t('{count} teams filed for {area}; the PDF has every one.', { count: team.count, area: report.area_designation })}</p>
        )}
      </div>

      {view === 'report' ? (
        <>
          <FiledReport report={report} />
          <div className="rpl-alert rpl-alert--info">
            <span className="rpl-alert-mark" aria-hidden="true">i</span>
            <p className="rpl-alert-body">{t('Reports can’t be edited after they’re sent.')}</p>
          </div>
        </>
      ) : (
        <section className="rpl-panel">
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
        if (!Array.isArray(page?.items)) throw new Error(t('The reports could not be read. Try again.'));
        setState({ phase: 'ready', rows: page.items, hasMore: page.hasMore === true, error: null });
      })
      .catch((e) => { if (alive) setState({ phase: 'error', rows: [], hasMore: false, error: message(e, t('The reports could not be loaded.')) }); });
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
    <div className="rpl-page">
      <PageHeader
        eyebrow={org?.name ?? t('Records')}
        title={t('Reports & CIAR')}
        description={t('Post-incident reports filed by the teams that responded, and each incident’s AI summary.')}
        actions={(
          <button type="button" className="rpl-button rpl-button--secondary" onClick={() => setAttempt((a) => a + 1)} disabled={state.phase === 'loading'}>{t('Refresh')}</button>
        )}
      />

      <div className="rpl-toolbar rpl-toolbar--plain">
        <label className="rpl-search">
          <Icon name="search" />
          <span className="web-sr-only">{t('Search reports on this page')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search areas, organizations, names')} />
        </label>
      </div>

      {state.phase === 'loading' ? (
        <StatePanel kind="loading" title={t('Loading reports…')} busy />
      ) : state.phase === 'error' ? (
        <StatePanel kind="error" title={t('The reports couldn’t load')} description={state.error} onRetry={() => setAttempt((a) => a + 1)} />
      ) : state.rows.length === 0 ? (
        <EmptyState icon="reports" title={offset > 0 ? t('No more reports') : t('No reports filed yet')}>{t('A team captain files a post-incident report on the mobile app after the fire is out.')}</EmptyState>
      ) : (
        <>
          <div className="web-table-wrap">
            <table className="web-table">
              <caption className="web-sr-only">{t('Filed post-incident reports')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('Incident')}</th>
                  <th scope="col">{t('Filed')}</th>
                  <th scope="col">{t('Organization')}</th>
                  <th scope="col">{t('Outcome')}</th>
                  <th scope="col"><span className="web-sr-only">{t('Open')}</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className="web-table-row">
                    <th scope="row">
                      <span className="rpl-cell-text">
                        <span className="rpl-cell-title">{r.area_designation}</span>
                        <span className="rpl-cell-meta">{r.filed_by_name ? t('By {name}', { name: r.filed_by_name }) : t('By the team captain')}{r.driver_name ? t(' · driver {name}', { name: r.driver_name }) : ''}</span>
                      </span>
                    </th>
                    <td className="rpl-cell-quiet">{time(r.submitted_at)}</td>
                    <td className="rpl-cell-strong">{r.organization_name || t('Not recorded')}</td>
                    <td><StatusChip {...outcome(r)} /></td>
                    <td className="web-table-action-cell">
                      <button type="button" className="web-table-row-action" onClick={() => setSelected(r)}>{t('Open')}<span className="web-sr-only">{' '}{t('the report for')}{' '}{r.area_designation}</span>
                      </button>
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr><td className="web-table-empty" colSpan={5}>{t('Nothing on this page matches “{query}”.', { query })}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <nav className="rpl-pager" aria-label={t('Report pages')}>
            <p className="rpl-table-foot">{t('Showing {from}–{to}', { from: offset + 1, to: offset + state.rows.length })}</p>
            <div className="rpl-pager-buttons">
              <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE_SIZE)); setQuery(''); }}>{t('Previous')}</button>
              <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" disabled={!state.hasMore} onClick={() => { setOffset(offset + PAGE_SIZE); setQuery(''); }}>{t('Next')}</button>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
