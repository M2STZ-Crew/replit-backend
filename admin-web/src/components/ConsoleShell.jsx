import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { useAuth } from '../auth.jsx';
import { PERM, can, consoleOf, roleLine, scopeLine } from '../lib/access.js';
import { PHONE_BELOW, RAIL_BELOW, useMedia } from '../lib/useMedia.js';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import Sidebar from './shell/Sidebar.jsx';
import TopBar from './shell/TopBar.jsx';
import { SETTINGS, consoleAccess, navFor } from './shell/nav.js';
import { useSoundSettings } from './SoundSettings.jsx';
import Icon from './ui/Icon.jsx';

/* The console frame (REPLIT (MAIN) 10 · A83–A85): the sidebar and the top
 * bar around the destination. 1280 px and wider keep the full 248 px sidebar;
 * 1024–1279 px collapse it to the 72 px rail. Narrower windows are not in the
 * design, so they keep the console's phone layout — the first four
 * destinations in a bottom bar, everything else in a More sheet. */

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

/* Who this console belongs to — the organisation, which sidebar it gets
 * (`access`: central or standard) and what the server lets it do (`console`,
 * lib/access.js) — for the pages that adapt to it. */
const ConsoleContext = createContext({
  org: null, access: 'central', console: consoleOf(null), refreshQueues: () => {},
});

export function useConsole() {
  return useContext(ConsoleContext);
}

function initials(name, email) {
  const source = (name || email || '?').trim();
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

export default function ConsoleShell({ active, onNavigate, children }) {
  const { user, logout } = useAuth();
  const { seenAt, newSince } = useLiveFeed();
  const sound = useSoundSettings();
  const rail = useMedia(RAIL_BELOW);
  const phone = useMedia(PHONE_BELOW);
  const [queues, setQueues] = useState({ affiliates: 0, ids: 0, requests: 0 });
  const [queueTick, setQueueTick] = useState(0);
  const refreshQueues = useCallback(() => setQueueTick((t) => t + 1), []);
  const [organizations, setOrganizations] = useState([]);
  const [moreOpen, setMoreOpen] = useState(false);
  const moreButton = useRef(null);
  const sheet = useRef(null);

  const consoleInfo = useMemo(() => consoleOf(user), [user]);
  const access = consoleAccess(consoleInfo);
  const items = useMemo(() => navFor(consoleInfo), [consoleInfo]);
  // Only the queues this Admin answers are read: the hub's two, and the
  // pending alarm escalations for whoever sets the level (BFP, or the system
  // Admin that sees everything).
  const reviewsAffiliates = can(consoleInfo, PERM.REVIEW_AFFILIATES);
  const reviewsIds = can(consoleInfo, PERM.REVIEW_IDS);
  const answersAlarms = can(consoleInfo, PERM.DECIDE_ALARM) || consoleInfo.variant === 'system';

  // Pending queues, refreshed whenever the operator moves between screens or
  // a screen settles an item. A queue that cannot be read shows no count
  // rather than a wrong one.
  useEffect(() => {
    let cancelled = false;
    const none = Promise.resolve([]);
    (async () => {
      const [affs, ids, requests] = await Promise.all([
        reviewsAffiliates ? api.affiliates('pending').catch(() => []) : none,
        reviewsIds ? api.pendingVerifications().catch(() => []) : none,
        answersAlarms ? api.alarmRequests('pending').catch(() => []) : none,
      ]);
      if (!cancelled) {
        setQueues({ affiliates: affs.length, ids: ids.length, requests: requests.length });
      }
    })();
    return () => { cancelled = true; };
  }, [active, queueTick, reviewsAffiliates, reviewsIds, answersAlarms]);

  useEffect(() => {
    let cancelled = false;
    api.organizations()
      .then((rows) => { if (!cancelled) setOrganizations(Array.isArray(rows) ? rows : []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // The More sheet behaves as a dialog: focus moves into it, Tab stays inside,
  // Escape closes it, and focus returns to the More button afterwards.
  useEffect(() => {
    if (!moreOpen) return undefined;
    const panel = sheet.current;
    const opener = moreButton.current;
    panel?.querySelector(FOCUSABLE)?.focus();
    function onKey(e) {
      if (e.key === 'Escape') {
        setMoreOpen(false);
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const focusable = [...panel.querySelectorAll(FOCUSABLE)];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      opener?.focus();
    };
  }, [moreOpen]);

  useEffect(() => { if (!phone) setMoreOpen(false); }, [phone]);

  function go(key) {
    setMoreOpen(false);
    onNavigate(key);
  }

  function counts(item) {
    const badge = item.badge;
    if (!badge) return { count: 0 };
    if (badge.startsWith('new:')) {
      // The surface you are looking at has nothing new to tell you about.
      if (item.key === active) return { count: 0 };
      const count = newSince(seenAt[badge.slice(4)]).length;
      return { count, label: `${count} new since you last looked` };
    }
    const count = queues[badge] ?? 0;
    return { count, label: `${count} waiting` };
  }

  // The organisation as the server named it on sign-in, with its full
  // profile (address, contacts) from the directory once that has loaded.
  const org = useMemo(() => {
    const named = consoleInfo.organization;
    const id = named?.id ?? user?.primary_org_id ?? null;
    const own = organizations.find((o) => o.id === id);
    return {
      id,
      profile: own ?? null,
      name: named?.name ?? own?.name ?? 'RepLiT · Pasay City',
      agency: named?.agency_type ?? own?.agency_type ?? null,
      role: roleLine(consoleInfo),
    };
  }, [organizations, user, consoleInfo]);

  const scope = scopeLine(consoleInfo);

  const person = {
    name: user?.full_name || user?.email || 'Signed in',
    email: user?.email || '',
    initials: initials(user?.full_name, user?.email),
  };

  const unread = active === 'incidents' ? 0 : newSince(seenAt.incidents).length;
  const barItems = items.slice(0, 4);
  const moreItems = items.slice(4);
  const moreCount = moreItems.reduce((sum, item) => sum + counts(item).count, 0);
  const moreActive = active === SETTINGS.key || moreItems.some((item) => item.key === active);

  return (
    <div className={`ad-shell${rail ? ' is-rail' : ''}`}>
      {!phone && (
        <Sidebar
          items={items}
          active={active}
          onNavigate={go}
          counts={counts}
          org={org}
          user={person}
          onSignOut={logout}
          rail={rail}
        />
      )}

      <div className="ad-main">
        <TopBar
          organization={org.name}
          scope={scope}
          soundOn={sound.enabled}
          onSound={() => go(SETTINGS.key)}
          unread={unread}
          onUnread={() => go('incidents')}
        />
        <main className="ad-content">
          <ConsoleContext.Provider value={{ org, access, console: consoleInfo, refreshQueues }}>
            {children}
          </ConsoleContext.Provider>
        </main>
      </div>

      {phone && (
        <nav className="ad-bar" aria-label="Destinations">
          {barItems.map((item) => {
            const { count, label } = counts(item);
            const on = active === item.key;
            return (
              <button
                key={item.key}
                type="button"
                className={`ad-bar-item${on ? ' is-active' : ''}`}
                onClick={() => go(item.key)}
                aria-current={on ? 'page' : undefined}
                aria-label={count ? `${item.label}, ${label}` : item.label}
              >
                <Icon name={item.icon} />
                <span>{item.label}</span>
                {count > 0 && <span className="ad-count" aria-hidden="true">{count}</span>}
              </button>
            );
          })}
          <button
            ref={moreButton}
            type="button"
            className={`ad-bar-item${moreActive ? ' is-active' : ''}`}
            onClick={() => setMoreOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            aria-label={moreCount ? `More, ${moreCount} waiting` : 'More'}
          >
            <Icon name="settings" />
            <span>More</span>
            {moreCount > 0 && <span className="ad-count" aria-hidden="true">{moreCount}</span>}
          </button>
        </nav>
      )}

      {phone && moreOpen && (
        <div className="ad-sheet-layer">
          <div className="ad-scrim" onClick={() => setMoreOpen(false)} aria-hidden="true" />
          <div
            className="ad-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ad-sheet-title"
            ref={sheet}
          >
            <span className="ad-sheet-grip" aria-hidden="true" />
            <div className="ad-sheet-head">
              <h2 id="ad-sheet-title" className="ad-sheet-title">More</h2>
              <button type="button" className="ad-icon-button" onClick={() => setMoreOpen(false)} aria-label="Close">
                <span aria-hidden="true">✕</span>
              </button>
            </div>
            {[...moreItems, SETTINGS].map((item) => {
              const { count, label } = counts(item);
              const on = active === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  className={`ad-nav-item${on ? ' is-active' : ''}`}
                  onClick={() => go(item.key)}
                  aria-current={on ? 'page' : undefined}
                >
                  <Icon name={item.icon} />
                  <span className="ad-nav-label">{item.label}</span>
                  {count > 0 && <span className="ad-count" aria-label={label}>{count}</span>}
                </button>
              );
            })}
            <div className="ad-user">
              <span className="ad-avatar" aria-hidden="true">{person.initials}</span>
              <span className="ad-user-text">
                <span className="ad-user-name">{person.name}</span>
                <span className="ad-user-email">{person.email}</span>
              </span>
              <button type="button" className="ad-icon-button" onClick={logout} aria-label="Sign out" title="Sign out">
                <Icon name="logout" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
