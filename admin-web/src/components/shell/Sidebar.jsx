import { useEffect, useRef, useState } from 'react';

import Icon from '../ui/Icon.jsx';
import { GROUPS, SETTINGS } from './nav.js';
import { t } from '../../i18n/i18n.jsx';

/* The pass 6 Admin sidebar (REPLIT (MAIN) 04 · Sidebar, Sidebar item, Rail
 * item): 248 px on the subtle surface with one hairline edge; collapsed (by
 * the toggle beside the logo, v1.12.50, and until then below 1280 px) a
 * 72 px rail of icon-only destinations whose label is the accessible name and
 * the tooltip. Active is the mobile nav treatment — coral tint, 1.5 px coral
 * edge, bright icon, bold label; inactive icons stay icon/secondary.
 *
 * Only the destinations scroll: the toggle, Settings and the account stay in
 * view however many destinations there are. */

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

function RailItem({ item, active, count, countLabel, onClick, tip }) {
  const on = active === item.key;
  return (
    <button
      type="button"
      className={`rpl-rail-item${on ? ' is-active' : ''}`}
      onClick={onClick}
      aria-current={on ? 'page' : undefined}
      aria-label={count ? `${item.label}, ${countLabel}` : item.label}
      {...tip(count ? `${item.label} · ${count}` : item.label)}
    >
      <Icon name={item.icon} size={24} />
      {count > 0 && <span className="rpl-count rpl-rail-count" aria-hidden="true">{count > 99 ? '99+' : count}</span>}
    </button>
  );
}

function Brand({ rail, onToggle, tip }) {
  const label = rail ? t('Expand sidebar') : t('Collapse sidebar');
  return (
    <div className="rpl-brand">
      <span className="rpl-brand-icon" aria-hidden="true">
        <img src="/icons/mark.svg" alt="" width="13" height="18" />
      </span>
      {!rail && (
        <span className="rpl-brand-words">
          <span className="rpl-brand-name">REPLIT</span>
          <span className="rpl-brand-sub">{t('Admin console')}</span>
        </span>
      )}
      <button
        type="button"
        className="rpl-icon-button rpl-sidebar-toggle"
        onClick={onToggle}
        aria-expanded={!rail}
        aria-controls="rpl-destinations"
        aria-label={label}
        {...(rail ? tip(label) : { title: label })}
      >
        <Icon name="sidebar" />
        <span className="rpl-sidebar-toggle-arrow" aria-hidden="true" />
      </button>
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
  items, active, onNavigate, counts, org, user, onSignOut, rail = false, onToggle,
}) {
  const nav = useRef(null);
  // The rail's tooltip is one label beside the sidebar, outside what clips.
  const [hint, setHint] = useState(null);

  const tip = (text) => {
    const show = (event) => {
      const r = event.currentTarget.getBoundingClientRect();
      setHint({ text, top: r.top + r.height / 2, left: r.right + 10 });
    };
    const hide = () => setHint(null);
    return {
      onPointerEnter: (event) => { if (event.pointerType !== 'touch') show(event); },
      onPointerLeave: hide,
      onPointerDown: hide,
      onFocus: (event) => { if (event.currentTarget.matches(':focus-visible')) show(event); },
      onBlur: hide,
    };
  };

  useEffect(() => { setHint(null); }, [rail, active]);

  useEffect(() => {
    if (!hint) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setHint(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [hint]);

  // Where the Admin is, in view in a list that scrolls.
  useEffect(() => {
    nav.current?.querySelector('.is-active')?.scrollIntoView({ block: 'nearest' });
  }, [active, rail]);

  const Item = rail ? RailItem : SidebarItem;
  return (
    <aside className={`rpl-sidebar${rail ? ' is-rail' : ''}`} aria-label={t('Console')}>
      <Brand rail={rail} onToggle={onToggle} tip={tip} />
      <Organization org={org} rail={rail} />

      <nav
        id="rpl-destinations"
        className="rpl-nav"
        aria-label={t('Destinations')}
        ref={nav}
        onScroll={() => setHint(null)}
      >
        {GROUPS.map((group) => {
          const groupItems = items.filter((item) => item.group === group.key);
          if (groupItems.length === 0) return null;
          return (
            <div className="rpl-nav-group" key={group.key} role="group" aria-label={group.label}>
              {!rail && <span className="rpl-nav-group-label" aria-hidden="true">{group.label}</span>}
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
                    tip={tip}
                    onClick={() => onNavigate(item.key)}
                  />
                );
              })}
            </div>
          );
        })}
      </nav>

      <div className="rpl-sidebar-foot">
        <Item
          item={SETTINGS}
          active={active}
          count={0}
          tip={tip}
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
            aria-label={t('Sign out')}
            {...(rail ? tip(t('Sign out')) : { title: t('Sign out') })}
          >
            <Icon name="logout" />
          </button>
        </div>
      </div>

      {rail && hint && (
        <span className="rpl-rail-tip" style={{ top: hint.top, left: hint.left }} aria-hidden="true">{hint.text}</span>
      )}
    </aside>
  );
}
