import { agencyLabel, useAuth } from '../auth.jsx';
import { awaitingAccept, useLiveFeed } from '../live/LiveFeed.jsx';
import { AGENCY_LABEL, since, statusOf } from '../lib/status.js';

/// Dashboard — the agency's picture at a glance (v10 Section 2.6.1).
///
/// Every number here is a count of incidents the server already scoped to this
/// agency; nothing is estimated. A card opens the incident on the map, where the
/// Accept control is.
export default function DashboardPage({ onNavigate }) {
  const { user } = useAuth();
  const { incidents, loaded, error, refresh } = useLiveFeed();
  const agency = user.agency_type;

  const awaiting = incidents.filter((inc) => awaitingAccept(inc, agency));
  const accepted = incidents.filter((inc) => (inc.accepted_agencies ?? []).includes(agency));
  const unrouted = incidents.filter((inc) => !(inc.routed_agencies ?? []).includes(agency));

  const kpis = [
    { label: 'Live incidents', value: incidents.length, foot: `Involving ${agencyLabel(agency)}` },
    {
      label: 'Awaiting your Accept', value: awaiting.length, foot: 'Routed to you by Admin',
      tone: awaiting.length > 0 ? 'var(--live)' : undefined,
    },
    { label: 'Accepted', value: accepted.length, foot: 'Acknowledged by your agency',
      tone: accepted.length > 0 ? 'var(--settled)' : undefined },
    { label: 'Not yet routed', value: unrouted.length, foot: 'Requested you; Admin has not routed it' },
  ];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="os-eyebrow">{agencyLabel(agency)} · Observer</span>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-sub">
            Live incidents where a reporter asked for {agencyLabel(agency)}. Fire Volunteer
            and BFP coordinators verify, dispatch and resolve; you watch and acknowledge.
          </p>
        </div>
        <button className="btn-ghost" onClick={refresh}>Refresh</button>
      </header>

      {error && <div className="note is-error">{error}</div>}

      <div className="kpis">
        {kpis.map((k) => (
          <section className="kpi" key={k.label}>
            <span className="os-eyebrow">{k.label}</span>
            <span className="kpi-value" style={k.tone ? { color: k.tone } : undefined}>
              {loaded ? k.value : '·'}
            </span>
            <span className="kpi-foot">{k.foot}</span>
          </section>
        ))}
      </div>

      {awaiting.length > 0 && (
        <section className="panel">
          <header className="panel-head">
            <span className="panel-title">Awaiting your Accept</span>
            <span className="os-eyebrow">Open one to acknowledge it</span>
          </header>
          <div className="cards">
            {awaiting.map((inc) => (
              <IncidentCard key={inc.id} inc={inc} agency={agency} urgent onOpen={onNavigate} />
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <header className="panel-head">
          <span className="panel-title">All live incidents</span>
          <span className="os-eyebrow">{incidents.length} involving {agencyLabel(agency)}</span>
        </header>
        {incidents.length === 0 ? (
          <p className="empty">
            {loaded
              ? `No live incidents have asked for ${agencyLabel(agency)}. They appear here the moment a reporter does.`
              : 'Loading…'}
          </p>
        ) : (
          <div className="cards">
            {incidents.map((inc) => (
              <IncidentCard key={inc.id} inc={inc} agency={agency} onOpen={onNavigate} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function IncidentCard({ inc, agency, urgent = false, onOpen }) {
  const st = statusOf(inc.status);
  const routed = (inc.routed_agencies ?? []).includes(agency);
  const accepted = (inc.accepted_agencies ?? []).includes(agency);
  return (
    <button
      className={`card${urgent ? ' is-urgent' : ''}`}
      onClick={() => onOpen('map', { incidentId: inc.id })}
      title={`Open ${inc.designation} on the map`}
    >
      <div className="card-top">
        <span className="card-name">{inc.designation}</span>
        <span className="card-status" style={{ color: st.color }}>
          <span className="dot" style={{ background: st.color }} />
          {st.label}
        </span>
      </div>
      <div className="card-agencies">
        {(inc.requested_agencies ?? []).map((a) => (
          <span key={a} className={`chip${a === agency ? ' is-mine' : ''}`}>{AGENCY_LABEL[a] ?? a}</span>
        ))}
      </div>
      <div className="card-foot">
        <span>
          {inc.report_count} report{inc.report_count === 1 ? '' : 's'} · {since(inc.reported_at)} ago
        </span>
        <span className={`card-state${accepted ? ' is-ok' : routed ? ' is-live' : ''}`}>
          {accepted ? '✓ Accepted' : routed ? 'Routed to you' : 'Not routed'}
        </span>
      </div>
    </button>
  );
}
