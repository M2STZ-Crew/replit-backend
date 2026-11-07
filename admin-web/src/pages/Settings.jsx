import { useState } from 'react';

import { useConsole } from '../components/ConsoleShell.jsx';
import { useSoundSettings } from '../components/SoundSettings.jsx';
import { Icon, PageHeader } from '../components/ui/index.js';
import {
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
import { api } from '../api/client.js';
import { LanguageSwitch, t } from '../i18n/i18n.jsx';
import { applyTheme, storedTheme } from '../theme.js';

/* Settings (REPLIT (MAIN) 10 · A70): notification sounds per category and
 * desktop alerts, kept in this browser. A new incident's sound loops until an
 * admin answers it (PRD v14 §4.13.1); muting its category is the way to
 * silence it here.
 *
 * Availability (AFK, A71) is not here: no endpoint stores or reports it yet
 * (PRD v13 §4.6.5, §17.3), so the switch is prepared as AvailabilityPanel
 * and shown only in the development preview. */

function Switch({ checked, onChange, label, disabled = false }) {
  return (
    <label className={`rpl-switch${disabled ? ' is-disabled' : ''}`}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="rpl-switch-track" aria-hidden="true" />
      <span className="web-sr-only">{label}</span>
    </label>
  );
}

function Row({ title, detail, children, dim = false }) {
  return (
    <div className={`rpl-setting${dim ? ' is-dim' : ''}`}>
      <div className="rpl-setting-text">
        <span className="rpl-setting-title">{title}</span>
        {detail && <span className="rpl-setting-detail">{detail}</span>}
      </div>
      <div className="rpl-setting-control">{children}</div>
    </div>
  );
}

/* The organisation's availability (A70, A71). UI READY: `afk`, `since` and
 * `busy` come from whoever owns the state; `onChange(next)` is called with the
 * wanted value and must resolve once the server has recorded it. */
export function AvailabilityPanel({ afk, since, busy = false, error = null, onChange }) {
  return (
    <section className="rpl-panel" aria-labelledby="rpl-availability-title">
      <h2 className="rpl-panel-title" id="rpl-availability-title">{t('Availability')}</h2>
      <Row
        title={afk
          ? since
            ? t('Away from the console since {since}', { since })
            : t('Away from the console')
          : t('At the console')}
        detail={t('Other Admins see your organization greyed out with an AFK chip. Incidents still move: any Coordinator of yours can acknowledge.')}
      >
        <Switch
          checked={afk}
          disabled={busy || !onChange}
          onChange={(next) => onChange?.(next)}
          label={t('Away from the console')}
        />
      </Row>
      {error && <p className="rpl-inline-error" role="alert">{error}</p>}
    </section>
  );
}

/* Account · Change password (follow-up 1.2): checked against the current
 * password by the API, which then signs the account out everywhere else and
 * keeps this browser signed in. The API's reason codes get the console's own
 * words, in the console's language. */
function PasswordPanel() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (next.length < 8 || next.length > 128) {
      setResult({ tone: 'error', text: t('Use 8 to 128 characters for the new password.') });
      return;
    }
    if (next !== again) {
      setResult({ tone: 'error', text: t('The two new passwords are not the same.') });
      return;
    }
    if (next === current) {
      setResult({ tone: 'error', text: t('The new password is the same as the current one.') });
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      await api.changePassword(current, next);
      setCurrent('');
      setNext('');
      setAgain('');
      setResult({
        tone: 'ok',
        text: t('Password changed. Other browsers and phones are signed out; this one stays signed in.'),
      });
    } catch (err) {
      const text =
        err?.code === 'wrong_password'
          ? t('That is not your current password.')
          : err?.code === 'same_password'
            ? t('The new password is the same as the current one.')
            : err?.status === 422
              ? t('Use 8 to 128 characters for the new password.')
              : err?.message || t('The password could not be changed. Try again.');
      setResult({ tone: 'error', text });
    } finally {
      setBusy(false);
    }
  };

  const field = (label, value, onChange, autoComplete) => (
    <label className="rpl-field">
      <span className="rpl-field-label">{label}</span>
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        disabled={busy}
        maxLength={128}
      />
    </label>
  );

  return (
    <section className="rpl-panel" aria-labelledby="rpl-account-title">
      <h2 className="rpl-panel-title" id="rpl-account-title">{t('Account')}</h2>
      <p className="rpl-panel-note">
        {t('Changing the password signs you out of RepLiT on other browsers and phones.')}
      </p>
      <form className="rpl-password-form" onSubmit={submit}>
        {field(t('Current password'), current, setCurrent, 'current-password')}
        {field(t('New password'), next, setNext, 'new-password')}
        {field(t('New password again'), again, setAgain, 'new-password')}
        <label className="rpl-password-show">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
          {t('Show passwords')}
        </label>
        {result && (
          <p
            className={`rpl-password-result ${result.tone === 'ok' ? 'is-ok' : 'rpl-field-error'}`}
            role={result.tone === 'ok' ? 'status' : 'alert'}
          >
            {result.text}
          </p>
        )}
        <button
          type="submit"
          className="rpl-button rpl-button--primary"
          disabled={busy || !current || !next || !again}
        >
          {busy ? t('Changing…') : t('Change password')}
        </button>
      </form>
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
    <div className="rpl-page rpl-page--narrow">
      <PageHeader
        eyebrow={org?.name ?? t('Console')}
        title={t('Settings')}
        description={t('Your language and password belong to your account. Sounds and alerts are kept in this browser.')}
      />
      <section className="rpl-panel" aria-labelledby="rpl-language-title">
        <h2 className="rpl-panel-title" id="rpl-language-title">{t('Language')}</h2>
        <Row
          title={t('English or Tagalog')}
          detail={t('Saved to your account: this console and the RepLiT app use it, and so do your alerts.')}
        >
          <LanguageSwitch />
        </Row>
      </section>

      <PasswordPanel />

      <section className="rpl-panel" aria-labelledby="rpl-sounds-title">
        <div className="rpl-panel-head">
          <h2 className="rpl-panel-title" id="rpl-sounds-title">{t('Notification sounds')}</h2>
          <Switch checked={sound.enabled} onChange={(enabled) => update({ enabled })} label={t('All sounds')} />
        </div>
        <p className="rpl-panel-note">{t('A sound per incident category, so you can tell them apart without looking. A new incident rings until you open it.')}</p>
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
                className="rpl-button rpl-button--secondary rpl-button--compact"
                onClick={() => update({ muted: { ...sound.muted, [c]: !muted } })}
                disabled={off}
                aria-pressed={muted}
              >
                {muted ? t('Muted') : t('Mute')}
              </button>
              <input
                className="rpl-range"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={sound.volume[c]}
                disabled={off || muted}
                onChange={(e) => update({ volume: { ...sound.volume, [c]: Number(e.target.value) } })}
                aria-label={t('{category} volume', { category: CATEGORY_LABEL[c] })}
                aria-valuetext={`${Math.round(sound.volume[c] * 100)}%`}
              />
              <span className="rpl-range-value" aria-hidden="true">
                {Math.round(sound.volume[c] * 100)}%
              </span>
              <button
                type="button"
                className="rpl-button rpl-button--secondary rpl-button--compact"
                onClick={() => previewCue(c)}
                disabled={off || muted || sound.volume[c] === 0}
              >
                <Icon name="volume" size={16} />{t('Test')}</button>
            </Row>
          );
        })}
      </section>

      <section className="rpl-panel" aria-labelledby="rpl-repeat-title">
        <h2 className="rpl-panel-title" id="rpl-repeat-title">{t('Alerts')}</h2>
        <Row title={t('Desktop alerts')} detail={t('When this tab is behind another window.')}>
          {alarm.permission === 'granted' ? (
            <Switch
              checked={alarm.desktop}
              onChange={(desktop) => setAlarmSettings({ desktop })}
              label={t('Desktop alerts')}
            />
          ) : alarm.permission === 'default' ? (
            <button
              type="button"
              className="rpl-button rpl-button--secondary rpl-button--compact"
              onClick={askDesktopPermission}
            >{t('Allow')}</button>
          ) : (
            <span className="rpl-setting-detail">
              {alarm.permission === 'denied' ? t('Blocked in browser settings') : t('Not available here')}
            </span>
          )}
        </Row>
      </section>

      <section className="rpl-panel" aria-labelledby="rpl-ground-title">
        <h2 className="rpl-panel-title" id="rpl-ground-title">{t('Appearance')}</h2>
        <Row title={t('Light ground')} detail={t('The console is designed on the dark ground.')}>
          <Switch
            checked={theme === 'light'}
            onChange={(light) => setTheme(applyTheme(light ? 'light' : 'dark'))}
            label={t('Light ground')}
          />
        </Row>
      </section>
    </div>
  );
}
