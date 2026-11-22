import { useEffect, useId, useState } from 'react';

import { api } from '../../api/client.js';
import { splitsIncidents } from '../../lib/access.js';
import {
  changeInCount, changeInMinutes, changeInShare, formatMinutes, formatShare, shortDate,
} from '../../lib/metrics.js';
import { ALARM_LEVEL, FIRE_TYPE, alarmLabel } from '../../lib/status.js';
import { t } from '../../i18n/i18n.jsx';
import StatePanel from '../ui/StatePanel.jsx';
import BarTable from './BarTable.jsx';
import FiresPerDay, { FiresPerDayTable } from './FiresPerDay.jsx';

/* The Dashboard's Statistics (v1.12.50; 22 Nov 2026: "Maglagay ng Statistic
 * Panel ( or gawing Statistic Dashboard nalang yung 'Response measures' )";
 * answered "Statistics dashboard"): 7, 30 or 90 days, and for an
 * organization's Admin its own incidents or all of them, in one row over
 * everything they scope. Changing either keeps the last drawing, dimmed, until
 * the new one is in. */

const PERIODS = [
  { days: 7, get short() { return t('7d'); }, get long() { return t('Last 7 days'); } },
  { days: 30, get short() { return t('30d'); }, get long() { return t('Last 30 days'); } },
  { days: 90, get short() { return t('90d'); }, get long() { return t('Last 90 days'); } },
];
const REFRESH_MS = 60_000;
const LADDER = Object.keys(ALARM_LEVEL);

function Segment({ label, options, value, onChange }) {
  return (
    <div className="rpl-stat-segment" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          className={`rpl-stat-choice${o.key === value ? ' is-selected' : ''}`}
          aria-pressed={o.key === value}
          aria-label={o.name}
          title={o.name}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Change({ change, days }) {
  const period = t('vs previous {days} days', { days });
  if (!change) return <span className="rpl-stat-change is-none">{t('No earlier data to compare')}</span>;
  if (!change.direction) return <span className="rpl-stat-change">{t('No change')} <span className="rpl-stat-period">{period}</span></span>;
  const tone = change.better == null ? '' : change.better ? ' is-better' : ' is-worse';
  return (
    <span className={`rpl-stat-change${tone}`}>
      <span className={`rpl-stat-arrow${change.direction > 0 ? ' is-up' : ''}`} aria-hidden="true" />
      <span className="rpl-stat-by">{change.text}</span>
      {change.better != null && <span className="web-sr-only">{change.better ? t('better') : t('worse')}</span>}
      <span className="rpl-stat-period">{period}</span>
    </span>
  );
}

function Tile({ value, label, note, change, days }) {
  return (
    <div className="rpl-stat">
      <dt className="rpl-stat-label">{label}</dt>
      <dd className="rpl-stat-value">{value}</dd>
      <dd className="rpl-stat-note">{note}</dd>
      <dd className="rpl-stat-foot"><Change change={change} days={days} /></dd>
    </div>
  );
}

const over = (n) => (n === 0 ? t('None yet')
  : n === 1 ? t('over {n} incident', { n }) : t('over {n} incidents', { n }));

function Figure({ title, action, children }) {
  const id = useId();
  return (
    <figure className="rpl-figure" aria-labelledby={id}>
      <figcaption className="rpl-figure-head">
        <h3 className="rpl-figure-title" id={id}>{title}</h3>
        {action}
      </figcaption>
      {children}
    </figure>
  );
}

function Numbers({ data }) {
  const [asTable, setAsTable] = useState(false);
  const { days, fires } = data;
  const ack = data.minutes_to_acknowledge;
  const scene = data.minutes_to_scene;
  const wrong = data.false_alarms;
  const own = data.scope === 'org';

  const barangays = data.barangays.map((b) => ({ key: b.pcode, name: b.name, detail: b.city, count: b.count }));
  const levels = data.alarm_levels.map(({ key, count }) => ({
    key: key ?? 'none',
    name: key ? alarmLabel(key) : t('No alarm yet'),
    count,
    color: key ? `--chart-step-${LADDER.indexOf(key) + 1}` : '--chart-rest',
  }));
  const types = data.fire_types.map(({ key, count }) => ({
    key: key ?? 'none',
    name: key ? FIRE_TYPE[key] ?? key : t('Not said yet'),
    count,
    color: key ? null : '--chart-rest',
  }));
  const none = t('No fires in this period.');

  return (
    <>
      <dl className="rpl-stat-tiles">
        <Tile
          days={days}
          value={formatMinutes(ack.value)}
          label={own ? t('Report to your acknowledgement') : t('Report to acknowledged')}
          note={over(ack.n)}
          change={changeInMinutes(ack.value, ack.previous)}
        />
        <Tile
          days={days}
          value={formatMinutes(scene.value)}
          label={t('Acknowledged to on scene')}
          note={over(scene.n)}
          change={changeInMinutes(scene.value, scene.previous)}
        />
        <Tile
          days={days}
          value={fires.value}
          label={t('Fires')}
          note={t('False alarms not counted')}
          change={changeInCount(fires.value, fires.previous)}
        />
        <Tile
          days={days}
          value={formatShare(wrong.value)}
          label={t('False alarms')}
          note={wrong.n ? t('of {n} decided', { n: wrong.n }) : t('None decided yet')}
          change={changeInShare(wrong.value, wrong.previous)}
        />
      </dl>

      <div className="rpl-figure-grid">
        <Figure
          title={t('Fires per day')}
          action={(
            <button type="button" className="rpl-text-button" onClick={() => setAsTable((v) => !v)}>
              {asTable ? t('Show chart') : t('Show table')}
            </button>
          )}
        >
          {asTable
            ? <FiresPerDayTable days={data.per_day} since={data.records_since} />
            : <FiresPerDay days={data.per_day} since={data.records_since} />}
        </Figure>

        <Figure title={t('Top barangays')}>
          <BarTable
            caption={t('Top barangays')}
            nameHeading={t('Barangay')}
            rows={barangays}
            total={barangays.length ? fires.value : 0}
            empty={fires.value ? t('No fire here has a barangay.') : none}
          />
          {barangays.length > 0 && data.without_barangay > 0 && (
            <p className="rpl-figure-note">{t('{count} outside a known barangay', { count: data.without_barangay })}</p>
          )}
        </Figure>

        <Figure title={t('Alarm levels')}>
          <BarTable caption={t('Alarm levels')} nameHeading={t('Alarm level')} rows={levels} total={fires.value} empty={none} />
        </Figure>

        <Figure title={t('Fire types')}>
          <BarTable caption={t('Fire types')} nameHeading={t('Fire type')} rows={types} total={fires.value} empty={none} />
        </Figure>
      </div>
    </>
  );
}

function Waiting() {
  return (
    <div className="rpl-skeleton rpl-stat-waiting" role="status">
      <span className="web-sr-only">{t('Loading statistics…')}</span>
      <div className="rpl-stat-tiles">
        {[0, 1, 2, 3].map((i) => <span key={i} className="rpl-skel rpl-skel-stat" aria-hidden="true" />)}
      </div>
      <div className="rpl-figure-grid">
        {[0, 1, 2, 3].map((i) => <span key={i} className="rpl-skel rpl-skel-chart" aria-hidden="true" />)}
      </div>
    </div>
  );
}

export default function StatisticsPanel({ access }) {
  const id = useId();
  const switches = splitsIncidents(access);
  const [days, setDays] = useState(30);
  const [scope, setScope] = useState(switches ? 'org' : 'all');
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let left = false;
    let asked = 0;
    async function load() {
      asked += 1;
      const mine = asked;
      try {
        const next = await api.incidentStatistics({ days, scope });
        if (left || mine !== asked) return;
        if (!Array.isArray(next?.per_day)) throw new Error('not statistics');
        setData(next);
        setFailed(false);
      } catch {
        if (!left && mine === asked) setFailed(true);
      }
    }
    setFailed(false);
    load();
    const timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') load();
    }, REFRESH_MS);
    return () => {
      left = true;
      clearInterval(timer);
    };
  }, [days, scope, attempt]);

  // The server answers "all" for who acts on every incident.
  const current = data && data.days === days && (!switches || data.scope === scope) ? data : null;
  const drawn = current ?? (failed ? null : data);

  return (
    <section className="rpl-stats" aria-labelledby={id}>
      <div className="rpl-stats-head">
        <h2 className="rpl-stats-title" id={id}>{t('Statistics')}</h2>
        <Segment
          label={t('Period')}
          value={days}
          onChange={setDays}
          options={PERIODS.map((p) => ({ key: p.days, label: p.short, name: p.long }))}
        />
        {switches && (
          <Segment
            label={t('Whose incidents')}
            value={scope}
            onChange={setScope}
            options={[
              { key: 'org', label: t('Your organization'), name: t('Your organization') },
              { key: 'all', label: t('All incidents'), name: t('All incidents') },
            ]}
          />
        )}
      </div>

      {drawn && !drawn.comparable && drawn.records_since && (
        <p className="rpl-stats-note">
          {t('Records start {date}, so there is no full period before this one to compare with yet.', { date: shortDate(drawn.records_since) })}
        </p>
      )}

      {failed && current && (
        <p className="rpl-stats-stale" role="status">
          {t('The statistics couldn’t update. These are the last ones loaded.')}{' '}
          <button type="button" className="rpl-text-button" onClick={() => setAttempt((n) => n + 1)}>{t('Try again')}</button>
        </p>
      )}

      {drawn ? (
        <div className={`rpl-stats-body${current ? '' : ' is-stale'}`} aria-busy={!current || undefined}>
          <Numbers data={drawn} />
        </div>
      ) : failed ? (
        <StatePanel
          kind="error"
          title={t('The statistics couldn’t load')}
          description={t('Check your connection, then try again.')}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      ) : <Waiting />}
    </section>
  );
}
