import { AGENCY_LABEL } from '../../lib/status.js';
import { t } from '../../i18n/i18n.jsx';

/* One filed Post-Incident Report, read only (REPLIT (MAIN) 10 · A61
 * 878:8354): when it happened, the unit and crew that went, and what the
 * captain wrote. The design's scene profile — fire type, smoke colour,
 * signs, water used, backup — is not on the server's report yet, so those
 * rows are not drawn. Reports cannot be edited after they are sent. */

const CLOCK = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
});
const time = (iso) => (iso ? CLOCK.format(new Date(iso)) : t('Not recorded'));

const ROLE = { get admin() { return t('Admin'); }, get sub_admin() { return t('Coordinator'); }, get response_team() { return t('Responder'); }, get general_user() { return t('Citizen'); } };

function Facts({ rows }) {
  return (
    <dl className="rpl-facts rpl-facts--wide">
      {rows.map(([t, v]) => (
        <div className="rpl-fact" key={t}><dt>{t}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

export default function FiledReport({ report: r }) {
  const units = r.units?.length ? r.units : (r.truck_label ? [{ name: r.truck_label, type: r.truck_type }] : []);
  const crew = (r.roster ?? []).map((m) => m.name || m.full_name).filter(Boolean);
  const scene = [
    [t('Outcome'), r.false_alarm ? t('False alarm — no fire found') : t('Fire responded to')],
    [t('Incident time'), time(r.incident_at)],
    [t('Fire out'), time(r.fire_out_at || r.resolved_at)],
    [t('Filed by'), `${r.filed_by_name || t('Name not recorded')} · ${ROLE[r.filed_by_role] ?? r.filed_by_role ?? '—'}`],
    [t('Agency'), AGENCY_LABEL[r.filed_by_agency] ?? r.filed_by_agency ?? t('Not recorded')],
  ];
  const team = [
    [t('Truck'), units.length ? units.map((u) => [u.name, u.type].filter(Boolean).join(' · ')).join(', ') : t('Not recorded')],
    [t('Driver'), r.driver_name || t('Not recorded')],
    [t('Crew'), crew.length ? crew.join(', ') : t('Not recorded')],
    [t('Equipment taken'), r.equipment_taken?.length ? r.equipment_taken.join(', ') : t('None recorded')],
  ];
  const narrative = r.false_alarm ? (r.false_alarm_note || r.notes) : r.notes;

  return (
    <div className="rpl-stack">
      <div className="rpl-report-grid">
        <section className="rpl-panel" aria-labelledby={`rpl-scene-${r.id}`}>
          <h3 className="rpl-decision-title" id={`rpl-scene-${r.id}`}>{t('Scene')}</h3>
          <Facts rows={scene} />
        </section>
        <section className="rpl-panel" aria-labelledby={`rpl-crew-${r.id}`}>
          <h3 className="rpl-decision-title" id={`rpl-crew-${r.id}`}>{t('Unit and crew')}</h3>
          <Facts rows={team} />
        </section>
      </div>
      <section className="rpl-panel" aria-labelledby={`rpl-narrative-${r.id}`}>
        <h3 className="rpl-decision-title" id={`rpl-narrative-${r.id}`}>{r.false_alarm ? t('What the team found') : t('Narrative')}</h3>
        <p className="rpl-decision-body rpl-report-narrative">{narrative || t('The team wrote no narrative.')}</p>
      </section>
    </div>
  );
}
