import { PERM, acknowledgedByUs, actsOn, can, routedWord } from '../../lib/access.js';
import { AGENCY_LABEL, OFF_FEED, alarmLabel, statusOf } from '../../lib/status.js';
import Place from '../Place.jsx';
import { ConfirmDialog } from '../ui/index.js';
import ZoomablePhoto from '../ui/ZoomablePhoto.jsx';
import AreaMap from './AreaMap.jsx';
import { agenciesOf, confidenceOf } from './IncidentTable.jsx';
import LifecycleChip from './LifecycleChip.jsx';
import LifecycleProgress from './LifecycleProgress.jsx';
import { t } from '../../i18n/i18n.jsx';

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
  push(d.reported_at, t('{area} created', { area: d.designation }), <>{t('First report,')}{' '}<Place lat={d.centroid_lat} lng={d.centroid_lng} /></>, 'live');
  const later = (evidence ?? []).slice(1);
  if (later.length) {
    const last = later.reduce((a, r) => (new Date(r.created_at) > new Date(a.created_at) ? r : a), later[0]);
    push(last.created_at, (later.length === 1
      ? t('{count} more report clustered', { count: later.length })
      : t('{count} more reports clustered', { count: later.length })), t('Joined the first report’s Area'), 'neutral');
  }
  push(
    d.verified_at,
    d.verified_by_name ? t('Acknowledged by {name}', { name: d.verified_by_name }) : t('Acknowledged'),
    [d.verified_by_agency ? AGENCY_LABEL[d.verified_by_agency] ?? d.verified_by_agency : t('Admin'), d.verified_by_organization].filter(Boolean).join(' · '),
    'accent',
  );
  // Every organisation that acknowledged after the first.
  (d.acceptances ?? []).filter((a) => !a.is_first).forEach((a) => push(
    a.accepted_at,
    t('{who} acknowledged too', { who: a.organization_name || (a.agency ? AGENCY_LABEL[a.agency] ?? a.agency : t('Admin')) }),
    a.user_name || null,
    'neutral',
  ));
  push(d.en_route_at, t('A unit set off'), t('The Area went En route'), 'live');
  push(d.arrived_at, t('Arrived on scene'), t('The first unit reached the Area'), 'live');
  push(d.alarm_level_set_at, t('Alarm set to {alarmLabel}', { alarmLabel: alarmLabel(d.alarm_level) }), t('Set by BFP'), 'live');
  push(d.resolved_at, t('Fire out'), d.resolved_by_name ? t('Marked by {resolved_by_name}', { resolved_by_name: d.resolved_by_name }) : t('Marked on scene'), 'ok');
  push(d.closed_at, t('Closed'), t('Post-incident report filed'), 'neutral');
  push(d.rejected_at, t('Rejected'), d.rejection_reason || (d.rejected_by_name ? t('By {rejected_by_name}', { rejected_by_name: d.rejected_by_name }) : ''), 'neutral');
  push(d.merged_at, t('Merged'), d.merged_by_name ? t('By {merged_by_name}', { merged_by_name: d.merged_by_name }) : t('Into another Area'), 'neutral');
  return items.sort((a, b) => new Date(b.at) - new Date(a.at));
}

function Facts({ rows }) {
  return (
    <dl className="rpl-facts rpl-facts--wide">
      {rows.map(([term, value]) => (
        <div className="rpl-fact" key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function involved(d) {
  const names = (d.acceptances ?? []).map((a) => a.organization_name || (a.agency ? AGENCY_LABEL[a.agency] ?? a.agency : t('Admin')));
  return names.length ? [...new Set(names)].join(' · ') : t('None yet');
}

/* Who acknowledged first, for the "add your organisation" card. */
function firstAcknowledger(d) {
  const first = (d.acceptances ?? []).find((a) => a.is_first);
  return first?.organization_name || d.verified_by_organization
    || (d.verified_by_agency ? AGENCY_LABEL[d.verified_by_agency] : null) || t('Another organization');
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
    <section className="rpl-panel rpl-decision" aria-labelledby="rpl-decision-title">
      <div className="rpl-decision-head">
        <h2 className="rpl-decision-title" id="rpl-decision-title">{orgName}</h2>
        <LifecycleChip status={d.status} />
      </div>
      <div className="rpl-alert rpl-alert--info">
        <span className="rpl-alert-mark" aria-hidden="true">i</span>
        <div className="rpl-alert-text">
          <p className="rpl-alert-title">{t('View only')}</p>
          <p className="rpl-alert-body">
            {t('{area} asked for {agencies}, not {routed}. You can follow it here but can’t act on it or see who reported it.', { area: d.designation, agencies: agenciesOf(d), routed: routedWord(access) })}</p>
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
      <section className="rpl-panel rpl-decision" aria-labelledby="rpl-decision-title">
        <div className="rpl-decision-head">
          <h2 className="rpl-decision-title" id="rpl-decision-title">{t('Acknowledge this Area')}</h2>
          <LifecycleChip status={status} />
        </div>
        <p className="rpl-decision-body">
          {t('{area} asked for {agencies}. Acknowledging says {org} has seen it and will check. It sends nobody: Coordinators decide who goes.', { area: d.designation, agencies: agenciesOf(d), org: orgName })}</p>
        <button type="button" className="rpl-button rpl-button--primary rpl-button--run" onClick={onAcknowledge} disabled={busy}>
          {busy ? t('Acknowledging…') : t('Acknowledge')}
        </button>
        <p className="rpl-decision-note">{t('Opening this page stopped the sound. It didn’t acknowledge the incident.')}</p>
      </section>
    );
  }
  if (!ours) {
    return (
      <section className="rpl-panel rpl-decision" aria-labelledby="rpl-decision-title">
        <div className="rpl-decision-head">
          <h2 className="rpl-decision-title" id="rpl-decision-title">{t('Acknowledge for {org}', { org: orgName })}</h2>
          <LifecycleChip status={status} />
        </div>
        <p className="rpl-decision-body">
          {d.verified_at
                ? t('{who} acknowledged it first at {time}.', { who: firstAcknowledger(d), time: clock(d.verified_at) })
                : t('{who} acknowledged it first.', { who: firstAcknowledger(d) })}
          {' '}{t('It asked for {agencies} too: acknowledge so everyone sees {org} is on it. It sends nobody.', { agencies: agenciesOf(d), org: orgName })}</p>
        <button type="button" className="rpl-button rpl-button--primary" onClick={onAcknowledge} disabled={busy}>
          {busy ? t('Acknowledging…') : t('Acknowledge for {orgName}', { orgName })}
        </button>
      </section>
    );
  }
  if (status === 'verified' || status === 'acknowledged') {
    const mine = ourAcknowledgement(d, access);
    const who = mine?.user_name ?? d.verified_by_name;
    const at = mine?.accepted_at ?? d.verified_at;
    return (
      <section className="rpl-panel rpl-decision" aria-labelledby="rpl-decision-title">
        <div className="rpl-decision-head">
          <h2 className="rpl-decision-title" id="rpl-decision-title">{t('Acknowledged')}</h2>
          <LifecycleChip status={status} />
        </div>
        <div className="rpl-success" role={acknowledgedNow ? 'status' : undefined}>
          <span className="rpl-success-check" aria-hidden="true">✓</span>
          <div>
            <p className="rpl-success-title">{mine
                ? (who ? t('Acknowledged for {org} by {name}', { org: orgName, name: who }) : t('Acknowledged for {org}', { org: orgName }))
                : (who ? t('Acknowledged by {name}', { name: who }) : t('Acknowledged'))} · {clock(at)}
            </p>
            <p className="rpl-success-body">{t('Coordinators and Responders can see it. It moves to En route when a unit sets off.')}</p>
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
    <section className="rpl-panel rpl-decision" aria-labelledby="rpl-onscene-title">
      <div className="rpl-decision-head">
        <h2 className="rpl-decision-title" id="rpl-onscene-title">{t('On scene')}</h2>
        <LifecycleChip status={d.status} />
      </div>
      {active.length === 0 ? (
        <p className="rpl-decision-body">{t('No unit is assigned to this Area right now.')}</p>
      ) : (
        <ul className="rpl-units">
          {active.map((x) => (
            <li key={x.id}>
              <span className="rpl-cell-title">{x.vehicle_name || x.responder_name || t('A responder')}</span>
              <span className="rpl-cell-meta">
                {[x.responder_name && x.vehicle_name ? x.responder_name : null, x.crew_role, t('since {time}', { time: clock(x.dispatched_at) })].filter(Boolean).join(' · ')}
              </span>
            </li>
          ))}
        </ul>
      )}
      {requests.map((r) => (
        <div className="rpl-request-line" key={r.id}>
          <span className="rpl-cell-title">{t('Alarm escalation ·')}{' '}{alarmLabel(r.requested_alarm_level)}
          </span>
          <span className="rpl-cell-meta">
            {r.requested_by_name ? t('From {requested_by_name} · ', { requested_by_name: r.requested_by_name }) : ''}{clock(r.created_at)} · {r.status === 'pending' ? t('waiting for BFP') : r.status}
          </span>
        </div>
      ))}
      {onAskAlarm && (
        <button type="button" className="rpl-button rpl-button--secondary" onClick={onAskAlarm} disabled={pending}>
          {pending ? t('Waiting for BFP to answer') : t('Ask BFP to raise the alarm')}
        </button>
      )}
    </section>
  );
}

export default function IncidentDetail({
  detail: d, evidence, dispatches, requests, reports,
  access, orgName = 'your organization',
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
    [t('Requested agencies'), agenciesOf(d)],
    [t('Confidence'), d.report_count === 1
      ? t('{confidence} ({count} report)', { confidence: confidenceOf(d), count: d.report_count })
      : t('{confidence} ({count} reports)', { confidence: confidenceOf(d), count: d.report_count })],
    ...(d.alarm_level ? [[t('Alarm level'), `${alarmLabel(d.alarm_level)}${d.alarm_level_set_at ? ' · set by BFP' : ''}`]] : []),
    ...(onScene && routed ? [[t('Units'), active.length ? active.map((x) => x.vehicle_name || x.responder_name).join(' · ') : t('None assigned')]] : []),
    [t('Location'), <Place lat={d.centroid_lat} lng={d.centroid_lng} stacked />],
    [t('First report'), `${clock(d.reported_at)}${firstReport ? t(' · {percent}% verified reporter', { percent: firstReport.user_verified_percent ?? 0 }) : ''}`],
    [t('Organizations involved'), involved(d)],
  ];
  const timeline = timelineOf(d, evidence);
  const sub = [
    d.arrived_at ? t('Arrived {clock}', { clock: clock(d.arrived_at) }) : t('First report {clock}', { clock: clock(d.reported_at) }),
    d.report_count === 1 ? t('{count} report', { count: d.report_count }) : t('{count} reports', { count: d.report_count }),
  ].join(' · ');
  const eyebrow = routed
    ? `${d.designation} · ${statusOf(d.status).label}`
    : t('{designation} · {label} · not routed to {orgName}', { designation: d.designation, label: statusOf(d.status).label, orgName });

  return (
    <div className="rpl-page rpl-incident">
      <button type="button" className="rpl-text-button rpl-back" onClick={onBack}>{t('← All incidents')}</button>
      <header className="web-page-header">
        <div className="web-page-header-copy">
          <p className="web-eyebrow">{eyebrow}</p>
          <h1 className="web-page-title">{d.designation}</h1>
          <p className="web-page-description">{sub}</p>
        </div>
      </header>

      {error && <p className="rpl-inline-error" role="alert">{error}</p>}

      <div className="rpl-incident-grid">
        <div className="rpl-incident-main">
          <AreaMap lat={d.centroid_lat} lng={d.centroid_lng} label={d.designation} />
          <section className="rpl-panel">
            <LifecycleProgress status={d.status} />
            <Facts rows={facts} />
          </section>
        </div>

        <div className="rpl-incident-side">
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
            <section className="rpl-panel rpl-decision" aria-labelledby="rpl-pir-title">
              <div className="rpl-decision-head">
                <h2 className="rpl-decision-title" id="rpl-pir-title">{t('Post-incident report')}</h2>
                <LifecycleChip status={d.status} />
              </div>
              <p className="rpl-decision-body">
                {reports.length === 0
                  ? t('Fire out. Waiting on the responding team captain’s report; the Area closes when it is filed.')
                  : (reports.length === 1
                    ? t('{count} team filed. Read them in Reports & CIAR, or download the record.', { count: reports.length })
                    : t('{count} teams filed. Read them in Reports & CIAR, or download the record.', { count: reports.length }))}
              </p>
              {reports.length > 0 && (
                <button type="button" className="rpl-button rpl-button--secondary" onClick={onPdf} disabled={busy}>{t('Download report (PDF)')}</button>
              )}
            </section>
          )}

          <section className="rpl-panel rpl-timeline-card" aria-labelledby="rpl-timeline-title">
            <h2 className="rpl-decision-title" id="rpl-timeline-title">{live ? t('Timeline') : t('What happened')}</h2>
            <ol className="rpl-timeline">
              {timeline.map((t) => (
                <li key={`${t.title}-${t.at}`} className={`rpl-timeline-item is-${t.tone}`}>
                  <span className="rpl-timeline-time">{clockS(t.at)}</span>
                  <span className="rpl-timeline-title">{t.title}</span>
                  {t.sub && <span className="rpl-timeline-sub">{t.sub}</span>}
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>

      {/* Who reported, their photos and where they stood are for the
          organizations the Area asked for (A25). */}
      {routed && (
        <section className="rpl-board-section" aria-labelledby="rpl-evidence-title">
          <div className="rpl-section-head">
            <h2 className="rpl-section-title" id="rpl-evidence-title">{t('Reports in this Area')}</h2>
            <span className="rpl-section-meta">{evidence.length}</span>
          </div>
          {evidence.length === 0 ? (
            <p className="rpl-empty-line">{t('No member reports.')}</p>
          ) : (
            <ul className="rpl-evidence">
              {evidence.map((r) => (
                <li key={r.id} className="rpl-evidence-item">
                  {r.photo_url
                    ? (
                      <ZoomablePhoto
                        src={r.photo_url}
                        alt={t('the scene reported by {name}', { name: r.reporter_name || t('a resident') })}
                        caption={`${r.reporter_name || t('A resident')} · ${clock(r.created_at)} · ${d.designation}`}
                        imageClassName="rpl-evidence-photo"
                      />
                    )
                    : <span className="rpl-evidence-photo is-missing">{t('No photo')}</span>}
                  <span className="rpl-cell-text">
                    <span className="rpl-cell-title">{r.reporter_name || t('Unnamed reporter')}</span>
                    <span className="rpl-cell-meta">
                      {clock(r.created_at)} · {r.user_verified_percent ?? 0}{t('% verified')}{r.gps_discrepancy_flag ? t(' · photo GPS disagrees with the phone') : ''}
                      {!r.has_exif ? t(' · no photo GPS') : ''}
                    </span>
                    <span className="rpl-cell-meta"><Place lat={r.device_lat} lng={r.device_lng} /></span>
                    {r.notes && <span className="rpl-evidence-note">“{r.notes}”</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <ConfirmDialog
        open={confirming}
        eyebrow={t('{designation} · asked for {agenciesOf}', { designation: d.designation, agenciesOf: agenciesOf(d) })}
        title={d.status === 'reported' ? t('Acknowledge {designation}?', { designation: d.designation }) : t('Acknowledge {designation} for {orgName}?', { designation: d.designation, orgName })}
        description={d.status === 'reported'
          ? t('{orgName} commits to go and check. The Area moves to Acknowledged; nobody is dispatched by this.', { orgName })
          : t('It is already acknowledged; this adds {orgName}. Nobody is dispatched by this.', { orgName })}
        confirmLabel={t('Acknowledge')}
        onClose={onCancelAcknowledge}
        onConfirm={onConfirmAcknowledge}
      />
    </div>
  );
}
