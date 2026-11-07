import { useEffect, useState } from 'react';

import { consoleOf, soundCategories } from '../lib/access.js';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import { CATEGORY_LABEL, categoriesOf } from '../sound/cues.js';
import { useConsole } from './ConsoleShell.jsx';
import {
  askDesktopPermission,
  kindOf,
  reportsOf,
  soundUnlocked,
  statusLabel,
  useAlarmSettings,
} from '../sound/alarm.js';
import { t } from '../i18n/i18n.jsx';

const BASE_TITLE = typeof document !== 'undefined' ? document.title : 'RepLiT Admin';

function ago(iso, now) {
  const mins = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return t('{mins} min ago', { mins });
  const hrs = Math.floor(mins / 60);
  return t('{hrs} h {mins} min ago', { hrs, mins: mins % 60 });
}

function clock(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/// While anything is unanswered, the tab's title blinks with the count, so the
/// console is findable among other tabs and on the taskbar.
function useTitleFlash(count) {
  useEffect(() => {
    if (!count) return undefined;
    const alert = count === 1
      ? t('({count}) New incident', { count })
      : t('({count}) New incidents', { count });
    let lit = false;
    const flip = () => {
      lit = !lit;
      document.title = lit ? alert : BASE_TITLE;
    };
    flip();
    const timer = setInterval(flip, 1000);
    return () => {
      clearInterval(timer);
      document.title = BASE_TITLE;
    };
  }, [count]);
}

/* The incidents still ringing, on top of every screen until each is answered.
 *
 * Opening one answers it and takes the admin to it; Acknowledge answers it in
 * place. It also says when the alarm cannot be heard — the browser holds sound
 * back until someone clicks the page — and offers desktop alerts for when the
 * console is behind another window. */
export default function AlarmBanner({ onOpen }) {
  const { alarms, acknowledge } = useLiveFeed();
  const { console: access } = useConsole() ?? {};
  const sounding = soundCategories(access ?? consoleOf(null));
  const alarm = useAlarmSettings();
  const [now, setNow] = useState(Date.now);
  const [canSound, setCanSound] = useState(soundUnlocked);

  useTitleFlash(alarms.length);

  // Keep "n min ago" honest while the banner is up.
  useEffect(() => {
    if (!alarms.length) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 20_000);
    return () => clearInterval(timer);
  }, [alarms.length]);

  useEffect(() => {
    if (canSound) return undefined;
    const unlocked = () => setCanSound(true);
    window.addEventListener('pointerdown', unlocked, { once: true });
    window.addEventListener('keydown', unlocked, { once: true });
    return () => {
      window.removeEventListener('pointerdown', unlocked);
      window.removeEventListener('keydown', unlocked);
    };
  }, [canSound]);

  if (!alarms.length) return null;

  const many = alarms.length > 1;

  // REPLIT (MAIN) 10 · A21 (865:1722): each ringing Area as a live-tinted
  // card — what came in and where, that its sound is looping, and Open
  // incident. Opening it stops the sound; it does not acknowledge the Area
  // (that is a separate act in the incident). "Stop the sound" silences it
  // without leaving the page.
  return (
    <section className="rpl-alarms" role="alert" aria-live="assertive">
      {many && (
        <div className="rpl-alarms-head">
          <span>{alarms.length}{' '}{t('new incidents are ringing')}</span>
          <button
            type="button"
            className="rpl-text-button"
            onClick={() => acknowledge(alarms.map((inc) => inc.id))}
          >{t('Stop every sound')}</button>
        </div>
      )}
      {alarms.map((inc) => {
        const kind = kindOf(inc);
        // The sound this Admin hears for it: its own agency's (lib/access.js).
        const heard = categoriesOf(inc).filter((c) => sounding.includes(c)).map((c) => CATEGORY_LABEL[c]).join(' · ') || kind;
        return (
          <div className="rpl-alarm" key={inc.id}>
            <span className="rpl-alarm-plate" aria-hidden="true">
              <img src="/icons/fire.svg" alt="" width="20" height="20" />
            </span>
            <div className="rpl-alarm-text">
              <p className="rpl-alarm-eyebrow">{t('New incident ·')}{' '}{heard}{' '}{t('sound playing')}</p>
              <p className="rpl-alarm-title">{kind}{' '}{t('reported —')}{' '}{inc.designation}</p>
              <p className="rpl-alarm-body">
                {reportsOf(inc)} · {statusLabel(inc.status)} ·{' '}
                <span title={new Date(inc.reported_at).toLocaleString()}>
                  {clock(inc.reported_at)}, {ago(inc.reported_at, now)}
                </span>{t('. Opening the incident stops the sound; it doesn’t acknowledge it.')}</p>
            </div>
            <span className="rpl-alarm-loop">
              <img src="/icons/volume.svg" alt="" width="16" height="16" />{t('Looping until answered')}</span>
            <button type="button" className="rpl-text-button" onClick={() => acknowledge(inc.id)}>{t('Stop the sound')}</button>
            <button type="button" className="rpl-button rpl-button--primary" onClick={() => onOpen(inc.id)}>{t('Open incident')}</button>
          </div>
        );
      })}

      {(!canSound || alarm.permission === 'default') && (
        <div className="rpl-alarms-hints">
          {!canSound && (
            <p>{t('The browser is holding the alarm sound back. Click anywhere on this page to let it ring.')}</p>
          )}
          {alarm.permission === 'default' && (
            <p>{t('Want an alert when this tab is in the background?')}{' '}
              <button type="button" className="rpl-text-button" onClick={askDesktopPermission}>{t('Turn on desktop alerts')}</button>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
