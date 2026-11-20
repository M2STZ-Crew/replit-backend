import 'leaflet/dist/leaflet.css';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { MapContainer, Marker, ZoomControl } from 'react-leaflet';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import { markerIcon } from '../components/map/markers.js';
import Place from '../components/Place.jsx';
import Icon from '../components/ui/Icon.jsx';
import {
  ConfirmDialog, EmptyState, PageHeader, Pager, StatePanel, StatusChip, usePager,
} from '../components/ui/index.js';
import { PERM, can } from '../lib/access.js';
import { degrees, knownAddress } from '../lib/place.js';
import { WATER_STATUS as STATUS, checkedOf, waterStatusOf as statusOf } from '../lib/water.js';
import BaseTiles from '../map/BaseTiles.jsx';
import WaterRequests, { WATER_REQUEST_LAYERS } from '../components/water/WaterRequests.jsx';
import MapManagement from './MapManagement.jsx';
import { t } from '../i18n/i18n.jsx';

/* Water resources (REPLIT (MAIN) 10 · A32 871:4044 list, A33 871:4382 map
 * and detail, A34 delete, A34b deleted; PRD v13 §4.9.6): every hydrant,
 * body of water and underground cistern, as a list or on the map, with its
 * detail and Delete — any Admin may delete a water resource.
 *
 * The server knows each source's status, not a level. The 5 % water level,
 * its history and "last checked by" an organisation arrive with the
 * water_resources table (PRD v13 §6.1, §17.3), so this page shows the status
 * it has and estimates nothing.
 *
 * v1.12.43 (19 Nov 2026, "One Water resources page"): everything about water
 * is here. Edit on map is the map editor with the water layers only (Map
 * settings keeps shelters and risk areas), and Requests holds the changes Fire
 * Volunteer and BFP coordinators propose from the app, for the Admin who may
 * (`map.manage`) to approve. A hydrant's status comes from the field, with who
 * checked it and when. */

// The editor's layers here; Map settings has the rest.
const WATER_LAYERS = ['hydrants', 'water', 'cisterns'];
const KIND_OF_LAYER = { hydrant: 'hydrant', bodies_of_water: 'water', underground_cistern: 'cistern' };

const KINDS = [
  { key: 'hydrant', get label() { return t('Hydrants'); }, get singular() { return t('Hydrant'); }, path: 'hydrants' },
  { key: 'water', get label() { return t('Bodies of water'); }, get singular() { return t('Body of water'); }, path: 'bodies-of-water' },
  { key: 'cistern', get label() { return t('Cisterns'); }, get singular() { return t('Cistern'); }, path: 'underground-cisterns' },
];
const kindOf = (key) => KINDS.find((k) => k.key === key);

// Status words and the last check are shared with the live map's details
// panel (lib/water.js, v1.12.47).

function nameOf(row) {
  const singular = kindOf(row.kind).singular;
  const label = row.kind === 'hydrant' ? row.code : row.name || row.code;
  return label ? `${label} · ${singular}` : singular;
}

// For search: the record's own address, else the street looked up for it
// (once known), else the degrees.
const placeOf = (row) => row.address
  || knownAddress(row.latitude, row.longitude)
  || degrees(row.latitude, row.longitude);

function Detail({ row, onClose, onDelete, floating = false }) {
  const status = statusOf(row);
  const checked = checkedOf(row);
  const facts = [
    [t('Status'), <StatusChip key="s" label={status.label} tone={status.tone} />],
    [checked.title, checked.at ?? '—'],
    [t('Location'), <Place lat={row.latitude} lng={row.longitude} address={row.address} stacked />],
  ];
  if (row.kind === 'hydrant') {
    facts.push([t('BFP status'), STATUS[row.bfp_status]?.label ?? '—']);
    if (row.ground_truth_notes) facts.push([t('Field note'), row.ground_truth_notes]);
  }
  if (row.kind === 'cistern' && row.capacity_liters != null) {
    facts.push([t('Capacity'), t('{amount} litres', { amount: row.capacity_liters.toLocaleString('en-PH') })]);
  }
  if (row.kind === 'water' && row.water_type) facts.push([t('Type'), row.water_type]);
  if (row.description) facts.push([t('Description'), row.description]);

  return (
    <aside className={floating ? 'rpl-map-panel rpl-water-panel' : 'rpl-detail'} aria-labelledby="rpl-water-detail-title">
      <div className="rpl-detail-head">
        <div>
          <p className="rpl-eyebrow">{kindOf(row.kind).singular}{row.code ? ` · ${row.code}` : ''}</p>
          <h2 className="rpl-detail-title" id="rpl-water-detail-title">{row.name || row.address || nameOf(row)}</h2>
        </div>
        <button type="button" className="rpl-icon-button" onClick={onClose} aria-label={t('Close details')}>
          <span aria-hidden="true">✕</span>
        </button>
      </div>
      <dl className="rpl-facts">
        {facts.map(([term, value]) => (
          <div className="rpl-fact" key={term}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <button type="button" className="rpl-button rpl-button--danger" onClick={onDelete}>{t('Delete resource')}</button>
    </aside>
  );
}

/* `initialEdit` ({ layer, id }): opened from Edit on the live map's details
 * panel (v1.12.47), on that source's form in Edit on map. */
export default function WaterResources({ onOpenIncident, initialEdit = null }) {
  const { console: access, refreshQueues } = useConsole();
  const managesMap = can(access, PERM.MANAGE_MAP);
  const [view, setView] = useState(initialEdit ? 'edit' : 'list');
  const [type, setType] = useState('all');
  const [state, setState] = useState({ loading: true, error: null, rows: [] });
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [notice, setNotice] = useState(null);
  const [requests, setRequests] = useState({ loading: false, error: null, rows: [] });
  const [requestAttempt, setRequestAttempt] = useState(0);

  // Coordinators' water changes awaiting an Admin (v1.12.43).
  useEffect(() => {
    if (!managesMap) return undefined;
    let alive = true;
    setRequests((r) => ({ ...r, loading: true, error: null }));
    api.mapLayerRequests('pending')
      .then((rows) => {
        if (!alive) return;
        const water = (Array.isArray(rows) ? rows : []).filter((r) => WATER_REQUEST_LAYERS.includes(r.layer_type));
        setRequests({ loading: false, error: null, rows: water });
      })
      .catch((e) => { if (alive) setRequests({ loading: false, error: e.message || t('The requests could not be loaded.'), rows: [] }); });
    return () => { alive = false; };
  }, [managesMap, requestAttempt]);

  // Back from the editor, the list and map show what was changed there.
  function switchView(next) {
    if (view === 'edit' && next !== 'edit') setAttempt((n) => n + 1);
    setView(next);
  }

  function targetName(req) {
    if (!req.target_id) return null;
    const row = state.rows.find((r) => r.kind === KIND_OF_LAYER[req.layer_type] && r.id === req.target_id);
    // The card already says the layer: the source's own name or code only.
    return row ? (row.kind === 'hydrant' ? row.code : row.name || row.code) || null : null;
  }

  function decided(message) {
    setNotice(message);
    setRequestAttempt((n) => n + 1);
    setAttempt((n) => n + 1);
    refreshQueues?.();
  }

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.all(KINDS.map((k) => api.mapLayer(k.path)))
      .then((results) => {
        if (!alive) return;
        const rows = KINDS.flatMap((k, i) => (Array.isArray(results[i]) ? results[i] : []).map((r) => ({ ...r, kind: k.key })));
        setState({ loading: false, error: null, rows });
      })
      .catch((e) => {
        if (alive) setState({ loading: false, error: e.message || t('The water resources could not be loaded.'), rows: [] });
      });
    return () => { alive = false; };
  }, [attempt]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  const term = query.trim().toLowerCase();
  const rows = useMemo(
    () => state.rows.filter((r) => (type === 'all' || r.kind === type)
      && (!term || `${nameOf(r)} ${placeOf(r)}`.toLowerCase().includes(term))),
    [state.rows, type, term],
  );
  const { shown, pager } = usePager(rows, { key: 'water', reset: [type, term] });
  const selected = state.rows.find((r) => `${r.kind}:${r.id}` === selectedId) ?? null;

  const confirmDelete = useCallback(async () => {
    const target = deleting;
    await api.mapLayerDelete(kindOf(target.kind).path, target.id);
    setState((s) => ({ ...s, rows: s.rows.filter((r) => !(r.kind === target.kind && r.id === target.id)) }));
    setSelectedId(null);
    setDeleting(null);
    setNotice(t('{nameOf} deleted. It is gone from every map; the deletion is in the audit log.', { nameOf: nameOf(target) }));
  }, [deleting]);

  const filters = (
    <div className="rpl-filters">
      <label className="rpl-search">
        <Icon name="search" />
        <span className="web-sr-only">{t('Search water resources')}</span>
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search codes, names and streets')} />
      </label>
      <label className="rpl-select">
        <span className="rpl-select-label">{t('Type')}</span>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="all">{t('All types')}</option>
          {KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
        </select>
      </label>
    </div>
  );

  return (
    <div className={`rpl-page${view === 'map' || view === 'edit' ? ' rpl-page--map' : ''}`}>
      <PageHeader
        eyebrow={t('Shared across every organization')}
        title={t('Water resources')}
        description={managesMap
          ? t('Every hydrant, body of water and underground cistern on the shared map. Any Admin may delete one; every deletion is recorded.')
          : t('Every hydrant, body of water and underground cistern on the shared map. Any Admin may delete one; every deletion is recorded. Fire Volunteer, BFP and central hub Admins add and change them.')}
        actions={managesMap && (
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => switchView('edit')}>{t('Add or change resources')}</button>
        )}
      />

      {notice && (
        <div className="rpl-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>
      )}

      <div className="rpl-tabs rpl-tabs--page" role="tablist" aria-label={t('View')}>
        {[
          { key: 'list', label: t('List') },
          { key: 'map', label: t('Map') },
          ...(managesMap ? [
            { key: 'edit', label: t('Edit on map') },
            { key: 'requests', label: t('Requests'), count: requests.rows.length },
          ] : []),
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={view === tab.key}
            className={`rpl-tab${view === tab.key ? ' is-active' : ''}`}
            onClick={() => switchView(tab.key)}
          >
            {tab.label}
            {tab.count > 0 && <span className="web-count-badge" aria-label={t('{count} waiting', { count: tab.count })}>{tab.count}</span>}
          </button>
        ))}
      </div>

      {(view === 'list' || view === 'map') && filters}

      {view === 'edit' ? (
        <div className="rpl-water-map rpl-water-editor">
          <MapManagement
            layers={WATER_LAYERS}
            initialLayer={initialEdit?.layer ?? 'hydrants'}
            initialEdit={initialEdit}
            onOpenIncident={onOpenIncident}
          />
        </div>
      ) : view === 'requests' ? (
        <WaterRequests
          requests={requests.rows}
          loading={requests.loading}
          error={requests.error}
          onRetry={() => setRequestAttempt((n) => n + 1)}
          targetName={targetName}
          onDecided={decided}
        />
      ) : state.loading ? (
        <StatePanel kind="loading" title={t('Loading water resources…')} />
      ) : state.error ? (
        <StatePanel kind="error" title={t('The water resources couldn’t load')} description={state.error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : state.rows.length === 0 ? (
        <EmptyState icon="water" title={t('No water resources yet')}>{t('Fire Volunteer Coordinators add hydrants, bodies of water and cisterns from the mobile app.')}</EmptyState>
      ) : view === 'map' ? (
        <div className="rpl-water-map">
          <MapContainer
            center={[14.5378, 121.0014]}
            zoom={15}
            zoomControl={false}
            attributionControl={false}
            style={{ height: '100%', width: '100%' }}
          >
            <BaseTiles />
            <ZoomControl position="bottomright" />
            {rows.filter((r) => r.latitude != null && r.longitude != null).map((r) => (
              <Marker
                key={`${r.kind}:${r.id}`}
                position={[r.latitude, r.longitude]}
                icon={markerIcon(r.kind, `${r.kind}:${r.id}` === selectedId)}
                eventHandlers={{ click: () => setSelectedId(`${r.kind}:${r.id}`) }}
                title={nameOf(r)}
              />
            ))}
          </MapContainer>
          {selected && (
            <Detail row={selected} floating onClose={() => setSelectedId(null)} onDelete={() => setDeleting(selected)} />
          )}
        </div>
      ) : (
        <div className={`rpl-split${selected ? ' has-detail' : ''}`}>
          <div className="rpl-stack">
            <div className="web-table-wrap">
              <table className="web-table">
                <caption className="web-sr-only">{t('Water resources')}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t('Resource')}</th>
                    <th scope="col">{t('Status')}</th>
                    <th scope="col">{t('Last checked')}</th>
                    <th scope="col"><span className="web-sr-only">{t('Open')}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const s = statusOf(r);
                    const c = checkedOf(r);
                    const key = `${r.kind}:${r.id}`;
                    return (
                      <tr key={key} className={`web-table-row${key === selectedId ? ' is-selected' : ''}`}>
                        <th scope="row">
                          <span className="rpl-cell-resource">
                            <span className="rpl-plate rpl-plate--water" aria-hidden="true">
                              <img src={`/icons/map/${r.kind}.svg`} alt="" width="16" height="16" />
                            </span>
                            <span className="rpl-cell-text">
                              <span className="rpl-cell-title">{nameOf(r)}</span>
                              <span className="rpl-cell-meta"><Place lat={r.latitude} lng={r.longitude} address={r.address} /></span>
                            </span>
                          </span>
                        </th>
                        <td><StatusChip label={s.label} tone={s.tone} /></td>
                        <td data-label={t('Last checked')}>
                          <span className="rpl-cell-text">
                            <span className="rpl-cell-value">{c.title}</span>
                            <span className="rpl-cell-meta">{c.at ?? '—'}</span>
                          </span>
                        </td>
                        <td className="web-table-action-cell">
                          <button
                            type="button"
                            className="rpl-icon-button"
                            onClick={() => setSelectedId(key)}
                            aria-label={t('Details and actions for {nameOf}', { nameOf: nameOf(r) })}
                            aria-current={key === selectedId ? 'true' : undefined}
                          >
                            <Icon name="more" size={24} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr><td className="web-table-empty" colSpan={4}>{t('Nothing matches these filters.')}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <Pager {...pager} />
          </div>
          {selected && <Detail row={selected} onClose={() => setSelectedId(null)} onDelete={() => setDeleting(selected)} />}
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        eyebrow={deleting ? kindOf(deleting.kind).singular : undefined}
        title={deleting ? t('Delete {nameOf}?', { nameOf: nameOf(deleting) }) : ''}
        description={t('It disappears from every Admin’s map and every Coordinator’s water patrol. This can’t be undone; the deletion is recorded with your name.')}
        confirmLabel={deleting ? t('Delete {thing}', { thing: kindOf(deleting.kind).singular.toLowerCase() }) : t('Delete')}
        destructive
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
