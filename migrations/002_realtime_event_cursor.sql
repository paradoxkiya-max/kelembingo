-- Realtime event cursor index.
-- The bridge consumes events in (created_at, id) order; id alone is a random UUID
-- and cannot be used as a monotonic cursor.
create index if not exists idx_system_events_created_at_id
    on public.system_events (created_at, id);
