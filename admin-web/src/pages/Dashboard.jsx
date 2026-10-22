import { Suspense, lazy, useCallback, useEffect, useState } from 'react';

import AlarmBanner from '../components/AlarmBanner.jsx';
import ConsoleShell from '../components/ConsoleShell.jsx';
import { NAV, SETTINGS } from '../components/shell/nav.js';
import { StatePanel } from '../components/ui/index.js';
import * as records from '../integrations/records.js';
import { LiveFeedProvider } from '../live/LiveFeed.jsx';
import { OPEN_INCIDENT_EVENT } from '../sound/alarm.js';
import SituationBoard from './SituationBoard.jsx';

/* Every destination but the Dashboard loads on first use, so signing in
 * fetches the console's frame and its first screen, not every page and the
 * map library behind them. Once the Dashboard is up, the rest are fetched in
 * the background, so moving between pages still feels immediate. */
const PAGES = {
  incidents: () => import('./IncidentDesk.jsx'),
  map: () => import('./LiveMapPage.jsx'),
  requests: () => import('./Requests.jsx'),
  water: () => import('./WaterResources.jsx'),
  reports: () => import('./Reports.jsx'),
  audit: () => import('./ActionRecord.jsx'),
  organization: () => import('./Organization.jsx'),
  accounts: () => import('./Accounts.jsx'),
  idreview: () => import('./IdReview.jsx'),
  affiliates: () => import('./Affiliates.jsx'),
  settings: () => import('./Settings.jsx'),
};
const IncidentDesk = lazy(PAGES.incidents);
const LiveMapPage = lazy(PAGES.map);
const Requests = lazy(PAGES.requests);
const WaterResources = lazy(PAGES.water);
const Reports = lazy(PAGES.reports);
const ActionRecord = lazy(PAGES.audit);
const Organization = lazy(PAGES.organization);
const Accounts = lazy(PAGES.accounts);
const IdReview = lazy(PAGES.idreview);
const Affiliates = lazy(PAGES.affiliates);
const Settings = lazy(PAGES.settings);

const KEYS = new Set([...NAV.map((item) => item.key), SETTINGS.key]);

/* The open destination lives in the address (#/incidents), so a reload stays
 * where the operator was instead of going back to the Dashboard. */
function destinationFromHash() {
  const key = window.location.hash.replace(/^#\/?/, '');
  return KEYS.has(key) ? key : 'dashboard';
}

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
  const [active, setActive] = useState(destinationFromHash);
  // The incident a dashboard card was clicked for, so the Incidents screen
  // opens on it directly (no separate list drill-down step).
  const [focusId, setFocusId] = useState(null);

  const go = useCallback((key, opts = {}) => {
    setActive(key);
    setFocusId(opts.incidentId ?? null);
    const hash = key === 'dashboard' ? '' : `#/${key}`;
    if (window.location.hash !== hash) {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${hash}`);
    }
  }, []);

  // A desktop alert was clicked: bring its incident up. Opening it there
  // acknowledges the alarm, as any open of an incident does.
  useEffect(() => {
    const open = (e) => go('incidents', { incidentId: e.detail });
    window.addEventListener(OPEN_INCIDENT_EVENT, open);
    return () => window.removeEventListener(OPEN_INCIDENT_EVENT, open);
  }, [go]);

  // The other pages, fetched once the browser is idle after the first screen.
  useEffect(() => {
    const prefetch = () => Object.values(PAGES).forEach((load) => load().catch(() => {}));
    if ('requestIdleCallback' in window) {
      const id = window.requestIdleCallback(prefetch, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const t = setTimeout(prefetch, 2000);
    return () => clearTimeout(t);
  }, []);

  const flush = active === 'map';

  return (
    <ConsoleShell active={active} onNavigate={go}>
      {/* The ringing Areas sit at the top of the page (A21); over the
          full-bleed map they sit above it instead. */}
      {flush && <AlarmBanner onOpen={(incidentId) => go('incidents', { incidentId })} />}
      <div className={`db-scroll ad-scroll${flush ? ' db-scroll-flush' : ''}`}>
        {!flush && <AlarmBanner onOpen={(incidentId) => go('incidents', { incidentId })} />}
        <Suspense fallback={<StatePanel kind="loading" title="Opening…" busy />}>
          <Destination active={active} focusId={focusId} go={go} />
        </Suspense>
      </div>
    </ConsoleShell>
  );
}
