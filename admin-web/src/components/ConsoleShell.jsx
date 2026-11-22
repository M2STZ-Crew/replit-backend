import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { useAuth } from '../auth.jsx';
import { PERM, can, consoleOf, roleLine, scopeLine } from '../lib/access.js';
import { PHONE_BELOW, RAIL_BELOW, useMedia } from '../lib/useMedia.js';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import Sidebar from './shell/Sidebar.jsx';
import TopBar from './shell/TopBar.jsx';
import { SETTINGS, consoleAccess, navFor } from './shell/nav.js';
import ConfirmDialog from './ui/ConfirmDialog.jsx';
import Icon from './ui/Icon.jsx';
import { t, useLanguage } from '../i18n/i18n.jsx';

/* The console frame (REPLIT (MAIN) 10 · A83–A85): the sidebar and the top
 * bar around the destination. 1280 px and wider open with the full 248 px
 * sidebar and 1024–1279 px with the 72 px rail, until the Admin picks one:
 * since v1.12.50 the toggle by the logo (22 Nov 2026: "Lagyan ng Sidebar
 * Toggle"; answered "In the sidebar") is remembered by the browser and works
 * at any desktop width. Narrower windows are not in the
 * design, so they keep the console's phone layout — the first four
 * destinations in a bottom bar, everything else in a More sheet. */

// The sidebar as this browser's Admin left it: 'collapsed', 'expanded', or
// null while nobody has chosen.
const SIDEBAR_STORE = 'replit.sidebar.v1';

function savedSidebar() {
  try {
    const saved = localStorage.getItem(SIDEBAR_STORE);
    return saved === 'collapsed' || saved === 'expanded' ? saved : null;
  } catch {
    return null;
  }
}

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
  const narrow = useMedia(RAIL_BELOW);
  const phone = useMedia(PHONE_BELOW);
  const [sidebar, setSidebar] = useState(savedSidebar);
  const rail = !phone && (sidebar ? sidebar === 'collapsed' : narrow);
  const [queues, setQueues] = useState({ affiliates: 0, ids: 0, requests: 0, strikes: 0, water: 0 });
  const [queueTick, setQueueTick] = useState(0);
  const refreshQueues = useCallback(() => setQueueTick((t) => t + 1), []);
  const [organizations, setOrganizations] = useState([]);
  const [moreOpen, setMoreOpen] = useState(false);
  // Signing out asks first (17 Nov 2026: "if the user press logout it make it
  // having a confirmation"): a signed-out console shows and sounds nothing new.
  const [askingSignOut, setAskingSignOut] = useState(false);
  const moreButton = useRef(null);
  const sheet = useRef(null);
  // The nav's labels are worked out once per account; a new language works
  // them out again, since the console is redrawn rather than rebuilt (i18n).
  const { language } = useLanguage();

  const consoleInfo = useMemo(() => consoleOf(user), [user]);
  const access = consoleAccess(consoleInfo);
  const items = useMemo(() => navFor(consoleInfo), [consoleInfo, language]); // eslint-disable-line react-hooks/exhaustive-deps
  // Only the queues this Admin answers are read: the hub's two, and the
  // pending alarm escalations for whoever sets the level (BFP, or the system
  // Admin that sees everything).
  const reviewsAffiliates = can(consoleInfo, PERM.REVIEW_AFFILIATES);
  const reviewsIds = can(consoleInfo, PERM.REVIEW_IDS);
  const reviewsStrikes = can(consoleInfo, PERM.REVIEW_STRIKES);
  const managesMap = can(consoleInfo, PERM.MANAGE_MAP);
  const answersAlarms = can(consoleInfo, PERM.DECIDE_ALARM) || consoleInfo.variant === 'system';

  // Pending queues, refreshed whenever the operator moves between screens or
  // a screen settles an item. A queue that cannot be read shows no count
  // rather than a wrong one.
  useEffect(() => {
    let cancelled = false;
    const none = Promise.resolve([]);
    (async () => {
      const [affs, ids, requests, toCheck, appeals, mapRequests] = await Promise.all([
        reviewsAffiliates ? api.affiliates('pending').catch(() => []) : none,
        reviewsIds ? api.pendingVerifications().catch(() => []) : none,
        answersAlarms ? api.alarmRequests('pending').catch(() => []) : none,
        // Prank reports (v1.12.41): 3rd and 4th steps to check, and appeals.
        reviewsStrikes ? api.reportStrikes('to_check').catch(() => []) : none,
        reviewsStrikes ? api.reportStrikes('appeals').catch(() => []) : none,
        // Coordinators' water changes awaiting approval (v1.12.43).
        managesMap ? api.mapLayerRequests('pending').catch(() => []) : none,
      ]);
      if (!cancelled) {
        setQueues({
          affiliates: affs.length,
          ids: ids.length,
          requests: requests.length,
          strikes: toCheck.length + appeals.length,
          water: (Array.isArray(mapRequests) ? mapRequests : []).filter(
            (r) => ['hydrant', 'bodies_of_water', 'underground_cistern'].includes(r.layer_type),
          ).length,
        });
      }
    })();
    return () => { cancelled = true; };
  }, [active, queueTick, reviewsAffiliates, reviewsIds, reviewsStrikes, managesMap, answersAlarms]);

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

  function toggleSidebar() {
    const next = rail ? 'expanded' : 'collapsed';
    setSidebar(next);
    try {
      localStorage.setItem(SIDEBAR_STORE, next);
    } catch {
      /* storage blocked: the choice holds for this visit */
    }
  }

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
      return { count, label: t('{count} new since you last looked', { count }) };
    }
    const count = queues[badge] ?? 0;
    return { count, label: t('{count} waiting', { count }) };
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
      name: named?.name ?? own?.name ?? t('RepLiT · Pasay City'),
      agency: named?.agency_type ?? own?.agency_type ?? null,
      role: roleLine(consoleInfo),
    };
  }, [organizations, user, consoleInfo, language]); // eslint-disable-line react-hooks/exhaustive-deps

  const scope = scopeLine(consoleInfo);

  const person = {
    name: user?.full_name || user?.email || t('Signed in'),
    email: user?.email || '',
    initials: initials(user?.full_name, user?.email),
  };

  const barItems = items.slice(0, 4);
  const moreItems = items.slice(4);
  const moreCount = moreItems.reduce((sum, item) => sum + counts(item).count, 0);
  const moreActive = active === SETTINGS.key || moreItems.some((item) => item.key === active);

  return (
    <div className={`rpl-shell${rail ? ' is-rail' : ''}${!rail && !phone && narrow ? ' is-tight' : ''}`}>
      {!phone && (
        <Sidebar
          items={items}
          active={active}
          onNavigate={go}
          counts={counts}
          org={org}
          user={person}
          onSignOut={() => setAskingSignOut(true)}
          rail={rail}
          onToggle={toggleSidebar}
        />
      )}

      <div className="rpl-main">
        <TopBar
          organization={org.name}
          scope={scope}
          access={consoleInfo}
          onAllSettings={() => go(SETTINGS.key)}
          onSignOut={() => setAskingSignOut(true)}
        />
        <main className="rpl-content">
          <ConsoleContext.Provider value={{ org, access, console: consoleInfo, refreshQueues }}>
            {children}
          </ConsoleContext.Provider>
        </main>
      </div>

      {phone && (
        <nav className="rpl-bar" aria-label={t('Destinations')}>
          {barItems.map((item) => {
            const { count, label } = counts(item);
            const on = active === item.key;
            return (
              <button
                key={item.key}
                type="button"
                className={`rpl-bar-item${on ? ' is-active' : ''}`}
                onClick={() => go(item.key)}
                aria-current={on ? 'page' : undefined}
                aria-label={count ? `${item.label}, ${label}` : item.label}
              >
                <Icon name={item.icon} />
                <span>{item.shortLabel ?? item.label}</span>
                {count > 0 && <span className="rpl-count" aria-hidden="true">{count}</span>}
              </button>
            );
          })}
          <button
            ref={moreButton}
            type="button"
            className={`rpl-bar-item${moreActive ? ' is-active' : ''}`}
            onClick={() => setMoreOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            aria-label={moreCount ? t('More, {count} waiting', { count: moreCount }) : t('More')}
          >
            <Icon name="more" />
            <span>{t('More')}</span>
            {moreCount > 0 && <span className="rpl-count" aria-hidden="true">{moreCount}</span>}
          </button>
        </nav>
      )}

      {phone && moreOpen && (
        <div className="rpl-sheet-layer">
          <div className="rpl-scrim" onClick={() => setMoreOpen(false)} aria-hidden="true" />
          <div
            className="rpl-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rpl-sheet-title"
            ref={sheet}
          >
            <span className="rpl-sheet-grip" aria-hidden="true" />
            <div className="rpl-sheet-head">
              <h2 id="rpl-sheet-title" className="rpl-sheet-title">{t('More')}</h2>
              <button type="button" className="rpl-icon-button" onClick={() => setMoreOpen(false)} aria-label={t('Close')}>
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
                  className={`rpl-nav-item${on ? ' is-active' : ''}`}
                  onClick={() => go(item.key)}
                  aria-current={on ? 'page' : undefined}
                >
                  <Icon name={item.icon} />
                  <span className="rpl-nav-label">{item.label}</span>
                  {count > 0 && <span className="rpl-count" aria-label={label}>{count}</span>}
                </button>
              );
            })}
            <div className="rpl-user">
              <span className="rpl-avatar" aria-hidden="true">{person.initials}</span>
              <span className="rpl-user-text">
                <span className="rpl-user-name">{person.name}</span>
                <span className="rpl-user-email">{person.email}</span>
              </span>
              <button
                type="button"
                className="rpl-icon-button"
                onClick={() => { setMoreOpen(false); setAskingSignOut(true); }}
                aria-label={t('Sign out')}
                title={t('Sign out')}
              >
                <Icon name="logout" />
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={askingSignOut}
        title={t('Sign out?')}
        description={t('You’ll need your email and password to sign in again. Until then, this browser won’t show or sound new alerts.')}
        confirmLabel={t('Sign out')}
        destructive
        onClose={() => setAskingSignOut(false)}
        onConfirm={logout}
      />
    </div>
  );
}
