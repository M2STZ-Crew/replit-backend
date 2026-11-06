import 'leaflet/dist/leaflet.css';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Circle,
  CircleMarker,
  MapContainer,
  Marker,
  Tooltip,
  useMapEvents,
  ZoomControl,
} from 'react-leaflet';

import BaseTiles, { useConsoleTheme } from '../map/BaseTiles.jsx';

import { api } from '../api/client.js';
import { outsidePasayStyle } from '../components/LiveMap.jsx';
import { ConfirmDialog } from '../components/ui/index.js';
import {
  RISK_CIRCLE_STYLE, RISK_RADIUS_M, RISK_RADIUS_MAX_M, RISK_RADIUS_MIN_M, markerIcon, riskRadius,
} from '../components/map/markers.js';
import { statusOf } from '../lib/status.js';
import { t } from '../i18n/i18n.jsx';

const PASAY = [14.5378, 121.0014];

// Marker colours per layer key.
const COLORS = {
  incidents: '#FF544E',
  evac: '#22C55E',
  risk: '#FF9066',
  hydrants: '#767575',
  water: '#4EA8FF',
  cisterns: '#9A8CFF',
};

// The five layers an admin can create/update/delete here.
const EDIT_LAYERS = [
  { key: 'risk', get label() { return t('Risk Areas'); }, get singular() { return t('Risk Area'); }, path: 'risk-zones', icon: '⚠', get tagline() { return t('High-priority zones'); } },
  { key: 'evac', get label() { return t('Evacuation Sites'); }, get singular() { return t('Evacuation Site'); }, path: 'evacuation-sites', icon: '🚪', get tagline() { return t('Safe gathering points — Pasay and beyond'); } },
  { key: 'hydrants', get label() { return t('Fire Hydrants'); }, get singular() { return t('Fire Hydrant'); }, path: 'hydrants', icon: '🚰', get tagline() { return t('Water supply points'); } },
  { key: 'water', get label() { return t('Bodies of Water'); }, get singular() { return t('Body of Water'); }, path: 'bodies-of-water', icon: '🌊', get tagline() { return t('Natural water sources'); } },
  { key: 'cisterns', get label() { return t('Underground Cisterns'); }, get singular() { return t('Cistern'); }, path: 'underground-cisterns', icon: '🛢', get tagline() { return t('Underground reserves'); } },
];

// The toggle chips on the map (order mirrors the design). `kind`:
//   'edit'      → an editable GIS layer with backend data
//   'incidents' → live incidents (read-only here; a click opens the incident)
//
// The design also showed Response Teams, Fire/Police Department, Hospital and
// Barangay Hall chips. None has data behind it — there is no station GIS
// table, and responder positions are per incident — so, as §2.7.1 asks, they
// are left out rather than drawn as toggles that do nothing.
const CHIPS = [
  { key: 'incidents', get label() { return t('Incidents'); }, kind: 'incidents' },
  { key: 'evac', get label() { return t('Evacuation Sites'); }, kind: 'edit' },
  { key: 'risk', get label() { return t('Risk Areas'); }, kind: 'edit' },
  { key: 'hydrants', get label() { return t('Fire Hydrants'); }, kind: 'edit' },
  { key: 'water', get label() { return t('Bodies of Water'); }, kind: 'edit' },
  { key: 'cisterns', get label() { return t('Underground Cisterns'); }, kind: 'edit' },
];

const RISK_OPTS = ['low', 'medium', 'high', 'critical'];
const STATUS_OPTS = ['operational', 'non_operational', 'under_maintenance', 'unknown'];

// Form field schema per editable layer (mirrors the backend create/update models).
const FIELDS = {
  risk: [
    { name: 'barangay', get label() { return t('Barangay'); }, type: 'text', required: true },
    { name: 'name', get label() { return t('Name'); }, type: 'text' },
    { name: 'risk_level', get label() { return t('Risk level'); }, type: 'select', options: RISK_OPTS, default: 'medium' },
    { name: 'centroid_lat', get label() { return t('Latitude'); }, type: 'coord', coord: 'lat', required: true },
    { name: 'centroid_lng', get label() { return t('Longitude'); }, type: 'coord', coord: 'lng', required: true },
    // The zone is its icon inside this circle, on every map.
    { name: 'radius_m', get label() { return t('Radius (metres)'); }, type: 'radius', required: true, default: String(RISK_RADIUS_M) },
    { name: 'description', get label() { return t('Description'); }, type: 'textarea' },
  ],
  evac: [
    { name: 'name', get label() { return t('Name'); }, type: 'text', required: true },
    { name: 'latitude', get label() { return t('Latitude'); }, type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', get label() { return t('Longitude'); }, type: 'coord', coord: 'lng', required: true },
    // Section 2.4: a fire in Pasay may need a shelter in the next city. Any city
    // other than Pasay is drawn with the distinct outside-Pasay marker.
    { name: 'city', get label() { return t('City / municipality'); }, type: 'text', required: true, default: 'Pasay City' },
    { name: 'capacity', get label() { return t('Capacity'); }, type: 'number' },
    { name: 'address', get label() { return t('Address'); }, type: 'text' },
    { name: 'contact_info', get label() { return t('Contact info'); }, type: 'text' },
    { name: 'is_active', get label() { return t('Active'); }, type: 'checkbox', default: true },
  ],
  hydrants: [
    { name: 'code', get label() { return t('Code'); }, type: 'text' },
    { name: 'latitude', get label() { return t('Latitude'); }, type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', get label() { return t('Longitude'); }, type: 'coord', coord: 'lng', required: true },
    { name: 'address', get label() { return t('Address'); }, type: 'text' },
    { name: 'bfp_status', get label() { return t('Status'); }, type: 'select', options: STATUS_OPTS, default: 'unknown' },
    { name: 'is_active', get label() { return t('Active'); }, type: 'checkbox', default: true },
  ],
  water: [
    { name: 'name', get label() { return t('Name'); }, type: 'text', required: true },
    { name: 'water_type', get label() { return t('Water type'); }, type: 'text' },
    { name: 'latitude', get label() { return t('Latitude'); }, type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', get label() { return t('Longitude'); }, type: 'coord', coord: 'lng', required: true },
    { name: 'is_accessible', get label() { return t('Accessible'); }, type: 'checkbox', default: true },
    { name: 'description', get label() { return t('Description'); }, type: 'textarea' },
  ],
  cisterns: [
    { name: 'name', get label() { return t('Name'); }, type: 'text' },
    { name: 'code', get label() { return t('Code'); }, type: 'text' },
    { name: 'latitude', get label() { return t('Latitude'); }, type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', get label() { return t('Longitude'); }, type: 'coord', coord: 'lng', required: true },
    { name: 'capacity_liters', get label() { return t('Capacity (liters)'); }, type: 'number' },
    { name: 'status', get label() { return t('Status'); }, type: 'select', options: STATUS_OPTS, default: 'unknown' },
    { name: 'address', get label() { return t('Address'); }, type: 'text' },
    { name: 'description', get label() { return t('Description'); }, type: 'textarea' },
    { name: 'is_active', get label() { return t('Active'); }, type: 'checkbox', default: true },
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

// Switched off with Active: off every map, but still here to switch back on.
function inactive(r) {
  return r.is_active === false;
}

function entryText(key, r) {
  const { title, sub } = baseText(key, r);
  return { title, sub: inactive(r) ? t('Inactive · {sub}', { sub }) : sub };
}

function baseText(key, r) {
  switch (key) {
    case 'risk':
      return {
        title: r.name || t('Risk Area · {barangay}', { barangay: r.barangay }),
        sub: t('{level} · Brgy. {barangay} · {radius} m', { level: prettify(r.risk_level), barangay: r.barangay, radius: Math.round(riskRadius(r)) }),
      };
    case 'evac': {
      const base =
        r.capacity != null
          ? (r.address
            ? t('Capacity {capacity} · {address}', { capacity: r.capacity, address: r.address })
            : t('Capacity {capacity}', { capacity: r.capacity }))
          : r.address || t('Evacuation site');
      return {
        title: r.name,
        sub: r.outside_pasay ? t('Outside Pasay · {city} · {base}', { city: r.city, base }) : base,
      };
    }
    case 'hydrants':
      return {
        title: r.code || t('Hydrant'),
        sub: `${prettify(r.effective_status)}${r.address ? ` · ${r.address}` : ''}`,
      };
    case 'water':
      return {
        title: r.name,
        sub: `${r.water_type || t('Water source')} · ${r.is_accessible ? t('Accessible') : t('Restricted')}`,
      };
    case 'cisterns':
      return {
        title: r.name || r.code || t('Cistern'),
        sub: `${prettify(r.status)}${r.capacity_liters ? ` · ${r.capacity_liters} L` : ''}`,
      };
    default:
      return { title: '—', sub: '' };
  }
}

function coerce(field, raw) {
  if (field.type === 'checkbox') return !!raw;
  if (field.type === 'number' || field.type === 'coord' || field.type === 'radius') {
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
      vals[f.name] = f.type === 'checkbox'
        ? !!v
        : v == null ? (f.type === 'radius' ? f.default : '') : String(v);
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

export default function MapManagement({ query = '', initialLayer, onOpenIncident }) {
  const theme = useConsoleTheme();
  const [data, setData] = useState({}); // key → array of rows
  const [incidents, setIncidents] = useState([]);
  const [enabled, setEnabled] = useState(
    () => new Set(['incidents', 'risk', 'evac', 'hydrants', 'water', 'cisterns']),
  );
  const [selected, setSelected] = useState(initialLayer ?? 'risk');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState([]); // layer keys that did not load
  const [attempt, setAttempt] = useState(0);
  const [deleting, setDeleting] = useState(null); // { layer, rec }
  // Open beside the map on a desktop. Closed on a phone, where the editor is a
  // bottom sheet that would otherwise cover most of the map on arrival.
  const [panelOpen, setPanelOpen] = useState(
    () => !window.matchMedia('(max-width: 700px)').matches,
  );
  const [form, setForm] = useState(null); // { layer, mode, id, values }
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  // After a save: on failure the old rows stay, and the toast says so.
  async function loadLayer(key) {
    const rows = await api.mapLayer(cfgOf(key).path, { includeInactive: true });
    setData((d) => ({ ...d, [key]: Array.isArray(rows) ? rows : [] }));
  }

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      const results = await Promise.allSettled(
        EDIT_LAYERS.map((l) => api.mapLayer(l.path, { includeInactive: true })),
      );
      const inc = await api.incidents().catch(() => []);
      if (!alive) return;
      const next = {};
      EDIT_LAYERS.forEach((l, i) => {
        const { value } = results[i];
        next[l.key] = Array.isArray(value) ? value : [];
      });
      setData(next);
      setFailed(EDIT_LAYERS.filter((_, i) => results[i].status === 'rejected').map((l) => l.key));
      setIncidents(Array.isArray(inc) ? inc : []);
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [attempt]);

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
        flash(t('{field} is required.', { field: f.label }), 'err');
        return;
      }
      if (f.coord && c != null) {
        const limit = f.coord === 'lat' ? 90 : 180;
        if (Math.abs(c) > limit) {
          flash(t('{label} goes from -{limit} to {limit2}.', { label: f.label, limit, limit2: limit }), 'err');
          return;
        }
      }
      if (f.type === 'number' && c != null && c < 0) {
        flash(t('{field} can’t be negative.', { field: f.label }), 'err');
        return;
      }
      if (f.type === 'radius' && (c < RISK_RADIUS_MIN_M || c > RISK_RADIUS_MAX_M)) {
        flash(t('The radius goes from {RISK_RADIUS_MIN_M} to {RISK_RADIUS_MAX_M} metres.', { RISK_RADIUS_MIN_M, RISK_RADIUS_MAX_M }), 'err');
        return;
      }
      payload[f.name] = c;
    }
    setSaving(true);
    try {
      const path = cfgOf(layer).path;
      if (form.mode === 'edit') await api.mapLayerUpdate(path, form.id, payload);
      else await api.mapLayerCreate(path, payload);
      setForm(null);
      flash(form.mode === 'edit' ? t('Marker updated.') : t('Marker added.'));
    } catch (e) {
      flash(e.message || t('Save failed.'), 'err');
      return;
    } finally {
      setSaving(false);
    }
    try {
      await loadLayer(layer);
    } catch {
      flash(t('Saved, but the list could not be refreshed. Try again.'), 'err');
      setFailed((keys) => [...new Set([...keys, layer])]);
    }
  }

  const confirmDelete = useCallback(async () => {
    const { layer, rec } = deleting;
    await api.mapLayerDelete(cfgOf(layer).path, rec.id);
    // Gone from every map; take it off this one without another read.
    setData((d) => ({ ...d, [layer]: (d[layer] || []).filter((r) => r.id !== rec.id) }));
    setForm((f) => (f && f.id === rec.id ? null : f));
    setDeleting(null);
    flash(t('Marker deleted.'));
  }, [deleting]);

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
    // A risk zone being edited shows the circle it will have.
    const radius = form.layer === 'risk' ? Number(form.values.radius_m) : NaN;
    return {
      lat,
      lng,
      color: COLORS[form.layer],
      radius: Number.isFinite(radius) && radius >= RISK_RADIUS_MIN_M ? radius : null,
    };
  }, [form]);

  return (
    <div className="mm-root">
      <div className="mm-map">
        <MapContainer
          center={PASAY}
          zoom={13}
          style={{ height: '100%', width: '100%', background: 'var(--map-ground)' }}
          zoomControl={false}
          attributionControl={false}
        >
          <BaseTiles />
          <ZoomControl position="bottomleft" />
          <ClickCapture active={!!form} onPick={handlePick} />

          {/* incidents — status-coloured, and a click opens the incident
              (unless a marker is being placed, when the click places it) */}
          {enabled.has('incidents') &&
            incidents.map((inc) => {
              if (inc.centroid_lat == null || inc.centroid_lng == null) return null;
              const st = statusOf(inc.status);
              return (
                <CircleMarker
                  key={`inc-${inc.id}`}
                  center={[inc.centroid_lat, inc.centroid_lng]}
                  radius={9}
                  pathOptions={{
                    color: '#fff',
                    weight: 1.5,
                    fillColor: st.color,
                    fillOpacity: 0.95,
                  }}
                  eventHandlers={
                    onOpenIncident && !form ? { click: () => onOpenIncident(inc.id) } : undefined
                  }
                >
                  <Tooltip>
                    {(inc.designation || t('Incident'))} · {st.label}
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
              // The zone being edited is drawn by the form preview instead.
              if (l.key === 'risk' && form?.layer === 'risk' && form.id === r.id) return null;
              if (l.key === 'risk') {
                // A risk zone is its icon inside its circle (24 Oct 2026).
                return [
                  <Circle
                    key={`halo-${r.id}`}
                    center={[p.lat, p.lng]}
                    radius={riskRadius(r)}
                    pathOptions={RISK_CIRCLE_STYLE}
                    // While a marker is being placed, a click inside a zone
                    // places it rather than opening that zone.
                    eventHandlers={form ? undefined : { click: () => openEdit('risk', r) }}
                  />,
                  <Marker
                    key={`m-${r.id}`}
                    position={[p.lat, p.lng]}
                    icon={markerIcon('risk')}
                    eventHandlers={{ click: () => openEdit('risk', r) }}
                  >
                    <Tooltip direction="top" offset={[0, -18]}>
                      {title}
                      {sub ? ` · ${sub}` : ''}
                    </Tooltip>
                  </Marker>,
                ];
              }
              return [
                <CircleMarker
                  key={`m-${r.id}`}
                  center={[p.lat, p.lng]}
                  radius={l.key === 'evac' && r.outside_pasay ? 9 : 7}
                  pathOptions={
                    l.key === 'evac' && r.outside_pasay
                      ? outsidePasayStyle(theme)
                      : { color: '#fff', weight: 1, fillColor: color, fillOpacity: inactive(r) ? 0.35 : 0.95 }
                  }
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

          {/* form preview: the risk zone's circle as it will be saved */}
          {formPoint?.radius && (
            <Circle
              center={[formPoint.lat, formPoint.lng]}
              radius={formPoint.radius}
              pathOptions={{ ...RISK_CIRCLE_STYLE, dashArray: '6 4', fillOpacity: 0.18 }}
              interactive={false}
            />
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
        {/* A class, not an inline right offset: the offset differs by screen
            width, and a 372px inline value left a phone's bar with no width. */}
        <div className={`mm-layers${panelOpen ? ' is-panel-open' : ''}`}>
          <span className="mm-layers-label">{t('☰ Layers')}</span>
          <div className="mm-chips">
            {CHIPS.map((c) => {
              const on = enabled.has(c.key);
              const color = COLORS[c.key];
              const count = c.kind === 'edit' ? (data[c.key] || []).length : incidents.length;
              return (
                <button
                  key={c.key}
                  className={`mm-chip${on ? ' on' : ''}`}
                  onClick={() => toggleChip(c.key)}
                  style={on ? { borderColor: `${color}88` } : undefined}
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
          <button className="mm-reopen" onClick={() => setPanelOpen(true)} title={t('Open editor')}>{t('‹ Layers')}</button>
        )}

        {/* editor panel */}
        {panelOpen && (
          <aside className="mm-panel">
            <div className="mm-panel-head">
              <div>
                <div className="mm-panel-eyebrow">{t('Shared by every organization')}</div>
                <div className="mm-panel-title">{t('Map settings')}</div>
              </div>
              <button
                className="mm-collapse"
                onClick={() => setPanelOpen(false)}
                title={t('Collapse')}
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

                <div className="mm-list" aria-busy={loading}>
                  {loading && <div className="mm-empty">{t('Loading {things}…', { things: selCfg.label.toLowerCase() })}</div>}
                  {!loading && failed.includes(selected) && (
                    <div className="mm-empty" role="alert">
                      {t('{things} could not be loaded.', { things: selCfg.label })}{' '}
                      <button type="button" className="mm-retry" onClick={() => setAttempt((n) => n + 1)}>{t('Try again')}</button>
                    </div>
                  )}
                  {!loading && !failed.includes(selected) && selRows.length === 0 && (
                    <div className="mm-empty">{t('No {things} yet.', { things: selCfg.label.toLowerCase() })}</div>
                  )}
                  {selRows.length > 0 && shownRows.length === 0 && (
                    <div className="mm-empty">{t('No matches for “{query}”.', { query })}</div>
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
                            title={t('Edit')}
                          >
                            ✎
                          </button>
                          <button
                            className="mm-iconbtn del"
                            onClick={() => setDeleting({ layer: selected, rec: r })}
                            title={t('Delete')}
                          >
                            🗑
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <button className="mm-add" onClick={openAdd}>{t('+ ADD')}{' '}{selCfg.singular.toUpperCase()}
                </button>
              </div>
            ) : (
              <div className="mm-panel-body">
                <div className="mm-form-title">
                  {form.mode === 'edit' ? t('Edit') : t('New')} {cfgOf(form.layer).singular}
                </div>
                <div className="mm-hint">{t('Click the map to set the location.')}</div>

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
                    if (f.type === 'radius') {
                      // A slider for the usual sizes and the exact number,
                      // both in metres; the circle on the map follows either.
                      const n = Number(val);
                      const id = `mm-${f.name}`;
                      return (
                        <div className="mm-form-row" key={f.name}>
                          <label className="mm-flabel" htmlFor={id}>
                            {f.label}
                            {f.required && <span className="mm-req"> *</span>}
                          </label>
                          <div className="mm-radius">
                            <input
                              className="mm-radius-slider"
                              type="range"
                              min={25}
                              max={1000}
                              step={5}
                              value={Number.isFinite(n) ? Math.min(Math.max(n, 25), 1000) : RISK_RADIUS_M}
                              onChange={(e) => setVal(e.target.value)}
                              aria-label={t('{field}, slider', { field: f.label })}
                            />
                            <input
                              id={id}
                              className="mm-input mm-radius-number"
                              type="number"
                              min={RISK_RADIUS_MIN_M}
                              max={RISK_RADIUS_MAX_M}
                              step={5}
                              value={val}
                              onChange={(e) => setVal(e.target.value)}
                            />
                          </div>
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
                  <button className="mm-back" onClick={() => setForm(null)} disabled={saving}>{t('Cancel')}</button>
                  <button className="mm-add" onClick={submitForm} disabled={saving}>
                    {saving ? t('SAVING…') : form.mode === 'edit' ? t('SAVE CHANGES') : t('ADD MARKER')}
                  </button>
                </div>
              </div>
            )}
          </aside>
        )}

        {toast && (
          <div className={`mm-toast${toast.kind === 'err' ? ' err' : ''}`} role="status">{toast.msg}</div>
        )}
      </div>

      <ConfirmDialog
        open={!!deleting}
        eyebrow={deleting ? cfgOf(deleting.layer).singular : undefined}
        title={deleting ? t('Delete {title}?', { title: entryText(deleting.layer, deleting.rec).title }) : ''}
        description={t('It disappears from every Admin’s map and every phone’s map. This can’t be undone.')}
        confirmLabel={deleting ? t('Delete {thing}', { thing: cfgOf(deleting.layer).singular.toLowerCase() }) : t('Delete')}
        destructive
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
