import { useEffect, useState } from 'react';

import AlarmBanner from '../components/AlarmBanner.jsx';
import ConsoleShell from '../components/ConsoleShell.jsx';
import * as records from '../integrations/records.js';
import { LiveFeedProvider } from '../live/LiveFeed.jsx';
import { OPEN_INCIDENT_EVENT } from '../sound/alarm.js';
import Accounts from './Accounts.jsx';
import ActionRecord from './ActionRecord.jsx';
import Affiliates from './Affiliates.jsx';
import IdReview from './IdReview.jsx';
import IncidentDesk from './IncidentDesk.jsx';
import LiveMapPage from './LiveMapPage.jsx';
import Organization from './Organization.jsx';
import Reports from './Reports.jsx';
import Requests from './Requests.jsx';
import Settings from './Settings.jsx';
import SituationBoard from './SituationBoard.jsx';
import WaterResources from './WaterResources.jsx';

export default function Dashboard() {
  return (
    <LiveFeedProvider>
      <Console />
    </LiveFeedProvider>
  );
}

function Destination({ active, focusId, go }) {
  switch (active) {
    case 'dashboard':
      return <SituationBoard onNavigate={go} />;
    case 'incidents':
      return <IncidentDesk key={focusId ?? 'desk'} focusId={focusId} />;
    case 'map':
      return <LiveMapPage onOpenIncident={(incidentId) => go('incidents', { incidentId })} />;
    case 'requests':
      return <Requests readRequests={records.readRequests} onOpenIncident={(incidentId) => go('incidents', { incidentId })} />;
    case 'water':
      return <WaterResources />;
    case 'reports':
      return (
        <Reports
          readReports={records.readReports}
          readIncidentReports={records.readIncidentReports}
          readSummary={records.readSummary}
          downloadIncidentPdf={records.downloadIncidentPdf}
        />
      );
    case 'audit':
      return <ActionRecord />;
    case 'organization':
      return <Organization onNavigate={go} />;
    case 'idreview':
      return <IdReview />;
    case 'affiliates':
      return <Affiliates />;
    case 'settings':
      return <Settings />;
    default:
      return <Accounts />;
  }
}

function Console() {
  const [active, setActive] = useState('dashboard');
  // The incident a dashboard card was clicked for, so the Incidents screen
  // opens on it directly (no separate list drill-down step).
  const [focusId, setFocusId] = useState(null);

  function go(key, opts = {}) {
    setActive(key);
    setFocusId(opts.incidentId ?? null);
  }

  // A desktop alert was clicked: bring its incident up. Opening it there
  // acknowledges the alarm, as any open of an incident does.
  useEffect(() => {
    const open = (e) => go('incidents', { incidentId: e.detail });
    window.addEventListener(OPEN_INCIDENT_EVENT, open);
    return () => window.removeEventListener(OPEN_INCIDENT_EVENT, open);
  }, []);

  const flush = active === 'map';

  return (
    <ConsoleShell active={active} onNavigate={go}>
      {/* The ringing Areas sit at the top of the page (A21); over the
          full-bleed map they sit above it instead. */}
      {flush && <AlarmBanner onOpen={(incidentId) => go('incidents', { incidentId })} />}
      <div className={`db-scroll ad-scroll${flush ? ' db-scroll-flush' : ''}`}>
        {!flush && <AlarmBanner onOpen={(incidentId) => go('incidents', { incidentId })} />}
        <Destination active={active} focusId={focusId} go={go} />
      </div>
    </ConsoleShell>
  );
}
