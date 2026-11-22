import QuickSettings from './QuickSettings.jsx';
import { t } from '../../i18n/i18n.jsx';

/* The pass 6 top bar (REPLIT (MAIN) 04 · Top bar): 64 px on the opaque ground
 * with one hairline — which organisation this is and what this Admin may act
 * on, availability, and since v1.12.50 one Settings button in place of the
 * sound and notification ones (22 Nov 2026; QuickSettings.jsx). Restrained:
 * it carries state, never the page's title. */

export function AvailabilityChip({ afk, since }) {
  return (
    <span className={`rpl-availability${afk ? ' is-afk' : ''}`}>
      <span className="rpl-availability-dot" aria-hidden="true" />
      {afk ? (since ? t('AFK since {since}', { since }) : 'AFK') : t('Available')}
    </span>
  );
}

/* `availability` is `{ afk, since }` once the server reports it (PRD v13
 * §4.6.5); until then it is null and the chip is not drawn — a state the
 * console cannot honour is not shown. */
export default function TopBar({
  organization, scope, access, availability = null, onAllSettings, onSignOut,
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

      {availability && <AvailabilityChip afk={availability.afk} since={availability.since} />}

      <QuickSettings access={access} onAllSettings={onAllSettings} onSignOut={onSignOut} />
    </header>
  );
}
