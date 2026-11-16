import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import { StartupError, StartupLoading } from './components/StartupScreen.jsx';
import Login from './pages/Login.jsx';

// The console and the affiliate form load on demand: the sign-in page, the
// first thing most visits show, does not wait for either.
const Dashboard = lazy(() => import('./pages/Dashboard.jsx'));
const Register = lazy(() => import('./pages/Register.jsx'));

function Protected({ children }) {
  const { user, loading, startupError, retry, logout } = useAuth();
  if (loading) return <StartupLoading />;
  if (!user && startupError) {
    return <StartupError message={startupError} onRetry={retry} onSignOut={logout} />;
  }
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  const { user, logout } = useAuth();
  return (
    <Suspense fallback={<StartupLoading />}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <Protected>
              <ErrorBoundary onSignOut={logout}>
                <Dashboard />
              </ErrorBoundary>
            </Protected>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
