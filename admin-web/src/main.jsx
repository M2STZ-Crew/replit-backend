import React, { useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App.jsx';
import { api } from './api/client.js';
import { AuthProvider, useAuth } from './auth.jsx';
import { LanguageProvider } from './i18n/i18n.jsx';
import './index.css';
import './styles/pass6.css';
import './styles/pass6-pages.css';
import './styles/pass6-auth.css';
import './styles/pass6-existing.css';
import './styles/pass6-incidents.css';
import './styles/pass6-map.css';
import './styles/pass6-access.css';
import { initTheme } from './theme.js';

// Before the first paint, so a reload never flashes the other ground.
initTheme();

/* English or Tagalog: the signed-in account's choice, saved back to it when an
 * Admin switches (Settings, or the sign-in page just before signing in). */
function Localized({ children }) {
  const { user } = useAuth();
  const save = useCallback((language) => (user ? api.setLanguage(language) : undefined), [user]);
  return (
    <LanguageProvider accountLanguage={user?.language} onSave={save}>
      {children}
    </LanguageProvider>
  );
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Localized>
          <App />
        </Localized>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
