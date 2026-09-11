/// Per-agency notification sounds (Master Context v10, Section 2.8).
///
/// Each incident category has a cue that is recognisable without looking at the
/// screen. The final audio has not been chosen — Section 2.8 records the
/// placeholders ("mamang pulis, tulong!" and so on) as text only, and selection
/// happens with the client during the pilot. Until then each category plays a
/// synthesized pattern that differs in rhythm and pitch from the others, so the
/// console is usable now rather than silent.
///
/// When the recordings exist, drop them in `public/sounds/` and set the path in
/// FILES below; a category with a file plays the file instead of its pattern.
///
/// This file is mirrored in observer-web/src/sound/cues.js — keep the two in step.

export const CATEGORIES = ['fire', 'police', 'medical', 'barangay'];

export const CATEGORY_LABEL = {
  fire: 'Fire',
  police: 'Police',
  medical: 'Medical',
  barangay: 'Barangay',
};

/// What Section 2.8 records as each category's intended cue.
export const PLACEHOLDER_CUE = {
  fire: 'Cue to be chosen',
  police: '“Mamang pulis, tulong!”',
  medical: '“Doc, doc, tulong!”',
  barangay: '“Bakbak kol!”',
};

/// Recorded cues, once chosen — e.g. police: '/sounds/police.mp3'.
const FILES = { fire: null, police: null, medical: null, barangay: null };

/// Synthesized placeholders. [frequency Hz, start s, duration s, optional end Hz]
const PATTERNS = {
  // Urgent two-tone hi-lo, four beats.
  fire: { wave: 'square', gain: 0.18, notes: [
    [988, 0, 0.14], [740, 0.16, 0.14], [988, 0.32, 0.14], [740, 0.48, 0.14],
  ] },
  // A rising-falling wail, like a siren.
  police: { wave: 'sawtooth', gain: 0.12, notes: [
    [620, 0, 0.45, 1180], [1180, 0.45, 0.45, 620],
  ] },
  // Three quick high beeps.
  medical: { wave: 'sine', gain: 0.3, notes: [
    [1320, 0, 0.09], [1320, 0.16, 0.09], [1320, 0.32, 0.09],
  ] },
  // Two low bell strikes with a long tail.
  barangay: { wave: 'triangle', gain: 0.35, notes: [
    [523, 0, 0.6], [392, 0.34, 0.8],
  ] },
};

/// Which cue(s) an incident calls for, from the agencies its reporters asked for.
export function categoriesOf(incident) {
  const requested = incident?.requested_agencies ?? [];
  const out = [];
  if (requested.includes('fire_volunteer') || requested.includes('bfp')) out.push('fire');
  for (const c of ['police', 'medical', 'barangay']) {
    if (requested.includes(c)) out.push(c);
  }
  return out;
}

// ── settings ────────────────────────────────────────────────────────────────
const KEY = 'replit.sound.v1';
const DEFAULTS = {
  enabled: true,
  volume: { fire: 0.8, police: 0.8, medical: 0.8, barangay: 0.8 },
  muted: { fire: false, police: false, medical: false, barangay: false },
};

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (!saved) return structuredClone(DEFAULTS);
    return {
      enabled: saved.enabled ?? true,
      volume: { ...DEFAULTS.volume, ...saved.volume },
      muted: { ...DEFAULTS.muted, ...saved.muted },
    };
  } catch {
    return structuredClone(DEFAULTS);
  }
}

let settings = load();
const listeners = new Set();

export function getSoundSettings() {
  return settings;
}

export function setSoundSettings(next) {
  settings = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — the setting still applies for this session */
  }
  listeners.forEach((fn) => fn(next));
}

export function subscribeSoundSettings(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// ── playback ────────────────────────────────────────────────────────────────
let ctx = null;

/// Browsers refuse to start audio before the user has interacted with the page,
/// so the context is created (or resumed) on the first click or key press.
function unlock() {
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
  } catch {
    ctx = null;
  }
}
if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', unlock, { passive: true });
  window.addEventListener('keydown', unlock);
}

function synth(pattern, volume, at) {
  for (const [freq, start, dur, endFreq] of pattern.notes) {
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    const t0 = at + start;
    osc.type = pattern.wave;
    osc.frequency.setValueAtTime(freq, t0);
    if (endFreq) osc.frequency.linearRampToValueAtTime(endFreq, t0 + dur);
    const peak = pattern.gain * volume;
    amp.gain.setValueAtTime(0.0001, t0);
    amp.gain.exponentialRampToValueAtTime(peak, t0 + 0.015);
    amp.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(amp).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }
}

function lengthOf(pattern) {
  return Math.max(...pattern.notes.map(([, start, dur]) => start + dur));
}

/// Play one category's cue now (ignores the mute settings — used by "Test").
export function previewCue(category, volume = settings.volume[category]) {
  if (FILES[category]) {
    const audio = new Audio(FILES[category]);
    audio.volume = Math.max(0, Math.min(1, volume));
    audio.play().catch(() => {});
    return;
  }
  unlock();
  if (!ctx || ctx.state !== 'running') return;
  synth(PATTERNS[category], volume, ctx.currentTime + 0.02);
}

/// Play the cues for a batch of newly arrived incidents, one after another, each
/// category at most once and within the user's settings. Muting a category mutes
/// only its stream — the badge and the card still announce the incident.
///
/// `only` limits the categories that may sound: the Admin Console plays every
/// category, an Observer Console only its own agency's (Section 2.8).
export function announce(incidents, only = CATEGORIES) {
  const s = settings;
  if (!s.enabled) return;
  const wanted = [];
  for (const inc of incidents) {
    for (const c of categoriesOf(inc)) {
      if (only.includes(c) && !wanted.includes(c) && !s.muted[c] && s.volume[c] > 0) {
        wanted.push(c);
      }
    }
  }
  if (wanted.length === 0) return;
  unlock();
  let delayMs = 0;
  for (const c of wanted) {
    const play = () => previewCue(c, s.volume[c]);
    if (delayMs === 0) play();
    else setTimeout(play, delayMs);
    delayMs += (FILES[c] ? 1500 : lengthOf(PATTERNS[c]) * 1000) + 350;
  }
}
