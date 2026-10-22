import Icon from '../ui/Icon.jsx';

/* The pass 6 top bar (REPLIT (MAIN) 04 · Top bar): 64 px on the opaque ground
 * with one hairline — which organisation this is and what this Admin may act
 * on, the sound state, availability and the unread count. Restrained: it
 * carries state, never the page's title. */

export function AvailabilityChip({ afk, since }) {
  return (
    <span className={`ad-availability${afk ? ' is-afk' : ''}`}>
      <span className="ad-availability-dot" aria-hidden="true" />
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
    <header className="ad-topbar">
      <p className="ad-topbar-context">
        <span className="ad-topbar-org">{organization}</span>
        {scope && (
          <>
            <span className="ad-topbar-sep" aria-hidden="true">·</span>
            <span className="ad-topbar-scope">{scope}</span>
          </>
        )}
      </p>

      <button
        type="button"
        className="ad-pill"
        onClick={onSound}
        aria-label={`${soundOn ? 'Sound on' : 'Sound off'}. Open sound settings`}
      >
        <Icon name="volume" size={16} />
        {soundOn ? 'Sound on' : 'Sound off'}
      </button>

      {availability && <AvailabilityChip afk={availability.afk} since={availability.since} />}

      <button
        type="button"
        className="ad-pill"
        onClick={onUnread}
        aria-label={
          unread > 0
            ? `${unread} new incident${unread === 1 ? '' : 's'} since you last looked. Open Incidents`
            : 'No new incidents. Open Incidents'
        }
      >
        <Icon name="notifications" size={16} />
        {unread > 0 && <span className="ad-count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>
    </header>
  );
}
