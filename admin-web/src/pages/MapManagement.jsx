import 'leaflet/dist/leaflet.css';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Circle,
  CircleMarker,
  MapContainer,
  Marker,
  Tooltip,
  useMap,
  useMapEvents,
  ZoomControl,
} from 'react-leaflet';

import BaseTiles, { useConsoleTheme } from '../map/BaseTiles.jsx';
import ZoomGate, { LAYER_MIN_ZOOM } from '../map/ZoomGate.jsx';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import { outsidePasayStyle } from '../components/LiveMap.jsx';
import { PointFacts, RISK } from '../components/map/PointDetail.jsx';
import {
  ConfirmDialog, Icon, Pager, SearchBox, Select, StatusChip, usePager,
} from '../components/ui/index.js';
import Skeleton from '../components/ui/Skeleton.jsx';
import {
  RISK_CIRCLE_STYLE, RISK_RADIUS_M, RISK_RADIUS_MAX_M, RISK_RADIUS_MIN_M, markerIcon, riskRadius,
} from '../components/map/markers.js';
import WaterRequests, { WATER_REQUEST_LAYERS } from '../components/water/WaterRequests.jsx';
import { PERM, can } from '../lib/access.js';
import { degrees, fireName, knownAddress, mapsLink } from '../lib/place.js';
import { statusOf } from '../lib/status.js';
import { WATER_STATUS, checkedOf, waterStatusOf, when } from '../lib/water.js';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import { t } from '../i18n/i18n.jsx';
import FirePulse from '../map/FirePulse.jsx';
import { alarmStatusOf } from '../lib/alarmStatus.js';

/* Map settings: the five layers every organisation's maps share.
 *
 * v1.12.50 (22 Nov 2026: "Pagsamahin nalang tong dalawang Page nato Tanggalin
 * na yung Water Resources Page ilagay nalang ito sa Map Settings Page katulad
 * ng dati"): Water resources is here again, with its Requests as the Water
 * requests tab and without its List, Map and Edit on map. Answered:
 *  - "All open, same rights": every Admin opens it. Fire Volunteer, BFP,
 *    central hub and system Admins add, edit and delete everything and
 *    approve water requests; the others view, and delete water.
 *  - "Into the side list": the list beside the map has the search, the status
 *    filter, each status in its colour, and the last check with who. A row
 *    opens its place on the map.
 * The server checks each of those again (map.manage, water.delete). */

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
// A hydrant checked on the ground in the last 6 months has a hydrant's own
// colour; the rest are gray (v1.12.46).
const VERIFIED_HYDRANT = '#4168AE';

// The five layers an admin can create/update/delete here. Each `icon` is
// its glyph in public/icons/layers (13 November 2026: the supplied icons in
// place of the emoji they had), drawn by <Icon> in the layer's colour.
const EDIT_LAYERS = [
  { key: 'hydrants', get label() { return t('Fire Hydrants'); }, get singular() { return t('Fire Hydrant'); }, path: 'hydrants', icon: 'layers/fire-hydrants', get tagline() { return t('Water supply points'); } },
  { key: 'water', get label() { return t('Bodies of Water'); }, get singular() { return t('Body of Water'); }, path: 'bodies-of-water', icon: 'layers/bodies-of-water', get tagline() { return t('Natural water sources'); } },
  { key: 'cisterns', get label() { return t('Underground Cisterns'); }, get singular() { return t('Cistern'); }, path: 'underground-cisterns', icon: 'layers/underground-cisterns', get tagline() { return t('Underground reserves'); } },
  { key: 'evac', get label() { return t('Evacuation Sites'); }, get singular() { return t('Evacuation Site'); }, path: 'evacuation-sites', icon: 'layers/evacuation-sites', get tagline() { return t('Safe gathering points — Pasay and beyond'); } },
  { key: 'risk', get label() { return t('Risk Areas'); }, get singular() { return t('Risk Area'); }, path: 'risk-zones', icon: 'layers/risk-areas', get tagline() { return t('High-priority zones'); } },
];
const WATER_LAYERS = ['hydrants', 'water', 'cisterns'];
const isWater = (key) => WATER_LAYERS.includes(key);
// The live map's word for each layer's places (components/map/PointDetail).
const KIND = { hydrants: 'hydrant', water: 'water', cisterns: 'cistern', evac: 'shelter', risk: 'risk' };
// A water request's layer, as this page names it.
const LAYER_OF_REQUEST = { hydrant: 'hydrants', bodies_of_water: 'water', underground_cistern: 'cisterns' };

// The toggle chips on the map. `kind`:
//   'edit'      → an editable GIS layer with backend data
//   'incidents' → live incidents (read-only here; a click opens the incident)
//
// The design also showed Response Teams, Fire/Police Department, Hospital and
// Barangay Hall chips. None has data behind it — there is no station GIS
// table, and responder positions are per incident — so, as §2.7.1 asks, they
// are left out rather than drawn as toggles that do nothing.
const CHIPS = [
  { key: 'incidents', get label() { return t('Incidents'); }, kind: 'incidents' },
  { key: 'hydrants', get label() { return t('Fire Hydrants'); }, kind: 'edit' },
  { key: 'water', get label() { return t('Bodies of Water'); }, kind: 'edit' },
  { key: 'cisterns', get label() { return t('Underground Cisterns'); }, kind: 'edit' },
  { key: 'evac', get label() { return t('Evacuation Sites'); }, kind: 'edit' },
  { key: 'risk', get label() { return t('Risk Areas'); }, kind: 'edit' },
];

const RISK_OPTS = ['low', 'medium', 'high', 'critical'];
// From the field since v1.12.43: low pressure, no access.
const STATUS_OPTS = ['operational', 'non_operational', 'low_pressure', 'no_access', 'under_maintenance', 'unknown'];

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
    { name: 'bfp_status', get label() { return t('BFP status'); }, type: 'select', options: STATUS_OPTS, default: 'unknown' },
    { name: 'is_active', get label() { return t('Active'); }, type: 'checkbox', default: true },
  ],
  water: [
    { name: 'name', get label() { return t('Name'); }, type: 'text', required: true },
    { name: 'water_type', get label() { return t('Water type'); }, type: 'text' },
    { name: 'latitude', get label() { return t('Latitude'); }, type: 'coord', coord: 'lat', required: true },
    { name: 'longitude', get label() { return t('Longitude'); }, type: 'coord', coord: 'lng', required: true },
    { name: 'is_accessible', get label() { return t('Accessible'); }, type: 'checkbox', default: true },
    { name: 'description', get label() { return t('Description'); }, type: 'textarea' },
    // Switched off, it leaves every map but this one (v1.12.43).
    { name: 'is_active', get label() { return t('Active'); }, type: 'checkbox', default: true },
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

function choiceLabel(field, value) {
  return (field.name === 'risk_level' ? RISK[value] : WATER_STATUS[value])?.label ?? value;
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

function titleOf(key, r) {
  switch (key) {
    case 'risk': return r.name || t('Risk Area · {barangay}', { barangay: r.barangay });
    case 'hydrants': return r.code || t('Hydrant');
    case 'cisterns': return r.name || r.code || t('Cistern');
    default: return r.name || '—';
  }
}

/* Where it is, in words: its own address, the street looked up for it once
 * known, else the degrees. */
function whereOf(key, r) {
  if (r.address) return r.address;
  const { lat, lng } = pointOf(key, r);
  if (lat == null || lng == null) return '';
  return knownAddress(lat, lng) || degrees(lat, lng);
}

/* A row's second line. */
function lineOf(key, r) {
  if (key === 'risk') {
    return t('{level} · Brgy. {barangay} · {radius} m', {
      level: RISK[r.risk_level]?.label ?? r.risk_level ?? '—', barangay: r.barangay, radius: Math.round(riskRadius(r)),
    });
  }
  if (key === 'evac') {
    const base = r.capacity != null
      ? (r.address
        ? t('Capacity {capacity} · {address}', { capacity: r.capacity, address: r.address })
        : t('Capacity {capacity}', { capacity: r.capacity }))
      : r.address || t('Evacuation site');
    return r.outside_pasay ? t('Outside Pasay · {city} · {base}', { city: r.city, base }) : base;
  }
  if (key === 'water') return [r.water_type, whereOf(key, r)].filter(Boolean).join(' · ');
  return whereOf(key, r);
}

/* A water source's third line: when it was last looked at, and by whom. */
function lastCheck(key, r) {
  if (!isWater(key)) return null;
  if (key === 'hydrants') {
    return r.ground_truth_at
      ? t('Checked {at}', { at: checkedOf({ ...r, kind: 'hydrant' }).at ?? '—' })
      : t('Never checked on the ground');
  }
  const at = when(r.updated_at);
  return at ? t('Record updated {at}', { at }) : null;
}

/* Its state in colour and words. */
function chipOf(key, r) {
  if (inactive(r)) return { label: t('Inactive'), tone: 'neutral' };
  return isWater(key) ? waterStatusOf({ ...r, kind: KIND[key] }) : null;
}

function stateKey(key, r) {
  if (inactive(r)) return 'inactive';
  if (key === 'water') return r.is_accessible ? 'accessible' : 'not_accessible';
  const value = key === 'hydrants' ? r.effective_status : r.status;
  return WATER_STATUS[value] ? value : 'unknown';
}

function stateChoices(key, withInactive) {
  const states = key === 'water'
    ? [{ key: 'accessible', label: t('Accessible') }, { key: 'not_accessible', label: t('Not accessible') }]
    : Object.entries(WATER_STATUS).map(([value, s]) => ({ key: value, label: s.label }));
  return withInactive ? [...states, { key: 'inactive', label: t('Inactive') }] : states;
}

function found(key, r, term) {
  return [titleOf(key, r), lineOf(key, r), r.name, r.code, r.address, r.city, r.barangay, whereOf(key, r)]
    .filter(Boolean).join(' ').toLowerCase()
    .includes(term);
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

/* The place asked for, in the middle of the map the panel leaves free: beside
 * it on a desktop, above it where it is a sheet. */
function CenterOn({ point, panel }) {
  const map = useMap();
  useEffect(() => {
    if (point?.lat == null || point?.lng == null) return;
    const zoom = Math.max(map.getZoom(), LAYER_MIN_ZOOM + 2);
    const box = map.getContainer().getBoundingClientRect();
    const cover = panel.current?.getBoundingClientRect();
    let dx = 0;
    let dy = 0;
    if (cover?.width) {
      if (cover.width >= box.width - 2) dy = (box.bottom - cover.top) / 2;
      else dx = (box.right - cover.left) / 2;
    }
    const middle = map.project([point.lat, point.lng], zoom).add([dx, dy]);
    map.setView(map.unproject(middle, zoom), zoom, { animate: false });
  }, [map, point, panel]);
  return null;
}

function Field({ field, value, onChange }) {
  const name = (
    <span className="mm-flabel">
      {field.label}
      {field.required && <span className="mm-req"> *</span>}
    </span>
  );
  if (field.type === 'checkbox') {
    return (
      <label className="mm-checkbox-row">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
      </label>
    );
  }
  if (field.type === 'select') {
    return (
      <Select
        variant="field"
        label={field.label}
        value={value}
        onChange={onChange}
        options={field.options.map((key) => ({ key, label: choiceLabel(field, key) }))}
      />
    );
  }
  if (field.type === 'radius') {
    // A slider for the usual sizes and the exact number, both in metres; the
    // circle on the map follows either.
    const n = Number(value);
    const id = `mm-${field.name}`;
    return (
      <div className="mm-form-row">
        <label htmlFor={id}>{name}</label>
        <div className="mm-radius">
          <input
            className="mm-radius-slider"
            type="range"
            min={25}
            max={1000}
            step={5}
            value={Number.isFinite(n) ? Math.min(Math.max(n, 25), 1000) : RISK_RADIUS_M}
            onChange={(e) => onChange(e.target.value)}
            aria-label={t('{field}, slider', { field: field.label })}
          />
          <input
            id={id}
            className="mm-input mm-radius-number"
            type="number"
            min={RISK_RADIUS_MIN_M}
            max={RISK_RADIUS_MAX_M}
            step={5}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
      </div>
    );
  }
  if (field.type === 'textarea') {
    return (
      <label className="mm-form-row">
        {name}
        <textarea className="mm-textarea" value={value} onChange={(e) => onChange(e.target.value)} />
      </label>
    );
  }
  const isNum = field.type === 'number' || field.type === 'coord';
  return (
    <label className="mm-form-row">
      {name}
      <input
        className="mm-input"
        type={isNum ? 'number' : 'text'}
        step={field.type === 'coord' ? 'any' : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

/* `initialEdit` ({ layer, id }): Edit pressed on the live map's details panel
 * (v1.12.47); this opens on that place's form, with the map on it. */
export default function MapManagement({ initialLayer, initialEdit = null, onOpenIncident }) {
  const theme = useConsoleTheme();
  const { console: access, refreshQueues } = useConsole();
  const { incidents, loaded: feedLoaded } = useLiveFeed();
  const manages = can(access, PERM.MANAGE_MAP);
  const deletesWater = can(access, PERM.DELETE_WATER);
  const mayDelete = (layer) => manages || (deletesWater && isWater(layer));

  const [view, setView] = useState('map');
  const [data, setData] = useState({}); // key → array of rows
  const [enabled, setEnabled] = useState(
    () => new Set(['incidents', ...EDIT_LAYERS.map((l) => l.key)]),
  );
  const [selected, setSelected] = useState(cfgOf(initialLayer)?.key ?? EDIT_LAYERS[0].key);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState([]); // layer keys that did not load
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const [opened, setOpened] = useState(null); // { layer, id }
  const [deleting, setDeleting] = useState(null); // { layer, rec }
  // Open beside the map on a desktop. Closed on a phone, where the editor is a
  // bottom sheet that would otherwise cover most of the map on arrival.
  const [panelOpen, setPanelOpen] = useState(
    () => Boolean(initialEdit) || !window.matchMedia('(max-width: 700px)').matches,
  );
  const [form, setForm] = useState(null); // { layer, mode, id, values }
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [focus, setFocus] = useState(null);
  const [requests, setRequests] = useState({ loading: manages, error: null, rows: [] });
  const [requestAttempt, setRequestAttempt] = useState(0);
  const editOpened = useRef(false);
  const panel = useRef(null);
  const body = useRef(null);
  const heading = useRef(null);
  const listTop = useRef(0);
  const lastRow = useRef(null);

  // After a save: on failure the old rows stay, and the toast says so.
  async function loadLayer(key) {
    const rows = await api.mapLayer(cfgOf(key).path, { includeInactive: manages });
    setData((d) => ({ ...d, [key]: Array.isArray(rows) ? rows : [] }));
  }

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      const results = await Promise.allSettled(
        EDIT_LAYERS.map((l) => api.mapLayer(l.path, { includeInactive: manages })),
      );
      if (!alive) return;
      const next = {};
      EDIT_LAYERS.forEach((l, i) => {
        const { value } = results[i];
        next[l.key] = Array.isArray(value) ? value : [];
      });
      setData(next);
      setFailed(EDIT_LAYERS.filter((_, i) => results[i].status === 'rejected').map((l) => l.key));
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [attempt, manages]);

  // Coordinators' water changes awaiting an Admin (v1.12.43).
  useEffect(() => {
    if (!manages) return undefined;
    let alive = true;
    setRequests((r) => ({ ...r, loading: r.rows.length === 0, error: null }));
    api.mapLayerRequests('pending')
      .then((rows) => {
        if (!alive) return;
        const water = (Array.isArray(rows) ? rows : []).filter((r) => WATER_REQUEST_LAYERS.includes(r.layer_type));
        setRequests({ loading: false, error: null, rows: water });
      })
      .catch((e) => {
        if (alive) setRequests({ loading: false, error: e.message || t('The requests could not be loaded.'), rows: [] });
      });
    return () => { alive = false; };
  }, [manages, requestAttempt]);

  const flash = useCallback((msg, kind = 'ok') => setToast({ msg, kind }), []);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), toast.kind === 'err' ? 6000 : 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  function toggleChip(key) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectLayer(key) {
    if (key === selected) return;
    setSelected(key);
    setQuery('');
    setStateFilter('all');
    listTop.current = 0;
  }

  function openAdd() {
    setOpened(null);
    setForm({ layer: selected, mode: 'add', id: null, values: initValues(selected, null) });
  }

  function openEdit(layer, rec) {
    selectLayer(layer);
    setForm({ layer, mode: 'edit', id: rec.id, values: initValues(layer, rec) });
  }

  // A row or a marker opens the place: what it is, and what may be done to it.
  function openPlace(layer, rec, { move = false } = {}) {
    selectLayer(layer);
    setOpened({ layer, id: rec.id });
    setPanelOpen(true);
    if (!move) return;
    setEnabled((on) => (on.has(layer) ? on : new Set([...on, layer])));
    setFocus(pointOf(layer, rec));
  }

  // The place Edit was pressed for, once the layers are in.
  useEffect(() => {
    if (loading || editOpened.current || !initialEdit) return;
    editOpened.current = true;
    const rec = (data[initialEdit.layer] || []).find((r) => r.id === initialEdit.id);
    if (!rec) {
      flash(t('That place is no longer on the map.'), 'err');
      return;
    }
    if (manages) openEdit(initialEdit.layer, rec);
    setOpened({ layer: initialEdit.layer, id: rec.id });
    setPanelOpen(true);
    setFocus(pointOf(initialEdit.layer, rec));
  }, [loading, data, initialEdit]); // eslint-disable-line react-hooks/exhaustive-deps

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

  async function confirmDelete() {
    const { layer, rec } = deleting;
    await api.mapLayerDelete(cfgOf(layer).path, rec.id);
    // Gone from every map; take it off this one without another read.
    setData((d) => ({ ...d, [layer]: (d[layer] || []).filter((r) => r.id !== rec.id) }));
    setForm((f) => (f && f.id === rec.id ? null : f));
    setOpened((o) => (o && o.id === rec.id ? null : o));
    setDeleting(null);
    flash(t('{title} deleted. It is gone from every map; the deletion is in the audit log.', { title: titleOf(layer, rec) }));
  }

  function targetName(req) {
    if (!req.target_id) return null;
    const layer = LAYER_OF_REQUEST[req.layer_type];
    const rec = (data[layer] || []).find((r) => r.id === req.target_id);
    // The card already says the layer: the source's own name or code only.
    return rec ? (layer === 'hydrants' ? rec.code : rec.name || rec.code) || null : null;
  }

  function requestDecided(message) {
    flash(message);
    setRequestAttempt((n) => n + 1);
    refreshQueues?.();
    Promise.all(WATER_LAYERS.map(loadLayer))
      .catch(() => flash(t('Saved, but the list could not be refreshed. Try again.'), 'err'));
  }

  const selCfg = cfgOf(selected);
  const selRows = data[selected] || [];
  const water = isWater(selected);
  const term = query.trim().toLowerCase();
  const searched = useMemo(
    () => (term ? selRows.filter((r) => found(selected, r, term)) : selRows),
    [selRows, selected, term],
  );
  const listRows = useMemo(
    () => (water && stateFilter !== 'all' ? searched.filter((r) => stateKey(selected, r) === stateFilter) : searched),
    [searched, selected, water, stateFilter],
  );
  const { shown: listed, pager } = usePager(listRows, { key: 'map-editor', reset: [selected, term, stateFilter] });
  const stateOptions = water
    ? [
      { key: 'all', label: t('All statuses') },
      ...stateChoices(selected, manages).map((choice) => ({
        ...choice,
        count: loading ? null : searched.filter((r) => stateKey(selected, r) === choice.key).length,
      })),
    ]
    : null;

  const openRec = opened ? (data[opened.layer] || []).find((r) => r.id === opened.id) ?? null : null;
  const mode = form ? 'form' : openRec ? 'place' : 'list';

  // What the panel turned into takes the focus and starts at its top; the
  // list comes back where it was left.
  const lastMode = useRef(mode);
  useEffect(() => {
    if (lastMode.current === mode) return;
    lastMode.current = mode;
    if (body.current) body.current.scrollTop = mode === 'list' ? listTop.current : 0;
    const now = document.activeElement;
    if (now && now !== document.body && !panel.current?.contains(now)) return;
    const row = mode === 'list' && lastRow.current
      ? panel.current?.querySelector(`[data-entry="${lastRow.current}"]`)
      : null;
    (row ?? heading.current)?.focus({ preventScroll: true });
  }, [mode]);

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

  const openPoint = openRec && !form ? pointOf(opened.layer, openRec) : null;
  const openChip = openRec ? chipOf(opened.layer, openRec) : null;

  const tabs = [
    { key: 'map', label: t('Map') },
    { key: 'requests', label: t('Water requests'), count: requests.rows.length },
  ];

  return (
    <div className="mm-page">
      <header className="mm-bar">
        <div className="mm-bar-copy">
          <p className="web-eyebrow">{t('Shared by every organization')}</p>
          <h1 className="web-page-title">{t('Map settings')}</h1>
        </div>
        {manages ? (
          <div className="rpl-tabs mm-tabs" role="tablist" aria-label={t('Map settings')}>
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={view === tab.key}
                className={`rpl-tab${view === tab.key ? ' is-active' : ''}`}
                onClick={() => setView(tab.key)}
              >
                {tab.label}
                {tab.count > 0 && <span className="web-count-badge" aria-label={t('{count} waiting', { count: tab.count })}>{tab.count}</span>}
              </button>
            ))}
          </div>
        ) : (
          <p className="mm-bar-note">
            {deletesWater
              ? t('View only, except that you can delete water resources. Fire Volunteer, BFP and central hub Admins make the other changes.')
              : t('View only. Fire Volunteer, BFP and central hub Admins make the changes.')}
          </p>
        )}
      </header>

      <div className="mm-root" hidden={view !== 'map'}>
        <div className="mm-map">
          <MapContainer
            center={PASAY}
            // At street level, so the editor opens on the points nearby (v1.12.39).
            zoom={LAYER_MIN_ZOOM}
            style={{ height: '100%', width: '100%', background: 'var(--map-ground)' }}
            zoomControl={false}
            attributionControl={false}
          >
            <BaseTiles />
            <ZoomControl position="bottomleft" />
            <ClickCapture active={!!form} onPick={handlePick} />
            {focus && <CenterOn point={focus} panel={panel} />}

            {/* The fires' pulse, under their markers (v1.12.48). */}
            {enabled.has('incidents') &&
              incidents
                .filter((inc) => inc.centroid_lat != null && inc.centroid_lng != null)
                .map((inc) => <FirePulse key={`pulse-${inc.id}`} lat={inc.centroid_lat} lng={inc.centroid_lng} />)}

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
                      {(fireName(inc.designation) || t('Incident'))} · {st.label}
                      {alarmStatusOf(inc).known ? ` · ${alarmStatusOf(inc).label}` : ''}
                    </Tooltip>
                  </CircleMarker>
                );
              })}

            {/* A risk zone is its icon inside its circle (24 Oct 2026). The circle
                is the zone, so it shows at every zoom, as on the app; the icon
                comes with the other places below. The zone being edited is drawn
                by the form preview instead. */}
            {enabled.has('risk') && (data.risk || []).map((r) => {
              const p = pointOf('risk', r);
              if (p.lat == null || p.lng == null) return null;
              if (form?.layer === 'risk' && form.id === r.id) return null;
              return (
                <Circle
                  key={`halo-${r.id}`}
                  center={[p.lat, p.lng]}
                  radius={riskRadius(r)}
                  pathOptions={RISK_CIRCLE_STYLE}
                  // While a marker is being placed, a click inside a zone
                  // places it rather than opening that zone.
                  eventHandlers={form ? undefined : { click: () => openPlace('risk', r) }}
                />
              );
            })}

            {/* GIS layers, the ones nearby, from street level in (v1.12.39) */}
            <ZoomGate
              active={EDIT_LAYERS.some((l) => enabled.has(l.key) && (data[l.key] || []).length > 0)}
              className={panelOpen ? 'mm-zoom-hint is-beside-panel' : 'mm-zoom-hint'}
            >
              {(near) => EDIT_LAYERS.filter((l) => enabled.has(l.key)).flatMap((l) =>
                (data[l.key] || []).map((r) => {
                  const p = pointOf(l.key, r);
                  if (p.lat == null || p.lng == null || !near(p.lat, p.lng)) return null;
                  // The zone being edited is drawn by the form preview instead.
                  if (l.key === 'risk' && form?.layer === 'risk' && form.id === r.id) return null;
                  const chip = chipOf(l.key, r);
                  const label = [titleOf(l.key, r), chip?.label ?? (isWater(l.key) ? null : lineOf(l.key, r))]
                    .filter(Boolean).join(' · ');
                  // While a marker is being placed, a click here places it.
                  const handlers = form ? undefined : { click: () => openPlace(l.key, r) };
                  if (l.key === 'risk') {
                    // The zone's icon; its circle is drawn above, at every zoom.
                    return [
                      <Marker
                        key={`m-${r.id}`}
                        position={[p.lat, p.lng]}
                        icon={markerIcon('risk', opened?.id === r.id)}
                        eventHandlers={handlers}
                      >
                        <Tooltip direction="top" offset={[0, -18]}>{label}</Tooltip>
                      </Marker>,
                    ];
                  }
                  const fill = l.key === 'hydrants' && r.verified ? VERIFIED_HYDRANT : COLORS[l.key];
                  return [
                    <CircleMarker
                      key={`m-${r.id}`}
                      center={[p.lat, p.lng]}
                      radius={l.key === 'evac' && r.outside_pasay ? 9 : 7}
                      pathOptions={
                        l.key === 'evac' && r.outside_pasay
                          ? outsidePasayStyle(theme)
                          : { color: '#fff', weight: 1, fillColor: fill, fillOpacity: inactive(r) ? 0.35 : 0.95 }
                      }
                      eventHandlers={handlers}
                    >
                      <Tooltip>{label}</Tooltip>
                    </CircleMarker>,
                  ];
                }),
              )}
            </ZoomGate>

            {/* the place that is open */}
            {openPoint?.lat != null && openPoint?.lng != null && (
              <CircleMarker
                key={`open-${opened.id}`}
                center={[openPoint.lat, openPoint.lng]}
                radius={14}
                interactive={false}
                pathOptions={{ color: '#FF7943', weight: 3, fill: false }}
              />
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
                    type="button"
                    className={`mm-chip${on ? ' on' : ''}`}
                    aria-pressed={on}
                    onClick={() => toggleChip(c.key)}
                    style={on ? { borderColor: `${color}88` } : undefined}
                  >
                    <span className="mm-chip-dot" style={{ background: color }} />
                    {c.label}
                    <span className="mm-chip-count">{(c.kind === 'edit' ? loading : !feedLoaded) ? '·' : count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* reopen tab when the panel is collapsed */}
          {!panelOpen && (
            <button type="button" className="mm-reopen" onClick={() => setPanelOpen(true)}>{t('‹ List')}</button>
          )}

          {/* the side list, and the place or form opened from it */}
          {panelOpen && (
            <aside className="mm-panel" ref={panel} aria-labelledby="mm-panel-title">
              <div className="mm-panel-head">
                {mode !== 'list' && (
                  <button
                    type="button"
                    className="rpl-icon-button mm-return"
                    disabled={saving}
                    onClick={() => (form ? setForm(null) : setOpened(null))}
                    aria-label={t('Back')}
                  >
                    <Icon name="chevron-right" />
                  </button>
                )}
                <div className="mm-panel-words">
                  {mode === 'place' && <p className="mm-panel-eyebrow">{cfgOf(opened.layer).singular}</p>}
                  <h2 className="mm-panel-title" id="mm-panel-title" tabIndex={-1} ref={heading}>
                    {mode === 'form'
                      ? `${form.mode === 'edit' ? t('Edit') : t('New')} ${cfgOf(form.layer).singular}`
                      : mode === 'place' ? titleOf(opened.layer, openRec) : selCfg.label}
                  </h2>
                  {mode === 'list' && (
                    <p className="mm-section-sub">
                      {loading ? selCfg.tagline : `${selRows.length === 1
                        ? t('{count} entry', { count: selRows.length })
                        : t('{count} entries', { count: selRows.length })} · ${selCfg.tagline}`}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  className="rpl-icon-button mm-collapse"
                  onClick={() => setPanelOpen(false)}
                  aria-label={t('Collapse')}
                  title={t('Collapse')}
                >
                  <Icon name="chevron-right" />
                </button>
              </div>

              <div
                className="mm-panel-body"
                ref={body}
                onScroll={(e) => { if (mode === 'list') listTop.current = e.currentTarget.scrollTop; }}
              >
                {mode === 'list' && (
                  <>
                    <div className="mm-grid" role="group" aria-label={t('Layer')}>
                      {EDIT_LAYERS.map((l) => (
                        <button
                          key={l.key}
                          type="button"
                          className={`mm-gcard${selected === l.key ? ' active' : ''}`}
                          aria-pressed={selected === l.key}
                          onClick={() => selectLayer(l.key)}
                        >
                          <span className="mm-gcard-top">
                            <span className="mm-gicon" style={{ '--kind': COLORS[l.key] }}>
                              <Icon name={l.icon} size={16} />
                            </span>
                            <span className="mm-gcount">{loading ? '·' : (data[l.key] || []).length}</span>
                          </span>
                          <span className="mm-glabel">{l.label}</span>
                        </button>
                      ))}
                    </div>

                    <div className="mm-tools">
                      <SearchBox
                        label={t('Search {things}', { things: selCfg.label })}
                        placeholder={water ? t('Search codes, names and streets') : t('Search names and places')}
                        value={query}
                        onChange={setQuery}
                      />
                      {stateOptions && (
                        <Select label={t('Status')} value={stateFilter} onChange={setStateFilter} options={stateOptions} />
                      )}
                    </div>

                    <div className="mm-list" aria-busy={loading}>
                      {loading && (
                        <div role="status">
                          <span className="web-sr-only">{t('Loading {things}…', { things: selCfg.label.toLowerCase() })}</span>
                          <Skeleton shape="table" rows={3} />
                        </div>
                      )}
                      {!loading && failed.includes(selected) && (
                        <div className="mm-empty" role="alert">
                          {t('{things} could not be loaded.', { things: selCfg.label })}{' '}
                          <button type="button" className="mm-retry" onClick={() => setAttempt((n) => n + 1)}>{t('Try again')}</button>
                        </div>
                      )}
                      {!loading && !failed.includes(selected) && selRows.length === 0 && (
                        <div className="mm-empty">{t('No {things} yet.', { things: selCfg.label.toLowerCase() })}</div>
                      )}
                      {selRows.length > 0 && listRows.length === 0 && (
                        <div className="mm-empty">{t('Nothing matches these filters.')}</div>
                      )}
                      {!loading && listed.map((r) => {
                        const title = titleOf(selected, r);
                        const chip = chipOf(selected, r);
                        const checked = lastCheck(selected, r);
                        return (
                          <div className={`mm-entry${inactive(r) ? ' is-inactive' : ''}`} key={r.id}>
                            <button
                              type="button"
                              className="mm-entry-open"
                              data-entry={r.id}
                              onClick={() => {
                                lastRow.current = r.id;
                                openPlace(selected, r, { move: true });
                              }}
                            >
                              <span className="mm-entry-top">
                                <span className="mm-entry-title">{title}</span>
                                {chip && <StatusChip label={chip.label} tone={chip.tone} />}
                              </span>
                              <span className="mm-entry-sub">{lineOf(selected, r)}</span>
                              {checked && <span className="mm-entry-check">{checked}</span>}
                            </button>
                            {mayDelete(selected) && (
                              <button
                                type="button"
                                className="mm-iconbtn del"
                                onClick={() => setDeleting({ layer: selected, rec: r })}
                                aria-label={t('Delete {title}', { title })}
                                title={t('Delete')}
                              >
                                <Icon name="delete" size={18} />
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    {listed.length > 0 && <Pager {...pager} compact />}
                  </>
                )}

                {mode === 'place' && (
                  <>
                    {inactive(openRec) && openChip && <StatusChip label={openChip.label} tone={openChip.tone} />}
                    <PointFacts kind={KIND[opened.layer]} row={openRec} incidents={incidents} onOpenIncident={onOpenIncident} />
                    {openPoint?.lat != null && openPoint?.lng != null && (
                      <a className="rpl-button rpl-button--secondary" href={mapsLink(openPoint.lat, openPoint.lng)} target="_blank" rel="noopener noreferrer">
                        {t('Open in Google Maps')}
                      </a>
                    )}
                  </>
                )}

                {mode === 'form' && (
                  <>
                    <p className="mm-hint">{t('Click the map to set the location.')}</p>
                    <div className="mm-form">
                      {FIELDS[form.layer].map((f) => (
                        <Field
                          key={`${form.layer}:${f.name}`}
                          field={f}
                          value={form.values[f.name]}
                          onChange={(v) => setForm((cur) => ({ ...cur, values: { ...cur.values, [f.name]: v } }))}
                        />
                      ))}
                    </div>
                  </>
                )}
              </div>

              {mode === 'list' && manages && (
                <div className="mm-panel-foot">
                  <button type="button" className="mm-add" onClick={openAdd}>{t('+ ADD')}{' '}{selCfg.singular.toUpperCase()}</button>
                </div>
              )}
              {mode === 'place' && (manages || mayDelete(opened.layer)) && (
                <div className="mm-panel-foot">
                  {mayDelete(opened.layer) && (
                    <button type="button" className="rpl-button rpl-button--danger" onClick={() => setDeleting({ layer: opened.layer, rec: openRec })}>{t('Delete')}</button>
                  )}
                  {manages && (
                    <button type="button" className="rpl-button rpl-button--primary" onClick={() => openEdit(opened.layer, openRec)}>{t('Edit')}</button>
                  )}
                </div>
              )}
              {mode === 'form' && (
                <div className="mm-panel-foot">
                  <button type="button" className="mm-back" onClick={() => setForm(null)} disabled={saving}>{t('Cancel')}</button>
                  <button type="button" className="mm-add" onClick={submitForm} disabled={saving}>
                    {saving ? t('SAVING…') : form.mode === 'edit' ? t('SAVE CHANGES') : t('ADD MARKER')}
                  </button>
                </div>
              )}
            </aside>
          )}
        </div>
      </div>

      {view === 'requests' && manages && (
        <div className="mm-requests">
          <WaterRequests
            requests={requests.rows}
            loading={requests.loading}
            error={requests.error}
            onRetry={() => setRequestAttempt((n) => n + 1)}
            targetName={targetName}
            onDecided={requestDecided}
          />
        </div>
      )}

      {toast && (
        <div className={`mm-toast${toast.kind === 'err' ? ' err' : ''}`} role="status">{toast.msg}</div>
      )}

      <ConfirmDialog
        open={!!deleting}
        eyebrow={deleting ? cfgOf(deleting.layer).singular : undefined}
        title={deleting ? t('Delete {title}?', { title: titleOf(deleting.layer, deleting.rec) }) : ''}
        description={t('It disappears from every Admin’s map and every phone’s map. This can’t be undone; the deletion is recorded with your name.')}
        confirmLabel={deleting ? t('Delete {thing}', { thing: cfgOf(deleting.layer).singular.toLowerCase() }) : t('Delete')}
        destructive
        onClose={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
