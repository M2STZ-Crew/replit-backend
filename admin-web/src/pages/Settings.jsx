import { useState } from 'react';

import { useConsole } from '../components/ConsoleShell.jsx';
import { useSoundSettings } from '../components/SoundSettings.jsx';
import { Icon, PageHeader } from '../components/ui/index.js';
import {
  REPEAT_CHOICES,
  askDesktopPermission,
  setAlarmSettings,
  useAlarmSettings,
} from '../sound/alarm.js';
import {
  CATEGORIES,
  CATEGORY_FOR,
  CATEGORY_LABEL,
  previewCue,
  setSoundSettings,
} from '../sound/cues.js';
import { applyTheme, storedTheme } from '../theme.js';

/* Settings (REPLIT (MAIN) 10 · A70): notification sounds per category, the
 * repeating alarm and desktop alerts, kept in this browser.
 *
 * Availability (AFK, A71) is not here: no endpoint stores or reports it yet
 * (PRD v13 §4.6.5, §17.3), so the switch is prepared as AvailabilityPanel
 * and shown only in the development preview. */

function Switch({ checked, onChange, label, disabled = false }) {
  return (
    <label className={`ad-switch${disabled ? ' is-disabled' : ''}`}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="ad-switch-track" aria-hidden="true" />
      <span className="web-sr-only">{label}</span>
    </label>
  );
}

function Row({ title, detail, children, dim = false }) {
  return (
    <div className={`ad-setting${dim ? ' is-dim' : ''}`}>
      <div className="ad-setting-text">
        <span className="ad-setting-title">{title}</span>
        {detail && <span className="ad-setting-detail">{detail}</span>}
      </div>
      <div className="ad-setting-control">{children}</div>
    </div>
  );
}

/* The organisation's availability (A70, A71). UI READY: `afk`, `since` and
 * `busy` come from whoever owns the state; `onChange(next)` is called with the
 * wanted value and must resolve once the server has recorded it. */
export function AvailabilityPanel({ afk, since, busy = false, error = null, onChange }) {
  return (
    <section className="ad-panel" aria-labelledby="ad-availability-title">
      <h2 className="ad-panel-title" id="ad-availability-title">Availability</h2>
      <Row
        title={afk ? `Away from the console${since ? ` since ${since}` : ''}` : 'At the console'}
        detail="Other Admins see your organisation greyed out with an AFK chip. Incidents still move: any Coordinator of yours can acknowledge."
      >
        <Switch
          checked={afk}
          disabled={busy || !onChange}
          onChange={(next) => onChange?.(next)}
          label="Away from the console"
        />
      </Row>
      {error && <p className="ad-inline-error" role="alert">{error}</p>}
    </section>
  );
}

export default function Settings() {
  const { org } = useConsole();
  const sound = useSoundSettings();
  const alarm = useAlarmSettings();
  const [theme, setTheme] = useState(storedTheme);
  const update = (patch) => setSoundSettings({ ...sound, ...patch });

  return (
    <div className="ad-page ad-page--narrow">
      <PageHeader
        eyebrow={org?.name ?? 'Console'}
        title="Settings"
        description="For this Admin console only. Sounds and alerts are kept in this browser."
      />
      <section className="ad-panel" aria-labelledby="ad-sounds-title">
        <div className="ad-panel-head">
          <h2 className="ad-panel-title" id="ad-sounds-title">Notification sounds</h2>
          <Switch checked={sound.enabled} onChange={(enabled) => update({ enabled })} label="All sounds" />
        </div>
        <p className="ad-panel-note">
          A sound per incident category, so you can tell them apart without looking. A new
          incident rings until you open it.
        </p>
        {CATEGORIES.map((c) => {
          const muted = sound.muted[c];
          const off = !sound.enabled;
          return (
            <Row
              key={c}
              title={CATEGORY_LABEL[c]}
              detail={CATEGORY_FOR[c]}
              dim={off || muted}
            >
              <button
                type="button"
                className="ad-button ad-button--secondary ad-button--compact"
                onClick={() => update({ muted: { ...sound.muted, [c]: !muted } })}
                disabled={off}
                aria-pressed={muted}
              >
                {muted ? 'Muted' : 'Mute'}
              </button>
              <input
                className="ad-range"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={sound.volume[c]}
                disabled={off || muted}
                onChange={(e) => update({ volume: { ...sound.volume, [c]: Number(e.target.value) } })}
                aria-label={`${CATEGORY_LABEL[c]} volume`}
                aria-valuetext={`${Math.round(sound.volume[c] * 100)}%`}
              />
              <span className="ad-range-value" aria-hidden="true">
                {Math.round(sound.volume[c] * 100)}%
              </span>
              <button
                type="button"
                className="ad-button ad-button--secondary ad-button--compact"
                onClick={() => previewCue(c)}
                disabled={off || muted || sound.volume[c] === 0}
              >
                <Icon name="volume" size={16} />
                Test
              </button>
            </Row>
          );
        })}
      </section>

      <section className="ad-panel" aria-labelledby="ad-repeat-title">
        <div className="ad-panel-head">
          <h2 className="ad-panel-title" id="ad-repeat-title">Ring until opened</h2>
          <Switch
            checked={alarm.repeat}
            onChange={(repeat) => setAlarmSettings({ repeat })}
            label="Ring until opened"
          />
        </div>
        <Row title="Ring again every" dim={!alarm.repeat}>
          <div className="ad-segment" role="group" aria-label="Ring again every">
            {REPEAT_CHOICES.map((sec) => (
              <button
                key={sec}
                type="button"
                className={`ad-chip${alarm.everySec === sec ? ' is-selected' : ''}`}
                onClick={() => setAlarmSettings({ everySec: sec })}
                disabled={!alarm.repeat}
                aria-pressed={alarm.everySec === sec}
              >
                {sec} s
              </button>
            ))}
          </div>
        </Row>
        <Row title="Desktop alerts" detail="When this tab is behind another window.">
          {alarm.permission === 'granted' ? (
            <Switch
              checked={alarm.desktop}
              onChange={(desktop) => setAlarmSettings({ desktop })}
              label="Desktop alerts"
            />
          ) : alarm.permission === 'default' ? (
            <button
              type="button"
              className="ad-button ad-button--secondary ad-button--compact"
              onClick={askDesktopPermission}
            >
              Allow
            </button>
          ) : (
            <span className="ad-setting-detail">
              {alarm.permission === 'denied' ? 'Blocked in browser settings' : 'Not available here'}
            </span>
          )}
        </Row>
      </section>

      <section className="ad-panel" aria-labelledby="ad-ground-title">
        <h2 className="ad-panel-title" id="ad-ground-title">Appearance</h2>
        <Row title="Light ground" detail="The console is designed on the dark ground.">
          <Switch
            checked={theme === 'light'}
            onChange={(light) => setTheme(applyTheme(light ? 'light' : 'dark'))}
            label="Light ground"
          />
        </Row>
      </section>
    </div>
  );
}
