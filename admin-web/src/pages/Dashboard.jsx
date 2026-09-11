import { useState } from 'react';

import { useAuth } from '../auth.jsx';
import ConsoleShell from '../components/ConsoleShell.jsx';
import { LiveFeedProvider } from '../live/LiveFeed.jsx';
import Accounts from './Accounts.jsx';
import ActionRecord from './ActionRecord.jsx';
import Affiliates from './Affiliates.jsx';
import IdReview from './IdReview.jsx';
import IncidentDesk from './IncidentDesk.jsx';
import MapManagement from './MapManagement.jsx';
import SituationBoard from './SituationBoard.jsx';

/* Topbar heading per section. The titles match the nav labels in ConsoleShell —
   a screen whose heading disagrees with the item you clicked is disorienting.
   `dashboard` is absent on purpose: it gets the personalised welcome. */
const HEAD = {
  incidents: {
    title: 'Incidents',
    sub: 'Accept incoming reports and route them to the agencies they asked for.',
  },
  map: {
    title: 'Live map',
    sub: 'Risk zones, evacuation sites, hydrants and water sources — Pasay City and beyond.',
  },
  affiliates: {
    title: 'Affiliates',
    sub: 'Applications for accreditation, and the organisations already on the network.',
  },
  accounts: {
    title: 'Accounts',
    sub: 'Everyone attached to an accredited organisation.',
  },
  idreview: {
    title: 'ID review',
    sub: 'National ID submissions awaiting approval.',
  },
  audit: {
    title: 'Audit log',
    sub: 'Append-only record of every consequential action.',
  },
};

export default function Dashboard() {
  return (
    <LiveFeedProvider>
      <Console />
    </LiveFeedProvider>
  );
}

function Console() {
  const { user } = useAuth();
  const [active, setActive] = useState('dashboard');
  // The incident a dashboard card was clicked for, so the Incidents screen
  // opens on it directly (Section 2.9: no separate list drill-down step).
  const [focusId, setFocusId] = useState(null);
  const [query, setQuery] = useState('');

  // Switch sections and clear the search so it doesn't carry across views.
  function go(key, opts = {}) {
    setActive(key);
    setFocusId(opts.incidentId ?? null);
    setQuery('');
  }

  const name = user?.full_name || user?.email || 'Admin';
  const head = HEAD[active];

  return (
    <ConsoleShell active={active} onNavigate={go}>
      <div className="db-main">
        <header className="db-topbar">
          <div>
            <div className="db-hello">
              {head?.title || `Welcome back, ${name.split(/\s+/)[0]}`}
            </div>
            <div className="db-hello-sub">
              {head?.sub || 'Here’s what’s happening across Pasay City right now.'}
            </div>
          </div>
          {/* Only the map reads this box. Every other screen carries its own
              filter, and a search field that silently does nothing is worse
              than no search field. */}
          {active === 'map' && (
            <div className="db-search">
              <span className="db-search-icon">🔍</span>
              <input
                className="db-search-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Find a marker…"
                aria-label="Find a marker"
              />
            </div>
          )}
        </header>

        <div className={`db-scroll${active === 'map' ? ' db-scroll-flush' : ''}`}>
          {active === 'dashboard' ? (
            <SituationBoard onNavigate={go} />
          ) : active === 'incidents' ? (
            <IncidentDesk key={focusId ?? 'desk'} focusId={focusId} />
          ) : active === 'map' ? (
            <MapManagement
              query={query}
              onOpenIncident={(incidentId) => go('incidents', { incidentId })}
            />
          ) : active === 'affiliates' ? (
            <Affiliates />
          ) : active === 'idreview' ? (
            <IdReview />
          ) : active === 'audit' ? (
            <ActionRecord />
          ) : (
            <Accounts />
          )}
        </div>
      </div>
    </ConsoleShell>
  );
}
