-- ============================================================================
-- Tier 1 dispatch enrichment + fleet seed.
-- Master context v8: manual dispatch records which vehicle + fireground role per
-- responder (for the audit trail / after-action PDF), and the fleet is real
-- equipment with a water-tank capacity. All statements are additive/idempotent.
-- ============================================================================

set search_path = public, extensions;

-- dispatch_logs: record the truck + fireground role for each assignment so the
-- audit log / PDF show who drove which unit in what role.
alter table public.dispatch_logs
  add column if not exists vehicle_name text,
  add column if not exists crew_role    text;

-- equipment: water-tank capacity (litres) for fire trucks.
alter table public.equipment
  add column if not exists capacity_liters integer;

-- Seed a sample fleet under the partner org (replace with the brigade's real
-- units). category = 'fire_truck' so the dispatch fleet picker can filter.
insert into public.equipment
    (organization_id, name, category, quantity, status, capacity_liters, description)
select o.id, v.name, 'fire_truck', 1,
       v.status::public.equipment_status, v.capacity_liters, 'Fire Truck'
from public.organizations o
cross join (values
  ('Apollo',   'available', 4000),
  ('Achilles', 'available', 3500),
  ('Hermes',   'in_use',    4000)
) as v(name, status, capacity_liters)
where o.name = 'Hercules Fire Brigade'
  and not exists (
    select 1 from public.equipment e
    where e.organization_id = o.id and e.name = v.name
  );

-- Give fire-volunteer staff without an org a home org so org-scoped reads
-- (equipment) and the dispatch picker work. Only fills nulls — never overwrites.
update public.users
set primary_org_id = (
      select id from public.organizations where name = 'Hercules Fire Brigade'
    )
where primary_org_id is null
  and role in ('sub_admin', 'response_team')
  and (agency_type = 'fire_volunteer'::public.agency_type or agency_type is null);
