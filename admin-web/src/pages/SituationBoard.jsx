import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import IncidentTable from '../components/incidents/IncidentTable.jsx';
import Icon from '../components/ui/Icon.jsx';
import { PageHeader } from '../components/ui/index.js';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import { formatMinutes, formatShare, responseMetrics } from '../lib/metrics.js';

/* Dashboard (REPLIT (MAIN) 10 · A20 865:1310, A21, A83; PRD v13 §4.6.2,
 * §4.14): this organisation's work first — the queues it must answer, one
 * click from their destination — then the active Areas.
 *
 * The design splits the Areas into "Routed to <org>" and "Other
 * organisations' incidents (view only)" and closes with each organisation's
 * availability (A72). Both wait on the server: it does not yet route an Area
 * to an Admin's organisation, so every Admin may act on every Area, and it
 * reports no AFK state. Until then the Areas are one table and the
 * availability strip is not drawn.
 *
 * The response measures under the fold are the console's existing pilot
 * measures (PRD v13 §13.2), kept below the design's content. */

const HISTORY_LIMIT = 500;
const METRICS_DAYS = 30;

function QueueCount({ icon, count, label, onOpen, loading, urgent = false }) {
  // Only the queue that cannot wait takes the coral edge (A20): an Area
  // nobody has acknowledged yet.
  const attention = urgent && count > 0;
  return (
    <button
      type="button"
      className={`ad-queue${attention ? ' is-attention' : ''}`}
      onClick={onOpen}
      aria-label={loading ? `${label}, loading` : `${count} ${label}`}
    >
      <span className={`ad-queue-plate${attention ? ' is-attention' : ''}`} aria-hidden="true">
        <Icon name={icon} />
      </span>
      <span className="ad-queue-text" aria-hidden="true">
        <span className="ad-queue-count">{loading ? '·' : count}</span>
        <span className="ad-queue-label">{label}</span>
      </span>
      <Icon name="chevron-right" size={18} />
    </button>
  );
}

export default function SituationBoard({ onNavigate }) {
  // Live incidents come from the console-wide feed, so this board updates on
  // the same poll that drives the badges and sounds.
  const { incidents, loaded } = useLiveFeed();
  const { org, access } = useConsole();
  const lastViewed = useSurfaceVisit('dashboard');
  const [allIncidents, setAllIncidents] = useState([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [queues, setQueues] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Closed incidents included, so the measures cover finished incidents.
      // 500 is the most the feed returns in one page.
      const history = await api.incidents({ activeOnly: false, limit: HISTORY_LIMIT }).catch(() => []);
      if (cancelled) return;
      setAllIncidents(Array.isArray(history) ? history : []);
      setHistoryLoaded(true);
    })();
    return () => { cancelled = true; };
  }, []);

  // The queues this Admin answers. A queue that cannot be read is left out
  // rather than shown as zero.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const read = (p) => p.then((rows) => (Array.isArray(rows) ? rows.length : null)).catch(() => null);
      const [requests, ids, affiliates] = await Promise.all([
        read(api.alarmRequests('pending')),
        read(api.pendingVerifications()),
        read(api.affiliates('pending')),
      ]);
      if (!cancelled) setQueues({ requests, ids, affiliates });
    })();
    return () => { cancelled = true; };
  }, []);

  const toAcknowledge = incidents.filter((inc) => inc.status === 'reported').length;
  const metrics = useMemo(
    () => responseMetrics(allIncidents, { days: METRICS_DAYS }),
    [allIncidents],
  );
  // If a full page came back and even its oldest incident is inside the
  // window, older ones in the window were cut off — say so.
  const metricsTruncated =
    allIncidents.length >= HISTORY_LIMIT &&
    Date.now() - new Date(allIncidents[allIncidents.length - 1]?.reported_at).getTime() <
      METRICS_DAYS * 864e5;

  const central = access === 'central';
  const queueList = [
    { key: 'incidents', icon: 'flame', label: 'To acknowledge', count: toAcknowledge, loading: !loaded, urgent: true },
    { key: 'requests', icon: 'requests', label: 'Requests to answer', count: queues?.requests },
    central && { key: 'affiliates', icon: 'organization', label: 'Affiliate requests', count: queues?.affiliates },
    central && { key: 'idreview', icon: 'verification', label: 'ID reviews', count: queues?.ids },
  ].filter((q) => q && (q.loading || queues == null || q.count != null));

  const eyebrow = org?.name ? `${org.name}${central ? ' · Central hub' : ''}` : 'Operations';

  return (
    <div className="ad-page ad-board">
      <PageHeader
        eyebrow={eyebrow}
        title="Dashboard"
        description="Your work first, then every active Area across Pasay City."
      />

      <section aria-label="Your queues" className="ad-queues">
        {queueList.map((q) => (
          <QueueCount
            key={q.key}
            icon={q.icon}
            label={q.label}
            count={q.count ?? 0}
            urgent={q.urgent}
            loading={q.loading || (q.key !== 'incidents' && queues == null)}
            onOpen={() => onNavigate(q.key)}
          />
        ))}
      </section>

      <section className="ad-board-section" aria-labelledby="ad-board-incidents-title">
        <div className="ad-section-head">
          <h2 className="ad-section-title" id="ad-board-incidents-title">Active incidents</h2>
          <span className="ad-section-meta">
            {loaded ? `${incidents.length} active` : ''}
          </span>
          <button type="button" className="ad-text-button" onClick={() => onNavigate('incidents')}>
            All incidents
          </button>
        </div>
        <IncidentTable
          incidents={incidents}
          lastViewed={lastViewed}
          loading={!loaded}
          onOpen={(inc) => onNavigate('incidents', { incidentId: inc.id })}
          emptyMessage="No active incidents. A new Area appears here the moment its first report is clustered."
        />
      </section>

      <section className="ad-panel" aria-labelledby="ad-board-metrics-title">
        <h2 className="ad-panel-title" id="ad-board-metrics-title">Response measures · last {METRICS_DAYS} days</h2>
        <p className="ad-panel-note">
          {historyLoaded
            ? `${metrics.count} incident${metrics.count === 1 ? '' : 's'}` +
              `${metricsTruncated ? ` (the latest ${HISTORY_LIMIT})` : ''}` +
              ' · medians over incidents that reached both steps'
            : 'Loading…'}
        </p>
        <div className="ad-measures">
          {[
            { label: 'Report to acknowledged', m: metrics.reportToVerify, fmt: 'time' },
            { label: 'Acknowledged to on scene', m: metrics.verifyToScene, fmt: 'time' },
            { label: 'Fire out to report filed', m: metrics.fireOutToReport, fmt: 'time' },
            { label: 'Reached high confidence', m: metrics.highConfidence, fmt: 'share' },
            { label: 'False alarms', m: metrics.falseAlarm, fmt: 'share' },
          ].map(({ label, m, fmt }) => (
            <div className="ad-measure" key={label}>
              <span className="ad-measure-label">{label}</span>
              <span className="ad-measure-value">
                {historyLoaded ? (fmt === 'time' ? formatMinutes(m.median) : formatShare(m.share)) : '·'}
              </span>
              <span className="ad-measure-foot">
                {m.n === 0 ? 'None yet' : `over ${m.n} incident${m.n === 1 ? '' : 's'}`}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
