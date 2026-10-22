import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ConfirmDialog, CountBadge, EmptyState, PageHeader, StatePanel, StatusChip,
} from '../src/components/ui/index.js';
import '../src/index.css';
import '../src/styles/pass6.css';
import '../src/styles/pass6-pages.css';

// Local development fixture. It has no API, authentication, or application
// routing. Vite's production entry remains index.html and excludes this page.
function FoundationsPreview() {
  const [open, setOpen] = useState(false);
  const [fail, setFail] = useState(false);
  const [pending, setPending] = useState(false);
  const [confirmed, setConfirmed] = useState(0);
  const [theme, setTheme] = useState('dark');
  const [retried, setRetried] = useState(0);

  async function confirm() {
    setPending(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 500));
      if (fail) throw new Error('Example failure. Try again.');
      setConfirmed((count) => count + 1);
      setOpen(false);
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="web-page web-preview">
      <PageHeader title="UI foundations" eyebrow="Development preview"
        description="Sample data only. The shared components in their pass 6 styling."
        actions={<button className="web-button" onClick={() => {
          const next = theme === 'dark' ? 'light' : 'dark';
          setTheme(next);
          document.documentElement.dataset.theme = next;
        }}>Use {theme === 'dark' ? 'light' : 'dark'} theme</button>} />
      <section className="web-preview-section" aria-labelledby="status-heading">
        <h2 id="status-heading">Statuses and counts</h2>
        <div className="web-preview-row">
          <StatusChip label="Reported" tone="danger" />
          <StatusChip label="Acknowledged" tone="accent" />
          <StatusChip label="On the way" tone="info" />
          <StatusChip label="On scene" tone="warn" />
          <StatusChip label="Fire out" tone="ok" />
          <CountBadge count={128} label={(count) => `${count} example incidents`} />
        </div>
      </section>
      <EmptyState icon="incidents" title="No incidents yet">An example empty list, as on the Incidents page.</EmptyState>
      <section className="web-preview-section" aria-labelledby="dialog-heading">
        <h2 id="dialog-heading">Confirmation</h2>
        <div className="web-preview-row">
          <button className="web-button web-button--primary" onClick={() => setOpen(true)}>Open example confirmation</button>
          <label><input type="checkbox" checked={fail} onChange={(event) => setFail(event.target.checked)} /> Simulate a failed request</label>
          <span role="status">Completed example actions: {confirmed}</span>
        </div>
        <ConfirmDialog open={open} title="Acknowledge example incident?" confirmLabel="Acknowledge"
          description="This example changes only the count in this preview."
          busy={pending} onClose={() => setOpen(false)} onConfirm={confirm} />
      </section>
      <StatePanel kind="empty" title="No incidents to show" description="New reports will appear here." />
      <StatePanel kind="error" title="Couldn't load incidents" description="Check your connection and try again."
        onRetry={() => setRetried((count) => count + 1)}>
        {retried > 0 && <span role="status">Example retry attempts: {retried}</span>}
      </StatePanel>
      <StatePanel kind="loading" title="Loading incidents" description="Getting the latest reports." />
    </main>
  );
}

if (import.meta.env.DEV) {
  createRoot(document.getElementById('root')).render(<React.StrictMode><FoundationsPreview /></React.StrictMode>);
}
