import { useEffect, useState } from 'react';

import { useLiveFeed } from '../live/LiveFeed.jsx';
import {
  askDesktopPermission,
  kindOf,
  reportsOf,
  soundUnlocked,
  statusLabel,
  useAlarmSettings,
} from '../sound/alarm.js';

const BASE_TITLE = typeof document !== 'undefined' ? document.title : 'RepLiT Admin';

function ago(iso, now) {
  const mins = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs} h ${mins % 60} min ago`;
}

function clock(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/// While anything is unanswered, the tab's title blinks with the count, so the
/// console is findable among other tabs and on the taskbar.
function useTitleFlash(count) {
  useEffect(() => {
    if (!count) return undefined;
    const alert = `(${count}) New incident${count === 1 ? '' : 's'}`;
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

  return (
    <section className="al" role="alert" aria-live="assertive">
      <header className="al-head">
        <span className="al-beacon" aria-hidden="true" />
        <span className="al-kicker">
          {many ? `${alarms.length} new incidents` : 'New incident'}
        </span>
        <span className="al-repeat">
          {alarm.repeat
            ? `Rings every ${alarm.everySec} s until acknowledged`
            : 'Repeat is off: this rang once'}
        </span>
        {many && (
          <button
            type="button"
            className="al-btn al-all"
            onClick={() => acknowledge(alarms.map((inc) => inc.id))}
          >
            Acknowledge all
          </button>
        )}
      </header>

      <ul className="al-list">
        {alarms.map((inc) => (
          <li className="al-item" key={inc.id}>
            <div className="al-what">
              <span className="al-name">{inc.designation}</span>
              <span className="al-meta">
                <span className="al-kind">{kindOf(inc)}</span>
                <span>{reportsOf(inc)}</span>
                <span>{statusLabel(inc.status)}</span>
                <span title={new Date(inc.reported_at).toLocaleString()}>
                  {clock(inc.reported_at)} · {ago(inc.reported_at, now)}
                </span>
              </span>
            </div>
            <div className="al-actions">
              <button type="button" className="al-btn is-primary" onClick={() => onOpen(inc.id)}>
                Open
              </button>
              <button type="button" className="al-btn" onClick={() => acknowledge(inc.id)}>
                Acknowledge
              </button>
            </div>
          </li>
        ))}
      </ul>

      {(!canSound || alarm.permission === 'default') && (
        <div className="al-hints">
          {!canSound && (
            <p className="al-hint">
              The browser is holding the alarm sound back. Click anywhere on this page to let
              it ring.
            </p>
          )}
          {alarm.permission === 'default' && (
            <p className="al-hint">
              Want an alert when this tab is in the background?{' '}
              <button type="button" className="al-link" onClick={askDesktopPermission}>
                Turn on desktop alerts
              </button>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
