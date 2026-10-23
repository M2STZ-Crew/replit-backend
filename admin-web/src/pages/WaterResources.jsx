import 'leaflet/dist/leaflet.css';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { MapContainer, Marker, ZoomControl } from 'react-leaflet';

import { api } from '../api/client.js';
import { markerIcon } from '../components/map/markers.js';
import Place from '../components/Place.jsx';
import Icon from '../components/ui/Icon.jsx';
import { ConfirmDialog, EmptyState, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';
import { degrees, knownAddress } from '../lib/place.js';
import BaseTiles from '../map/BaseTiles.jsx';

/* Water resources (REPLIT (MAIN) 10 · A32 871:4044 list, A33 871:4382 map
 * and detail, A34 delete, A34b deleted; PRD v13 §4.9.6): every hydrant,
 * body of water and underground cistern, as a list or on the map, with its
 * detail and Delete — any Admin may delete a water resource.
 *
 * The server knows each source's status, not a level. The 5 % water level,
 * its history and "last checked by" an organisation arrive with the
 * water_resources table (PRD v13 §6.1, §17.3), so this page shows the status
 * it has and estimates nothing. Adding and updating a source (A35) stays out:
 * the design blocks it pending a product decision (02 · conflict 18, Q10). */

const KINDS = [
  { key: 'hydrant', label: 'Hydrants', singular: 'Hydrant', path: 'hydrants' },
  { key: 'water', label: 'Bodies of water', singular: 'Body of water', path: 'bodies-of-water' },
  { key: 'cistern', label: 'Cisterns', singular: 'Cistern', path: 'underground-cisterns' },
];
const kindOf = (key) => KINDS.find((k) => k.key === key);

const STATUS = {
  operational: { label: 'Operational', tone: 'ok' },
  non_operational: { label: 'Not usable', tone: 'danger' },
  under_maintenance: { label: 'Under maintenance', tone: 'warn' },
  unknown: { label: 'Not checked', tone: 'neutral' },
};

function statusOf(row) {
  if (row.kind === 'water') {
    return row.is_accessible ? { label: 'Accessible', tone: 'ok' } : { label: 'Not accessible', tone: 'danger' };
  }
  const value = row.kind === 'hydrant' ? row.effective_status : row.status;
  return STATUS[value] ?? STATUS.unknown;
}

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

const WHEN = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
});
const when = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : WHEN.format(d);
};

/* When the source was last looked at: a hydrant's on-the-ground check, else
 * the record's last change. */
function checkedOf(row) {
  if (row.kind === 'hydrant' && row.ground_truth_at) {
    return { title: 'Checked on the ground', at: when(row.ground_truth_at) };
  }
  return { title: 'Record updated', at: when(row.updated_at) };
}

const PAGE = 10;

function Detail({ row, onClose, onDelete, floating = false }) {
  const status = statusOf(row);
  const checked = checkedOf(row);
  const facts = [
    ['Status', <StatusChip key="s" label={status.label} tone={status.tone} />],
    [checked.title, checked.at ?? '—'],
    ['Location', <Place lat={row.latitude} lng={row.longitude} address={row.address} stacked />],
  ];
  if (row.kind === 'hydrant') {
    facts.push(['BFP status', STATUS[row.bfp_status]?.label ?? '—']);
    if (row.ground_truth_notes) facts.push(['Field note', row.ground_truth_notes]);
  }
  if (row.kind === 'cistern' && row.capacity_liters != null) {
    facts.push(['Capacity', `${row.capacity_liters.toLocaleString('en-PH')} litres`]);
  }
  if (row.kind === 'water' && row.water_type) facts.push(['Type', row.water_type]);
  if (row.description) facts.push(['Description', row.description]);

  return (
    <aside className={floating ? 'ad-map-panel ad-water-panel' : 'ad-detail'} aria-labelledby="ad-water-detail-title">
      <div className="ad-detail-head">
        <div>
          <p className="ad-eyebrow">{kindOf(row.kind).singular}{row.code ? ` · ${row.code}` : ''}</p>
          <h2 className="ad-detail-title" id="ad-water-detail-title">{row.name || row.address || nameOf(row)}</h2>
        </div>
        <button type="button" className="ad-icon-button" onClick={onClose} aria-label="Close details">
          <span aria-hidden="true">✕</span>
        </button>
      </div>
      <dl className="ad-facts">
        {facts.map(([term, value]) => (
          <div className="ad-fact" key={term}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <button type="button" className="ad-button ad-button--danger" onClick={onDelete}>
        Delete resource
      </button>
    </aside>
  );
}

export default function WaterResources() {
  const [view, setView] = useState('list');
  const [type, setType] = useState('all');
  const [state, setState] = useState({ loading: true, error: null, rows: [] });
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [notice, setNotice] = useState(null);

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
        if (alive) setState({ loading: false, error: e.message || 'The water resources could not be loaded.', rows: [] });
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
  useEffect(() => { setPage(0); }, [type, term]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const selected = state.rows.find((r) => `${r.kind}:${r.id}` === selectedId) ?? null;

  const confirmDelete = useCallback(async () => {
    const target = deleting;
    await api.mapLayerDelete(kindOf(target.kind).path, target.id);
    setState((s) => ({ ...s, rows: s.rows.filter((r) => !(r.kind === target.kind && r.id === target.id)) }));
    setSelectedId(null);
    setDeleting(null);
    setNotice(`${nameOf(target)} deleted. It is gone from every map; the deletion is in the audit log.`);
  }, [deleting]);

  const filters = (
    <div className="ad-filters">
      <label className="ad-search">
        <Icon name="search" />
        <span className="web-sr-only">Search water resources</span>
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search codes, names and streets" />
      </label>
      <label className="ad-select">
        <span className="ad-select-label">Type</span>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="all">All types</option>
          {KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
        </select>
      </label>
    </div>
  );

  return (
    <div className={`ad-page${view === 'map' ? ' ad-page--map' : ''}`}>
      <PageHeader
        eyebrow="Shared across every organisation"
        title="Water resources"
        description="Every hydrant, body of water and underground cistern on the shared map. Any Admin may delete one; every deletion is recorded."
      />

      {notice && (
        <div className="ad-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>
      )}

      <div className="ad-tabs ad-tabs--page" role="tablist" aria-label="View">
        {[{ key: 'list', label: 'List' }, { key: 'map', label: 'Map' }].map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={view === t.key}
            className={`ad-tab${view === t.key ? ' is-active' : ''}`}
            onClick={() => setView(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {filters}

      {state.loading ? (
        <StatePanel kind="loading" title="Loading water resources…" />
      ) : state.error ? (
        <StatePanel kind="error" title="The water resources couldn’t load" description={state.error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : state.rows.length === 0 ? (
        <EmptyState icon="water" title="No water resources yet">
          Fire Volunteer Coordinators add hydrants, bodies of water and cisterns from the mobile app.
        </EmptyState>
      ) : view === 'map' ? (
        <div className="ad-water-map">
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
        <div className={`ad-split${selected ? ' has-detail' : ''}`}>
          <div className="ad-stack">
            <div className="web-table-wrap">
              <table className="web-table">
                <caption className="web-sr-only">Water resources</caption>
                <thead>
                  <tr>
                    <th scope="col">Resource</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last checked</th>
                    <th scope="col"><span className="web-sr-only">Open</span></th>
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
                          <span className="ad-cell-resource">
                            <span className="ad-plate ad-plate--water" aria-hidden="true">
                              <img src={`/icons/map/${r.kind}.svg`} alt="" width="16" height="16" />
                            </span>
                            <span className="ad-cell-text">
                              <span className="ad-cell-title">{nameOf(r)}</span>
                              <span className="ad-cell-meta"><Place lat={r.latitude} lng={r.longitude} address={r.address} /></span>
                            </span>
                          </span>
                        </th>
                        <td><StatusChip label={s.label} tone={s.tone} /></td>
                        <td>
                          <span className="ad-cell-text">
                            <span className="ad-cell-value">{c.title}</span>
                            <span className="ad-cell-meta">{c.at ?? '—'}</span>
                          </span>
                        </td>
                        <td className="web-table-action-cell">
                          <button
                            type="button"
                            className="ad-icon-button"
                            onClick={() => setSelectedId(key)}
                            aria-label={`Details and actions for ${nameOf(r)}`}
                            aria-current={key === selectedId ? 'true' : undefined}
                          >
                            <Icon name="more" size={24} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr><td className="web-table-empty" colSpan={4}>Nothing matches these filters.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="ad-pager">
              <span className="ad-pager-range">
                {rows.length === 0 ? 'Showing 0 of 0' : `Showing ${page * PAGE + 1}–${Math.min(rows.length, page * PAGE + PAGE)} of ${rows.length}`}
              </span>
              {pages > 1 && (
                <nav className="ad-pager-pages" aria-label="Pages">
                  <button type="button" className="ad-page-button" onClick={() => setPage((p) => p - 1)} disabled={page === 0} aria-label="Previous page">‹</button>
                  {Array.from({ length: pages }, (_, i) => (
                    <button key={i} type="button" className={`ad-page-button${i === page ? ' is-current' : ''}`} onClick={() => setPage(i)} aria-current={i === page ? 'page' : undefined}>{i + 1}</button>
                  ))}
                  <button type="button" className="ad-page-button" onClick={() => setPage((p) => p + 1)} disabled={page >= pages - 1} aria-label="Next page">›</button>
                </nav>
              )}
            </div>
          </div>
          {selected && <Detail row={selected} onClose={() => setSelectedId(null)} onDelete={() => setDeleting(selected)} />}
        </div>
      )}

      <ConfirmDialog
        open={!!deleting}
        eyebrow={deleting ? kindOf(deleting.kind).singular : undefined}
        title={deleting ? `Delete ${nameOf(deleting)}?` : ''}
        description="It disappears from every Admin’s map and every Coordinator’s water patrol. This can’t be undone; the deletion is recorded with your name."
        confirmLabel={deleting ? `Delete ${kindOf(deleting.kind).singular.toLowerCase()}` : 'Delete'}
        destructive
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
