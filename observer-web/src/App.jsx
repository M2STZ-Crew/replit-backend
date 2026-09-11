import { useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth.jsx';
import ObserverShell from './components/ObserverShell.jsx';
import { LiveFeedProvider } from './live/LiveFeed.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import HistoryPage from './pages/HistoryPage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import MonitoringPage from './pages/MonitoringPage.jsx';

function Console() {
  const { user } = useAuth();
  const [active, setActive] = useState('dashboard');
  // The incident a dashboard card (or the routed banner) was opened for.
  const [focusId, setFocusId] = useState(null);

  function go(key, opts = {}) {
    setActive(key);
    setFocusId(opts.incidentId ?? null);
  }

  return (
    <LiveFeedProvider user={user}>
      <ObserverShell active={active} onNavigate={go}>
        {active === 'dashboard' ? (
          <DashboardPage onNavigate={go} />
        ) : active === 'map' ? (
          <MonitoringPage key={focusId ?? 'map'} focusId={focusId} />
        ) : (
          <HistoryPage />
        )}
      </ObserverShell>
    </LiveFeedProvider>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="screen-center">Loading…</div>;
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/" element={user ? <Console /> : <Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
