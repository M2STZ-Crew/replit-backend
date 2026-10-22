import { AGENCY_LABEL, ago } from '../../lib/status.js';
import { RAIL_BELOW, useMedia } from '../../lib/useMedia.js';
import Icon from '../ui/Icon.jsx';
import LifecycleChip from './LifecycleChip.jsx';

/* The incident list (REPLIT (MAIN) 04 · Incident row; PRD v13 §4.6.2, §4.14):
 * the Area and where it is, its status, the agencies its reporters asked for,
 * confidence, how many reports, and when it last changed. Unread — reported
 * since this surface was last viewed — is a coral dot and a coral edge.
 *
 * The design's "Your org" column (Routed to you / View only) waits on the
 * server routing Areas per Admin organisation; today every Admin may act on
 * every Area, so the column would say the same thing on every row and is not
 * drawn. The address line is the degrees until the server stores
 * resolved_address (PRD v13 §4.10).
 *
 * Below 1280 px, beside the rail, the rows stack as cards (A85). */

const BAND = { high: 'High', medium: 'Medium', low: 'Low' };

const LOADED = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });

export function degrees(lat, lng) {
  if (lat == null || lng == null) return 'Location unknown';
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lng).toFixed(4)}° ${lng >= 0 ? 'E' : 'W'}`;
}

export function agenciesOf(inc) {
  const list = (inc.requested_agencies ?? []).map((a) => AGENCY_LABEL[a] ?? a);
  return list.length ? list.join(' · ') : 'Not stated';
}

export function confidenceOf(inc) {
  const band = BAND[inc.confidence_band] ?? '—';
  return `${band} · ${(inc.confidence_score ?? 0).toFixed(2)}`;
}

function IncidentCards({ incidents, isNew, selectedId, onOpen, loading, emptyMessage, staleAt }) {
  if (incidents.length === 0) {
    return <p className="ad-empty-line">{loading ? 'Loading incidents…' : emptyMessage}</p>;
  }
  return (
    <ul className={`ad-incident-cards${staleAt ? ' is-stale' : ''}`} aria-busy={loading || undefined}>
      {incidents.map((inc) => {
        const unread = isNew(inc);
        const stats = [
          ['Reports', inc.report_count],
          ['Confidence', confidenceOf(inc)],
          [staleAt ? 'Last loaded' : 'Updated', staleAt ? LOADED.format(new Date(staleAt)) : ago(inc.updated_at ?? inc.reported_at)],
        ];
        return (
          <li key={inc.id} className={`ad-incident-card${unread ? ' is-unread' : ''}${inc.id === selectedId ? ' is-selected' : ''}`}>
            <LifecycleChip status={inc.status} />
            <div className="ad-cell-resource">
              <span className="ad-plate ad-plate--fire" aria-hidden="true"><Icon name="flame" /></span>
              <span className="ad-cell-text">
                <span className="ad-cell-title">
                  {inc.designation}
                  {unread && <span className="web-sr-only">, new since you last looked</span>}
                </span>
                <span className="ad-cell-meta">{degrees(inc.centroid_lat, inc.centroid_lng)} · {agenciesOf(inc)}</span>
              </span>
            </div>
            <dl className="ad-incident-card-stats">
              {stats.map(([t, v]) => (
                <div key={t}><dt>{t}</dt><dd>{v}</dd></div>
              ))}
            </dl>
            <button type="button" className="ad-button ad-button--secondary" onClick={() => onOpen(inc)}>
              Open incident<span className="web-sr-only"> {inc.designation}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export default function IncidentTable({
  incidents, lastViewed, selectedId, onOpen, loading = false, emptyMessage, staleAt = null,
}) {
  const stacked = useMedia(RAIL_BELOW);
  const lastMs = lastViewed ? new Date(lastViewed).getTime() : Infinity;
  const isNew = (inc) => new Date(inc.reported_at).getTime() > lastMs;

  if (stacked) {
    return (
      <IncidentCards
        incidents={incidents}
        isNew={isNew}
        selectedId={selectedId}
        onOpen={onOpen}
        loading={loading}
        emptyMessage={emptyMessage}
        staleAt={staleAt}
      />
    );
  }

  return (
    <div className={`web-table-wrap${staleAt ? ' is-stale' : ''}`}>
      <table className="web-table ad-incidents" aria-busy={loading || undefined}>
        <thead>
          <tr>
            <th scope="col">Area</th>
            <th scope="col">Status</th>
            <th scope="col">Requested</th>
            <th scope="col">Confidence</th>
            <th scope="col">Reports</th>
            <th scope="col">Updated</th>
            <th scope="col"><span className="web-sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((inc) => {
            const unread = isNew(inc);
            const selected = inc.id === selectedId;
            return (
              <tr
                key={inc.id}
                className={`web-table-row${selected ? ' is-selected' : ''}${unread ? ' is-unread' : ''}`}
              >
                <th scope="row">
                  <span className="ad-cell-area">
                    <span className={`ad-unread-dot${unread ? ' is-on' : ''}`} aria-hidden="true" />
                    <span className="ad-cell-text">
                      <span className="ad-cell-title">
                        {inc.designation}
                        {unread && <span className="web-sr-only">, new since you last looked</span>}
                      </span>
                      <span className="ad-cell-meta">{degrees(inc.centroid_lat, inc.centroid_lng)}</span>
                    </span>
                  </span>
                </th>
                <td><LifecycleChip status={inc.status} /></td>
                <td>{agenciesOf(inc)}</td>
                <td>{confidenceOf(inc)}</td>
                <td className="ad-cell-strong">{inc.report_count}</td>
                <td className="ad-cell-quiet">
                  {staleAt ? `Last loaded ${LOADED.format(new Date(staleAt))}` : ago(inc.updated_at ?? inc.reported_at)}
                </td>
                <td className="web-table-action-cell">
                  <button
                    type="button"
                    className="web-table-row-action"
                    onClick={() => onOpen(inc)}
                    aria-current={selected ? 'true' : undefined}
                  >
                    Open<span className="web-sr-only"> {inc.designation}</span>
                  </button>
                </td>
              </tr>
            );
          })}
          {incidents.length === 0 && (
            <tr>
              <td className="web-table-empty" colSpan={7}>
                {loading ? 'Loading incidents…' : emptyMessage}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
