import { useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import StatisticsPanel from '../components/stats/StatisticsPanel.jsx';
import Icon from '../components/ui/Icon.jsx';
import { PageHeader } from '../components/ui/index.js';
import { useLiveFeed, useSurfaceVisit } from '../live/LiveFeed.jsx';
import {
  PERM, acknowledgedByUs, actsOn, can, splitsIncidents, variantLabel,
} from '../lib/access.js';
import { t } from '../i18n/i18n.jsx';

/* Dashboard (REPLIT (MAIN) 10 · A20 865:1310; PRD v13 §4.6.2, §4.14): this
 * organisation's work first, one click from where it is answered, then how
 * responses are going.
 *
 * v1.12.50 (22 Nov 2026):
 *  - "Tanggaling yung Active Incidents na panel", answered "All incident
 *    tables": no Admin's Dashboard lists incidents. A new one still rings in
 *    the banner on top, and the Incidents card opens the list.
 *  - "Palitan yong name ng 'To Acknowledge' to 'Incidents'", answered
 *    "Active + to acknowledge": the active fires routed to this Admin, and
 *    under that how many it still has to acknowledge; the "Active, routed to
 *    you" card is gone.
 *  - Statistics replaces Response measures (components/stats).
 *
 * The availability strip (A72) is not drawn: the server stores no AFK state
 * yet. */

function QueueCard({ icon, count, label, note, onOpen, loading, attention = false }) {
  const read = loading
    ? t('{label}, loading', { label })
    : [t('{count} {label}', { count, label }), note].filter(Boolean).join(', ');
  return (
    <button
      type="button"
      className={`rpl-queue${attention ? ' is-attention' : ''}`}
      onClick={onOpen}
      aria-label={read}
    >
      <span className={`rpl-queue-plate${attention ? ' is-attention' : ''}`} aria-hidden="true">
        <Icon name={icon} />
      </span>
      <span className="rpl-queue-text" aria-hidden="true">
        <span className="rpl-queue-count">
          {loading ? <span className="rpl-skel rpl-skel-count" /> : count}
        </span>
        <span className="rpl-queue-label">{label}</span>
        {note !== undefined && (
          <span className={`rpl-queue-note${attention ? ' is-attention' : ''}`}>{loading ? ' ' : note}</span>
        )}
      </span>
      <Icon name="chevron-right" size={18} />
    </button>
  );
}

export default function SituationBoard({ onNavigate }) {
  // Live incidents come from the console-wide feed, so the card moves with
  // the same poll that drives the badges and sounds.
  const { incidents, loaded } = useLiveFeed();
  const { org, console: access } = useConsole();
  useSurfaceVisit('dashboard');
  const [queues, setQueues] = useState(null);

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
  const routed = incidents.filter((inc) => actsOn(access, inc));
  const toAcknowledge = routed.filter((inc) => !acknowledgedByUs(access, inc)).length;
  const incidentsNote = toAcknowledge > 0
    ? t('{count} to acknowledge', { count: toAcknowledge })
    : routed.length ? t('All acknowledged') : t('None active');

  const others = [
    answersAlarms && { key: 'requests', icon: 'requests', label: t('Alarm Escalations'), count: queues?.requests },
    reviewsAffiliates && { key: 'affiliates', icon: 'organization', label: t('Affiliate requests'), count: queues?.affiliates },
    reviewsIds && { key: 'idreview', icon: 'verification', label: t('ID reviews'), count: queues?.ids },
  ].filter((q) => q && (queues == null || q.count != null));

  const eyebrow = org?.name ? `${org.name} · ${variantLabel(access)}` : t('Operations');

  return (
    <div className="rpl-page rpl-board">
      <PageHeader
        eyebrow={eyebrow}
        title={t('Dashboard')}
        description={t('Your work first, then how responses are going.')}
      />

      <section aria-label={t('Your queues')} className="rpl-queues">
        <QueueCard
          icon="incidents"
          label={t('Incidents')}
          count={routed.length}
          note={incidentsNote}
          loading={!loaded}
          // The one queue that cannot wait takes the coral edge (A20).
          attention={loaded && toAcknowledge > 0}
          onOpen={() => onNavigate('incidents', split ? { tab: 'routed' } : {})}
        />
        {others.map((q) => (
          <QueueCard
            key={q.key}
            icon={q.icon}
            label={q.label}
            count={q.count ?? 0}
            loading={queues == null}
            onOpen={() => onNavigate(q.key)}
          />
        ))}
      </section>

      <StatisticsPanel access={access} />
    </div>
  );
}
