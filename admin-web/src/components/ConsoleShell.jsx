import { useEffect, useRef, useState } from 'react';

import { api } from '../api/client.js';
import { useAuth } from '../auth.jsx';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import SoundSettings from './SoundSettings.jsx';
import { applyTheme, storedTheme } from '../theme.js';

/* Icons are inline SVG rather than a font or sprite: there are only a handful,
   they never change, and this keeps the shell dependency-free. */
const Icon = {
  grid: (
    <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>
  ),
  map: <><path d="M9 3l6 2 6-2v16l-6 2-6-2-6 2V5l6-2z" /><path d="M9 3v16M15 5v16" /></>,
  flame: <path d="M12 3c1 3.5 5 5.6 5 10a5 5 0 01-10 0c0-2 .8-3.3 2-4.5.3 1.7 1.2 2.6 2.2 2.8C10.6 9 11 6 12 3z" />,
  users: (
    <><path d="M16 20v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2" /><circle cx="9" cy="7" r="3.2" />
      <path d="M22 20v-2a4 4 0 00-3-3.8" /><path d="M16 4.2A3.2 3.2 0 0117 10" /></>
  ),
  shield: (
    <><path d="M12 3l8 4v5c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V7l8-4z" /><circle cx="12" cy="11" r="2.4" />
      <path d="M8.6 17c.7-1.7 2-2.6 3.4-2.6s2.7.9 3.4 2.6" /></>
  ),
  doc: <><path d="M6 3h9l4 4v14H6z" /><path d="M9 9h7M9 13h7M9 17h4" /></>,
  id: <><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="12" r="2.2" /><path d="M14 10h4M14 14h4" /></>,
  chevron: <path d="M15 6l-6 6 6 6" />,
  out: <><path d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3" /><path d="M10 8l-4 4 4 4M6 12h9" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 019.5 4a7 7 0 108.9 10.5z" />,
  more: <><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></>,
  close: <path d="M6 6l12 12M18 6L6 18" />,
};

function Svg({ path, size = 13, stroke = 'var(--accent)' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke}
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {path}
    </svg>
  );
}

/* Nav model. `badge` names a counter. The two incident surfaces carry the v10
   red count (Section 2.9): incidents reported since the operator last viewed
   that surface. The governance queues keep their accent pending-count.

   On a phone the Operations items sit in the bottom bar and the Governance
   items move into the More sheet. All seven in one bar left each ~53px wide
   under a 9px label; four is what a thumb can hit reliably. */
const NAV = [
  { key: 'dashboard', label: 'Situation board', short: 'Board', icon: Icon.grid, group: 'Operations', badge: 'new:dashboard' },
  { key: 'incidents', label: 'Incidents', short: 'Incidents', icon: Icon.flame, group: 'Operations', badge: 'new:incidents' },
  { key: 'map', label: 'Live map', short: 'Map', icon: Icon.map, group: 'Operations' },
  { key: 'affiliates', label: 'Affiliates', icon: Icon.users, group: 'Governance', badge: 'affiliates' },
  { key: 'accounts', label: 'Accounts', icon: Icon.shield, group: 'Governance' },
  { key: 'idreview', label: 'ID review', icon: Icon.id, group: 'Governance', badge: 'ids' },
  { key: 'audit', label: 'Audit log', icon: Icon.doc, group: 'Governance' },
];
const GROUPS = ['Operations', 'Governance'];

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

function initials(name, email) {
  const source = (name || email || '?').trim();
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

function Posture({ active, pending }) {
  return (
    <div className="cs-posture">
      <div className="cs-posture-top">
        <span className="dc-eyebrow">City posture</span>
        <span className={`cs-posture-level${active > 0 ? ' is-elevated' : ''}`}>
          {active > 0 ? 'Elevated' : 'Normal'}
        </span>
      </div>
      <p className="cs-posture-note">
        {active === 0
          ? 'No active incidents.'
          : `${active} active incident${active === 1 ? '' : 's'}` +
            (pending > 0 ? ` · ${pending} awaiting verification` : '')}
      </p>
    </div>
  );
}

function NavItem({ item, active, slim = false, count, onClick }) {
  const isNew = item.badge?.startsWith('new:');
  const on = active === item.key;
  return (
    <button
      className={`cs-item${on ? ' is-active' : ''}`}
      onClick={onClick}
      title={slim ? item.label : undefined}
      aria-current={on ? 'page' : undefined}
    >
      <span className="cs-item-icon"><Svg path={item.icon} /></span>
      {!slim && <span className="cs-item-label">{item.label}</span>}
      {!slim && count > 0 && (
        <span
          className={`cs-badge${isNew ? ' is-new' : ''}`}
          aria-label={isNew ? `${count} new since you last looked` : `${count} pending`}
        >
          {count}
        </span>
      )}
      {slim && count > 0 && <span className={`cs-dot${isNew ? ' is-new' : ''}`} />}
    </button>
  );
}

export default function ConsoleShell({ active, onNavigate, children }) {
  // Which ground the console draws on. The switch sits with sign-out in
  // the sidebar; nothing else about the layout changes with it.
  const [theme, setTheme] = useState(storedTheme);
  const { user, logout } = useAuth();
  const { stats, seenAt, newSince } = useLiveFeed();
  const [slim, setSlim] = useState(
    () => localStorage.getItem('replit.nav.slim') === '1',
  );
  const [queues, setQueues] = useState({ affiliates: 0, ids: 0 });
  const [moreOpen, setMoreOpen] = useState(false);
  const moreButton = useRef(null);
  const sheet = useRef(null);

  useEffect(() => {
    localStorage.setItem('replit.nav.slim', slim ? '1' : '0');
  }, [slim]);

  // Governance queue counts, refreshed whenever the operator moves between screens.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [affs, ids] = await Promise.all([
        api.affiliates('pending').catch(() => []),
        api.pendingVerifications().catch(() => []),
      ]);
      if (!cancelled) setQueues({ affiliates: affs.length, ids: ids.length });
    })();
    return () => { cancelled = true; };
  }, [active]);

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
      const items = [...panel.querySelectorAll(FOCUSABLE)];
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
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

  function go(key) {
    setMoreOpen(false);
    onNavigate(key);
  }

  function countFor(badge, key) {
    if (!badge) return 0;
    if (badge.startsWith('new:')) {
      // The surface you are looking at has nothing new to tell you about.
      if (key === active) return 0;
      return newSince(seenAt[badge.slice(4)]).length;
    }
    return queues[badge] ?? 0;
  }

  const activeCount = stats?.active_incidents ?? 0;
  const pendingVerify = stats?.pending_verify ?? 0;
  const governance = NAV.filter((n) => n.group === 'Governance');
  const governanceCount = governance.reduce((sum, n) => sum + countFor(n.badge, n.key), 0);
  const moreActive = governance.some((n) => n.key === active);
  const name = user?.full_name || user?.email || 'Signed in';

  return (
    <div className={`cs${slim ? ' is-slim' : ''}`}>
      <aside className="cs-nav">
        <div className="cs-brand">
          <img src="/assets/logo-mark.png" alt="" width="34" height="34" />
          {!slim && (
            <div className="cs-brand-text">
              <span className="cs-brand-name">RepLiT</span>
              <span className="cs-brand-sub">Admin console</span>
            </div>
          )}
          <button
            className="cs-collapse"
            onClick={() => setSlim((s) => !s)}
            title={slim ? 'Expand navigation' : 'Minimise navigation'}
            aria-label={slim ? 'Expand navigation' : 'Minimise navigation'}
          >
            <Svg path={Icon.chevron} stroke="var(--label)" />
          </button>
        </div>

        {GROUPS.map((group) => (
          <div className="cs-group" key={group}>
            {!slim && <span className="cs-group-label">{group}</span>}
            {NAV.filter((n) => n.group === group).map((n) => (
              <NavItem
                key={n.key}
                item={n}
                active={active}
                slim={slim}
                count={countFor(n.badge, n.key)}
                onClick={() => go(n.key)}
              />
            ))}
          </div>
        ))}

        <div className="cs-spacer" />

        {!slim && <Posture active={activeCount} pending={pendingVerify} />}

        <SoundSettings slim={slim} />

        <div className="cs-user">
          <span className="cs-avatar">{initials(user?.full_name, user?.email)}</span>
          {!slim && (
            <div className="cs-user-text">
              <span className="cs-user-name">{name}</span>
              <span className="cs-user-role">Admin · full access</span>
            </div>
          )}
          <button
            className="cs-signout"
            onClick={() => setTheme(applyTheme(theme === 'light' ? 'dark' : 'light'))}
            title={theme === 'light' ? 'Switch to the dark ground' : 'Switch to the light ground'}
            aria-label="Switch theme"
          >
            <Svg path={theme === 'light' ? Icon.moon : Icon.sun} stroke="var(--muted)" />
          </button>
          <button className="cs-signout" onClick={logout} title="Sign out" aria-label="Sign out">
            <Svg path={Icon.out} stroke="var(--muted)" />
          </button>
        </div>
      </aside>

      <main className="cs-main">{children}</main>

      {/* Below 900px the sidebar becomes a bottom bar: the three Operations
          screens plus More. Only the red new-incident count survives on the
          bar itself; the governance queues total onto More. */}
      <nav className="cs-bar" aria-label="Sections">
        {NAV.filter((n) => n.group === 'Operations').map((n) => {
          const count = countFor(n.badge, n.key);
          const on = active === n.key;
          return (
            <button
              key={n.key}
              className={`cs-bar-item${on ? ' is-active' : ''}`}
              onClick={() => go(n.key)}
              aria-current={on ? 'page' : undefined}
            >
              <Svg path={n.icon} size={19} stroke={on ? 'var(--accent)' : 'var(--muted)'} />
              <span>{n.short}</span>
              {count > 0 && (
                <span className="cs-bar-new" aria-label={`${count} new`}>{count}</span>
              )}
            </button>
          );
        })}
        <button
          ref={moreButton}
          className={`cs-bar-item${moreActive ? ' is-active' : ''}`}
          onClick={() => setMoreOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={moreOpen}
        >
          <Svg path={Icon.more} size={19} stroke={moreActive ? 'var(--accent)' : 'var(--muted)'} />
          <span>More</span>
          {governanceCount > 0 && (
            <span className="cs-bar-count" aria-label={`${governanceCount} pending`}>
              {governanceCount}
            </span>
          )}
        </button>
      </nav>

      {/* Everything the sidebar holds beyond the three Operations screens.
          Without it a phone had no way to reach the governance pages, the
          sound controls, or sign out — the whole sidebar is hidden there. */}
      {moreOpen && (
        <div className="cs-sheet-layer">
          <div className="cs-scrim" onClick={() => setMoreOpen(false)} aria-hidden="true" />
          <div
            className="cs-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="cs-sheet-title"
            ref={sheet}
          >
            <span className="cs-sheet-grip" aria-hidden="true" />
            <div className="cs-sheet-head">
              <span id="cs-sheet-title" className="cs-sheet-title">More</span>
              <button className="cs-sheet-close" onClick={() => setMoreOpen(false)} aria-label="Close">
                <Svg path={Icon.close} size={16} stroke="var(--label)" />
              </button>
            </div>

            <div className="cs-group">
              <span className="cs-group-label">Governance</span>
              {governance.map((n) => (
                <NavItem
                  key={n.key}
                  item={n}
                  active={active}
                  count={countFor(n.badge, n.key)}
                  onClick={() => go(n.key)}
                />
              ))}
            </div>

            <Posture active={activeCount} pending={pendingVerify} />

            <SoundSettings />

            {/* The sidebar keeps this switch beside sign-out, and the sidebar
                is hidden below 900px — so on a phone the sheet is the only
                way to reach the light ground. */}
            <button
              className="cs-sheet-ground"
              onClick={() => setTheme(applyTheme(theme === 'light' ? 'dark' : 'light'))}
              aria-pressed={theme === 'light'}
            >
              <Svg path={theme === 'light' ? Icon.moon : Icon.sun} stroke="var(--label)" />
              {theme === 'light' ? 'Switch to the dark ground' : 'Switch to the light ground'}
            </button>

            <div className="cs-user">
              <span className="cs-avatar">{initials(user?.full_name, user?.email)}</span>
              <div className="cs-user-text">
                <span className="cs-user-name">{name}</span>
                <span className="cs-user-role">Admin · full access</span>
              </div>
              <button className="cs-sheet-signout" onClick={logout}>
                <Svg path={Icon.out} stroke="var(--label)" />
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
