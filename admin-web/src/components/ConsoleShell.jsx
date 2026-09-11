import { useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { useAuth } from '../auth.jsx';
import { useLiveFeed } from '../live/LiveFeed.jsx';
import SoundSettings from './SoundSettings.jsx';

/* Icons are inline SVG rather than a font or sprite: there are nine of them,
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
   that surface. The governance queues keep their accent pending-count. */
const NAV = [
  { key: 'dashboard', label: 'Situation board', icon: Icon.grid, group: 'Operations', badge: 'new:dashboard' },
  { key: 'incidents', label: 'Incidents', icon: Icon.flame, group: 'Operations', badge: 'new:incidents' },
  { key: 'map', label: 'Live map', icon: Icon.map, group: 'Operations' },
  { key: 'affiliates', label: 'Affiliates', icon: Icon.users, group: 'Governance', badge: 'affiliates' },
  { key: 'accounts', label: 'Accounts', icon: Icon.shield, group: 'Governance' },
  { key: 'idreview', label: 'ID review', icon: Icon.id, group: 'Governance', badge: 'ids' },
  { key: 'audit', label: 'Audit log', icon: Icon.doc, group: 'Governance' },
];

function initials(name, email) {
  const source = (name || email || '?').trim();
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

export default function ConsoleShell({ active, onNavigate, children }) {
  const { user, logout } = useAuth();
  const { stats, seenAt, newSince } = useLiveFeed();
  const [slim, setSlim] = useState(
    () => localStorage.getItem('replit.nav.slim') === '1',
  );
  const [queues, setQueues] = useState({ affiliates: 0, ids: 0 });

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
  const groups = ['Operations', 'Governance'];

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

        {groups.map((group) => (
          <div className="cs-group" key={group}>
            {!slim && <span className="cs-group-label">{group}</span>}
            {NAV.filter((n) => n.group === group).map((n) => {
              const count = countFor(n.badge, n.key);
              const isNew = n.badge?.startsWith('new:');
              return (
                <button
                  key={n.key}
                  className={`cs-item${active === n.key ? ' is-active' : ''}`}
                  onClick={() => onNavigate(n.key)}
                  title={slim ? n.label : undefined}
                  aria-current={active === n.key ? 'page' : undefined}
                >
                  <span className="cs-item-icon"><Svg path={n.icon} /></span>
                  {!slim && <span className="cs-item-label">{n.label}</span>}
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
            })}
          </div>
        ))}

        <div className="cs-spacer" />

        {!slim && (
          <div className="cs-posture">
            <div className="cs-posture-top">
              <span className="dc-eyebrow">City posture</span>
              <span className={`cs-posture-level${activeCount > 0 ? ' is-elevated' : ''}`}>
                {activeCount > 0 ? 'Elevated' : 'Normal'}
              </span>
            </div>
            <p className="cs-posture-note">
              {activeCount === 0
                ? 'No active incidents.'
                : `${activeCount} active incident${activeCount === 1 ? '' : 's'}` +
                  (pendingVerify > 0 ? ` · ${pendingVerify} awaiting verification` : '')}
            </p>
          </div>
        )}

        <SoundSettings slim={slim} />

        <div className="cs-user">
          <span className="cs-avatar">{initials(user?.full_name, user?.email)}</span>
          {!slim && (
            <div className="cs-user-text">
              <span className="cs-user-name">{user?.full_name || user?.email || 'Signed in'}</span>
              <span className="cs-user-role">Admin · full access</span>
            </div>
          )}
          <button className="cs-signout" onClick={logout} title="Sign out" aria-label="Sign out">
            <Svg path={Icon.out} stroke="var(--muted)" />
          </button>
        </div>
      </aside>

      <main className="cs-main">{children}</main>

      {/* Below 900px the sidebar becomes a bottom bar: on a phone, thumb reach
          matters more than the grouping, so labels are shortened and only the
          red new-incident dot survives. */}
      <nav className="cs-bar" aria-label="Sections">
        {NAV.map((n) => {
          const count = n.badge?.startsWith('new:') ? countFor(n.badge, n.key) : 0;
          return (
            <button
              key={n.key}
              className={`cs-bar-item${active === n.key ? ' is-active' : ''}`}
              onClick={() => onNavigate(n.key)}
              aria-current={active === n.key ? 'page' : undefined}
            >
              <Svg path={n.icon} size={17} stroke={active === n.key ? 'var(--accent)' : 'var(--muted)'} />
              <span>{n.label.split(' ')[0]}</span>
              {count > 0 && <span className="cs-bar-new">{count}</span>}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
