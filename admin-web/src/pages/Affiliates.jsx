import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client.js';
import { agencyAuthority, agencyLabel } from '../auth.jsx';
import { useConsole } from '../components/ConsoleShell.jsx';
import OrgDialog from '../components/OrgDialog.jsx';
import { ConfirmDialog, EmptyState, Icon, PageHeader, StatePanel, StatusChip } from '../components/ui/index.js';
import { t } from '../i18n/i18n.jsx';

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
  { key: 'pending', get label() { return t('Waiting'); } },
  { key: 'approved', get label() { return t('Accepted'); } },
  { key: 'rejected', get label() { return t('Declined'); } },
  { key: 'network', get label() { return t('On the network'); } },
];

const contactOf = (r) => r.contact_name || r.contact_email || 'the contact';

function subline(r, result) {
  if (result) {
    const time = CLOCK.format(new Date(r.reviewed_at ?? Date.now()));
    return result.invite_email_sent
      ? t('Accepted {time} · link sent', { time })
      : t('Accepted {time}', { time });
  }
  if (r.status === 'approved') return t('Accepted {day}', { day: day(r.reviewed_at) });
  if (r.status === 'rejected') return t('Declined {day}', { day: day(r.reviewed_at) });
  return t('{agency} · sent {date}', { agency: agencyLabel(r.agency_type), date: day(r.created_at) });
}

/* What the accept call reported (A06b). Provisioning is best effort on the
 * server, so a partial result is shown as it is rather than as success. */
function AcceptOutcome({ result, request }) {
  const email = result.account_email || request.contact_email;
  if (result.invite_email_sent) {
    return (
      <div className="rpl-alert rpl-alert--ok" role="status">
        <span className="rpl-alert-mark" aria-hidden="true">✓</span>
        <div className="rpl-alert-text">
          <p className="rpl-alert-title">{t('Accepted — password link sent')}</p>
          <p className="rpl-alert-body">{t('Sent to {email} at {time}. They sign in as the organization’s Coordinator.', { email, time: CLOCK.format(new Date(request.reviewed_at ?? Date.now())) })}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="rpl-alert rpl-alert--warn" role="status">
      <span className="rpl-alert-mark" aria-hidden="true">!</span>
      <div className="rpl-alert-text">
        <p className="rpl-alert-title">
          {result.account_provisioned ? t('Accepted — the email didn’t send') : t('Accepted — no Coordinator account yet')}
        </p>
        <p className="rpl-alert-body">
          {result.detail || (result.account_provisioned
            ? t('The account for {email} is ready, but the password email failed. They can use “Forgot password” on the app.', { email })
            : t('The organization was created without a Coordinator account.'))}
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
    [t('Organization type'), agencyLabel(r.agency_type)],
    [t('Address'), r.address || t('Not given')],
    ...(roster != null ? [[t('Roster size'), roster === 1 ? t('{count} member', { count: roster }) : t('{count} members', { count: roster })]] : []),
    ...(equipment != null ? [[t('Equipment'), equipment === 1 ? t('{count} unit', { count: equipment }) : t('{count} units', { count: equipment })]] : []),
    ...(details.sec_certificate_name ? [[t('SEC certificate'), details.sec_certificate_name]] : []),
    [t('Submitted by'), r.contact_name || t('Not given')],
    [t('Email'), r.contact_email || t('Not given')],
    [t('Mobile'), r.contact_phone || t('Not given')],
    ...(r.message ? [[t('Message'), r.message]] : []),
    ...(r.status === 'rejected' && r.review_notes ? [[t('Reason declined'), r.review_notes]] : []),
  ];
  const eyebrow = r.status === 'pending'
    ? t('{agencyLabel} · waiting since {day}', { agencyLabel: agencyLabel(r.agency_type), day: day(r.created_at) })
    : `${agencyLabel(r.agency_type)} · ${r.status === 'approved' ? 'accepted' : 'declined'} ${day(r.reviewed_at)}`;
  const org = r.organization_id ? orgs.find((o) => o.id === r.organization_id) : null;

  return (
    <section className="rpl-panel rpl-aff-detail" aria-labelledby="rpl-aff-title">
      <header className="rpl-aff-detail-head">
        <p className="web-eyebrow">{eyebrow}</p>
        <h2 className="rpl-decision-title rpl-aff-title" id="rpl-aff-title">{r.organization_name}</h2>
      </header>
      <dl className="rpl-facts rpl-facts--wide">
        {facts.map(([t, v]) => (
          <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
        ))}
      </dl>

      {result && <AcceptOutcome result={result} request={r} />}

      {r.status === 'pending' && !result && (
        <>
          <div className="rpl-alert rpl-alert--info">
            <span className="rpl-alert-mark" aria-hidden="true">i</span>
            <p className="rpl-alert-body">
              {r.contact_email
                ? t('Accepting creates the organization and a Coordinator account for {contact_email}, and emails them a link to set their password.', { contact_email: r.contact_email })
                : t('No email was given, so accepting creates the organization without a Coordinator account.')}
            </p>
          </div>
          <div className="rpl-aff-actions">
            <button type="button" className="rpl-button rpl-button--secondary" onClick={onDecline}>{t('Decline')}</button>
            <button type="button" className="rpl-button rpl-button--primary" onClick={onAccept}>{t('Accept')}</button>
          </div>
        </>
      )}

      {org && (
        <button type="button" className="rpl-button rpl-button--secondary" onClick={() => onOpenOrg(org.id)}>{t('Open')}{' '}{org.name}
        </button>
      )}
    </section>
  );
}

function Network({ orgs, onOpen }) {
  if (orgs.length === 0) {
    return <EmptyState icon="organization" title={t('No organizations yet')}>{t('An organization joins the network when its affiliate request is accepted.')}</EmptyState>;
  }
  return (
    <div className="web-table-wrap">
      <table className="web-table">
        <caption className="web-sr-only">{t('Accredited organizations')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('Organization')}</th>
            <th scope="col">{t('Type')}</th>
            <th scope="col">{t('Authority')}</th>
            <th scope="col">{t('Personnel')}</th>
            <th scope="col">{t('Units')}</th>
            <th scope="col">{t('Status')}</th>
            <th scope="col"><span className="web-sr-only">{t('Open')}</span></th>
          </tr>
        </thead>
        <tbody>
          {orgs.map((o) => {
            const auth = agencyAuthority(o.agency_type);
            return (
              <tr key={o.id} className="web-table-row">
                <th scope="row">
                  <span className="rpl-cell-text">
                    <span className="rpl-cell-title">{o.name}</span>
                    {(o.address || o.created_at) && (
                      <span className="rpl-cell-meta">{o.address || t('On the network since {day}', { day: day(o.created_at) })}</span>
                    )}
                  </span>
                </th>
                <td>{agencyLabel(o.agency_type)}</td>
                <td>
                  <span title={auth.note ?? undefined}>
                    {auth.label}
                  </span>
                </td>
                <td className="rpl-cell-strong">{o.personnel_count ?? 0}</td>
                <td className="rpl-cell-strong">{o.equipment_count ?? 0}</td>
                <td><StatusChip label={o.is_active ? t('Active') : t('Inactive')} tone={o.is_active ? 'ok' : 'neutral'} /></td>
                <td className="web-table-action-cell">
                  <button type="button" className="web-table-row-action" onClick={() => onOpen(o.id)} aria-haspopup="dialog">{t('Open')}<span className="web-sr-only"> {o.name}</span>
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
      setError(e.message || t('The affiliate requests could not be loaded.'));
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
    setNotice(t('{org} accepted', { org: r.organization_name }));
    setTab('approved');
    setSelectedId(r.id);
    refreshQueues?.();
    await load();
  }

  async function decline() {
    const r = confirm.request;
    if (!reason.trim()) throw new Error(t('Give a reason — it is recorded with the request.'));
    await api.affiliateReject(r.id, reason.trim());
    setConfirm(null);
    setNotice(t('{org} declined', { org: r.organization_name }));
    setTab('rejected');
    setSelectedId(r.id);
    refreshQueues?.();
    await load();
  }

  return (
    <div className="rpl-page">
      <PageHeader
        eyebrow={t('{org} · Central hub', { org: org?.name ?? t('Central hub') })}
        title={t('Affiliate requests')}
        description={t('Organizations asking to join. Accepting creates the organization and its Coordinator account, and emails the contact a link to set their password.')}
      />

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label={t('Affiliate requests')}>
          {TABS.map((t) => {
            const count = t.key === 'network' ? orgs.length : lists[t.key]?.length ?? 0;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={`rpl-tab${tab === t.key ? ' is-active' : ''}`}
                onClick={() => { setTab(t.key); setSelectedId(null); }}
              >
                {t.label}
                {phase === 'ready' && t.key === 'pending' && count > 0 && <span className="web-count-badge">{count}</span>}
                {phase === 'ready' && t.key === 'network' && <span className="rpl-tab-count">{count}</span>}
              </button>
            );
          })}
        </div>
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" skeleton="cards" rows={4} title={t('Loading affiliate requests…')} busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title={t('The affiliate requests couldn’t load')} description={error} onRetry={load} />
      ) : tab === 'network' ? (
        <Network orgs={orgs} onOpen={setOpenOrgId} />
      ) : list.length === 0 ? (
        <EmptyState icon="affiliates" title={{ pending: t('Nothing waiting'), approved: t('None accepted yet'), rejected: t('None declined') }[tab]}>
          {tab === 'pending'
            ? t('A request appears here when an organization sends the public affiliate form.')
            : t('Decided requests stay here for reference.')}
        </EmptyState>
      ) : (
        <div className="rpl-aff-grid">
          <ul className="rpl-panel rpl-aff-list" aria-label={TABS.find((t) => t.key === tab).label}>
            {list.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={`rpl-idr-row${selected?.id === r.id ? ' is-selected' : ''}`}
                  onClick={() => setSelectedId(r.id)}
                  aria-current={selected?.id === r.id ? 'true' : undefined}
                >
                  <span className="rpl-idr-plate" aria-hidden="true"><Icon name="organization" /></span>
                  <span className="rpl-cell-text">
                    <span className="rpl-cell-title">{r.organization_name}</span>
                    <span className="rpl-cell-meta">{subline(r, results[r.id])}</span>
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
        eyebrow={t('Affiliate request · {agency}', { agency: confirm ? agencyLabel(confirm.request.agency_type) : '' })}
        title={t('Accept {org}?', { org: confirm?.request.organization_name ?? '' })}
        description={confirm?.request.contact_email
          ? t('We create the organization and a Coordinator account for {contactOf}, and email {contact_email} a link to set their password.', { contactOf: contactOf(confirm.request), contact_email: confirm.request.contact_email })
          : t('We create the organization. No email was given, so no Coordinator account is created.')}
        confirmLabel={confirm?.request.contact_email ? t('Accept and send link') : t('Accept')}
        onClose={() => setConfirm(null)}
        onConfirm={accept}
      />
      <ConfirmDialog
        open={confirm?.kind === 'decline'}
        destructive
        eyebrow={t('Affiliate request · {agency}', { agency: confirm ? agencyLabel(confirm.request.agency_type) : '' })}
        title={t('Decline {org}?', { org: confirm?.request.organization_name ?? '' })}
        description={t('No organization or account is created. RepLiT doesn’t email {contactOf} about it, so let them know yourself.', { contactOf: contactOf(confirm?.request ?? {}) })}
        confirmLabel={t('Decline request')}
        onClose={() => setConfirm(null)}
        onConfirm={decline}
      >
        <label className="rpl-field">
          <span className="rpl-field-label">{t('Reason')}</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} placeholder={t('e.g. Not registered with the SEC')} />
          <span className="rpl-field-help">{t('Recorded with the request.')}</span>
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

      {notice && <div className="rpl-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
    </div>
  );
}
