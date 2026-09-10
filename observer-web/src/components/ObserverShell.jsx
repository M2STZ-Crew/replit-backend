import { useAuth, agencyLabel } from '../auth.jsx';
import { awaitingAccept, useLiveFeed } from '../live/LiveFeed.jsx';
import SoundSettings from './SoundSettings.jsx';

const Icon = {
  grid: (
    <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>
  ),
  map: <><path d="M9 3l6 2 6-2v16l-6 2-6-2-6 2V5l6-2z" /><path d="M9 3v16M15 5v16" /></>,
  doc: <><path d="M6 3h9l4 4v14H6z" /><path d="M9 9h7M9 13h7M9 17h4" /></>,
  out: <><path d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3" /><path d="M10 8l-4 4 4 4M6 12h9" /></>,
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

function initials(name, email) {
  const source = (name || email || '?').trim();
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?';
}

export default function ObserverShell({ active, onNavigate, children }) {
  const { user, logout } = useAuth();
  const { incidents, alert, dismissAlert } = useLiveFeed();
  const agency = user?.agency_type;
  const pending = incidents.filter((inc) => awaitingAccept(inc, agency)).length;

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

        <div className="os-standing">
          <span className="os-eyebrow">Signed in for</span>
          <span className="os-standing-agency">{agencyLabel(agency)}</span>
          <p className="os-standing-note">
            You see incidents where a reporter asked for your agency. When Admin routes
            one to you, press <strong>Accept</strong> on the map.
          </p>
        </div>

        <nav className="os-items" aria-label="Sections">
          {NAV.map((n) => (
            <button
              key={n.key}
              className={`os-item${active === n.key ? ' is-active' : ''}`}
              onClick={() => onNavigate(n.key)}
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
            <span className="os-user-name">{user?.full_name || user?.email}</span>
            <span className="os-eyebrow">Team captain · Observer</span>
          </div>
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
              onClick={() => { onNavigate('map', { incidentId: alert.id }); dismissAlert(); }}
            >
              Open to Accept
            </button>
            <button className="os-alert-x" onClick={dismissAlert} aria-label="Dismiss">×</button>
          </div>
        )}
        {children}
      </main>

      {/* Below 900px the sidebar becomes a bottom bar. */}
      <nav className="os-bar" aria-label="Sections">
        {NAV.map((n) => (
          <button
            key={n.key}
            className={`os-bar-item${active === n.key ? ' is-active' : ''}`}
            onClick={() => onNavigate(n.key)}
            aria-current={active === n.key ? 'page' : undefined}
          >
            <Svg path={n.icon} size={18} />
            <span>{n.label}</span>
            {n.key === 'map' && pending > 0 && <span className="os-bar-badge">{pending}</span>}
          </button>
        ))}
      </nav>
    </div>
  );
}
