import Icon from '../ui/Icon.jsx';
import { GROUPS, SETTINGS } from './nav.js';

/* The pass 6 Admin sidebar (REPLIT (MAIN) 04 · Sidebar, Sidebar item, Rail
 * item): 248 px on the subtle surface with one hairline edge; below 1280 px a
 * 72 px rail of icon-only destinations whose label is the accessible name and
 * the tooltip. Active is the mobile nav treatment — coral tint, 1.5 px coral
 * edge, bright icon, bold label; inactive icons stay icon/secondary. */

const AGENCY_PLATE = {
  fire_volunteer: { icon: 'fire', tone: 'fire' },
  bfp: { icon: 'fire', tone: 'fire' },
  police: { icon: 'organization', tone: 'police' },
  medical: { icon: 'organization', tone: 'medical' },
  barangay: { icon: 'barangay', tone: 'barangay' },
};

function CountBadge({ count, label }) {
  if (!count) return null;
  return (
    <span className="rpl-count" aria-label={label}>
      {count > 99 ? '99+' : count}
    </span>
  );
}

function SidebarItem({ item, active, count, countLabel, onClick }) {
  const on = active === item.key;
  return (
    <button
      type="button"
      className={`rpl-nav-item${on ? ' is-active' : ''}`}
      onClick={onClick}
      aria-current={on ? 'page' : undefined}
    >
      <Icon name={item.icon} />
      <span className="rpl-nav-label">{item.label}</span>
      <CountBadge count={count} label={countLabel} />
    </button>
  );
}

function RailItem({ item, active, count, countLabel, onClick }) {
  const on = active === item.key;
  return (
    <button
      type="button"
      className={`rpl-rail-item${on ? ' is-active' : ''}`}
      onClick={onClick}
      aria-current={on ? 'page' : undefined}
      aria-label={count ? `${item.label}, ${countLabel}` : item.label}
      title={item.label}
    >
      <Icon name={item.icon} size={24} />
      {count > 0 && <span className="rpl-count rpl-rail-count" aria-hidden="true">{count > 99 ? '99+' : count}</span>}
    </button>
  );
}

function Brand({ rail }) {
  return (
    <div className="rpl-brand">
      <span className="rpl-brand-icon" aria-hidden="true">
        <img src="/icons/mark.svg" alt="" width="13" height="18" />
      </span>
      {!rail && (
        <span className="rpl-brand-words">
          <span className="rpl-brand-name">REPLIT</span>
          <span className="rpl-brand-sub">Admin console</span>
        </span>
      )}
    </div>
  );
}

function Organization({ org, rail }) {
  const plate = AGENCY_PLATE[org.agency] ?? { icon: 'organization', tone: 'neutral' };
  const tile = (
    <span className={`rpl-plate rpl-plate--${plate.tone}`} aria-hidden="true">
      <Icon name={plate.icon} size={16} />
    </span>
  );
  if (rail) {
    return (
      <div className="rpl-org is-rail" title={`${org.name} · ${org.role}`}>
        {tile}
        <span className="web-sr-only">{`${org.name}, ${org.role}`}</span>
      </div>
    );
  }
  return (
    <div className="rpl-org">
      {tile}
      <span className="rpl-org-text">
        <span className="rpl-org-name">{org.name}</span>
        <span className="rpl-org-role">{org.role}</span>
      </span>
    </div>
  );
}

/* `items` are the destinations this Admin gets (see nav.js); `counts(item)`
 * returns `{ count, label }` for its badge. */
export default function Sidebar({
  items, active, onNavigate, counts, org, user, onSignOut, rail = false,
}) {
  const Item = rail ? RailItem : SidebarItem;
  return (
    <aside className={`rpl-sidebar${rail ? ' is-rail' : ''}`} aria-label="Console">
      <Brand rail={rail} />
      <Organization org={org} rail={rail} />

      <nav className="rpl-nav" aria-label="Destinations">
        {GROUPS.map((group) => {
          const groupItems = items.filter((item) => item.group === group);
          if (groupItems.length === 0) return null;
          return (
            <div className="rpl-nav-group" key={group} role="group" aria-label={group}>
              {!rail && <span className="rpl-nav-group-label" aria-hidden="true">{group}</span>}
              {rail && <span className="rpl-rail-rule" aria-hidden="true" />}
              {groupItems.map((item) => {
                const { count, label } = counts(item);
                return (
                  <Item
                    key={item.key}
                    item={item}
                    active={active}
                    count={count}
                    countLabel={label}
                    onClick={() => onNavigate(item.key)}
                  />
                );
              })}
            </div>
          );
        })}
      </nav>

      <span className="rpl-spacer" />

      <Item
        item={SETTINGS}
        active={active}
        count={0}
        onClick={() => onNavigate(SETTINGS.key)}
      />

      <div className={`rpl-user${rail ? ' is-rail' : ''}`}>
        <span className="rpl-avatar" aria-hidden="true">{user.initials}</span>
        {!rail && (
          <span className="rpl-user-text">
            <span className="rpl-user-name">{user.name}</span>
            <span className="rpl-user-email">{user.email}</span>
          </span>
        )}
        <button
          type="button"
          className="rpl-icon-button"
          onClick={onSignOut}
          aria-label="Sign out"
          title="Sign out"
        >
          <Icon name="logout" />
        </button>
      </div>
    </aside>
  );
}
