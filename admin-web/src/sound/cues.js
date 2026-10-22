/// Per-agency notification sounds (Master Context v10, Section 2.8).
///
/// Each incident category has a cue that is recognisable without looking at the
/// screen. Since v1.12.9 they are the recordings chosen for the pilot, in
/// `public/sounds/` (the mobile app plays the same files). They are decoded
/// once into the page's audio context, which the first click or key press
/// unlocks, so they play on the same timing rules as before.
///
/// If a recording cannot be fetched or decoded, that category falls back to a
/// synthesized pattern, so an alarm is never silent because of a missing file.

export const CATEGORIES = ['fire', 'police', 'medical', 'barangay'];

export const CATEGORY_LABEL = {
  fire: 'Fire',
  police: 'Police',
  medical: 'Medical',
  barangay: 'Barangay',
};

/// Who each category's sound is for.
export const CATEGORY_FOR = {
  fire: 'Fire Volunteers and BFP',
  police: 'Police',
  medical: 'Medical teams',
  barangay: 'Barangay',
};

/// The recordings.
const FILES = {
  fire: '/sounds/fire.mp3',
  police: '/sounds/police.mp3',
  medical: '/sounds/medical.mp3',
  barangay: '/sounds/barangay.mp3',
};

/// Fallbacks when a recording will not load. [frequency Hz, start s, duration s, optional end Hz]
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

/// Each recording, decoded once: category -> Promise<AudioBuffer | null>.
const buffers = {};

/// Every source started and not yet ended, so [stopCues] can silence them.
const sounding = new Set();

function track(node) {
  sounding.add(node);
  node.onended = () => sounding.delete(node);
}

function bufferFor(category) {
  if (!ctx) return Promise.resolve(null);
  buffers[category] ??= fetch(FILES[category])
    .then((res) => (res.ok ? res.arrayBuffer() : Promise.reject(new Error(res.statusText))))
    .then((bytes) => ctx.decodeAudioData(bytes))
    .catch(() => null);
  return buffers[category];
}

/// Browsers refuse to start audio before the user has interacted with the page,
/// so the context is created (or resumed) on the first click or key press, and
/// the recordings start loading then, ready for the first alarm.
function unlock() {
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    CATEGORIES.forEach(bufferFor);
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
    track(osc);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }
}

function lengthOf(pattern) {
  return Math.max(...pattern.notes.map(([, start, dur]) => start + dur));
}

/// Schedule one category's cue at `at` (context time); returns how long it lasts.
async function playAt(category, volume, at) {
  const buffer = await bufferFor(category);
  if (!buffer) {
    synth(PATTERNS[category], volume, at);
    return lengthOf(PATTERNS[category]);
  }
  const source = ctx.createBufferSource();
  const amp = ctx.createGain();
  source.buffer = buffer;
  amp.gain.value = Math.max(0, Math.min(1, volume));
  source.connect(amp).connect(ctx.destination);
  track(source);
  source.start(Math.max(at, ctx.currentTime));
  return buffer.duration;
}

/// Play one category's cue now (ignores the mute settings — used by "Test").
export function previewCue(category, volume = settings.volume[category]) {
  unlock();
  if (!ctx || ctx.state !== 'running') return;
  playAt(category, volume, ctx.currentTime + 0.02);
}

/// Silence everything playing or scheduled now (PRD v14 §4.13.1: the loop
/// stops the moment the operator answers it).
export function stopCues() {
  for (const node of sounding) {
    try {
      node.stop();
    } catch {
      /* already stopped */
    }
  }
  sounding.clear();
}

/// Play the cues for a batch of incidents, one after another, each category at
/// most once and within the user's settings. Muting a category mutes only its
/// stream — the badge and the card still announce the incident. Resolves to
/// how long the batch lasts, in seconds (0 when nothing could sound).
export async function announce(incidents) {
  const s = settings;
  if (!s.enabled) return 0;
  const wanted = [];
  for (const inc of incidents) {
    for (const c of categoriesOf(inc)) {
      if (!wanted.includes(c) && !s.muted[c] && s.volume[c] > 0) wanted.push(c);
    }
  }
  if (wanted.length === 0) return 0;
  unlock();
  if (!ctx || ctx.state !== 'running') return 0;
  const start = ctx.currentTime + 0.02;
  let at = start;
  for (const c of wanted) {
    at += (await playAt(c, s.volume[c], at)) + 0.35;
  }
  return at - start;
}
