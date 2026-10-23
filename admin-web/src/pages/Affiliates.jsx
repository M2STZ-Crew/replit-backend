import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyAuthority, agencyLabel } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import OrgDialog from '../components/OrgDialog.jsx';
import { ConfirmDialog, EmptyState, Icon, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';

/* Affiliate requests (REPLIT (MAIN) 10 · A05 860:194, A06 860:528, A06b
 * 860:796, A06c 860:1028; Section 2.6): organisations asking to join, and
 * the central hub's decision on each.
 *
 * Accepting creates the organisation and a Coordinator account for the
 * contact's email, and emails them a link to set their password — what the
 * server does today. The design's one-time Admin registration link (A07–A12)
 * waits on server support; its 48-hour expiry is not claimed here. Declining
 * records the reason; the server sends no email about it, so the dialog says
 * so.
 *
 * "On the network" keeps every accredited organisation one click away, with
 * its people, equipment and the application it joined with. */

const SECTOR_COLOR = {
  fire_volunteer: '#FF9066',
  bfp: '#FF544E',
  police: '#6098D6',
  medical: '#22C55E',
  barangay: '#8a8a8a',
};
const GLYPH = {
  fire_volunteer: 'glyph-firefighter',
  bfp: 'glyph-fire',
  police: 'glyph-police',
  medical: 'glyph-hospital',
  barangay: 'glyph-people',
};

const DAY = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
});
const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const day = (iso) => (iso ? DAY.format(new Date(iso)) : '—');

const TABS = [
  { key: 'pending', label: 'Waiting' },
  { key: 'approved', label: 'Accepted' },
  { key: 'rejected', label: 'Declined' },
  { key: 'network', label: 'On the network' },
];

const contactOf = (r) => r.contact_name || r.contact_email || 'the contact';

function subline(r, result) {
  if (result) return `Accepted ${CLOCK.format(new Date(r.reviewed_at ?? Date.now()))}${result.invite_email_sent ? ' · link sent' : ''}`;
  if (r.status === 'approved') return `Accepted ${day(r.reviewed_at)}`;
  if (r.status === 'rejected') return `Declined ${day(r.reviewed_at)}`;
  return `${agencyLabel(r.agency_type)} · sent ${day(r.created_at)}`;
}

/* What the accept call reported (A06b). Provisioning is best effort on the
 * server, so a partial result is shown as it is rather than as success. */
function AcceptOutcome({ result, request }) {
  const email = result.account_email || request.contact_email;
  if (result.invite_email_sent) {
    return (
      <div className="ad-alert ad-alert--ok" role="status">
        <span className="ad-alert-mark" aria-hidden="true">✓</span>
        <div className="ad-alert-text">
          <p className="ad-alert-title">Accepted — password link sent</p>
          <p className="ad-alert-body">Sent to {email} at {CLOCK.format(new Date(request.reviewed_at ?? Date.now()))}. They sign in as the organisation’s Coordinator.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="ad-alert ad-alert--warn" role="status">
      <span className="ad-alert-mark" aria-hidden="true">!</span>
      <div className="ad-alert-text">
        <p className="ad-alert-title">
          {result.account_provisioned ? 'Accepted — the email didn’t send' : 'Accepted — no Coordinator account yet'}
        </p>
        <p className="ad-alert-body">
          {result.detail || (result.account_provisioned
            ? `The account for ${email} is ready, but the password email failed. They can use “Forgot password” on the app.`
            : 'The organisation was created without a Coordinator account.')}
        </p>
      </div>
    </div>
  );
}

function RequestDetail({ request: r, result, orgs, onAccept, onDecline, onOpenOrg }) {
  const details = r.details ?? {};
  const roster = Array.isArray(details.roster) ? details.roster.length : null;
  const equipment = Array.isArray(details.equipment) ? details.equipment.length : null;
  const facts = [
    ['Organisation type', agencyLabel(r.agency_type)],
    ['Address', r.address || 'Not given'],
    ...(roster != null ? [['Roster size', `${roster} member${roster === 1 ? '' : 's'}`]] : []),
    ...(equipment != null ? [['Equipment', `${equipment} unit${equipment === 1 ? '' : 's'}`]] : []),
    ...(details.sec_certificate_name ? [['SEC certificate', details.sec_certificate_name]] : []),
    ['Submitted by', r.contact_name || 'Not given'],
    ['Email', r.contact_email || 'Not given'],
    ['Mobile', r.contact_phone || 'Not given'],
    ...(r.message ? [['Message', r.message]] : []),
    ...(r.status === 'rejected' && r.review_notes ? [['Reason declined', r.review_notes]] : []),
  ];
  const eyebrow = r.status === 'pending'
    ? `${agencyLabel(r.agency_type)} · waiting since ${day(r.created_at)}`
    : `${agencyLabel(r.agency_type)} · ${r.status === 'approved' ? 'accepted' : 'declined'} ${day(r.reviewed_at)}`;
  const org = r.organization_id ? orgs.find((o) => o.id === r.organization_id) : null;

  return (
    <section className="ad-panel ad-aff-detail" aria-labelledby="ad-aff-title">
      <header className="ad-aff-detail-head">
        <p className="web-eyebrow">{eyebrow}</p>
        <h2 className="ad-decision-title ad-aff-title" id="ad-aff-title">{r.organization_name}</h2>
      </header>
      <dl className="ad-facts ad-facts--wide">
        {facts.map(([t, v]) => (
          <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
        ))}
      </dl>

      {result && <AcceptOutcome result={result} request={r} />}

      {r.status === 'pending' && !result && (
        <>
          <div className="ad-alert ad-alert--info">
            <span className="ad-alert-mark" aria-hidden="true">i</span>
            <p className="ad-alert-body">
              {r.contact_email
                ? `Accepting creates the organisation and a Coordinator account for ${r.contact_email}, and emails them a link to set their password.`
                : 'No email was given, so accepting creates the organisation without a Coordinator account.'}
            </p>
          </div>
          <div className="ad-aff-actions">
            <button type="button" className="ad-button ad-button--secondary" onClick={onDecline}>Decline</button>
            <button type="button" className="ad-button ad-button--primary" onClick={onAccept}>Accept</button>
          </div>
        </>
      )}

      {org && (
        <button type="button" className="ad-button ad-button--secondary" onClick={() => onOpenOrg(org.id)}>
          Open {org.name}
        </button>
      )}
    </section>
  );
}

function Network({ orgs, onOpen }) {
  if (orgs.length === 0) {
    return <EmptyState icon="organization" title="No organisations yet">An organisation joins the network when its affiliate request is accepted.</EmptyState>;
  }
  return (
    <div className="web-table-wrap">
      <table className="web-table">
        <caption className="web-sr-only">Accredited organisations</caption>
        <thead>
          <tr>
            <th scope="col">Organisation</th>
            <th scope="col">Type</th>
            <th scope="col">Authority</th>
            <th scope="col">Personnel</th>
            <th scope="col">Units</th>
            <th scope="col">Status</th>
            <th scope="col"><span className="web-sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {orgs.map((o) => {
            const auth = agencyAuthority(o.agency_type);
            return (
              <tr key={o.id} className="web-table-row">
                <th scope="row">
                  <span className="ad-cell-text">
                    <span className="ad-cell-title">{o.name}</span>
                    {(o.address || o.created_at) && (
                      <span className="ad-cell-meta">{o.address || `On the network since ${day(o.created_at)}`}</span>
                    )}
                  </span>
                </th>
                <td>{agencyLabel(o.agency_type)}</td>
                <td>
                  <span title={auth.note ?? undefined}>
                    {auth.label}
                  </span>
                </td>
                <td className="ad-cell-strong">{o.personnel_count ?? 0}</td>
                <td className="ad-cell-strong">{o.equipment_count ?? 0}</td>
                <td><StatusChip label={o.is_active ? 'Active' : 'Inactive'} tone={o.is_active ? 'ok' : 'neutral'} /></td>
                <td className="web-table-action-cell">
                  <button type="button" className="web-table-row-action" onClick={() => onOpen(o.id)} aria-haspopup="dialog">
                    Open<span className="web-sr-only"> {o.name}</span>
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Affiliates() {
  const { org, refreshQueues } = useConsole();
  const [requests, setRequests] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('pending');
  const [selectedId, setSelectedId] = useState(null);
  const [results, setResults] = useState({});
  const [confirm, setConfirm] = useState(null);
  const [reason, setReason] = useState('');
  const [openOrgId, setOpenOrgId] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [r, o] = await Promise.all([api.affiliates(), api.organizations()]);
      setRequests(Array.isArray(r) ? r : []);
      setOrgs(Array.isArray(o) ? o : []);
      setPhase('ready');
    } catch (e) {
      setError(e.message || 'The affiliate requests could not be loaded.');
      setPhase('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  const lists = useMemo(() => {
    const by = { pending: [], approved: [], rejected: [] };
    for (const r of requests) (by[r.status] ?? []).push(r);
    by.approved.sort((a, b) => new Date(b.reviewed_at ?? 0) - new Date(a.reviewed_at ?? 0));
    by.rejected.sort((a, b) => new Date(b.reviewed_at ?? 0) - new Date(a.reviewed_at ?? 0));
    return by;
  }, [requests]);

  const list = lists[tab] ?? [];
  const selected = list.find((r) => r.id === selectedId) ?? list[0] ?? null;
  const applicationOf = useMemo(() => {
    const byOrg = new Map();
    for (const r of lists.approved) if (r.organization_id && !byOrg.has(r.organization_id)) byOrg.set(r.organization_id, r);
    return byOrg;
  }, [lists]);
  const openOrg = orgs.find((o) => o.id === openOrgId) ?? null;

  async function accept() {
    const r = confirm.request;
    const result = await api.affiliateAccept(r.id, '');
    setConfirm(null);
    setResults((prev) => ({ ...prev, [r.id]: result }));
    setNotice(`${r.organization_name} accepted`);
    setTab('approved');
    setSelectedId(r.id);
    refreshQueues?.();
    await load();
  }

  async function decline() {
    const r = confirm.request;
    if (!reason.trim()) throw new Error('Give a reason — it is recorded with the request.');
    await api.affiliateReject(r.id, reason.trim());
    setConfirm(null);
    setNotice(`${r.organization_name} declined`);
    setTab('rejected');
    setSelectedId(r.id);
    refreshQueues?.();
    await load();
  }

  return (
    <div className="ad-page">
      <PageHeader
        eyebrow={`${org?.name ?? 'Central hub'} · Central hub`}
        title="Affiliate requests"
        description="Organisations asking to join. Accepting creates the organisation and its Coordinator account, and emails the contact a link to set their password."
      />

      <div className="ad-toolbar">
        <div className="ad-tabs" role="tablist" aria-label="Affiliate requests">
          {TABS.map((t) => {
            const count = t.key === 'network' ? orgs.length : lists[t.key]?.length ?? 0;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={`ad-tab${tab === t.key ? ' is-active' : ''}`}
                onClick={() => { setTab(t.key); setSelectedId(null); }}
              >
                {t.label}
                {phase === 'ready' && t.key === 'pending' && count > 0 && <span className="web-count-badge">{count}</span>}
                {phase === 'ready' && t.key === 'network' && <span className="ad-tab-count">{count}</span>}
              </button>
            );
          })}
        </div>
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" title="Loading affiliate requests…" busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title="The affiliate requests couldn’t load" description={error} onRetry={load} />
      ) : tab === 'network' ? (
        <Network orgs={orgs} onOpen={setOpenOrgId} />
      ) : list.length === 0 ? (
        <EmptyState icon="affiliates" title={{ pending: 'Nothing waiting', approved: 'None accepted yet', rejected: 'None declined' }[tab]}>
          {tab === 'pending'
            ? 'A request appears here when an organisation sends the public affiliate form.'
            : 'Decided requests stay here for reference.'}
        </EmptyState>
      ) : (
        <div className="ad-aff-grid">
          <ul className="ad-panel ad-aff-list" aria-label={TABS.find((t) => t.key === tab).label}>
            {list.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={`ad-idr-row${selected?.id === r.id ? ' is-selected' : ''}`}
                  onClick={() => setSelectedId(r.id)}
                  aria-current={selected?.id === r.id ? 'true' : undefined}
                >
                  <span className="ad-idr-plate" aria-hidden="true"><Icon name="organization" /></span>
                  <span className="ad-cell-text">
                    <span className="ad-cell-title">{r.organization_name}</span>
                    <span className="ad-cell-meta">{subline(r, results[r.id])}</span>
                  </span>
                  <Icon name="chevron-right" />
                </button>
              </li>
            ))}
          </ul>
          {selected && (
            <RequestDetail
              request={selected}
              result={results[selected.id] ?? null}
              orgs={orgs}
              onAccept={() => setConfirm({ kind: 'accept', request: selected })}
              onDecline={() => { setReason(''); setConfirm({ kind: 'decline', request: selected }); }}
              onOpenOrg={setOpenOrgId}
            />
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirm?.kind === 'accept'}
        eyebrow={`Affiliate request · ${confirm ? agencyLabel(confirm.request.agency_type) : ''}`}
        title={`Accept ${confirm?.request.organization_name ?? ''}?`}
        description={confirm?.request.contact_email
          ? `We create the organisation and a Coordinator account for ${contactOf(confirm.request)}, and email ${confirm.request.contact_email} a link to set their password.`
          : 'We create the organisation. No email was given, so no Coordinator account is created.'}
        confirmLabel={confirm?.request.contact_email ? 'Accept and send link' : 'Accept'}
        onClose={() => setConfirm(null)}
        onConfirm={accept}
      />
      <ConfirmDialog
        open={confirm?.kind === 'decline'}
        destructive
        eyebrow={`Affiliate request · ${confirm ? agencyLabel(confirm.request.agency_type) : ''}`}
        title={`Decline ${confirm?.request.organization_name ?? ''}?`}
        description={`No organisation or account is created. RepLiT doesn’t email ${contactOf(confirm?.request ?? {})} about it, so let them know yourself.`}
        confirmLabel="Decline request"
        onClose={() => setConfirm(null)}
        onConfirm={decline}
      >
        <label className="ad-field">
          <span className="ad-field-label">Reason</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} placeholder="e.g. Not registered with the SEC" />
          <span className="ad-field-help">Recorded with the request.</span>
        </label>
      </ConfirmDialog>

      {openOrg && (
        <OrgDialog
          org={openOrg}
          application={applicationOf.get(openOrg.id) ?? null}
          glyph={GLYPH[openOrg.agency_type] ?? 'glyph-people'}
          color={SECTOR_COLOR[openOrg.agency_type] ?? '#8a8a8a'}
          onClose={() => setOpenOrgId(null)}
        />
      )}

      {notice && <div className="ad-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
    </div>
  );
}
