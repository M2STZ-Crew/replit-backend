import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App.jsx';
import { AuthProvider } from './auth.jsx';
import './index.css';
import './styles/pass6.css';
import './styles/pass6-pages.css';
import './styles/pass6-auth.css';
import './styles/pass6-existing.css';
import './styles/pass6-incidents.css';
import './styles/pass6-map.css';
import { initTheme } from './theme.js';

// Before the first paint, so a reload never flashes the other ground.
initTheme();

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
