import React from 'react';
import { createRoot } from 'react-dom/client';

import { BASE } from '../src/api/client.js';
import { AuthContext } from '../src/auth.jsx';
import Dashboard from '../src/pages/Dashboard.jsx';
import '../src/index.css';
import '../src/styles/pass6.css';
import '../src/styles/pass6-pages.css';
import '../src/styles/pass6-existing.css';
import '../src/styles/pass6-incidents.css';
import '../src/styles/pass6-map.css';
import '../src/styles/pass6-access.css';

/* DEVELOPMENT PREVIEW ONLY — the whole console, signed in as a fictional
 * Admin, on fictional data. Every request the console makes to the API base
 * is answered here in memory; nothing reaches a server, the stored session is
 * never read or written, and a "delete" only removes the row from this page.
 * Open http://localhost:5173/docs/console-preview.html on the Vite dev server.
 * Not part of the production build (vite builds index.html only).
 *
 * ?as= picks which organisation's Admin is signed in (A00 permission
 * variants): central (the default), police, medical, barangay,
 * fire_volunteer, bfp, or system. */

if (import.meta.env.DEV) {
  const at = (minutesAgo) => new Date(Date.now() - minutesAgo * 60000).toISOString();
  const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

  const incident = (n, designation, status, minutes, extra = {}) => ({
    id: id(100 + n),
    designation,
    status,
    centroid_lat: 14.5378 + n * 0.0021,
    centroid_lng: 121.0014 - n * 0.0017,
    report_count: 2 + n,
    confidence_score: 0.38 + n * 0.08,
    confidence_band: n > 2 ? 'high' : n > 0 ? 'medium' : 'low',
    alarm_level: null,
    active_dispatch_count: status === 'en_route' || status === 'arrived' ? 1 : 0,
    reported_at: at(minutes),
    updated_at: at(Math.max(0, minutes - 2)),
    requested_agencies: n % 2 ? ['fire_volunteer', 'medical'] : ['fire_volunteer'],
    routed_agencies: ['fire_volunteer'],
    accepted_agencies: status === 'reported' ? [] : ['fire_volunteer'],
    route_count: 1,
    ...extra,
  });

  // A drawn stand-in for an uploaded photo; no real document is shown.
  const placeholder = (label) => `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="300"><rect width="480" height="300" rx="16" fill="#2a2a2a"/><text x="240" y="160" fill="#a1a1a1" font-family="sans-serif" font-size="22" text-anchor="middle">${label}</text></svg>`,
  )}`;

  // Which Admin is signed in, as the server would describe it on /auth/me.
  const EVERY = ['incidents.acknowledge', 'incidents.overlaps', 'water.delete', 'accounts.coordinators'];
  const ORGS = {
    central: { id: id(10), name: 'Example Barangay Hub', agency: 'barangay', hub: true },
    barangay: { id: id(15), name: 'Example Barangay Office', agency: 'barangay' },
    fire_volunteer: { id: id(11), name: 'Example Fire Volunteers', agency: 'fire_volunteer' },
    bfp: { id: id(13), name: 'Example BFP Station', agency: 'bfp' },
    police: { id: id(12), name: 'Example Police Station', agency: 'police' },
    medical: { id: id(14), name: 'Example Medical Team', agency: 'medical' },
  };
  const as = new URLSearchParams(window.location.search).get('as') || 'central';
  const signedIn = ORGS[as] ?? null;
  const consoleFor = () => {
    if (!signedIn) {
      return {
        variant: 'system', scope: 'system', organization: null, act_agencies: null,
        permissions: [...EVERY, 'incidents.coordinate', 'affiliates.review', 'verifications.review',
          'map.manage', 'accounts.any', 'organizations.all', 'records.all'],
      };
    }
    const fire = ['fire_volunteer', 'bfp'].includes(signedIn.agency);
    return {
      variant: signedIn.hub ? 'central' : signedIn.agency,
      scope: signedIn.hub ? 'central' : 'organization',
      organization: { id: signedIn.id, name: signedIn.name, agency_type: signedIn.agency, is_central_hub: Boolean(signedIn.hub) },
      act_agencies: fire ? ['fire_volunteer', 'bfp'] : [signedIn.agency],
      permissions: [
        ...EVERY,
        ...(signedIn.agency === 'fire_volunteer' ? ['alarm.request'] : []),
        ...(signedIn.agency === 'bfp' ? ['alarm.decide'] : []),
        ...(signedIn.hub ? ['affiliates.review', 'verifications.review', 'organizations.all'] : []),
      ],
    };
  };

  const fixtures = {
    me: {
      id: id(1),
      email: 'example.admin@example.test',
      full_name: 'Example Admin',
      role: 'admin',
      agency_type: null,
      primary_org_id: signedIn?.id ?? null,
      console: consoleFor(),
    },
    incidents: [
      incident(0, 'Example Area 1.2', 'reported', 3, { requested_agencies: ['fire_volunteer', 'police'] }),
      incident(1, 'Example Area 2.1', 'verified', 14, { accepted_organization_ids: [id(11)] }),
      incident(2, 'Example Area 3', 'en_route', 26, { requested_agencies: ['fire_volunteer', 'police', 'barangay'], accepted_agencies: ['fire_volunteer'], accepted_organization_ids: [id(11)] }),
      incident(3, 'Example Area 4.1', 'arrived', 41, { requested_agencies: ['bfp', 'medical'], accepted_agencies: ['bfp', 'medical'], accepted_organization_ids: [id(13), id(14)] }),
      incident(4, 'Example Area 1.3', 'reported', 1, { centroid_lat: 14.5384, centroid_lng: 121.0021, requested_agencies: ['medical'] }),
    ],
    organizations: [
      { id: id(10), name: 'Example Barangay Hub', agency_type: 'barangay', is_active: true, is_central_hub: true, personnel_count: 4, equipment_count: 1, address: 'Example Street, Sample Barangay', contact_email: 'hub@example.test', contact_phone: null, created_at: at(60 * 24 * 40) },
      { id: id(11), name: 'Example Fire Volunteers', agency_type: 'fire_volunteer', is_active: true, personnel_count: 9, equipment_count: 3 },
      { id: id(12), name: 'Example Police Station', agency_type: 'police', is_active: true, personnel_count: 3, equipment_count: 0, address: 'Sample Avenue, Example City', contact_email: 'police@example.test', contact_phone: null, created_at: at(60 * 24 * 30) },
      { id: id(13), name: 'Example BFP Station', agency_type: 'bfp', is_active: true, personnel_count: 2, equipment_count: 1 },
      { id: id(14), name: 'Example Medical Team', agency_type: 'medical', is_active: true, personnel_count: 2, equipment_count: 0 },
      { id: id(15), name: 'Example Barangay Office', agency_type: 'barangay', is_active: true, personnel_count: 1, equipment_count: 0 },
    ],
    hydrants: [
      { id: id(200), code: 'EX-074', latitude: 14.538, longitude: 121.0, address: 'Example Avenue corner Sample Street', bfp_status: 'operational', ground_truth_status: 'operational', ground_truth_at: at(180), effective_status: 'operational', source: 'manual', is_active: true, created_at: at(9000), updated_at: at(180) },
      { id: id(201), code: 'EX-091', latitude: 14.541, longitude: 121.004, address: 'Sample Road', bfp_status: 'unknown', ground_truth_status: null, ground_truth_at: null, effective_status: 'non_operational', source: 'manual', is_active: true, created_at: at(9000), updated_at: at(4000) },
    ],
    water: [
      { id: id(210), name: 'Example Creek', water_type: 'Creek', latitude: 14.535, longitude: 121.006, is_accessible: true, created_at: at(9000), updated_at: at(2000) },
    ],
    cisterns: [],
    alarmRequests: [
      { id: id(300), area_id: id(102), area_designation: 'Example Area 3', requested_by: id(2), requested_by_name: 'Example Captain', requested_alarm_level: 'second_alarm', justification: 'Fictional example: fire spreading to the next roof.', status: 'pending', created_at: at(20), updated_at: at(20) },
      { id: id(301), area_id: id(103), area_designation: 'Example Area 4.1', requested_by: id(3), requested_by_name: 'Example Lieutenant', requested_alarm_level: 'first_alarm', justification: null, status: 'approved', reviewed_by: id(4), reviewed_at: at(30), executed_at: at(30), review_notes: null, created_at: at(36), updated_at: at(30) },
      { id: id(302), area_id: id(109), area_designation: 'Example Area 9', requested_by: id(3), requested_by_name: 'Example Lieutenant', requested_alarm_level: 'third_alarm', justification: 'Fictional example: wind picking up.', status: 'rejected', reviewed_by: id(4), reviewed_at: at(1500), review_notes: 'Fictional example: contained at 1st alarm.', created_at: at(1510), updated_at: at(1500) },
    ],
    personnel: {
      [id(10)]: [
        { id: id(20), full_name: 'Example Coordinator', role: 'sub_admin', agency_type: 'barangay', verified_percent: 100, badge: 'green_check' },
        { id: id(21), full_name: 'Sample Responder', role: 'response_team', agency_type: 'barangay', verified_percent: 60, badge: 'light_green' },
      ],
      [id(11)]: [
        { id: id(22), full_name: 'Example Captain', role: 'sub_admin', agency_type: 'fire_volunteer', verified_percent: 85, badge: 'green' },
        { id: id(23), full_name: 'Example Lieutenant', role: 'response_team', agency_type: 'fire_volunteer', verified_percent: 40, badge: 'yellow' },
      ],
      [id(12)]: [
        { id: id(1), full_name: 'Example Admin', role: 'admin', agency_type: null, email: 'example.admin@example.test', is_active: true, created_at: at(60 * 24 * 30) },
        { id: id(24), full_name: 'Example Desk Officer', role: 'sub_admin', agency_type: 'police', email: 'desk.officer@example.test', title: 'Desk officer', is_active: true, created_at: at(60 * 24 * 12), created_by_name: 'Example Admin' },
        { id: id(25), full_name: 'Sample Patrol Lead', role: 'sub_admin', agency_type: 'police', email: 'patrol.lead@example.test', title: 'Patrol lead', is_active: false, created_at: at(60 * 24 * 20), created_by_name: 'Example Admin', deactivated_at: at(60 * 24 * 2) },
        { id: id(26), full_name: 'Example Patrol Officer', role: 'response_team', agency_type: 'police', email: 'patrol.officer@example.test', is_active: true, created_at: at(60 * 24 * 10), created_by_name: 'Example Desk Officer' },
      ],
    },
    equipment: [
      { id: id(30), organization_id: id(10), name: 'Example Rescue Van', category: 'vehicle', capacity_liters: null, status: 'available' },
      { id: id(31), organization_id: id(10), name: 'Example Water Tank', category: 'tanker', capacity_liters: 2000, status: 'in_use' },
    ],
    reports: [
      { id: id(700), area_id: id(105), area_designation: 'Example Area 5', resolved_at: at(200), incident_at: at(260), fire_out_at: at(205), filed_by: id(22), filed_by_name: 'Example Captain', filed_by_role: 'sub_admin', filed_by_agency: 'fire_volunteer', organization_id: id(11), organization_name: 'Example Fire Volunteers', units: [{ name: 'Example Tanker', type: 'Tanker' }], truck_label: 'Example Tanker', truck_type: 'Tanker', driver_name: 'Example Driver', roster: [{ name: 'Example Driver' }, { name: 'Example Lieutenant' }], equipment_taken: ['2 hoses', '1 nozzle'], notes: 'Fictional example: kitchen fire, contained to one room.', false_alarm: false, submitted_at: at(190) },
      { id: id(701), area_id: id(106), area_designation: 'Example Area 6', resolved_at: at(1500), incident_at: at(1520), fire_out_at: null, filed_by: id(22), filed_by_name: 'Example Captain', filed_by_role: 'sub_admin', filed_by_agency: 'fire_volunteer', organization_id: id(11), organization_name: 'Example Fire Volunteers', units: [], truck_label: 'Example Tanker', truck_type: 'Tanker', driver_name: 'Example Driver', roster: [], equipment_taken: [], notes: null, false_alarm: true, false_alarm_note: 'Fictional example: smoke from a grill, no fire.', submitted_at: at(1490) },
    ],
    summaries: {
      [id(105)]: [{ id: id(710), incident_id: id(105), summary_text: 'Fictional example summary.' + String.fromCharCode(10, 10) + 'One team responded; the fire was out within the hour.', generated_at: at(185) }],
    },
    verifications: [
      { id: id(600), user_id: id(60), email: 'resident@example.test', full_name: 'Example Resident', type: 'national_id', status: 'manual_review', provider: 'didit', submitted_at: at(130), id_image_url: placeholder('Example ID card'), selfie_image_url: null },
    ],
    affiliates: [
      { id: id(400), organization_name: 'Example Rescue Brigade', agency_type: 'fire_volunteer', status: 'pending', contact_name: 'Example Contact', contact_email: 'brigade@example.test', contact_phone: '0900 000 0000', address: 'Sample Street corner Example Avenue', details: { roster: [{ full_name: 'Example Member' }, { full_name: 'Sample Member' }], equipment: [], sec_certificate_name: null }, created_at: at(600), updated_at: at(600) },
      { id: id(401), organization_name: 'Example Fire Volunteers', agency_type: 'fire_volunteer', status: 'approved', organization_id: id(11), contact_name: 'Example Captain', contact_email: 'captain@example.test', reviewed_at: at(60 * 24 * 9), created_at: at(60 * 24 * 10), updated_at: at(60 * 24 * 9) },
    ],
    audit: [
      { id: id(800), actor_user_id: id(1), actor_role: 'admin', actor_agency: null, action: 'incident.accept', entity_type: 'area', entity_id: id(101), area_id: id(101), area_designation: 'Example Area 2.1', metadata: {}, created_at: at(12) },
      { id: id(801), actor_user_id: id(22), actor_role: 'sub_admin', actor_agency: 'fire_volunteer', action: 'report.post_incident_report', entity_type: 'post_incident_report', entity_id: id(700), area_id: id(105), area_designation: 'Example Area 5', metadata: {}, created_at: at(190) },
      { id: id(802), actor_user_id: null, actor_role: null, actor_agency: null, action: 'area.merged', entity_type: 'area', entity_id: id(107), area_id: id(107), area_designation: 'Example Area 7', metadata: { notes: 'Fictional example: merged into Example Area 6.' }, created_at: at(1600) },
    ],
    overlaps: [
      { id: id(500), area_a_id: id(100), area_b_id: id(104), area_a_designation: 'Example Area 1.2', area_b_designation: 'Example Area 1.3', distance_m: 82, expires_at: new Date(Date.now() + 110000).toISOString(), created_at: at(0) },
    ],
  };

  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!url.startsWith(BASE)) return realFetch(input, init);
    const { pathname, searchParams } = new URL(url);
    const method = (init.method || 'GET').toUpperCase();
    await new Promise((r) => setTimeout(r, 250));

    if (method === 'DELETE') {
      const match = pathname.match(/^\/map\/([a-z-]+)\/(.+)$/);
      if (match) {
        const key = { hydrants: 'hydrants', 'bodies-of-water': 'water', 'underground-cisterns': 'cisterns' }[match[1]];
        if (key) fixtures[key] = fixtures[key].filter((r) => r.id !== match[2]);
      }
      return new Response(null, { status: 204 });
    }
    // Simulated in this page only: an overlap decision.
    const decide = method === 'POST' && pathname.match(/^\/areas\/overlaps\/([^/]+)\/(merge|keep-separate)$/);
    if (decide) {
      const o = fixtures.overlaps.find((x) => x.id === decide[1]);
      fixtures.overlaps = fixtures.overlaps.filter((x) => x.id !== decide[1]);
      if (o && decide[2] === 'merge') fixtures.incidents = fixtures.incidents.filter((i) => i.id !== o.area_b_id);
      return json({ message: 'ok' });
    }
    // Simulated in this page only: Acknowledge moves the fictional Area on.
    const accept = method === 'POST' && pathname.match(/^\/incidents\/([^/]+)\/accept$/);
    if (accept) {
      const ours = fixtures.me.console?.organization;
      fixtures.incidents = fixtures.incidents.map((i) => (i.id === accept[1]
        ? {
          ...i,
          ...(i.status === 'reported' ? { status: 'verified', verified_at: new Date().toISOString(), verified_by_name: fixtures.me.full_name } : {}),
          accepted_agencies: ours ? [...new Set([...(i.accepted_agencies ?? []), ours.agency_type])] : i.accepted_agencies,
          accepted_organization_ids: ours ? [...new Set([...(i.accepted_organization_ids ?? []), ours.id])] : i.accepted_organization_ids,
          updated_at: new Date().toISOString(),
        }
        : i));
      return json({ ok: true });
    }
    // Simulated in this page only: an affiliate decision.
    const affiliate = method === 'POST' && pathname.match(/^\/affiliates\/([^/]+)\/(accept|reject)$/);
    if (affiliate) {
      const now = new Date().toISOString();
      fixtures.affiliates = fixtures.affiliates.map((a) => (a.id === affiliate[1]
        ? { ...a, status: affiliate[2] === 'accept' ? 'approved' : 'rejected', reviewed_at: now, updated_at: now, review_notes: JSON.parse(init.body || '{}').notes ?? null }
        : a));
      const row = fixtures.affiliates.find((a) => a.id === affiliate[1]);
      return json(affiliate[2] === 'accept'
        ? { request: row, account_email: row.contact_email, account_provisioned: true, account_created: true, invite_email_sent: true, detail: null }
        : row);
    }
    // Simulated in this page only: an ID review decision.
    const review = method === 'POST' && pathname.match(/^\/admin\/verifications\/([^/]+)\/(approve|reject)$/);
    if (review) {
      fixtures.verifications = fixtures.verifications.filter((v) => v.id !== review[1]);
      return json({ verified: review[2] === 'approve', verified_percent: review[2] === 'approve' ? 60 : 10, badge: 'light_green', message: 'ok' });
    }
    // Simulated in this page only: a Coordinator account made, or turned off/on.
    if (method === 'POST' && pathname === '/admin/coordinators') {
      const body = JSON.parse(init.body || '{}');
      const orgId = body.organization_id || fixtures.me.primary_org_id;
      const row = { id: id(40 + Math.floor(Math.random() * 900)), full_name: body.full_name, role: 'sub_admin', agency_type: signedIn?.agency ?? 'police', email: body.email, title: body.title, is_active: true, created_at: new Date().toISOString(), created_by_name: fixtures.me.full_name };
      fixtures.personnel[orgId] = [...(fixtures.personnel[orgId] ?? []), row];
      return json({ coordinator: row, invite_email_sent: true, detail: null }, 201);
    }
    const flip = method === 'POST' && pathname.match(/^\/admin\/coordinators\/([^/]+)\/(deactivate|reactivate)$/);
    if (flip) {
      const on = flip[2] === 'reactivate';
      Object.keys(fixtures.personnel).forEach((k) => {
        fixtures.personnel[k] = fixtures.personnel[k].map((p) => (p.id === flip[1]
          ? { ...p, is_active: on, deactivated_at: on ? null : new Date().toISOString() } : p));
      });
      return json({});
    }
    // Simulated in this page only: alarm escalations raised and decided.
    if (method === 'POST' && pathname === '/alarm-requests') {
      const body = JSON.parse(init.body || '{}');
      const area = fixtures.incidents.find((i) => i.id === body.area_id);
      const row = { id: id(390 + fixtures.alarmRequests.length), area_id: body.area_id, area_designation: area?.designation, requested_by: id(1), requested_by_name: fixtures.me.full_name, requested_alarm_level: body.requested_alarm_level, justification: body.justification, status: 'pending', created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      fixtures.alarmRequests = [row, ...fixtures.alarmRequests];
      return json(row, 201);
    }
    const answer = method === 'POST' && pathname.match(/^\/alarm-requests\/([^/]+)\/(execute|reject)$/);
    if (answer) {
      const now = new Date().toISOString();
      fixtures.alarmRequests = fixtures.alarmRequests.map((r) => (r.id === answer[1]
        ? { ...r, status: answer[2] === 'execute' ? 'approved' : 'rejected', reviewed_at: now, executed_at: answer[2] === 'execute' ? now : null, review_notes: JSON.parse(init.body || '{}').notes ?? null }
        : r));
      return json(fixtures.alarmRequests.find((r) => r.id === answer[1]));
    }
    if (method !== 'GET') return json({ detail: 'This preview does not save changes.' }, 409);

    if (pathname === '/auth/me') return json(fixtures.me);
    if (pathname === '/incidents/stats') {
      return json({ active_incidents: fixtures.incidents.length, pending_verify: 1, units_deployed: 2, units_standby: 3, pending_reports: 0 });
    }
    if (pathname === '/incidents') return json(fixtures.incidents);
    if (pathname === '/areas/overlaps/pending') return json(fixtures.overlaps);
    const one = pathname.match(/^\/incidents\/([^/]+)$/);
    if (one) return json(fixtures.incidents.find((i) => i.id === one[1]) ?? {}, one ? 200 : 404);
    if (pathname === '/map/hydrants') return json(fixtures.hydrants);
    if (pathname === '/map/bodies-of-water') return json(fixtures.water);
    if (pathname === '/map/underground-cisterns') return json(fixtures.cisterns);
    if (pathname === '/alarm-requests') {
      const status = searchParams.get('status');
      return json(status ? fixtures.alarmRequests.filter((r) => r.status === status) : fixtures.alarmRequests);
    }
    if (pathname === '/admin/verifications/pending') return json(fixtures.verifications);
    const areaEvidence = pathname.match(/^\/incidents\/([^/]+)\/reports$/);
    if (areaEvidence) {
      const area = fixtures.incidents.find((i) => i.id === areaEvidence[1]);
      if (!area) return json([]);
      return json([
        { id: id(900), reporter_id: id(61), reporter_name: 'Example Resident', photo_url: placeholder('Example scene photo'), device_lat: area.centroid_lat + 0.0002, device_lng: area.centroid_lng - 0.0001, has_exif: true, gps_discrepancy_flag: false, user_verified_percent: 60, selected_agencies: area.requested_agencies, notes: 'Fictional example: smoke from a second floor.', created_at: area.reported_at },
        { id: id(901), reporter_id: id(62), reporter_name: 'Sample Neighbour', photo_url: null, device_lat: area.centroid_lat - 0.0001, device_lng: area.centroid_lng + 0.0002, has_exif: false, gps_discrepancy_flag: false, user_verified_percent: 10, selected_agencies: area.requested_agencies, notes: null, created_at: area.updated_at },
      ]);
    }
    if (pathname === '/post-incident-reports') {
      const offset = Number(searchParams.get('offset') || 0);
      const limit = Number(searchParams.get('limit') || 50);
      return json(fixtures.reports.slice(offset, offset + limit));
    }
    const areaReports = pathname.match(/^\/incidents\/([^/]+)\/post-incident-reports$/);
    if (areaReports) return json(fixtures.reports.filter((r) => r.area_id === areaReports[1]));
    const summaries = pathname.match(/^\/incidents\/([^/]+)\/summaries$/);
    if (summaries) return json(fixtures.summaries[summaries[1]] ?? []);
    if (pathname === '/affiliates') {
      const status = searchParams.get('status');
      return json(status ? fixtures.affiliates.filter((r) => r.status === status) : fixtures.affiliates);
    }
    if (pathname === '/organizations') return json(fixtures.organizations);
    const people = pathname.match(/^\/organizations\/([^/]+)\/personnel$/);
    if (people) return json(fixtures.personnel[people[1]] ?? []);
    if (pathname === '/equipment') return json(fixtures.equipment.filter((e) => e.organization_id === searchParams.get('organization_id')));
    if (pathname === '/audit-logs') return json(fixtures.audit);
    return json([]);
  };

  const session = {
    user: fixtures.me,
    loading: false,
    login: async () => {},
    logout: () => window.alert('Preview: signing out is not available here.'),
  };

  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <AuthContext.Provider value={session}>
        <Dashboard />
      </AuthContext.Provider>
    </React.StrictMode>,
  );
}
