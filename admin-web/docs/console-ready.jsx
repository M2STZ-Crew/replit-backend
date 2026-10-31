import React, { useCallback, useState } from 'react';
import { createRoot } from 'react-dom/client';

import CreateCoordinatorDialog from '../src/components/accounts/CreateCoordinatorDialog.jsx';
import CorrectionDialog from '../src/components/audit/CorrectionDialog.jsx';
import CiarView from '../src/components/reports/CiarView.jsx';
import NewRequestDialog from '../src/components/requests/NewRequestDialog.jsx';
import AdminRegistration from '../src/pages/AdminRegistration.jsx';
import Reports from '../src/pages/Reports.jsx';
import Requests from '../src/pages/Requests.jsx';
import { AvailabilityPanel } from '../src/pages/Settings.jsx';
import '../src/index.css';
import '../src/styles/pass6.css';
import '../src/styles/pass6-pages.css';
import '../src/styles/pass6-auth.css';
import '../src/styles/pass6-existing.css';
import '../src/styles/pass6-incidents.css';
import '../src/styles/pass6-map.css';
import '../src/styles/pass6-access.css';

/* DEVELOPMENT PREVIEW ONLY — the UI READY components (features the server
 * does not support yet) and the empty and failed states of the integrated
 * Requests and Reports pages, on fictional data. Every callback here is
 * simulated in this page: nothing is fetched, sent or stored, and no
 * component is reachable from the console's navigation.
 * Open http://localhost:5173/docs/console-ready.html on the Vite dev server.
 * Not part of the production build (vite builds index.html only). */

const wait = (ms = 600) => new Promise((r) => setTimeout(r, ms));

const AREAS = [
  { id: 'a1', label: 'Example Area 1.2 · Sample Street' },
  { id: 'a2', label: 'Example Area 3.1 · Example Avenue' },
];
const ORGS = [
  { id: 'o1', name: 'Example Fire Bureau' },
  { id: 'o2', name: 'Example Medical Team' },
];
const CIAR = {
  lockedAt: '10:26 PM',
  source: 'compiled from the report and the audit log',
  parts: [
    { key: 'timeline', title: 'Timeline and confidence', rows: [['First report', '9:38:51 PM'], ['First acknowledge', '9:41:12 PM · Example Captain'], ['Fire out confirmed', '10:11:02 PM'], ['Final confidence', '0.86 · High']] },
    { key: 'scene', title: 'Scene profile', rows: [['Fire type', 'Fictional — Residential'], ['Smoke colour', 'Grey-white']] },
    { key: 'evidence', title: 'Evidence trail', text: 'Fictional example: seven clustered reports, four with photo GPS.' },
    { key: 'command', title: 'Command audit log', text: 'Fictional example: acknowledged, en route, arrived, fire out.' },
    { key: 'resources', title: 'Resources and logistics', rows: [['Truck', 'Example Tanker'], ['Water used', 'Fictional — 1,500 L']] },
    { key: 'narrative', title: 'Formal narrative', text: 'Fictional example narrative for the preview only.' },
  ],
};

function Section({ id, frames, title, note, children }) {
  return (
    <section className="ready-section" aria-labelledby={id}>
      <header className="ready-head">
        <p className="web-eyebrow">{frames}</p>
        <h2 className="rpl-decision-title" id={id}>{title}</h2>
        {note && <p className="rpl-decision-body">{note}</p>}
      </header>
      {children}
    </section>
  );
}

function Choice({ value, options, onChange, label }) {
  return (
    <div className="rpl-choice-options" role="group" aria-label={label}>
      {options.map(([k, text]) => (
        <button key={k} type="button" className={`rpl-choice-option${value === k ? ' is-on' : ''}`} onClick={() => onChange(k)} aria-pressed={value === k}>
          {text}
        </button>
      ))}
    </div>
  );
}

function PageStates() {
  const [which, setWhich] = useState('requests-empty');
  const empty = useCallback(async () => { await wait(); return []; }, []);
  const failing = useCallback(async () => { await wait(); throw new Error('Fictional failure: the server did not answer.'); }, []);
  const emptyPage = useCallback(async () => { await wait(); return { items: [], hasMore: false }; }, []);
  const none = useCallback(async () => [], []);
  const noSummary = useCallback(async () => ({ state: null, summary: null }), []);
  const noPdf = useCallback(async () => {}, []);
  const reader = which.endsWith('empty') ? (which.startsWith('requests') ? empty : emptyPage) : failing;
  return (
    <Section id="ready-states" frames="10 · A40, A60 · integrated pages" title="Empty and failed states"
             note="The live pages, given readers that return nothing or fail.">
      <Choice label="State" value={which} onChange={setWhich} options={[
        ['requests-empty', 'Requests · empty'], ['requests-failed', 'Requests · failed'],
        ['reports-empty', 'Reports · empty'], ['reports-failed', 'Reports · failed'],
      ]} />
      <div className="ready-frame">
        {which.startsWith('requests')
          ? <Requests key={which} readRequests={reader} />
          : <Reports key={which} readReports={reader} readIncidentReports={none} readSummary={noSummary} downloadIncidentPdf={noPdf} />}
      </div>
    </Section>
  );
}

function Coordinator() {
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState(null);
  const [fail, setFail] = useState(false);
  return (
    <Section id="ready-coordinator" frames="10 · A49, A49b" title="Create a Coordinator account"
             note="Waits on a server contract without an Admin-chosen password, with a title, and with an organisation for the Admin.">
      <div className="ready-actions">
        <button type="button" className="rpl-button rpl-button--primary" onClick={() => { setCreated(null); setOpen(true); }}>Create Coordinator</button>
        <label className="ready-toggle"><input type="checkbox" checked={fail} onChange={(e) => setFail(e.target.checked)} /> Simulate a failure</label>
      </div>
      {created && (
        <div className="rpl-alert rpl-alert--ok" role="status">
          <span className="rpl-alert-mark" aria-hidden="true">✓</span>
          <div className="rpl-alert-text">
            <p className="rpl-alert-title">Coordinator account created</p>
            <p className="rpl-alert-body">{created.fullName} · {created.email}{created.title ? ` · ${created.title}` : ''}. Preview only — nothing was sent.</p>
          </div>
        </div>
      )}
      <CreateCoordinatorDialog
        open={open}
        organization="Example Fire Volunteers"
        onClose={() => setOpen(false)}
        onCreate={async (v) => {
          await wait();
          if (fail) throw new Error('Fictional failure: that email already has an account.');
          setCreated(v);
          setOpen(false);
        }}
      />
    </Section>
  );
}

function NewRequest() {
  const [kind, setKind] = useState(null);
  const [sent, setSent] = useState(null);
  return (
    <Section id="ready-requests" frames="10 · A43, A44" title="Requests between Admins"
             note="Waits on server support for water and backup requests from one organisation to another.">
      <div className="ready-actions">
        <button type="button" className="rpl-button rpl-button--primary" onClick={() => setKind('water')}>Need water</button>
        <button type="button" className="rpl-button rpl-button--secondary" onClick={() => setKind('backup')}>Need backup</button>
      </div>
      {sent && <pre className="ready-out">{JSON.stringify(sent, null, 2)}</pre>}
      <NewRequestDialog
        open={kind != null}
        kind={kind ?? 'water'}
        areas={AREAS}
        organizations={ORGS}
        roles={['Firefighter', 'Medic', 'Driver']}
        onClose={() => setKind(null)}
        onSend={async (v) => { await wait(); setSent(v); setKind(null); }}
      />
    </Section>
  );
}

function Availability() {
  const [afk, setAfk] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <Section id="ready-afk" frames="10 · A70, A71" title="Availability (AFK)"
             note="Waits on the server storing and reporting an organisation’s availability.">
      <div className="ready-frame ready-frame--narrow">
        <AvailabilityPanel
          afk={afk}
          since={afk ? '9:42 PM' : null}
          busy={busy}
          onChange={async (next) => { setBusy(true); await wait(); setAfk(next); setBusy(false); }}
        />
      </div>
    </Section>
  );
}

function Ciar() {
  const [state, setState] = useState('ready');
  return (
    <Section id="ready-ciar" frames="10 · A62, A63, A63b" title="CIAR — six parts"
             note="Waits on the server writing a structured CIAR; today it writes a narrative AI summary, shown on the live Reports page.">
      <Choice label="CIAR state" value={state} onChange={setState} options={[['ready', 'Ready'], ['generating', 'Generating'], ['failed', 'Couldn’t be generated']]} />
      <CiarView key={state} state={state} ciar={CIAR} onRetry={() => setState('generating')} />
    </Section>
  );
}

function Correction() {
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState(null);
  return (
    <Section id="ready-correction" frames="10 · A65, A66" title="Add a correction"
             note="Waits on the audit log accepting correction entries.">
      <div className="ready-actions">
        <button type="button" className="rpl-button rpl-button--secondary" onClick={() => setOpen(true)}>Add correction</button>
      </div>
      {added && <pre className="ready-out">{JSON.stringify(added, null, 2)}</pre>}
      <CorrectionDialog
        open={open}
        target={{ label: 'Example Area 1.2' }}
        fields={[{ key: 'fire_type', label: 'Fire type', current: 'Fictional — Residential' }, { key: 'driver', label: 'Driver', current: 'Example Driver' }]}
        onClose={() => setOpen(false)}
        onSubmit={async (v) => { await wait(); setAdded(v); setOpen(false); }}
      />
    </Section>
  );
}

function Registration() {
  const [state, setState] = useState('valid');
  const [done, setDone] = useState(null);
  // A fictional rule and domain for the preview; the real ones are the server's.
  const rule = { test: (p) => /^[a-z0-9-]{3,40}$/.test(p), help: '3–40 characters: lowercase letters, numbers, hyphens' };
  const check = useCallback(async (p) => { await wait(400); if (p === 'taken') return 'taken'; if (p === 'admin') return 'not_allowed'; return 'available'; }, []);
  return (
    <Section id="ready-registration" frames="10 · A07–A11" title="Admin registration link"
             note="Waits on the server issuing one-time Admin registration links. Try “taken” or “admin” as the prefix.">
      <Choice label="Link state" value={state} onChange={(s) => { setDone(null); setState(s); }} options={[['valid', 'Valid'], ['expired', 'Expired'], ['used', 'Already used']]} />
      {done && <p className="rpl-alert-body">Preview only: would create {done.email}.</p>}
      <div className="ready-frame ready-frame--auth">
        <AdminRegistration
          key={state}
          link={{ state, organization: 'Example Rescue Brigade', expiresAt: 'in 48 hours (fictional)' }}
          domain=".admin@example.test"
          rule={rule}
          checkPrefix={check}
          onCreate={async (v) => { await wait(); setDone(v); }}
        />
      </div>
    </Section>
  );
}

function Gallery() {
  return (
    <main className="ready">
      <header className="ready-top">
        <p className="web-eyebrow">Development preview · fictional data</p>
        <h1 className="web-page-title">UI READY</h1>
        <p className="web-page-description">Prepared screens for features the server does not support yet, and the integrated pages’ empty and failed states. Nothing here reaches a server.</p>
      </header>
      <PageStates />
      <Coordinator />
      <NewRequest />
      <Availability />
      <Ciar />
      <Correction />
      <Registration />
    </main>
  );
}

if (import.meta.env.DEV) {
  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <Gallery />
    </React.StrictMode>,
  );
}
