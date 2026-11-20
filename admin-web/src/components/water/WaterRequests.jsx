import { useState } from 'react';

import { api } from '../../api/client.js';
import Place from '../Place.jsx';
import { ConfirmDialog, EmptyState, StatePanel, StatusChip } from '../ui/index.js';
import { t } from '../../i18n/i18n.jsx';

/* Coordinators' water changes awaiting an Admin (v1.12.43; 19 Nov 2026:
 * "Status at once, rest approved"). A Fire Volunteer or BFP coordinator adds,
 * changes or switches off a water source from the app; approving applies it to
 * every map, and either answer is sent to the coordinator. A hydrant's status
 * never waits here: it is on the map the moment it is set. */

export const WATER_REQUEST_LAYERS = ['hydrant', 'bodies_of_water', 'underground_cistern'];

const LAYER = {
  hydrant: { get label() { return t('Hydrant'); }, kind: 'hydrant' },
  bodies_of_water: { get label() { return t('Body of water'); }, kind: 'water' },
  underground_cistern: { get label() { return t('Cistern'); }, kind: 'cistern' },
};

const FIELD = {
  get name() { return t('Name'); },
  get code() { return t('Code'); },
  get address() { return t('Address'); },
  get description() { return t('Description'); },
  get water_type() { return t('Type'); },
  get capacity_liters() { return t('Capacity (litres)'); },
  get bfp_status() { return t('Status'); },
  get status() { return t('Status'); },
  get is_accessible() { return t('Accessible'); },
};

const WHEN = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
});

/* "Switch off" is a change that only sets is_active false: said as such. */
export function whatOf(req) {
  const data = req.proposed_data || {};
  if (req.operation === 'update' && Object.keys(data).length === 1 && data.is_active === false) {
    return { label: t('Switch off'), tone: 'warn' };
  }
  if (req.operation === 'create') return { label: t('New'), tone: 'info' };
  if (req.operation === 'delete') return { label: t('Remove'), tone: 'danger' };
  return { label: t('Change'), tone: 'accent' };
}

function valueOf(key, value) {
  if (typeof value === 'boolean') return value ? t('Yes') : t('No');
  if (key === 'capacity_liters' && typeof value === 'number') return value.toLocaleString('en-PH');
  return String(value);
}

function Request({ req, target, onDecide }) {
  const layer = LAYER[req.layer_type] ?? { label: req.layer_type };
  const what = whatOf(req);
  const data = req.proposed_data || {};
  const hasPoint = typeof data.latitude === 'number' && typeof data.longitude === 'number';
  // With a point, Location already says the address.
  const fields = Object.entries(data).filter(([k]) => FIELD[k] !== undefined && data[k] !== null && data[k] !== ''
    && !(hasPoint && k === 'address'));
  const who = [req.requested_by_name, req.organization_name].filter(Boolean).join(' · ') || t('A coordinator');
  return (
    <li className="rpl-water-request">
      <div className="rpl-strike-head">
        <span className="rpl-cell-text">
          <span className="rpl-cell-title">{layer.label}{target ? ` · ${target}` : ''}</span>
          <span className="rpl-cell-meta">{who} · {WHEN.format(new Date(req.created_at))}</span>
        </span>
        <StatusChip label={what.label} tone={what.tone} />
      </div>
      {req.reason && <p className="rpl-strike-reason">“{req.reason}”</p>}
      {(fields.length > 0 || hasPoint) && (
        <dl className="rpl-facts rpl-facts--wide">
          {hasPoint && (
            <div className="rpl-fact"><dt>{t('Location')}</dt><dd><Place lat={data.latitude} lng={data.longitude} address={data.address} stacked /></dd></div>
          )}
          {fields.map(([key, value]) => (
            <div className="rpl-fact" key={key}><dt>{FIELD[key]}</dt><dd>{valueOf(key, value)}</dd></div>
          ))}
        </dl>
      )}
      <div className="rpl-strike-actions">
        <button type="button" className="rpl-button rpl-button--secondary" onClick={() => onDecide(req, 'reject')}>{t('Reject')}</button>
        <button type="button" className="rpl-button rpl-button--primary" onClick={() => onDecide(req, 'approve')}>{t('Approve')}</button>
      </div>
    </li>
  );
}

/* `requests` are the pending water ones; `targetName(req)` names the source a
 * change concerns; `onDecided(message)` reloads after an answer. */
export default function WaterRequests({ requests, loading, error, onRetry, targetName, onDecided }) {
  const [deciding, setDeciding] = useState(null);
  const [note, setNote] = useState('');

  function decide(req, kind) {
    setNote('');
    setDeciding({ req, kind });
  }

  async function confirm() {
    const { req, kind } = deciding;
    const text = note.trim() || null;
    if (kind === 'approve') await api.approveMapLayerRequest(req.id, text);
    else await api.rejectMapLayerRequest(req.id, text);
    setDeciding(null);
    onDecided(kind === 'approve'
      ? t('Approved. It is on every map now, and the coordinator was told.')
      : t('Rejected. The coordinator was told.'));
  }

  if (loading) return <StatePanel kind="loading" skeleton="cards" rows={2} title={t('Loading requests…')} busy />;
  if (error) return <StatePanel kind="error" title={t('The requests couldn’t load')} description={error} onRetry={onRetry} />;
  if (requests.length === 0) {
    return (
      <EmptyState icon="water" title={t('No requests waiting')}>
        {t('When a Fire Volunteer or BFP coordinator adds, changes or switches off a water source in the app, it waits here for you. Hydrant status needs no approval.')}
      </EmptyState>
    );
  }
  const approving = deciding?.kind === 'approve';
  return (
    <>
      <ul className="rpl-strike-list">
        {requests.map((req) => (
          <Request key={req.id} req={req} target={targetName(req)} onDecide={decide} />
        ))}
      </ul>
      <ConfirmDialog
        open={Boolean(deciding)}
        eyebrow={deciding ? `${LAYER[deciding.req.layer_type]?.label ?? ''} · ${whatOf(deciding.req).label}` : ''}
        title={approving ? t('Approve this change?') : t('Reject this change?')}
        description={approving
          ? t('It goes on every map at once, and the coordinator is told.')
          : t('Nothing on the map changes. The coordinator is told, with your note.')}
        confirmLabel={approving ? t('Approve') : t('Reject')}
        destructive={!approving}
        onClose={() => setDeciding(null)}
        onConfirm={confirm}
      >
        {deciding && (
          <label className="rpl-field">
            <span className="rpl-field-label">{t('Note for the coordinator (optional)')}</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} rows={3} />
          </label>
        )}
      </ConfirmDialog>
    </>
  );
}
