import Place from '../Place.jsx';
import StatusChip from '../ui/StatusChip.jsx';
import { riskRadius } from './markers.js';
import { distanceText, fireName, mapsLink, metresBetween } from '../../lib/place.js';
import { WATER_STATUS, checkedOf, waterStatusOf, when } from '../../lib/water.js';
import { t } from '../../i18n/i18n.jsx';

/* A place on the live map, opened by a click (v1.12.47; 20 Nov 2026: "in the
 * admin map, make evacuation, hydrants, and things are interactable";
 * answered "Open a details panel"): what it is and its state, its capacity
 * and contact, how far the nearest live fire is, Google Maps, and Edit for the
 * Admin who manages the map. */

// The live map's kinds, and the map editor's layer for each.
export const POINT_KINDS = {
  hydrant: { get singular() { return t('Hydrant'); }, layer: 'hydrants' },
  water: { get singular() { return t('Body of water'); }, layer: 'water' },
  cistern: { get singular() { return t('Cistern'); }, layer: 'cisterns' },
  shelter: { get singular() { return t('Evacuation site'); }, layer: 'evac' },
  risk: { get singular() { return t('Risk zone'); }, layer: 'risk' },
};

const RISK = {
  low: { get label() { return t('Low'); }, tone: 'neutral' },
  medium: { get label() { return t('Medium'); }, tone: 'warn' },
  high: { get label() { return t('High'); }, tone: 'danger' },
  critical: { get label() { return t('Critical'); }, tone: 'danger' },
};

export function pointOf(kind, row) {
  return kind === 'risk'
    ? { lat: row.centroid_lat, lng: row.centroid_lng }
    : { lat: row.latitude, lng: row.longitude };
}

/* The live fire nearest a point, and how far it is, or null. */
export function nearestFire(point, incidents) {
  if (point.lat == null || point.lng == null) return null;
  let best = null;
  for (const inc of incidents ?? []) {
    if (inc.centroid_lat == null || inc.centroid_lng == null) continue;
    const m = metresBetween(point.lat, point.lng, inc.centroid_lat, inc.centroid_lng);
    if (!best || m < best.m) best = { inc, m };
  }
  return best;
}

function titleOf(kind, row) {
  if (kind === 'hydrant') return row.code || row.address || t('Hydrant');
  if (kind === 'risk') return row.name || t('Risk Area · {barangay}', { barangay: row.barangay });
  return row.name || row.code || row.address || POINT_KINDS[kind].singular;
}

/* A hydrant is verified by a check on the ground in the last 6 months
 * (v1.12.46); the rest are gray on the map. */
function fieldCheck(row) {
  const checked = checkedOf({ ...row, kind: 'hydrant' });
  if (row.verified) return t('Verified · {at}', { at: checked.at ?? '—' });
  return row.ground_truth_at
    ? t('Not verified · last checked {at}', { at: checked.at ?? '—' })
    : t('Not verified · never checked on the ground');
}

function factsOf(kind, row) {
  const facts = [];
  const add = (term, value) => { if (value != null && value !== '') facts.push([term, value]); };
  if (kind === 'hydrant' || kind === 'water' || kind === 'cistern') {
    const status = waterStatusOf({ ...row, kind });
    add(t('Status'), <StatusChip label={status.label} tone={status.tone} />);
  }
  switch (kind) {
    case 'hydrant':
      add(t('Field check'), fieldCheck(row));
      add(t('BFP status'), WATER_STATUS[row.bfp_status]?.label);
      add(t('Field note'), row.ground_truth_notes);
      break;
    case 'water':
      add(t('Type'), row.water_type);
      add(t('Record updated'), when(row.updated_at));
      break;
    case 'cistern':
      add(t('Capacity'), row.capacity_liters != null
        ? t('{amount} litres', { amount: Number(row.capacity_liters).toLocaleString('en-PH') })
        : t('Not recorded'));
      add(t('Record updated'), when(row.updated_at));
      break;
    case 'shelter':
      add(t('Capacity'), row.capacity != null
        ? t('{count} people', { count: Number(row.capacity).toLocaleString('en-PH') })
        : t('Not recorded'));
      add(t('Contact'), row.contact_info || t('Not recorded'));
      if (row.outside_pasay) add(t('City'), t('{city}, outside Pasay', { city: row.city || '—' }));
      break;
    case 'risk': {
      const level = RISK[row.risk_level];
      add(t('Risk level'), level ? <StatusChip label={level.label} tone={level.tone} /> : null);
      add(t('Barangay'), row.barangay);
      add(t('Radius'), t('{metres} m', { metres: Math.round(riskRadius(row)) }));
      break;
    }
    default:
      break;
  }
  add(t('Description'), row.description);
  const p = pointOf(kind, row);
  add(t('Location'), <Place lat={p.lat} lng={p.lng} address={row.address || null} stacked />);
  return facts;
}

export default function PointDetail({ kind, row, incidents, onClose, onOpenIncident, onEdit }) {
  const p = pointOf(kind, row);
  const near = nearestFire(p, incidents);
  const facts = factsOf(kind, row);
  return (
    <aside className="rpl-map-panel rpl-point-panel" aria-labelledby="rpl-point-title">
      <div className="rpl-detail-head">
        <div>
          <p className="rpl-eyebrow">{POINT_KINDS[kind].singular}</p>
          <h2 className="rpl-detail-title" id="rpl-point-title">{titleOf(kind, row)}</h2>
        </div>
        <button type="button" className="rpl-icon-button" onClick={onClose} aria-label={t('Close details')}>
          <span aria-hidden="true">✕</span>
        </button>
      </div>
      <dl className="rpl-facts">
        {facts.map(([term, value]) => (
          <div className="rpl-fact" key={term}><dt>{term}</dt><dd>{value}</dd></div>
        ))}
        <div className="rpl-fact">
          <dt>{t('Nearest live fire')}</dt>
          <dd>
            {near ? (
              <>
                {`${distanceText(near.m)} · `}
                <button type="button" className="rpl-text-button rpl-text-button--inline" onClick={() => onOpenIncident(near.inc.id)}>
                  {fireName(near.inc.place_line || near.inc.designation)}
                </button>
              </>
            ) : t('No live fire now')}
          </dd>
        </div>
      </dl>
      <div className="rpl-point-actions">
        {p.lat != null && p.lng != null && (
          <a className="rpl-button rpl-button--secondary" href={mapsLink(p.lat, p.lng)} target="_blank" rel="noopener noreferrer">
            {t('Open in Google Maps')}
          </a>
        )}
        {onEdit && (
          <button type="button" className="rpl-button rpl-button--primary" onClick={onEdit}>{t('Edit')}</button>
        )}
      </div>
    </aside>
  );
}
