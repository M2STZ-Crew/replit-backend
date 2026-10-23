import { AGENCY_LABEL, OFF_FEED, alarmLabel, statusOf } from '../../lib/status.js';
import Place from '../Place.jsx';
import { ConfirmDialog } from '../ui/index.js';
import ZoomablePhoto from '../ui/ZoomablePhoto.jsx';
import AreaMap from './AreaMap.jsx';
import { agenciesOf, confidenceOf } from './IncidentTable.jsx';
import LifecycleChip from './LifecycleChip.jsx';
import LifecycleProgress from './LifecycleProgress.jsx';

/* One Area, in full (REPLIT (MAIN) 10 · A23 867:2193, A24 867:2419, A24b
 * 867:2662, A26 868:2888): the map and its progress with the facts, beside
 * the decision this organisation can take and the timeline.
 *
 * What is drawn is what the server returns, with the street looked up by
 * the console beside the degrees (components/Place.jsx) until the server
 * stores it. Left out until it serves them: the fire type, the
 * safety roll call and help alerts (A26), and "Send a request for this
 * Area" (Admin-to-Admin requests). */

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const CLOCK_S = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit', second: '2-digit',
});

const clock = (iso) => (iso ? CLOCK.format(new Date(iso)) : '—');
const clockS = (iso) => (iso ? CLOCK_S.format(new Date(iso)) : '—');

/* What happened, newest first, from the timestamps the Area carries. */
function timelineOf(d, evidence) {
  const items = [];
  const push = (at, title, sub, tone) => at && items.push({ at, title, sub, tone });
  push(d.reported_at, `${d.designation} created`, <>First report, <Place lat={d.centroid_lat} lng={d.centroid_lng} /></>, 'live');
  const later = (evidence ?? []).slice(1);
  if (later.length) {
    const last = later.reduce((a, r) => (new Date(r.created_at) > new Date(a.created_at) ? r : a), later[0]);
    push(last.created_at, `${later.length} more report${later.length === 1 ? '' : 's'} clustered`, 'Joined the first report’s Area', 'neutral');
  }
  push(
    d.verified_at,
    `Acknowledged${d.verified_by_name ? ` by ${d.verified_by_name}` : ''}`,
    [d.verified_by_agency ? AGENCY_LABEL[d.verified_by_agency] ?? d.verified_by_agency : 'Admin', d.verified_by_organization].filter(Boolean).join(' · '),
    'accent',
  );
  push(d.en_route_at, 'A unit set off', 'The Area went En route', 'live');
  push(d.arrived_at, 'Arrived on scene', 'The first unit reached the Area', 'live');
  push(d.alarm_level_set_at, `Alarm set to ${alarmLabel(d.alarm_level)}`, 'Set by BFP', 'live');
  push(d.resolved_at, 'Fire out', d.resolved_by_name ? `Marked by ${d.resolved_by_name}` : 'Marked on scene', 'ok');
  push(d.closed_at, 'Closed', 'Post-incident report filed', 'neutral');
  push(d.rejected_at, 'Rejected', d.rejection_reason || (d.rejected_by_name ? `By ${d.rejected_by_name}` : ''), 'neutral');
  push(d.merged_at, 'Merged', d.merged_by_name ? `By ${d.merged_by_name}` : 'Into another Area', 'neutral');
  return items.sort((a, b) => new Date(b.at) - new Date(a.at));
}

function Facts({ rows }) {
  return (
    <dl className="ad-facts ad-facts--wide">
      {rows.map(([term, value]) => (
        <div className="ad-fact" key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function involved(d) {
  const names = (d.acceptances ?? []).map((a) => a.organization_name || (a.agency ? AGENCY_LABEL[a.agency] ?? a.agency : 'Admin'));
  return names.length ? [...new Set(names)].join(' · ') : 'None yet';
}

/* The decision card (A23 / A24b): what this Admin may do with the Area now. */
function Decision({ d, onAcknowledge, busy, acknowledgedNow }) {
  const status = d.status;
  if (status === 'reported') {
    return (
      <section className="ad-panel ad-decision" aria-labelledby="ad-decision-title">
        <div className="ad-decision-head">
          <h2 className="ad-decision-title" id="ad-decision-title">Acknowledge this Area</h2>
          <LifecycleChip status={status} />
        </div>
        <p className="ad-decision-body">
          {d.designation} asked for {agenciesOf(d)}. Acknowledging says your organisation has seen it
          and will check. It sends nobody: Coordinators decide who goes.
        </p>
        <button type="button" className="ad-button ad-button--primary ad-button--run" onClick={onAcknowledge} disabled={busy}>
          {busy ? 'Acknowledging…' : 'Acknowledge'}
        </button>
        <p className="ad-decision-note">
          Opening this page stopped the sound. It didn’t acknowledge the incident.
        </p>
      </section>
    );
  }
  if (status === 'verified' || status === 'acknowledged') {
    return (
      <section className="ad-panel ad-decision" aria-labelledby="ad-decision-title">
        <div className="ad-decision-head">
          <h2 className="ad-decision-title" id="ad-decision-title">Acknowledged</h2>
          <LifecycleChip status={status} />
        </div>
        <div className="ad-success" role={acknowledgedNow ? 'status' : undefined}>
          <span className="ad-success-check" aria-hidden="true">✓</span>
          <div>
            <p className="ad-success-title">
              Acknowledged{d.verified_by_name ? ` by ${d.verified_by_name}` : ''} · {clock(d.verified_at)}
            </p>
            <p className="ad-success-body">
              Coordinators and Responders can see it. It moves to En route when a unit sets off.
            </p>
          </div>
        </div>
      </section>
    );
  }
  return null;
}

/* On scene (A26): the units this Area has, and any alarm escalation raised
 * for it. */
function OnScene({ d, dispatches, requests }) {
  const active = (dispatches ?? []).filter((x) => x.status === 'active');
  return (
    <section className="ad-panel ad-decision" aria-labelledby="ad-onscene-title">
      <div className="ad-decision-head">
        <h2 className="ad-decision-title" id="ad-onscene-title">On scene</h2>
        <LifecycleChip status={d.status} />
      </div>
      {active.length === 0 ? (
        <p className="ad-decision-body">No unit is assigned to this Area right now.</p>
      ) : (
        <ul className="ad-units">
          {active.map((x) => (
            <li key={x.id}>
              <span className="ad-cell-title">{x.vehicle_name || x.responder_name || 'A responder'}</span>
              <span className="ad-cell-meta">
                {[x.responder_name && x.vehicle_name ? x.responder_name : null, x.crew_role, `since ${clock(x.dispatched_at)}`].filter(Boolean).join(' · ')}
              </span>
            </li>
          ))}
        </ul>
      )}
      {requests.map((r) => (
        <div className="ad-request-line" key={r.id}>
          <span className="ad-cell-title">
            Alarm escalation · {alarmLabel(r.requested_alarm_level)}
          </span>
          <span className="ad-cell-meta">
            {r.requested_by_name ? `From ${r.requested_by_name} · ` : ''}{clock(r.created_at)} · {r.status === 'pending' ? 'waiting for BFP' : r.status}
          </span>
        </div>
      ))}
    </section>
  );
}

export default function IncidentDetail({
  detail: d, evidence, dispatches, requests, reports,
  busy, error, confirming, acknowledgedNow,
  onAskAcknowledge, onCancelAcknowledge, onConfirmAcknowledge, onBack, onPdf,
}) {
  const live = !OFF_FEED.includes(d.status);
  const onScene = d.status === 'en_route' || d.status === 'arrived';
  const firstReport = (evidence ?? [])[0];
  const active = (dispatches ?? []).filter((x) => x.status === 'active');
  const facts = [
    ['Requested agencies', agenciesOf(d)],
    ['Confidence', `${confidenceOf(d)} (${d.report_count} report${d.report_count === 1 ? '' : 's'})`],
    ...(d.alarm_level ? [['Alarm level', `${alarmLabel(d.alarm_level)}${d.alarm_level_set_at ? ' · set by BFP' : ''}`]] : []),
    ...(onScene ? [['Units', active.length ? active.map((x) => x.vehicle_name || x.responder_name).join(' · ') : 'None assigned']] : []),
    ['Location', <Place lat={d.centroid_lat} lng={d.centroid_lng} stacked />],
    ['First report', `${clock(d.reported_at)}${firstReport ? ` · ${firstReport.user_verified_percent ?? 0}% verified reporter` : ''}`],
    ['Organisations involved', involved(d)],
  ];
  const timeline = timelineOf(d, evidence);
  const sub = [
    d.arrived_at ? `Arrived ${clock(d.arrived_at)}` : `First report ${clock(d.reported_at)}`,
    `${d.report_count} report${d.report_count === 1 ? '' : 's'}`,
  ].join(' · ');

  return (
    <div className="ad-page ad-incident">
      <button type="button" className="ad-text-button ad-back" onClick={onBack}>
        ← All incidents
      </button>
      <header className="web-page-header">
        <div className="web-page-header-copy">
          <p className="web-eyebrow">{d.designation} · {statusOf(d.status).label}</p>
          <h1 className="web-page-title">{d.designation}</h1>
          <p className="web-page-description">{sub}</p>
        </div>
      </header>

      {error && <p className="ad-inline-error" role="alert">{error}</p>}

      <div className="ad-incident-grid">
        <div className="ad-incident-main">
          <AreaMap lat={d.centroid_lat} lng={d.centroid_lng} label={d.designation} />
          <section className="ad-panel">
            <LifecycleProgress status={d.status} />
            <Facts rows={facts} />
          </section>
        </div>

        <div className="ad-incident-side">
          {onScene ? (
            <OnScene d={d} dispatches={dispatches} requests={requests} />
          ) : (
            <Decision d={d} busy={busy} acknowledgedNow={acknowledgedNow} onAcknowledge={onAskAcknowledge} />
          )}

          {(d.status === 'post_incident_report' || reports.length > 0) && (
            <section className="ad-panel ad-decision" aria-labelledby="ad-pir-title">
              <div className="ad-decision-head">
                <h2 className="ad-decision-title" id="ad-pir-title">Post-incident report</h2>
                <LifecycleChip status={d.status} />
              </div>
              <p className="ad-decision-body">
                {reports.length === 0
                  ? 'Fire out. Waiting on the responding team captain’s report; the Area closes when it is filed.'
                  : `${reports.length} team${reports.length === 1 ? '' : 's'} filed. Read them in Reports & CIAR, or download the record.`}
              </p>
              {reports.length > 0 && (
                <button type="button" className="ad-button ad-button--secondary" onClick={onPdf} disabled={busy}>
                  Download report (PDF)
                </button>
              )}
            </section>
          )}

          <section className="ad-panel ad-timeline-card" aria-labelledby="ad-timeline-title">
            <h2 className="ad-decision-title" id="ad-timeline-title">{live ? 'Timeline' : 'What happened'}</h2>
            <ol className="ad-timeline">
              {timeline.map((t) => (
                <li key={`${t.title}-${t.at}`} className={`ad-timeline-item is-${t.tone}`}>
                  <span className="ad-timeline-time">{clockS(t.at)}</span>
                  <span className="ad-timeline-title">{t.title}</span>
                  {t.sub && <span className="ad-timeline-sub">{t.sub}</span>}
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>

      <section className="ad-board-section" aria-labelledby="ad-evidence-title">
        <div className="ad-section-head">
          <h2 className="ad-section-title" id="ad-evidence-title">Reports in this Area</h2>
          <span className="ad-section-meta">{evidence.length}</span>
        </div>
        {evidence.length === 0 ? (
          <p className="ad-empty-line">No member reports.</p>
        ) : (
          <ul className="ad-evidence">
            {evidence.map((r) => (
              <li key={r.id} className="ad-evidence-item">
                {r.photo_url
                  ? (
                    <ZoomablePhoto
                      src={r.photo_url}
                      alt={`the scene reported by ${r.reporter_name || 'a resident'}`}
                      caption={`${r.reporter_name || 'A resident'} · ${clock(r.created_at)} · ${d.designation}`}
                      imageClassName="ad-evidence-photo"
                    />
                  )
                  : <span className="ad-evidence-photo is-missing">No photo</span>}
                <span className="ad-cell-text">
                  <span className="ad-cell-title">{r.reporter_name || 'Unnamed reporter'}</span>
                  <span className="ad-cell-meta">
                    {clock(r.created_at)} · {r.user_verified_percent ?? 0}% verified
                    {r.gps_discrepancy_flag ? ' · photo GPS disagrees with the phone' : ''}
                    {!r.has_exif ? ' · no photo GPS' : ''}
                  </span>
                  <span className="ad-cell-meta"><Place lat={r.device_lat} lng={r.device_lng} /></span>
                  {r.notes && <span className="ad-evidence-note">“{r.notes}”</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={confirming}
        eyebrow={`${d.designation} · asked for ${agenciesOf(d)}`}
        title={`Acknowledge ${d.designation}?`}
        description="Your organisation commits to go and check. The Area moves to Acknowledged; nobody is dispatched by this."
        confirmLabel="Acknowledge"
        onClose={onCancelAcknowledge}
        onConfirm={onConfirmAcknowledge}
      />
    </div>
  );
}
