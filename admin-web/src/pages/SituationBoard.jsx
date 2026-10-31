import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import IncidentTable from '../components/incidents/IncidentTable.jsx';
import Icon from '../components/ui/Icon.jsx';
import { PageHeader } from '../components/ui/index.js';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import {
  PERM, acknowledgedByUs, actsOn, can, splitsIncidents, variantLabel, yourOrg,
} from '../lib/access.js';
import { formatMinutes, formatShare, responseMetrics } from '../lib/metrics.js';

/* Dashboard (REPLIT (MAIN) 10 · A20 865:1310, A21 865:1722, A83; PRD v13
 * §4.6.2, §4.14): this organisation's work first — the queues it must answer,
 * one click from their destination — then the active Areas.
 *
 * An Admin that acts on some Areas only (every organisation's, the central
 * hub's) gets them split as the design draws them: "Routed to <org>" with
 * its "Your org" chip, then "Other organisations' incidents", view only. The
 * system Admin acts on every Area, so it keeps one table. The availability
 * strip (A72) is not drawn: the server stores no AFK state yet.
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
  const { org, console: access } = useConsole();
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

  // What this Admin answers: alarm escalations for whoever sets the level
  // (BFP, or the system Admin), affiliates and IDs for the hub.
  const answersAlarms = can(access, PERM.DECIDE_ALARM) || access.variant === 'system';
  const reviewsAffiliates = can(access, PERM.REVIEW_AFFILIATES);
  const reviewsIds = can(access, PERM.REVIEW_IDS);

  // The queues this Admin answers. A queue that cannot be read is left out
  // rather than shown as zero.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const read = (p) => p.then((rows) => (Array.isArray(rows) ? rows.length : null)).catch(() => null);
      const skip = Promise.resolve(null);
      const [requests, ids, affiliates] = await Promise.all([
        answersAlarms ? read(api.alarmRequests('pending')) : skip,
        reviewsIds ? read(api.pendingVerifications()) : skip,
        reviewsAffiliates ? read(api.affiliates('pending')) : skip,
      ]);
      if (!cancelled) setQueues({ requests, ids, affiliates });
    })();
    return () => { cancelled = true; };
  }, [answersAlarms, reviewsIds, reviewsAffiliates]);

  const split = splitsIncidents(access);
  const routed = split ? incidents.filter((inc) => actsOn(access, inc)) : incidents;
  const others = split ? incidents.filter((inc) => !actsOn(access, inc)) : [];
  const toAcknowledge = routed.filter((inc) => !acknowledgedByUs(access, inc)).length;
  const orgStatus = split ? (inc) => yourOrg(access, inc) : null;
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

  const queueList = [
    { key: 'incidents', icon: 'flame', label: 'To acknowledge', count: toAcknowledge, loading: !loaded, urgent: true, live: true },
    split && { key: 'incidents', id: 'routed', icon: 'incidents', label: 'Active, routed to you', count: routed.length, loading: !loaded, live: true },
    answersAlarms && { key: 'requests', icon: 'requests', label: 'Requests to answer', count: queues?.requests },
    reviewsAffiliates && { key: 'affiliates', icon: 'organization', label: 'Affiliate requests', count: queues?.affiliates },
    reviewsIds && { key: 'idreview', icon: 'verification', label: 'ID reviews', count: queues?.ids },
  ].filter((q) => q && (q.live || queues == null || q.count != null));

  const eyebrow = org?.name ? `${org.name} · ${variantLabel(access)}` : 'Operations';

  return (
    <div className="ad-page ad-board">
      <PageHeader
        eyebrow={eyebrow}
        title="Dashboard"
        description={split
          ? 'Your work first. Other organizations’ incidents are below for awareness.'
          : 'Your work first, then every active Area across Pasay City.'}
      />

      <section aria-label="Your queues" className="ad-queues">
        {queueList.map((q) => (
          <QueueCount
            key={q.id ?? q.key}
            icon={q.icon}
            label={q.label}
            count={q.count ?? 0}
            urgent={q.urgent}
            loading={q.loading || (!q.live && queues == null)}
            onOpen={() => onNavigate(q.key, split && q.key === 'incidents' ? { tab: 'routed' } : {})}
          />
        ))}
      </section>

      <section className="ad-board-section" aria-labelledby="ad-board-incidents-title">
        <div className="ad-section-head">
          <h2 className="ad-section-title" id="ad-board-incidents-title">
            {split ? `Routed to ${org?.name ?? 'your organization'}` : 'Active incidents'}
          </h2>
          <span className="ad-section-meta">
            {loaded ? `${routed.length} active` : ''}
          </span>
          <button type="button" className="ad-text-button" onClick={() => onNavigate('incidents')}>
            All incidents
          </button>
        </div>
        <IncidentTable
          incidents={routed}
          lastViewed={lastViewed}
          loading={!loaded}
          yourOrg={orgStatus}
          onOpen={(inc) => onNavigate('incidents', { incidentId: inc.id })}
          emptyMessage={split
            ? 'Nothing is routed to you right now. An Area that asks for your agency appears here, with its sound.'
            : 'No active incidents. A new Area appears here the moment its first report is clustered.'}
        />
      </section>

      {split && (
        <section className="ad-board-section" aria-labelledby="ad-board-others-title">
          <div className="ad-section-head">
            <h2 className="ad-section-title" id="ad-board-others-title">Other organizations’ incidents</h2>
            <span className="ad-section-meta">View only</span>
          </div>
          <IncidentTable
            incidents={others}
            lastViewed={lastViewed}
            loading={!loaded}
            yourOrg={orgStatus}
            onOpen={(inc) => onNavigate('incidents', { incidentId: inc.id })}
            emptyMessage="No other active incidents in Pasay right now."
          />
        </section>
      )}

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
