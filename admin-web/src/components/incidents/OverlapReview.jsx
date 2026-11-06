import { useEffect, useState } from 'react';

import { api } from '../../api/client.js';
import { statusOf } from '../../lib/status.js';
import { ConfirmDialog, PageHeader, StatePanel } from '../ui/index.js';
import AreaMap from './AreaMap.jsx';
import { agenciesOf, confidenceOf } from './IncidentTable.jsx';
import Skeleton from '../ui/Skeleton.jsx';
import { t } from '../../i18n/i18n.jsx';

/* Two Areas that grew within range of each other (REPLIT (MAIN) 10 · A27
 * 868:3155, A27b 868:3356; PRD v13 §4.3): are they one fire? Merge moves the
 * newer Area's reports into the older one and closes the newer as Merged;
 * Keep separate leaves both. The server fixes the direction — the second
 * Area is the one absorbed — and gives a dispatcher 120 seconds; after that
 * the two stay separate on their own. */

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });

function useSecondsLeft(expiresAt) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - now) / 1000));
}

function Side({ title, area }) {
  const rows = area ? [
    [t('Reports'), t('{report_count} · first at {time}', { report_count: area.report_count, time: CLOCK.format(new Date(area.reported_at)) })],
    [t('Status'), statusOf(area.status).label],
    [t('Requested agencies'), agenciesOf(area)],
    [t('Confidence'), confidenceOf(area)],
  ] : [];
  return (
    <section className="rpl-panel">
      <h2 className="rpl-decision-title">{title}</h2>
      {area ? (
        <dl className="rpl-facts rpl-facts--wide">
          {rows.map(([t, v]) => (
            <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      ) : (
        <>
          <p className="web-sr-only" role="status">{t('Loading…')}</p>
          <Skeleton shape="lines" rows={4} />
        </>
      )}
    </section>
  );
}

export default function OverlapReview({ overlap, onDone, onBack }) {
  const [a, setA] = useState(null);
  const [b, setB] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const left = useSecondsLeft(overlap.expires_at);
  const nameA = overlap.area_a_designation;
  const nameB = overlap.area_b_designation;

  useEffect(() => {
    let alive = true;
    Promise.all([api.incident(overlap.area_a_id), api.incident(overlap.area_b_id)])
      .then(([x, y]) => { if (alive) { setA(x); setB(y); } })
      .catch((e) => { if (alive) setError(e.message || t('These Areas could not be loaded.')); });
    return () => { alive = false; };
  }, [overlap]);

  async function keepSeparate() {
    setBusy(true);
    setError(null);
    try {
      await api.overlapKeepSeparate(overlap.id);
      onDone(t('{nameA} and {nameB} kept separate', { nameA, nameB }));
    } catch (e) {
      setError(e.message || t('The decision was not saved.'));
      setBusy(false);
    }
  }

  async function merge() {
    await api.overlapMerge(overlap.id);
    onDone(t('{nameB} merged into {nameA}', { nameB, nameA }));
  }

  const minutes = Math.floor(left / 60);
  const seconds = String(left % 60).padStart(2, '0');
  const expired = left === 0;

  return (
    <div className="rpl-page">
      <button type="button" className="rpl-text-button rpl-back" onClick={onBack}>{t('← All incidents')}</button>
      <PageHeader
        eyebrow={t('Overlap')}
        title={t('Are these the same fire?')}
        description={t('{nameA} and {nameB} are {round} m apart. Merge them if they are one fire, or keep them separate.', { nameA, nameB, round: Math.round(overlap.distance_m) })}
      />

      {error && <p className="rpl-inline-error" role="alert">{error}</p>}
      {!a && !b && !error && <StatePanel kind="loading" skeleton="detail" rows={2} title={t('Loading both Areas…')} />}

      <AreaMap
        height={240}
        areas={[
          { lat: a?.centroid_lat, lng: a?.centroid_lng, label: nameA },
          { lat: b?.centroid_lat, lng: b?.centroid_lng, label: nameB },
        ]}
      />

      <div className="rpl-overlap-sides">
        <Side title={t('{nameA} · keeps its number', { nameA })} area={a} />
        <Side title={t('{nameB} · would close as merged', { nameB })} area={b} />
      </div>

      <div className="rpl-overlap-foot">
        <p className="rpl-decision-body">{t('Merging moves {nameB}’s reports into {nameA} and can’t be undone. Keeping them separate leaves both Areas as they are.', { nameA, nameB })}{' '}
          <strong className={expired ? 'rpl-expired' : undefined}>
            {expired
              ? t('The time to decide has passed; they stay separate.')
              : (minutes > 0
                ? t('Decide within {minutes} min {seconds} s, or they stay separate.', { minutes, seconds })
                : t('Decide within {seconds} s, or they stay separate.', { seconds }))}
          </strong>
        </p>
        <button type="button" className="rpl-button rpl-button--secondary" onClick={keepSeparate} disabled={busy || expired}>{t('Keep separate')}</button>
        <button type="button" className="rpl-button rpl-button--primary" onClick={() => setConfirming(true)} disabled={busy || expired || !b}>{t('Merge into {nameA}', { nameA })}
        </button>
      </div>

      <ConfirmDialog
        open={confirming}
        eyebrow={t('Overlap · {nameA} and {nameB}', { nameA, nameB })}
        title={t('Merge {nameB} into {nameA}?', { nameB, nameA })}
        description={b?.report_count === 1
          ? t('{nameB}’s {count} report joins {nameA}. {nameB} ends as Merged for every organization. This can’t be undone.', { nameB, nameA, count: b?.report_count ?? '' })
          : t('{nameB}’s {count} reports join {nameA}. {nameB} ends as Merged for every organization. This can’t be undone.', { nameB, nameA, count: b?.report_count ?? '' })}
        confirmLabel={t('Merge areas')}
        destructive
        onClose={() => setConfirming(false)}
        onConfirm={merge}
      />
    </div>
  );
}
