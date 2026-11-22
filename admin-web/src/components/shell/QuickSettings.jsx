import { useEffect, useId, useRef, useState } from 'react';

import { LanguageSwitch, t } from '../../i18n/i18n.jsx';
import { soundCategories } from '../../lib/access.js';
import {
  askDesktopPermission, setAlarmSettings, useAlarmSettings, useSoundUnlocked,
} from '../../sound/alarm.js';
import { setSoundSettings } from '../../sound/cues.js';
import { applyTheme, useTheme } from '../../theme.js';
import { useSoundSettings } from '../SoundSettings.jsx';
import Icon from '../ui/Icon.jsx';
import Switch from '../ui/Switch.jsx';

/* The header's one button (v1.12.50; 22 Nov 2026: "Tanggalin yung 'Sound on
 * Button' and 'Notification Button' Palitan nalang to ng 'Settings Button'";
 * answered "Quick menu + mute warning"): a gear with the settings an Admin
 * reaches for. While the alarm cannot be heard, switched off or held back by
 * the browser, the gear has a red dot and says "Sound off". */

function Row({ title, detail, warn = false, stacked = false, children }) {
  return (
    <div className={`rpl-quick-row${stacked ? ' is-stacked' : ''}`}>
      <span className="rpl-quick-text">
        <span className="rpl-quick-title">{title}</span>
        {detail && <span className={`rpl-quick-detail${warn ? ' is-warn' : ''}`}>{detail}</span>}
      </span>
      {children}
    </div>
  );
}

const THEMES = [
  { key: 'dark', get label() { return t('Dark'); } },
  { key: 'light', get label() { return t('Light'); } },
];

/* Whether this Admin's alarm can be heard, and switching it on or off. On
 * also brings back its own agency's sound when every one of those was muted,
 * or on would still be silent. */
function useAlarmSound(access) {
  const sound = useSoundSettings();
  const unlocked = useSoundUnlocked();
  const mine = soundCategories(access);
  const heard = mine.some((c) => !sound.muted[c] && sound.volume[c] > 0);
  const on = sound.enabled && heard;
  function set(next) {
    if (!next || heard) {
      setSoundSettings({ ...sound, enabled: next });
      return;
    }
    const muted = { ...sound.muted };
    const volume = { ...sound.volume };
    for (const c of mine) {
      muted[c] = false;
      if (!(volume[c] > 0)) volume[c] = 0.8;
    }
    setSoundSettings({ ...sound, enabled: true, muted, volume });
  }
  return { on, blocked: on && !unlocked, set };
}

export default function QuickSettings({ access, onAllSettings, onSignOut }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const root = useRef(null);
  const gear = useRef(null);
  const panel = useRef(null);
  const alarm = useAlarmSound(access);
  const desktop = useAlarmSettings();
  const theme = useTheme();
  const silent = !alarm.on || alarm.blocked;

  useEffect(() => {
    if (!open) return undefined;
    panel.current?.focus({ preventScroll: true });
    const away = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false);
    };
    const onKey = (event) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      gear.current?.focus();
    };
    document.addEventListener('pointerdown', away, true);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', away, true);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  function leave(action) {
    setOpen(false);
    gear.current?.focus();
    action();
  }

  const desktopState = {
    denied: t('Blocked in browser settings'),
    unsupported: t('Not available here'),
  }[desktop.permission];

  return (
    <div
      className="rpl-quick"
      ref={root}
      // Tabbing out of it closes it.
      onBlur={(event) => {
        if (open && event.relatedTarget && !root.current?.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={gear}
        type="button"
        className={`rpl-gear${silent ? ' is-silent' : ''}${open ? ' is-open' : ''}`}
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={silent ? t('Sound off. Quick settings') : t('Quick settings')}
        title={t('Quick settings')}
      >
        <span className="rpl-gear-icon" aria-hidden="true">
          <Icon name="settings" />
          {silent && <span className="rpl-gear-dot" />}
        </span>
        {silent && <span className="rpl-gear-words">{t('Sound off')}</span>}
      </button>
      <span className="web-sr-only" role="status">{silent ? t('Sound off') : ''}</span>

      {open && (
        <div
          ref={panel}
          id={id}
          className="rpl-quick-panel"
          role="dialog"
          aria-label={t('Quick settings')}
          tabIndex={-1}
        >
          <Row
            title={t('Alarm sound')}
            detail={!alarm.on
              ? t('New incidents won’t ring in this browser.')
              : alarm.blocked ? t('The browser holds it back until you click the page.') : null}
            warn
          >
            <Switch checked={alarm.on} onChange={alarm.set} label={t('Alarm sound')} />
          </Row>

          <Row title={t('Desktop alerts')} detail={desktopState}>
            {desktop.permission === 'granted' && (
              <Switch
                checked={desktop.desktop}
                onChange={(next) => setAlarmSettings({ desktop: next })}
                label={t('Desktop alerts')}
              />
            )}
            {desktop.permission === 'default' && (
              <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" onClick={askDesktopPermission}>{t('Allow')}</button>
            )}
          </Row>

          <Row title={t('Language')} stacked>
            <LanguageSwitch className="rpl-quick-choice" />
          </Row>

          <Row title={t('Appearance')} stacked>
            <div className="rpl-segment rpl-quick-choice" role="radiogroup" aria-label={t('Appearance')}>
              {THEMES.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  role="radio"
                  aria-checked={theme === key}
                  className={`rpl-chip${theme === key ? ' is-selected' : ''}`}
                  onClick={() => applyTheme(key)}
                >
                  {theme === key && <span aria-hidden="true">✓</span>}
                  {label}
                </button>
              ))}
            </div>
          </Row>

          <button type="button" className="rpl-quick-item" onClick={() => leave(onAllSettings)}>
            {t('All settings')}
            <Icon name="chevron-right" size={18} />
          </button>
          <button type="button" className="rpl-quick-item" onClick={() => leave(onSignOut)}>
            {t('Sign out')}
            <Icon name="logout" size={18} />
          </button>
        </div>
      )}
    </div>
  );
}
