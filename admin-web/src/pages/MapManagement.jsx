import 'leaflet/dist/leaflet.css';

import { useEffect, useMemo, useState } from 'react';
import {
  Circle,
  CircleMarker,
  MapContainer,
  TileLayer,
  Tooltip,
  useMapEvents,
  ZoomControl,
} from 'react-leaflet';

import { api } from '../api/client.js';

const PASAY = [14.5378, 121.0014];

// Marker colours per layer key.
const COLORS = {
  incidents: '#FF544E',
  evac: '#22C55E',
  risk: '#FF9066',
  hydrants: '#767575',
  water: '#4EA8FF',
  cisterns: '#9A8CFF',
  teams: '#FF9066',
  fire: '#767575',
  police: '#767575',
  hospital: '#767575',
  barangay: '#767575',
};

// The five layers an admin can create/update/delete here.
const EDIT_LAYERS = [
  { key: 'risk', label: 'Risk Areas', singular: 'Risk Area', path: 'risk-zones', icon: '⚠', tagline: 'High-priority zones' },
  { key: 'evac', label: 'Evacuation Sites', singular: 'Evacuation Site', path: 'evacuation-sites', icon: '🚪', tagline: 'Safe gathering points' },
  { key: 'hydrants', label: 'Fire Hydrants', singular: 'Fire Hydrant', path: 'hydrants', icon: '🚰', tagline: 'Water supply points' },
  { key: 'water', label: 'Bodies of Water', singular: 'Body of Water', path: 'bodies-of-water', icon: '🌊', tagline: 'Natural water sources' },
  { key: 'cisterns', label: 'Underground Cisterns', singular: 'Cistern', path: 'underground-cisterns', icon: '🛢', tagline: 'Underground reserves' },
];

// The toggle chips on the map (order mirrors the design). `kind`:
//   'edit'      → an editable GIS layer with backend data
//   'incidents' → live incidents (read-only here)
//   'none'      → no backend data yet (honest no-op toggle)
const CHIPS = [
  { key: 'incidents', label: 'Incidents', kind: 'incidents' },
  { key: 'evac', label: 'Evacuation Sites', kind: 'edit' },
  { key: 'risk', label: 'Risk Areas', kind: 'edit' },
  { key: 'teams', label: 'Response Teams', kind: 'none' },
  { key: 'hydrants', label: 'Fire Hydrants', kind: 'edit' },
  { key: 'water', label: 'Bodies of Water', kind: 'edit' },
  { key: 'cisterns', label: 'Underground Cisterns', kind: 'edit' },
  { key: 'fire', label: 'Fire Department', kind: 'none' },
  { key: 'police', label: 'Police Department', kind: 'none' },
  { key: 'hospital', label: 'Hospital', kind: 'none' },
  { key: 'barangay', label: 'Barangay Hall', kind: 'none' },
];

const RISK_OPTS = ['low', 'medium', 'high', 'critical'];
const STATUS_OPTS = ['operational', 'non_operational', 'under_maintenance', 'unknown'];

// Form field schema per editable layer (mirrors the backend create/update models).
const FIELDS = {
  risk: [
    { name: 'barangay', label: 'Barangay', type: 'text', required: true },
    { name: 'name', label: 'Name', type: 'text' },
    { name: 'risk_level', label: 'Risk level', type: 'select', options: RISK_OPTS, default: 'medium' },
    { name: 'centroid_lat', label: 'Latitude', type: 'coord', coord: 'lat', required: true },
    { name: 'centroid_lng', label: 'Longitude', type: 'coord', coord: 'lng', required: true },
    { name: 'description', label: 'Description', type: 'textarea' },
  ],
  evac: [
    { name: 'name', label: 'Name', type: 'text', required: true },
    { name: 'latitude', label: 'Latitude', type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', label: 'Longitude', type: 'coord', coord: 'lng', required: true },
    { name: 'capacity', label: 'Capacity', type: 'number' },
    { name: 'address', label: 'Address', type: 'text' },
    { name: 'contact_info', label: 'Contact info', type: 'text' },
    { name: 'is_active', label: 'Active', type: 'checkbox', default: true },
  ],
  hydrants: [
    { name: 'code', label: 'Code', type: 'text' },
    { name: 'latitude', label: 'Latitude', type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', label: 'Longitude', type: 'coord', coord: 'lng', required: true },
    { name: 'address', label: 'Address', type: 'text' },
    { name: 'bfp_status', label: 'Status', type: 'select', options: STATUS_OPTS, default: 'unknown' },
    { name: 'is_active', label: 'Active', type: 'checkbox', default: true },
  ],
  water: [
    { name: 'name', label: 'Name', type: 'text', required: true },
    { name: 'water_type', label: 'Water type', type: 'text' },
    { name: 'latitude', label: 'Latitude', type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', label: 'Longitude', type: 'coord', coord: 'lng', required: true },
    { name: 'is_accessible', label: 'Accessible', type: 'checkbox', default: true },
    { name: 'description', label: 'Description', type: 'textarea' },
  ],
  cisterns: [
    { name: 'name', label: 'Name', type: 'text' },
    { name: 'code', label: 'Code', type: 'text' },
    { name: 'latitude', label: 'Latitude', type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', label: 'Longitude', type: 'coord', coord: 'lng', required: true },
    { name: 'capacity_liters', label: 'Capacity (liters)', type: 'number' },
    { name: 'status', label: 'Status', type: 'select', options: STATUS_OPTS, default: 'unknown' },
    { name: 'address', label: 'Address', type: 'text' },
    { name: 'description', label: 'Description', type: 'textarea' },
    { name: 'is_active', label: 'Active', type: 'checkbox', default: true },
  ],
};

function cfgOf(key) {
  return EDIT_LAYERS.find((l) => l.key === key);
}

function prettify(s) {
  if (!s) return '';
  return String(s)
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function coordNames(layer) {
  const f = FIELDS[layer];
  return [f.find((x) => x.coord === 'lat')?.name, f.find((x) => x.coord === 'lng')?.name];
}

function pointOf(key, r) {
  if (key === 'risk') return { lat: r.centroid_lat, lng: r.centroid_lng };
  return { lat: r.latitude, lng: r.longitude };
}

function entryText(key, r) {
  switch (key) {
    case 'risk':
      return {
        title: r.name || `Risk Area · ${r.barangay}`,
        sub: `${prettify(r.risk_level)} · Brgy. ${r.barangay}`,
      };
    case 'evac':
      return {
        title: r.name,
        sub:
          r.capacity != null
            ? `Capacity ${r.capacity}${r.address ? ` · ${r.address}` : ''}`
            : r.address || 'Evacuation site',
      };
    case 'hydrants':
      return {
        title: r.code || 'Hydrant',
        sub: `${prettify(r.effective_status)}${r.address ? ` · ${r.address}` : ''}`,
      };
    case 'water':
      return {
        title: r.name,
        sub: `${r.water_type || 'Water source'} · ${r.is_accessible ? 'Accessible' : 'Restricted'}`,
      };
    case 'cisterns':
      return {
        title: r.name || r.code || 'Cistern',
        sub: `${prettify(r.status)}${r.capacity_liters ? ` · ${r.capacity_liters} L` : ''}`,
      };
    default:
      return { title: '—', sub: '' };
  }
}

function coerce(field, raw) {
  if (field.type === 'checkbox') return !!raw;
  if (field.type === 'number' || field.type === 'coord') {
    if (raw === '' || raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  if (raw == null) return null;
  const s = String(raw).trim();
  return s === '' ? null : s;
}

function initValues(layer, rec) {
  const vals = {};
  for (const f of FIELDS[layer]) {
    if (rec) {
      const v = rec[f.name];
      vals[f.name] = f.type === 'checkbox' ? !!v : v == null ? '' : String(v);
    } else if (f.type === 'checkbox') {
      vals[f.name] = f.default ?? true;
    } else {
      vals[f.name] = f.default ?? '';
    }
  }
  return vals;
}

// Captures map clicks while a form is open so the admin can drop/move the marker.
function ClickCapture({ active, onPick }) {
  useMapEvents({
    click(e) {
      if (active) onPick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

export default function MapManagement({ query = '' }) {
  const [data, setData] = useState({}); // key → array of rows
  const [incidents, setIncidents] = useState([]);
  const [enabled, setEnabled] = useState(
    () => new Set(['incidents', 'risk', 'evac', 'hydrants', 'water', 'cisterns']),
  );
  const [selected, setSelected] = useState('risk');
  const [panelOpen, setPanelOpen] = useState(true);
  const [form, setForm] = useState(null); // { layer, mode, id, values }
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  async function loadLayer(key) {
    const cfg = cfgOf(key);
    try {
      const rows = await api.mapLayer(cfg.path);
      setData((d) => ({ ...d, [key]: Array.isArray(rows) ? rows : [] }));
    } catch {
      setData((d) => ({ ...d, [key]: [] }));
    }
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      const results = await Promise.all(
        EDIT_LAYERS.map((l) => api.mapLayer(l.path).catch(() => [])),
      );
      const inc = await api.incidents().catch(() => []);
      if (!alive) return;
      const next = {};
      EDIT_LAYERS.forEach((l, i) => {
        next[l.key] = Array.isArray(results[i]) ? results[i] : [];
      });
      setData(next);
      setIncidents(Array.isArray(inc) ? inc : []);
    })();
    return () => {
      alive = false;
    };
  }, []);

  function flash(msg, kind = 'ok') {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3200);
  }

  function toggleChip(key) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function openAdd() {
    setForm({ layer: selected, mode: 'add', id: null, values: initValues(selected, null) });
  }

  function openEdit(layer, rec) {
    setSelected(layer);
    setForm({ layer, mode: 'edit', id: rec.id, values: initValues(layer, rec) });
  }

  function handlePick(lat, lng) {
    const [latName, lngName] = coordNames(form.layer);
    setForm((f) => ({
      ...f,
      values: { ...f.values, [latName]: lat.toFixed(6), [lngName]: lng.toFixed(6) },
    }));
  }

  async function submitForm() {
    const layer = form.layer;
    const payload = {};
    for (const f of FIELDS[layer]) {
      const c = coerce(f, form.values[f.name]);
      if (f.required && (c == null || c === '')) {
        flash(`${f.label} is required.`, 'err');
        return;
      }
      payload[f.name] = c;
    }
    setSaving(true);
    try {
      const path = cfgOf(layer).path;
      if (form.mode === 'edit') await api.mapLayerUpdate(path, form.id, payload);
      else await api.mapLayerCreate(path, payload);
      flash(form.mode === 'edit' ? 'Marker updated.' : 'Marker added.');
      setForm(null);
      await loadLayer(layer);
    } catch (e) {
      flash(e.message || 'Save failed.', 'err');
    } finally {
      setSaving(false);
    }
  }

  async function removeEntry(layer, rec) {
    const { title } = entryText(layer, rec);
    if (!window.confirm(`Delete "${title}"? This cannot be undone.`)) return;
    try {
      await api.mapLayerDelete(cfgOf(layer).path, rec.id);
      flash('Marker deleted.');
      if (form && form.id === rec.id) setForm(null);
      await loadLayer(layer);
    } catch (e) {
      flash(e.message || 'Delete failed.', 'err');
    }
  }

  const selCfg = cfgOf(selected);
  const selRows = data[selected] || [];
  const term = query.trim().toLowerCase();
  const shownRows = term
    ? selRows.filter((r) => {
        const { title, sub } = entryText(selected, r);
        return `${title} ${sub}`.toLowerCase().includes(term);
      })
    : selRows;

  // Temporary marker preview for the form being edited.
  const formPoint = useMemo(() => {
    if (!form) return null;
    const [latName, lngName] = coordNames(form.layer);
    const lat = parseFloat(form.values[latName]);
    const lng = parseFloat(form.values[lngName]);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    return { lat, lng, color: COLORS[form.layer] };
  }, [form]);

  return (
    <div className="mm-root">
      <div className="mm-map">
        <MapContainer
          center={PASAY}
          zoom={13}
          style={{ height: '100%', width: '100%', background: '#0b0b0b' }}
          zoomControl={false}
          attributionControl={false}
        >
          <TileLayer url="https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png" />
          <ZoomControl position="bottomleft" />
          <ClickCapture active={!!form} onPick={handlePick} />

          {/* incidents */}
          {enabled.has('incidents') &&
            incidents.map((inc) => {
              if (inc.centroid_lat == null || inc.centroid_lng == null) return null;
              return (
                <CircleMarker
                  key={`inc-${inc.id}`}
                  center={[inc.centroid_lat, inc.centroid_lng]}
                  radius={9}
                  pathOptions={{
                    color: '#fff',
                    weight: 1.5,
                    fillColor: COLORS.incidents,
                    fillOpacity: 0.95,
                  }}
                >
                  <Tooltip>
                    {(inc.designation || 'Incident')} · {inc.status}
                  </Tooltip>
                </CircleMarker>
              );
            })}

          {/* editable GIS layers */}
          {EDIT_LAYERS.filter((l) => enabled.has(l.key)).flatMap((l) =>
            (data[l.key] || []).map((r) => {
              const p = pointOf(l.key, r);
              if (p.lat == null || p.lng == null) return null;
              const { title, sub } = entryText(l.key, r);
              const color = COLORS[l.key];
              return [
                l.key === 'risk' ? (
                  <Circle
                    key={`halo-${r.id}`}
                    center={[p.lat, p.lng]}
                    radius={150}
                    pathOptions={{ color, weight: 1, fillColor: color, fillOpacity: 0.12 }}
                  />
                ) : null,
                <CircleMarker
                  key={`m-${r.id}`}
                  center={[p.lat, p.lng]}
                  radius={7}
                  pathOptions={{ color: '#fff', weight: 1, fillColor: color, fillOpacity: 0.95 }}
                  eventHandlers={{ click: () => openEdit(l.key, r) }}
                >
                  <Tooltip>
                    {title}
                    {sub ? ` · ${sub}` : ''}
                  </Tooltip>
                </CircleMarker>,
              ];
            }),
          )}

          {/* form preview marker */}
          {formPoint && (
            <CircleMarker
              center={[formPoint.lat, formPoint.lng]}
              radius={9}
              pathOptions={{
                color: '#fff',
                weight: 2,
                fillColor: formPoint.color,
                fillOpacity: 0.6,
                dashArray: '3',
              }}
            />
          )}
        </MapContainer>

        {/* layers toggle bar */}
        <div className="mm-layers" style={{ right: panelOpen ? 372 : 120 }}>
          <span className="mm-layers-label">☰ Layers</span>
          <div className="mm-chips">
            {CHIPS.map((c) => {
              const on = enabled.has(c.key);
              const color = COLORS[c.key];
              const count =
                c.kind === 'edit'
                  ? (data[c.key] || []).length
                  : c.kind === 'incidents'
                    ? incidents.length
                    : null;
              return (
                <button
                  key={c.key}
                  className={`mm-chip${on ? ' on' : ''}${c.kind === 'none' ? ' empty' : ''}`}
                  onClick={() => toggleChip(c.key)}
                  style={on ? { borderColor: `${color}88` } : undefined}
                  title={c.kind === 'none' ? 'No data source yet' : undefined}
                >
                  <span className="mm-chip-dot" style={{ background: color }} />
                  {c.label}
                  {count != null && <span className="mm-chip-count">{count}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* reopen tab when the editor is collapsed */}
        {!panelOpen && (
          <button className="mm-reopen" onClick={() => setPanelOpen(true)} title="Open editor">
            ‹ Layers
          </button>
        )}

        {/* editor panel */}
        {panelOpen && (
          <aside className="mm-panel">
            <div className="mm-panel-head">
              <div>
                <div className="mm-panel-eyebrow">Editing layer</div>
                <div className="mm-panel-title">Map Layers</div>
              </div>
              <button
                className="mm-collapse"
                onClick={() => setPanelOpen(false)}
                title="Collapse"
              >
                ›
              </button>
            </div>

            {!form ? (
              <div className="mm-panel-body">
                <div className="mm-grid">
                  {EDIT_LAYERS.map((l) => (
                    <button
                      key={l.key}
                      className={`mm-gcard${selected === l.key ? ' active' : ''}`}
                      onClick={() => setSelected(l.key)}
                    >
                      <div className="mm-gcard-top">
                        <span
                          className="mm-gicon"
                          style={{ background: `${COLORS[l.key]}26`, color: COLORS[l.key] }}
                        >
                          {l.icon}
                        </span>
                        <span className="mm-gcount">{(data[l.key] || []).length}</span>
                      </div>
                      <div className="mm-glabel">{l.label}</div>
                    </button>
                  ))}
                </div>

                <div className="mm-section">
                  <div className="mm-section-l">
                    <div className="mm-section-title">{selCfg.label}</div>
                    <div className="mm-section-sub">
                      {selRows.length} {selRows.length === 1 ? 'entry' : 'entries'} ·{' '}
                      {selCfg.tagline}
                    </div>
                  </div>
                  <span
                    className="mm-section-icon"
                    style={{ background: `${COLORS[selected]}26`, color: COLORS[selected] }}
                  >
                    {selCfg.icon}
                  </span>
                </div>

                <div className="mm-list">
                  {selRows.length === 0 && (
                    <div className="mm-empty">No {selCfg.label.toLowerCase()} yet.</div>
                  )}
                  {selRows.length > 0 && shownRows.length === 0 && (
                    <div className="mm-empty">No matches for “{query}”.</div>
                  )}
                  {shownRows.map((r) => {
                    const { title, sub } = entryText(selected, r);
                    return (
                      <div className="mm-entry" key={r.id}>
                        <div className="mm-entry-texts">
                          <div className="mm-entry-title">{title}</div>
                          <div className="mm-entry-sub">{sub}</div>
                        </div>
                        <div className="mm-entry-actions">
                          <button
                            className="mm-iconbtn"
                            onClick={() => openEdit(selected, r)}
                            title="Edit"
                          >
                            ✎
                          </button>
                          <button
                            className="mm-iconbtn del"
                            onClick={() => removeEntry(selected, r)}
                            title="Delete"
                          >
                            🗑
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <button className="mm-add" onClick={openAdd}>
                  + ADD {selCfg.singular.toUpperCase()}
                </button>
              </div>
            ) : (
              <div className="mm-panel-body">
                <div className="mm-form-title">
                  {form.mode === 'edit' ? 'Edit' : 'New'} {cfgOf(form.layer).singular}
                </div>
                <div className="mm-hint">Click the map to set the location.</div>

                <div className="mm-form">
                  {FIELDS[form.layer].map((f) => {
                    const val = form.values[f.name];
                    const setVal = (v) =>
                      setForm((cur) => ({ ...cur, values: { ...cur.values, [f.name]: v } }));
                    if (f.type === 'checkbox') {
                      return (
                        <label className="mm-checkbox-row" key={f.name}>
                          <input
                            type="checkbox"
                            checked={!!val}
                            onChange={(e) => setVal(e.target.checked)}
                          />
                          {f.label}
                        </label>
                      );
                    }
                    if (f.type === 'select') {
                      return (
                        <div className="mm-form-row" key={f.name}>
                          <div className="mm-flabel">{f.label}</div>
                          <select
                            className="mm-select"
                            value={val}
                            onChange={(e) => setVal(e.target.value)}
                          >
                            {f.options.map((o) => (
                              <option key={o} value={o}>
                                {prettify(o)}
                              </option>
                            ))}
                          </select>
                        </div>
                      );
                    }
                    if (f.type === 'textarea') {
                      return (
                        <div className="mm-form-row" key={f.name}>
                          <div className="mm-flabel">{f.label}</div>
                          <textarea
                            className="mm-textarea"
                            value={val}
                            onChange={(e) => setVal(e.target.value)}
                          />
                        </div>
                      );
                    }
                    const isNum = f.type === 'number' || f.type === 'coord';
                    return (
                      <div className="mm-form-row" key={f.name}>
                        <div className="mm-flabel">
                          {f.label}
                          {f.required && <span className="mm-req"> *</span>}
                        </div>
                        <input
                          className="mm-input"
                          type={isNum ? 'number' : 'text'}
                          step={f.type === 'coord' ? 'any' : undefined}
                          value={val}
                          onChange={(e) => setVal(e.target.value)}
                        />
                      </div>
                    );
                  })}
                </div>

                <div className="mm-form-actions">
                  <button className="mm-back" onClick={() => setForm(null)} disabled={saving}>
                    Cancel
                  </button>
                  <button className="mm-add" onClick={submitForm} disabled={saving}>
                    {saving ? 'SAVING…' : form.mode === 'edit' ? 'SAVE CHANGES' : 'ADD MARKER'}
                  </button>
                </div>
              </div>
            )}
          </aside>
        )}

        {toast && (
          <div className={`mm-toast${toast.kind === 'err' ? ' err' : ''}`}>{toast.msg}</div>
        )}
      </div>
    </div>
  );
}
