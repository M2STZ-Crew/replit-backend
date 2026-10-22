import { useEffect, useState } from 'react';

import { api } from '../../api/client.js';
import { statusOf } from '../../lib/status.js';
import { ConfirmDialog, PageHeader, StatePanel } from '../ui/index.js';
import AreaMap from './AreaMap.jsx';
import { agenciesOf, confidenceOf } from './IncidentTable.jsx';

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
    ['Reports', `${area.report_count} · first at ${CLOCK.format(new Date(area.reported_at))}`],
    ['Status', statusOf(area.status).label],
    ['Requested agencies', agenciesOf(area)],
    ['Confidence', confidenceOf(area)],
  ] : [];
  return (
    <section className="ad-panel">
      <h2 className="ad-decision-title">{title}</h2>
      {area ? (
        <dl className="ad-facts ad-facts--wide">
          {rows.map(([t, v]) => (
            <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      ) : (
        <p className="ad-decision-body">Loading…</p>
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
      .catch((e) => { if (alive) setError(e.message || 'These Areas could not be loaded.'); });
    return () => { alive = false; };
  }, [overlap]);

  async function keepSeparate() {
    setBusy(true);
    setError(null);
    try {
      await api.overlapKeepSeparate(overlap.id);
      onDone(`${nameA} and ${nameB} kept separate`);
    } catch (e) {
      setError(e.message || 'The decision was not saved.');
      setBusy(false);
    }
  }

  async function merge() {
    await api.overlapMerge(overlap.id);
    onDone(`${nameB} merged into ${nameA}`);
  }

  const minutes = Math.floor(left / 60);
  const seconds = String(left % 60).padStart(2, '0');
  const expired = left === 0;

  return (
    <div className="ad-page">
      <button type="button" className="ad-text-button ad-back" onClick={onBack}>← All incidents</button>
      <PageHeader
        eyebrow="Overlap"
        title="Are these the same fire?"
        description={`${nameA} and ${nameB} are ${Math.round(overlap.distance_m)} m apart. Merge them if they are one fire, or keep them separate.`}
      />

      {error && <p className="ad-inline-error" role="alert">{error}</p>}
      {!a && !b && !error && <StatePanel kind="loading" title="Loading both Areas…" />}

      <AreaMap
        height={240}
        areas={[
          { lat: a?.centroid_lat, lng: a?.centroid_lng, label: nameA },
          { lat: b?.centroid_lat, lng: b?.centroid_lng, label: nameB },
        ]}
      />

      <div className="ad-overlap-sides">
        <Side title={`${nameA} · keeps its number`} area={a} />
        <Side title={`${nameB} · would close as merged`} area={b} />
      </div>

      <div className="ad-overlap-foot">
        <p className="ad-decision-body">
          Merging moves {nameB}’s reports into {nameA} and can’t be undone. Keeping them separate
          leaves both Areas as they are.{' '}
          <strong className={expired ? 'ad-expired' : undefined}>
            {expired
              ? 'The time to decide has passed; they stay separate.'
              : `Decide within ${minutes > 0 ? `${minutes} min ` : ''}${seconds} s, or they stay separate.`}
          </strong>
        </p>
        <button type="button" className="ad-button ad-button--secondary" onClick={keepSeparate} disabled={busy || expired}>
          Keep separate
        </button>
        <button type="button" className="ad-button ad-button--primary" onClick={() => setConfirming(true)} disabled={busy || expired || !b}>
          Merge into {nameA}
        </button>
      </div>

      <ConfirmDialog
        open={confirming}
        eyebrow={`Overlap · ${nameA} and ${nameB}`}
        title={`Merge ${nameB} into ${nameA}?`}
        description={`${nameB}’s ${b?.report_count ?? ''} report${b?.report_count === 1 ? '' : 's'} join ${nameA}. ${nameB} ends as Merged for every organisation. This can’t be undone.`}
        confirmLabel="Merge areas"
        destructive
        onClose={() => setConfirming(false)}
        onConfirm={merge}
      />
    </div>
  );
}
