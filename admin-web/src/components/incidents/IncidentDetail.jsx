import { PERM, acknowledgedByUs, actsOn, can, routedWord } from '../../lib/access.js';
import { AGENCY_LABEL, OFF_FEED, alarmLabel, statusOf } from '../../lib/status.js';
import Place from '../Place.jsx';
import { ConfirmDialog } from '../ui/index.js';
import ZoomablePhoto from '../ui/ZoomablePhoto.jsx';
import AreaMap from './AreaMap.jsx';
import { agenciesOf, confidenceOf } from './IncidentTable.jsx';
import LifecycleChip from './LifecycleChip.jsx';
import LifecycleProgress from './LifecycleProgress.jsx';

/* One Area, in full (REPLIT (MAIN) 10 · A23 867:2193, A24 867:2419, A24b
 * 867:2662, A25 867:2909, A26 868:2888): the map and its progress with the
 * facts, beside the decision this organisation can take and the timeline.
 *
 * What this Admin may do comes from `access` (lib/access.js; the server
 * checks it again): acknowledge an Area routed to its organisation — first,
 * or adding its organisation to one already acknowledged — or follow one
 * routed elsewhere, view only (A25), without the reporters' details. A Fire
 * Volunteer Admin may ask BFP to raise the alarm on scene (A45).
 *
 * What is drawn is what the server returns, with the street looked up by
 * the console beside the degrees (components/Place.jsx) until the server
 * stores it. Left out until it serves them: the fire type, the safety roll
 * call and help alerts (A26), and Admin-to-Admin water and backup requests. */

const CLOCK = new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit' });
const CLOCK_S = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', hour: 'numeric', minute: '2-digit', second: '2-digit',
});

const clock = (iso) => (iso ? CLOCK.format(new Date(iso)) : '—');
const clockS = (iso) => (iso ? CLOCK_S.format(new Date(iso)) : '—');

const ON_SCENE = ['en_route', 'arrived'];

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
  // Every organisation that acknowledged after the first.
  (d.acceptances ?? []).filter((a) => !a.is_first).forEach((a) => push(
    a.accepted_at,
    `${a.organization_name || (a.agency ? AGENCY_LABEL[a.agency] ?? a.agency : 'Admin')} acknowledged too`,
    a.user_name || null,
    'neutral',
  ));
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

/* Who acknowledged first, for the "add your organisation" card. */
function firstAcknowledger(d) {
  const first = (d.acceptances ?? []).find((a) => a.is_first);
  return first?.organization_name || d.verified_by_organization
    || (d.verified_by_agency ? AGENCY_LABEL[d.verified_by_agency] : null) || 'Another organisation';
}

/* Our own acknowledgement, for the Acknowledged card. */
function ourAcknowledgement(d, access) {
  const orgId = access?.organization?.id;
  if (!orgId) return null;
  return (d.acceptances ?? []).find((a) => a.organization_id === orgId) ?? null;
}

/* A25: an Area routed to other organisations. */
function ViewOnly({ d, access, orgName }) {
  return (
    <section className="ad-panel ad-decision" aria-labelledby="ad-decision-title">
      <div className="ad-decision-head">
        <h2 className="ad-decision-title" id="ad-decision-title">{orgName}</h2>
        <LifecycleChip status={d.status} />
      </div>
      <div className="ad-alert ad-alert--info">
        <span className="ad-alert-mark" aria-hidden="true">i</span>
        <div className="ad-alert-text">
          <p className="ad-alert-title">View only</p>
          <p className="ad-alert-body">
            {d.designation} asked for {agenciesOf(d)}, not {routedWord(access)}. You can follow it
            here but can’t act on it or see who reported it.
          </p>
        </div>
      </div>
    </section>
  );
}

/* The decision card (A23 / A24b): what this Admin may do with the Area now. */
function Decision({ d, access, orgName, onAcknowledge, busy, acknowledgedNow }) {
  const status = d.status;
  const ours = acknowledgedByUs(access, d);
  if (!ours && status === 'reported') {
    return (
      <section className="ad-panel ad-decision" aria-labelledby="ad-decision-title">
        <div className="ad-decision-head">
          <h2 className="ad-decision-title" id="ad-decision-title">Acknowledge this Area</h2>
          <LifecycleChip status={status} />
        </div>
        <p className="ad-decision-body">
          {d.designation} asked for {agenciesOf(d)}. Acknowledging says {orgName} has seen it
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
  if (!ours) {
    return (
      <section className="ad-panel ad-decision" aria-labelledby="ad-decision-title">
        <div className="ad-decision-head">
          <h2 className="ad-decision-title" id="ad-decision-title">Acknowledge for {orgName}</h2>
          <LifecycleChip status={status} />
        </div>
        <p className="ad-decision-body">
          {firstAcknowledger(d)} acknowledged it first{d.verified_at ? ` at ${clock(d.verified_at)}` : ''}.
          {' '}It asked for {agenciesOf(d)} too: acknowledge so everyone sees {orgName} is on it. It sends nobody.
        </p>
        <button type="button" className="ad-button ad-button--primary" onClick={onAcknowledge} disabled={busy}>
          {busy ? 'Acknowledging…' : `Acknowledge for ${orgName}`}
        </button>
      </section>
    );
  }
  if (status === 'verified' || status === 'acknowledged') {
    const mine = ourAcknowledgement(d, access);
    const who = mine?.user_name ?? d.verified_by_name;
    const at = mine?.accepted_at ?? d.verified_at;
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
              Acknowledged{mine ? ` for ${orgName}` : ''}{who ? ` by ${who}` : ''} · {clock(at)}
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

/* On scene (A26): the units this Area has, any alarm escalation raised for
 * it, and — for a Fire Volunteer Admin — asking BFP to raise the alarm. */
function OnScene({ d, dispatches, requests, onAskAlarm }) {
  const active = (dispatches ?? []).filter((x) => x.status === 'active');
  const pending = requests.some((r) => r.status === 'pending');
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
      {onAskAlarm && (
        <button type="button" className="ad-button ad-button--secondary" onClick={onAskAlarm} disabled={pending}>
          {pending ? 'Waiting for BFP to answer' : 'Ask BFP to raise the alarm'}
        </button>
      )}
    </section>
  );
}

export default function IncidentDetail({
  detail: d, evidence, dispatches, requests, reports,
  access, orgName = 'your organisation',
  busy, error, confirming, acknowledgedNow,
  onAskAcknowledge, onCancelAcknowledge, onConfirmAcknowledge, onBack, onPdf, onAskAlarm,
}) {
  const live = !OFF_FEED.includes(d.status);
  const onScene = ON_SCENE.includes(d.status);
  const routed = actsOn(access, d);
  const canAct = routed && can(access, PERM.ACKNOWLEDGE);
  const ours = acknowledgedByUs(access, d);
  const mayAskAlarm = canAct && onScene && can(access, PERM.REQUEST_ALARM) && Boolean(onAskAlarm);
  const firstReport = (evidence ?? [])[0];
  const active = (dispatches ?? []).filter((x) => x.status === 'active');
  const facts = [
    ['Requested agencies', agenciesOf(d)],
    ['Confidence', `${confidenceOf(d)} (${d.report_count} report${d.report_count === 1 ? '' : 's'})`],
    ...(d.alarm_level ? [['Alarm level', `${alarmLabel(d.alarm_level)}${d.alarm_level_set_at ? ' · set by BFP' : ''}`]] : []),
    ...(onScene && routed ? [['Units', active.length ? active.map((x) => x.vehicle_name || x.responder_name).join(' · ') : 'None assigned']] : []),
    ['Location', <Place lat={d.centroid_lat} lng={d.centroid_lng} stacked />],
    ['First report', `${clock(d.reported_at)}${firstReport ? ` · ${firstReport.user_verified_percent ?? 0}% verified reporter` : ''}`],
    ['Organisations involved', involved(d)],
  ];
  const timeline = timelineOf(d, evidence);
  const sub = [
    d.arrived_at ? `Arrived ${clock(d.arrived_at)}` : `First report ${clock(d.reported_at)}`,
    `${d.report_count} report${d.report_count === 1 ? '' : 's'}`,
  ].join(' · ');
  const eyebrow = routed
    ? `${d.designation} · ${statusOf(d.status).label}`
    : `${d.designation} · ${statusOf(d.status).label} · not routed to ${orgName}`;

  return (
    <div className="ad-page ad-incident">
      <button type="button" className="ad-text-button ad-back" onClick={onBack}>
        ← All incidents
      </button>
      <header className="web-page-header">
        <div className="web-page-header-copy">
          <p className="web-eyebrow">{eyebrow}</p>
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
          {!canAct ? (
            live && <ViewOnly d={d} access={access} orgName={orgName} />
          ) : (
            <>
              {live && (!onScene || !ours) && (
                <Decision
                  d={d}
                  access={access}
                  orgName={orgName}
                  busy={busy}
                  acknowledgedNow={acknowledgedNow}
                  onAcknowledge={onAskAcknowledge}
                />
              )}
              {onScene && (
                <OnScene
                  d={d}
                  dispatches={dispatches}
                  requests={requests}
                  onAskAlarm={mayAskAlarm ? onAskAlarm : null}
                />
              )}
            </>
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

      {/* Who reported, their photos and where they stood are for the
          organisations the Area asked for (A25). */}
      {routed && (
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
      )}

      <ConfirmDialog
        open={confirming}
        eyebrow={`${d.designation} · asked for ${agenciesOf(d)}`}
        title={d.status === 'reported' ? `Acknowledge ${d.designation}?` : `Acknowledge ${d.designation} for ${orgName}?`}
        description={d.status === 'reported'
          ? `${orgName} commits to go and check. The Area moves to Acknowledged; nobody is dispatched by this.`
          : `It is already acknowledged; this adds ${orgName}. Nobody is dispatched by this.`}
        confirmLabel="Acknowledge"
        onClose={onCancelAcknowledge}
        onConfirm={onConfirmAcknowledge}
      />
    </div>
  );
}
