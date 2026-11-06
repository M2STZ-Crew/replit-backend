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
import { t } from '../i18n/i18n.jsx';

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
      className={`rpl-queue${attention ? ' is-attention' : ''}`}
      onClick={onOpen}
      aria-label={loading ? t('{label}, loading', { label }) : t('{count} {label}', { count, label })}
    >
      <span className={`rpl-queue-plate${attention ? ' is-attention' : ''}`} aria-hidden="true">
        <Icon name={icon} />
      </span>
      <span className="rpl-queue-text" aria-hidden="true">
        <span className="rpl-queue-count">{loading ? '·' : count}</span>
        <span className="rpl-queue-label">{label}</span>
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
    { key: 'incidents', icon: 'flame', label: t('To acknowledge'), count: toAcknowledge, loading: !loaded, urgent: true, live: true },
    split && { key: 'incidents', id: 'routed', icon: 'incidents', label: t('Active, routed to you'), count: routed.length, loading: !loaded, live: true },
    answersAlarms && { key: 'requests', icon: 'requests', label: t('Requests to answer'), count: queues?.requests },
    reviewsAffiliates && { key: 'affiliates', icon: 'organization', label: t('Affiliate requests'), count: queues?.affiliates },
    reviewsIds && { key: 'idreview', icon: 'verification', label: t('ID reviews'), count: queues?.ids },
  ].filter((q) => q && (q.live || queues == null || q.count != null));

  const eyebrow = org?.name ? `${org.name} · ${variantLabel(access)}` : t('Operations');

  return (
    <div className="rpl-page rpl-board">
      <PageHeader
        eyebrow={eyebrow}
        title={t('Dashboard')}
        description={split
          ? t('Your work first. Other organizations’ incidents are below for awareness.')
          : t('Your work first, then every active Area across Pasay City.')}
      />

      <section aria-label={t('Your queues')} className="rpl-queues">
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

      <section className="rpl-board-section" aria-labelledby="rpl-board-incidents-title">
        <div className="rpl-section-head">
          <h2 className="rpl-section-title" id="rpl-board-incidents-title">
            {split ? t('Routed to {org}', { org: org?.name ?? t('your organization') }) : t('Active incidents')}
          </h2>
          <span className="rpl-section-meta">
            {loaded ? t('{count} active', { count: routed.length }) : ''}
          </span>
          <button type="button" className="rpl-text-button" onClick={() => onNavigate('incidents')}>{t('All incidents')}</button>
        </div>
        <IncidentTable
          incidents={routed}
          lastViewed={lastViewed}
          loading={!loaded}
          yourOrg={orgStatus}
          onOpen={(inc) => onNavigate('incidents', { incidentId: inc.id })}
          emptyMessage={split
            ? t('Nothing is routed to you right now. An Area that asks for your agency appears here, with its sound.')
            : t('No active incidents. A new Area appears here the moment its first report is clustered.')}
        />
      </section>

      {split && (
        <section className="rpl-board-section" aria-labelledby="rpl-board-others-title">
          <div className="rpl-section-head">
            <h2 className="rpl-section-title" id="rpl-board-others-title">{t('Other organizations’ incidents')}</h2>
            <span className="rpl-section-meta">{t('View only')}</span>
          </div>
          <IncidentTable
            incidents={others}
            lastViewed={lastViewed}
            loading={!loaded}
            yourOrg={orgStatus}
            onOpen={(inc) => onNavigate('incidents', { incidentId: inc.id })}
            emptyMessage={t('No other active incidents in Pasay right now.')}
          />
        </section>
      )}

      <section className="rpl-panel" aria-labelledby="rpl-board-metrics-title">
        <h2 className="rpl-panel-title" id="rpl-board-metrics-title">{t('Response measures · last {days} days', { days: METRICS_DAYS })}</h2>
        <p className="rpl-panel-note">
          {historyLoaded
            ? (metrics.count === 1
                ? t('{count} incident', { count: metrics.count })
                : t('{count} incidents', { count: metrics.count })) +
              (metricsTruncated ? t(' (the latest {HISTORY_LIMIT})', { HISTORY_LIMIT }) : '') +
              t(' · medians over incidents that reached both steps')
            : <span className="rpl-skel rpl-skel-line" style={{ width: 220, height: 12, display: 'inline-block' }} aria-label={t('Loading')} />}
        </p>
        <div className="rpl-measures">
          {[
            { label: t('Report to acknowledged'), m: metrics.reportToVerify, fmt: 'time' },
            { label: t('Acknowledged to on scene'), m: metrics.verifyToScene, fmt: 'time' },
            { label: t('Fire out to report filed'), m: metrics.fireOutToReport, fmt: 'time' },
            { label: t('Reached high confidence'), m: metrics.highConfidence, fmt: 'share' },
            { label: t('False alarms'), m: metrics.falseAlarm, fmt: 'share' },
          ].map(({ label, m, fmt }) => (
            <div className="rpl-measure" key={label}>
              <span className="rpl-measure-label">{label}</span>
              <span className="rpl-measure-value">
                {historyLoaded ? (fmt === 'time' ? formatMinutes(m.median) : formatShare(m.share)) : '·'}
              </span>
              <span className="rpl-measure-foot">
                {m.n === 0 ? t('None yet') : (m.n === 1 ? t('over {n} incident', { n: m.n }) : t('over {n} incidents', { n: m.n }))}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
