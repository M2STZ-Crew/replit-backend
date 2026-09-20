import { useEffect, useRef, useState } from 'react';

import { useAuth, agencyLabel } from '../auth.jsx';
import { awaitingAccept, useLiveFeed } from '../live/LiveFeed.jsx';
import SoundSettings from './SoundSettings.jsx';
import { applyTheme, storedTheme } from '../theme.js';

const Icon = {
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 019.5 4a7 7 0 108.9 10.5z" />,
  grid: (
    <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>
  ),
  map: <><path d="M9 3l6 2 6-2v16l-6 2-6-2-6 2V5l6-2z" /><path d="M9 3v16M15 5v16" /></>,
  doc: <><path d="M6 3h9l4 4v14H6z" /><path d="M9 9h7M9 13h7M9 17h4" /></>,
  out: <><path d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3" /><path d="M10 8l-4 4 4 4M6 12h9" /></>,
  user: <><circle cx="12" cy="8" r="3.6" /><path d="M4.5 20.5c1.4-3.6 4.2-5.5 7.5-5.5s6.1 1.9 7.5 5.5" /></>,
  close: <path d="M6 6l12 12M18 6L6 18" />,
};

function Svg({ path, size = 14, stroke = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke}
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {path}
    </svg>
  );
}

/// Three surfaces and nothing else (v10 Section 2.6.1). Equipment, affiliate
/// organisations and account management are Admin and Coordinator concerns, so
/// they are not in this menu at all — not greyed out, absent.
const NAV = [
  { key: 'dashboard', label: 'Dashboard', sub: 'Your agency at a glance', icon: Icon.grid },
  { key: 'map', label: 'Map', sub: 'Monitoring', icon: Icon.map },
  { key: 'history', label: 'Audit log', sub: 'History', icon: Icon.doc },
];

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

function initials(name, email) {
  const source = (name || email || '?').trim();
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

function Standing({ agency }) {
  return (
    <div className="os-standing">
      <span className="os-eyebrow">Signed in for</span>
      <span className="os-standing-agency">{agencyLabel(agency)}</span>
      <p className="os-standing-note">
        You see incidents where a reporter asked for your agency. When Admin routes
        one to you, press <strong>Accept</strong> on the map.
      </p>
    </div>
  );
}

export default function ObserverShell({ active, onNavigate, children }) {
  // Which ground the console draws on — the switch is beside sign-out.
  const [theme, setTheme] = useState(storedTheme);
  const { user, logout } = useAuth();
  const { incidents, alert, dismissAlert } = useLiveFeed();
  const [accountOpen, setAccountOpen] = useState(false);
  const accountButton = useRef(null);
  const sheet = useRef(null);
  const agency = user?.agency_type;
  const pending = incidents.filter((inc) => awaitingAccept(inc, agency)).length;
  const name = user?.full_name || user?.email;

  // The Account sheet behaves as a dialog: focus moves into it, Tab stays
  // inside, Escape closes it, and focus returns to the button that opened it.
  useEffect(() => {
    if (!accountOpen) return undefined;
    const panel = sheet.current;
    const opener = accountButton.current;
    panel?.querySelector(FOCUSABLE)?.focus();
    function onKey(e) {
      if (e.key === 'Escape') {
        setAccountOpen(false);
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
  }, [accountOpen]);

  function go(key, opts) {
    setAccountOpen(false);
    onNavigate(key, opts);
  }

  return (
    <div className="os">
      <aside className="os-nav">
        <div className="os-brand">
          <img src="/assets/logo-mark.png" alt="" width="32" height="32" />
          <div className="os-brand-text">
            <span className="os-brand-name">RepLiT</span>
            <span className="os-eyebrow">Observer console</span>
          </div>
        </div>

        <Standing agency={agency} />

        <nav className="os-items" aria-label="Sections">
          {NAV.map((n) => (
            <button
              key={n.key}
              className={`os-item${active === n.key ? ' is-active' : ''}`}
              onClick={() => go(n.key)}
              aria-current={active === n.key ? 'page' : undefined}
            >
              <span className="os-item-icon"><Svg path={n.icon} /></span>
              <span className="os-item-text">
                <span className="os-item-label">{n.label}</span>
                <span className="os-item-sub">{n.sub}</span>
              </span>
              {n.key === 'map' && pending > 0 && (
                <span className="os-badge" aria-label={`${pending} awaiting your Accept`}>{pending}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="os-spacer" />

        <SoundSettings categories={[agency]} />

        <div className="os-user">
          <span className="os-avatar">{initials(user?.full_name, user?.email)}</span>
          <div className="os-user-text">
            <span className="os-user-name">{name}</span>
            <span className="os-eyebrow">Team captain · Observer</span>
          </div>
          <button
            className="os-icon-btn"
            onClick={() => setTheme(applyTheme(theme === 'light' ? 'dark' : 'light'))}
            title={theme === 'light' ? 'Switch to the dark ground' : 'Switch to the light ground'}
            aria-label="Switch theme"
          >
            <Svg path={theme === 'light' ? Icon.moon : Icon.sun} />
          </button>
          <button className="os-icon-btn" onClick={logout} title="Sign out" aria-label="Sign out">
            <Svg path={Icon.out} />
          </button>
        </div>
      </aside>

      <main className="os-main">
        {alert && (
          <div className="os-alert" role="status">
            <span className="os-alert-dot" />
            <span>
              Admin routed <strong>{alert.designation}</strong> to {agencyLabel(agency)}.
            </span>
            <button
              className="os-alert-go"
              onClick={() => { go('map', { incidentId: alert.id }); dismissAlert(); }}
            >
              Open to Accept
            </button>
            <button className="os-alert-x" onClick={dismissAlert} aria-label="Dismiss">×</button>
          </div>
        )}
        {children}
      </main>

      {/* Below 900px the sidebar becomes a bottom bar. Its last item opens the
          Account sheet, which carries what the sidebar did beyond navigation —
          the agency standing, the sound controls and signing out. Hiding the
          sidebar used to leave a phone with no way to reach any of them. */}
      <nav className="os-bar" aria-label="Sections">
        {NAV.map((n) => (
          <button
            key={n.key}
            className={`os-bar-item${active === n.key ? ' is-active' : ''}`}
            onClick={() => go(n.key)}
            aria-current={active === n.key ? 'page' : undefined}
          >
            <Svg path={n.icon} size={18} />
            <span>{n.label}</span>
            {n.key === 'map' && pending > 0 && <span className="os-bar-badge">{pending}</span>}
          </button>
        ))}
        <button
          ref={accountButton}
          className="os-bar-item"
          onClick={() => setAccountOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={accountOpen}
        >
          <Svg path={Icon.user} size={18} />
          <span>Account</span>
        </button>
      </nav>

      {accountOpen && (
        <div className="os-sheet-layer">
          <div className="os-scrim" onClick={() => setAccountOpen(false)} aria-hidden="true" />
          <div
            className="os-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="os-sheet-title"
            ref={sheet}
          >
            <span className="os-sheet-grip" aria-hidden="true" />
            <div className="os-sheet-head">
              <span id="os-sheet-title" className="os-sheet-title">Account</span>
              <button className="os-sheet-close" onClick={() => setAccountOpen(false)} aria-label="Close">
                <Svg path={Icon.close} size={16} />
              </button>
            </div>

            <Standing agency={agency} />

            <SoundSettings categories={[agency]} />

            {/* The sidebar keeps this switch beside sign-out, and the sidebar
                is hidden below 900px — so on a phone the sheet is the only
                way to reach the light ground. */}
            <button
              className="os-sheet-ground"
              onClick={() => setTheme(applyTheme(theme === 'light' ? 'dark' : 'light'))}
              aria-pressed={theme === 'light'}
            >
              <Svg path={theme === 'light' ? Icon.moon : Icon.sun} />
              {theme === 'light' ? 'Switch to the dark ground' : 'Switch to the light ground'}
            </button>

            <div className="os-user">
              <span className="os-avatar">{initials(user?.full_name, user?.email)}</span>
              <div className="os-user-text">
                <span className="os-user-name">{name}</span>
                <span className="os-eyebrow">Team captain · Observer</span>
              </div>
              <button className="os-sheet-signout" onClick={logout}>
                <Svg path={Icon.out} />
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
