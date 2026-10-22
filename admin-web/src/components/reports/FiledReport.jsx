import { AGENCY_LABEL } from '../../lib/status.js';

/* One filed Post-Incident Report, read only (REPLIT (MAIN) 10 · A61
 * 878:8354): when it happened, the unit and crew that went, and what the
 * captain wrote. The design's scene profile — fire type, smoke colour,
 * signs, water used, backup — is not on the server's report yet, so those
 * rows are not drawn. Reports cannot be edited after they are sent. */

const CLOCK = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
});
const time = (iso) => (iso ? CLOCK.format(new Date(iso)) : 'Not recorded');

const ROLE = { admin: 'Admin', sub_admin: 'Coordinator', response_team: 'Responder', general_user: 'Citizen' };

function Facts({ rows }) {
  return (
    <dl className="ad-facts ad-facts--wide">
      {rows.map(([t, v]) => (
        <div className="ad-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

export default function FiledReport({ report: r }) {
  const units = r.units?.length ? r.units : (r.truck_label ? [{ name: r.truck_label, type: r.truck_type }] : []);
  const crew = (r.roster ?? []).map((m) => m.name || m.full_name).filter(Boolean);
  const scene = [
    ['Outcome', r.false_alarm ? 'False alarm — no fire found' : 'Fire responded to'],
    ['Incident time', time(r.incident_at)],
    ['Fire out', time(r.fire_out_at || r.resolved_at)],
    ['Filed by', `${r.filed_by_name || 'Name not recorded'} · ${ROLE[r.filed_by_role] ?? r.filed_by_role ?? '—'}`],
    ['Agency', AGENCY_LABEL[r.filed_by_agency] ?? r.filed_by_agency ?? 'Not recorded'],
  ];
  const team = [
    ['Truck', units.length ? units.map((u) => [u.name, u.type].filter(Boolean).join(' · ')).join(', ') : 'Not recorded'],
    ['Driver', r.driver_name || 'Not recorded'],
    ['Crew', crew.length ? crew.join(', ') : 'Not recorded'],
    ['Equipment taken', r.equipment_taken?.length ? r.equipment_taken.join(', ') : 'None recorded'],
  ];
  const narrative = r.false_alarm ? (r.false_alarm_note || r.notes) : r.notes;

  return (
    <div className="ad-stack">
      <div className="ad-report-grid">
        <section className="ad-panel" aria-labelledby={`ad-scene-${r.id}`}>
          <h3 className="ad-decision-title" id={`ad-scene-${r.id}`}>Scene</h3>
          <Facts rows={scene} />
        </section>
        <section className="ad-panel" aria-labelledby={`ad-crew-${r.id}`}>
          <h3 className="ad-decision-title" id={`ad-crew-${r.id}`}>Unit and crew</h3>
          <Facts rows={team} />
        </section>
      </div>
      <section className="ad-panel" aria-labelledby={`ad-narrative-${r.id}`}>
        <h3 className="ad-decision-title" id={`ad-narrative-${r.id}`}>{r.false_alarm ? 'What the team found' : 'Narrative'}</h3>
        <p className="ad-decision-body ad-report-narrative">{narrative || 'The team wrote no narrative.'}</p>
      </section>
    </div>
  );
}
