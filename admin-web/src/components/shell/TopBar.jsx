import Icon from '../ui/Icon.jsx';

/* The pass 6 top bar (REPLIT (MAIN) 04 · Top bar): 64 px on the opaque ground
 * with one hairline — which organisation this is and what this Admin may act
 * on, the sound state, availability and the unread count. Restrained: it
 * carries state, never the page's title. */

export function AvailabilityChip({ afk, since }) {
  return (
    <span className={`rpl-availability${afk ? ' is-afk' : ''}`}>
      <span className="rpl-availability-dot" aria-hidden="true" />
      {afk ? (since ? `AFK since ${since}` : 'AFK') : 'Available'}
    </span>
  );
}

/* `availability` is `{ afk, since }` once the server reports it (PRD v13
 * §4.6.5); until then it is null and the chip is not drawn — a state the
 * console cannot honour is not shown. */
export default function TopBar({
  organization, scope, soundOn, onSound, availability = null, unread = 0, onUnread,
}) {
  return (
    <header className="rpl-topbar">
      <p className="rpl-topbar-context">
        <span className="rpl-topbar-org">{organization}</span>
        {scope && (
          <>
            <span className="rpl-topbar-sep" aria-hidden="true">·</span>
            <span className="rpl-topbar-scope">{scope}</span>
          </>
        )}
      </p>

      <button
        type="button"
        className="rpl-pill"
        onClick={onSound}
        aria-label={`${soundOn ? 'Sound on' : 'Sound off'}. Open sound settings`}
      >
        <Icon name="volume" size={16} />
        {soundOn ? 'Sound on' : 'Sound off'}
      </button>

      {availability && <AvailabilityChip afk={availability.afk} since={availability.since} />}

      <button
        type="button"
        className="rpl-pill"
        onClick={onUnread}
        aria-label={
          unread > 0
            ? `${unread} new incident${unread === 1 ? '' : 's'} since you last looked. Open Incidents`
            : 'No new incidents. Open Incidents'
        }
      >
        <Icon name="notifications" size={16} />
        {unread > 0 && <span className="rpl-count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>
    </header>
  );
}
