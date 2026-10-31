import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel, useAuth } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import { EmptyState, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';

/* Organisation (REPLIT (MAIN) 10 · A47 875:7012): the signed-in Admin's own
 * organisation — its profile, how many Coordinators and Responders it has,
 * and its equipment.
 *
 * The design's "Accepted by … on …", roster size from the affiliate request
 * and per-organisation alert sound are not stored with an organisation yet,
 * so those rows are not drawn. Every other accredited organisation is under
 * Affiliates. */

const DAY = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', day: 'numeric', month: 'short', year: 'numeric' });

const EQUIPMENT = {
  available: { label: 'Ready', tone: 'ok' },
  in_use: { label: 'Deployed', tone: 'accent' },
  maintenance: { label: 'Maintenance', tone: 'warn' },
  out_of_service: { label: 'Out of service', tone: 'neutral' },
};

function words(s) {
  return s ? String(s).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : '—';
}

function Facts({ rows }) {
  return (
    <dl className="ad-facts ad-facts--wide">
      {rows.map(([t, v]) => (
        <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

export default function Organization({ onNavigate }) {
  const { user } = useAuth();
  const { org } = useConsole();
  const profile = org?.profile ?? null;
  const [people, setPeople] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!profile) return;
    setPhase('loading');
    setError(null);
    try {
      const [p, e] = await Promise.all([api.orgPersonnel(profile.id), api.orgEquipment(profile.id)]);
      setPeople(Array.isArray(p) ? p : []);
      setEquipment(Array.isArray(e) ? e : []);
      setPhase('ready');
    } catch (err) {
      setError(err.message || 'The organization could not be loaded.');
      setPhase('error');
    }
  }, [profile]);
  useEffect(() => { load(); }, [load]);

  if (!profile) {
    return (
      <div className="ad-page">
        <PageHeader eyebrow="Organization" title="Organization" />
        <EmptyState icon="organization" title="No organization on this account">
          Your Admin account isn’t attached to an accredited organization, so there is no profile to show. The organizations on the network are under Affiliates.
        </EmptyState>
      </div>
    );
  }

  const coordinators = people.filter((p) => p.role === 'sub_admin').length;
  const responders = people.filter((p) => p.role === 'response_team').length;
  const contact = [profile.contact_email, profile.contact_phone].filter(Boolean).join(' · ');
  const profileRows = [
    ['Type', agencyLabel(profile.agency_type)],
    ['Admin', [user?.full_name, user?.email].filter(Boolean).join(' · ') || '—'],
    ['Address', profile.address || 'Not on record'],
    ['Contact', contact || 'Not on record'],
    ['Status', profile.is_active ? 'Active' : 'Inactive'],
  ];

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={`Organization · ${agencyLabel(profile.agency_type)}`}
        title={profile.name}
        description={profile.created_at ? `On the network since ${DAY.format(new Date(profile.created_at))}.` : null}
      />

      {phase === 'error' ? (
        <StatePanel kind="error" title="The organization couldn’t load" description={error} onRetry={load} />
      ) : (
        <>
          <div className="ad-incident-grid">
            <section className="ad-panel" aria-labelledby="ad-org-profile">
              <h2 className="ad-decision-title" id="ad-org-profile">Profile</h2>
              <Facts rows={profileRows} />
              {profile.description && <p className="ad-decision-body ad-org-about">{profile.description}</p>}
            </section>

            <section className="ad-panel ad-decision" aria-labelledby="ad-org-people" aria-busy={phase === 'loading' || undefined}>
              <h2 className="ad-decision-title" id="ad-org-people">People</h2>
              <Facts rows={[
                ['Coordinators', phase === 'loading' ? '…' : String(coordinators)],
                ['Responders', phase === 'loading' ? '…' : `${responders} · created by your Coordinators`],
              ]} />
              <div className="ad-alert ad-alert--info">
                <span className="ad-alert-mark" aria-hidden="true">i</span>
                <p className="ad-alert-body">Coordinators create Responder accounts for their team on the mobile app.</p>
              </div>
              {onNavigate && (
                <button type="button" className="ad-button ad-button--secondary" onClick={() => onNavigate('accounts')}>
                  View accounts
                </button>
              )}
            </section>
          </div>

          <section className="ad-board-section" aria-labelledby="ad-org-equipment">
            <div className="ad-section-head">
              <h2 className="ad-section-title" id="ad-org-equipment">Equipment</h2>
              <span className="ad-section-meta">{phase === 'ready' ? equipment.length : '…'}</span>
            </div>
            {phase === 'loading' ? (
              <StatePanel kind="loading" title="Loading equipment…" busy />
            ) : equipment.length === 0 ? (
              <p className="ad-empty-line">No equipment on record.</p>
            ) : (
              <div className="web-table-wrap">
                <table className="web-table">
                  <caption className="web-sr-only">Equipment</caption>
                  <thead>
                    <tr>
                      <th scope="col">Equipment</th>
                      <th scope="col">Category</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {equipment.map((e) => (
                      <tr key={e.id} className="web-table-row">
                        <th scope="row"><span className="ad-cell-title">{e.name}</span></th>
                        <td>
                          {words(e.category)}
                          {e.capacity_liters ? ` · ${Number(e.capacity_liters).toLocaleString()} L` : ''}
                        </td>
                        <td><StatusChip {...(EQUIPMENT[e.status] ?? { label: words(e.status), tone: 'neutral' })} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
