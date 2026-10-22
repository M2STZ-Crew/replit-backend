import { useEffect, useState } from 'react';

import { CATEGORY_LABEL, categoriesOf } from './cues.js';

/// The repeating incident alarm (Admin Console).
///
/// A cue that plays once is easy to miss: the admin is on a call, away from the
/// desk, or on another tab. So a new incident keeps ringing, and keeps its
/// banner on every screen, until an admin acknowledges it here — by pressing
/// Acknowledge, by opening the incident, or by clicking its desktop alert. It
/// stops by itself only when the incident leaves the live feed (closed,
/// rejected or merged), because then there is nothing left to be aware of.
///
/// Acknowledgements are kept in this browser, so a reload does not silence an
/// alarm nobody answered, and does not re-ring one that was. Each admin answers
/// their own alarm: acknowledging on one machine does not silence another.

/// After sign-in or a reload, incidents reported this recently that this
/// browser never acknowledged ring again. Older ones do not, or a first sign-in
/// would ring for every open incident at once.
export const CATCH_UP_MS = 30 * 60 * 1000;

/// A desktop alert's click asks the console to open this incident.
export const OPEN_INCIDENT_EVENT = 'replit:open-incident';

const KEY = 'replit.alarm.v1';
const ACK_KEY = 'replit.ack.v1';
const ACK_KEEP_MS = 7 * 24 * 60 * 60 * 1000;
const DEFAULTS = { desktop: true };

// ── settings ────────────────────────────────────────────────────────────────
function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null');
    return { ...DEFAULTS, desktop: saved?.desktop ?? DEFAULTS.desktop };
  } catch {
    return { ...DEFAULTS };
  }
}

let settings = loadSettings();
const listeners = new Set();

function emit() {
  listeners.forEach((fn) => fn());
}

export function getAlarmSettings() {
  return settings;
}

export function setAlarmSettings(patch) {
  settings = { ...settings, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* storage unavailable — the setting still applies for this session */
  }
  emit();
}

/// The alarm settings and desktop-alert permission, re-rendering on change.
export function useAlarmSettings() {
  const read = () => ({ ...settings, permission: desktopPermission() });
  const [state, setState] = useState(read);
  useEffect(() => {
    const fn = () => setState(read());
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return state;
}

// ── acknowledgements ────────────────────────────────────────────────────────
function loadAcks() {
  try {
    const saved = JSON.parse(localStorage.getItem(ACK_KEY) || '{}');
    const cutoff = Date.now() - ACK_KEEP_MS;
    return Object.fromEntries(
      Object.entries(saved).filter(([, at]) => new Date(at).getTime() > cutoff),
    );
  } catch {
    return {};
  }
}

let acks = loadAcks();

export function isAcknowledged(id) {
  return Boolean(acks[id]);
}

export function recordAcknowledged(ids) {
  const at = new Date().toISOString();
  acks = { ...acks };
  for (const id of ids) {
    acks[id] = at;
    shown.get(id)?.close();
    shown.delete(id);
  }
  try {
    localStorage.setItem(ACK_KEY, JSON.stringify(acks));
  } catch {
    /* the alarm is still answered for this session */
  }
}

// ── how an incident reads in an alert ───────────────────────────────────────
const STATUS_LABEL = {
  reported: 'Awaiting acceptance',
  verified: 'Accepted',
  en_route: 'Responders en route',
  arrived: 'Responders on scene',
  fire_out: 'Fire out',
  post_incident_report: 'Report owed',
};

export function statusLabel(status) {
  return STATUS_LABEL[status] ?? status;
}

export function kindOf(incident) {
  const cats = categoriesOf(incident).map((c) => CATEGORY_LABEL[c]);
  return cats.length ? cats.join(' · ') : 'Incident';
}

export function reportsOf(incident) {
  const n = incident.report_count ?? 1;
  return `${n} ${n === 1 ? 'report' : 'reports'}`;
}

// ── desktop alerts ──────────────────────────────────────────────────────────
const shown = new Map();

export function desktopPermission() {
  return typeof Notification === 'undefined' ? 'unsupported' : Notification.permission;
}

/// Must run from a click: browsers ignore a permission request made on their own.
export async function askDesktopPermission() {
  if (desktopPermission() !== 'default') return;
  try {
    await Notification.requestPermission();
  } finally {
    emit();
  }
}

/// Raise (or raise again) a system notification per incident, only while the
/// console is out of sight: on screen, the banner already says it. One tag per
/// incident, so a repeat replaces its own alert rather than stacking copies.
export function notifyDesktop(incidents, { again = false } = {}) {
  if (!settings.desktop || desktopPermission() !== 'granted') return;
  if (typeof document !== 'undefined' && !document.hidden) return;
  for (const inc of incidents) {
    try {
      const n = new Notification(`New incident: ${inc.designation}`, {
        body: `${kindOf(inc)} · ${reportsOf(inc)} · ${statusLabel(inc.status)}. `
          + 'Open the Admin Console to acknowledge it.',
        tag: `incident-${inc.id}`,
        renotify: again,
        requireInteraction: true,
        icon: '/assets/logo-mark.png',
      });
      n.onclick = () => {
        window.focus();
        window.dispatchEvent(new CustomEvent(OPEN_INCIDENT_EVENT, { detail: inc.id }));
        n.close();
      };
      shown.set(inc.id, n);
    } catch {
      /* some browsers (Android Chrome) only allow notifications from a service worker */
    }
  }
}

/// Whether the browser will let the alarm make a sound yet: until someone has
/// clicked or typed on the page, audio is held back.
export function soundUnlocked() {
  const ua = typeof navigator !== 'undefined' ? navigator.userActivation : null;
  return ua ? ua.hasBeenActive : true;
}
