import { useEffect, useRef, useState } from 'react';

import {
  CATEGORIES,
  CATEGORY_LABEL,
  PLACEHOLDER_CUE,
  getSoundSettings,
  previewCue,
  setSoundSettings,
  subscribeSoundSettings,
} from '../sound/cues.js';

export function useSoundSettings() {
  const [settings, setSettings] = useState(getSoundSettings);
  useEffect(() => subscribeSoundSettings(setSettings), []);
  return settings;
}

const Speaker = ({ on }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 9h4l5-4v14l-5-4H4z" />
    {on ? <path d="M16.5 8.5a5 5 0 010 7M19 6a8.5 8.5 0 010 12" /> : <path d="M17 9l5 6M22 9l-5 6" />}
  </svg>
);

/// Notification-sound controls (Section 2.8): one switch turns every cue off,
/// and each category has its own mute and volume. Muting a category silences
/// only that stream — the badge and card still announce the incident.
///
/// `categories` limits the rows, for a console that only ever plays some.
export default function SoundSettings({ slim = false, categories = CATEGORIES }) {
  const settings = useSoundSettings();
  const [open, setOpen] = useState(false);
  const root = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      if (root.current && !root.current.contains(e.target)) setOpen(false);
    };
    const esc = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  function update(patch) {
    setSoundSettings({ ...settings, ...patch });
  }

  return (
    <div className={`ss${slim ? ' is-slim' : ''}`} ref={root}>
      <button
        className={`ss-toggle${settings.enabled ? '' : ' is-off'}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Notification sounds"
      >
        <Speaker on={settings.enabled} />
        {!slim && <span>{settings.enabled ? 'Sounds on' : 'Sounds off'}</span>}
      </button>

      {open && (
        <div className="ss-panel" role="dialog" aria-label="Notification sounds">
          <div className="ss-head">
            <div>
              <span className="dc-eyebrow">Notification sounds</span>
              <p className="ss-note">A cue per incident category, so you can tell them apart without looking.</p>
            </div>
            <label className="ss-switch">
              <input
                type="checkbox"
                checked={settings.enabled}
                onChange={(e) => update({ enabled: e.target.checked })}
              />
              <span aria-hidden="true" />
              <span className="ss-sr">All sounds</span>
            </label>
          </div>

          {categories.map((c) => {
            const muted = settings.muted[c];
            const disabled = !settings.enabled;
            return (
              <div className={`ss-row${disabled || muted ? ' is-dim' : ''}`} key={c}>
                <div className="ss-row-top">
                  <span className="ss-cat">{CATEGORY_LABEL[c]}</span>
                  <span className="ss-cue">{PLACEHOLDER_CUE[c]}</span>
                </div>
                <div className="ss-row-controls">
                  <button
                    className={`ss-mute${muted ? ' is-on' : ''}`}
                    onClick={() => update({ muted: { ...settings.muted, [c]: !muted } })}
                    disabled={disabled}
                    aria-pressed={muted}
                  >
                    {muted ? 'Muted' : 'Mute'}
                  </button>
                  <input
                    className="ss-range"
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={settings.volume[c]}
                    disabled={disabled || muted}
                    onChange={(e) =>
                      update({ volume: { ...settings.volume, [c]: Number(e.target.value) } })
                    }
                    aria-label={`${CATEGORY_LABEL[c]} volume`}
                  />
                  <button
                    className="ss-test"
                    onClick={() => previewCue(c)}
                    disabled={disabled || muted || settings.volume[c] === 0}
                  >
                    Test
                  </button>
                </div>
              </div>
            );
          })}

          <p className="ss-foot">
            Placeholder cues. The final recordings are chosen with the client during the
            pilot.
          </p>
        </div>
      )}
    </div>
  );
}
