-- KelemBingo adapter schema.
-- The application continues to use firestore_db.py; this migration only
-- provides its existing SQLAlchemy tables in PostgreSQL.

create table if not exists public.firestore_documents (
    collection text not null,
    doc_id text not null,
    data text,
    created_at timestamp without time zone not null default current_timestamp,
    updated_at timestamp without time zone not null default current_timestamp,
    primary key (collection, doc_id)
);

create index if not exists idx_firestore_documents_collection
    on public.firestore_documents (collection);

create table if not exists public.system_events (
    id text primary key,
    collection text,
    doc_id text,
    event_type text,
    created_at timestamp without time zone not null default current_timestamp
);

create index if not exists idx_system_events_created_at
    on public.system_events (created_at);

create table if not exists public.operation_records (
    operation_key text primary key,
    operation text not null,
    result text not null,
    created_at timestamp without time zone not null default current_timestamp
);

create table if not exists public.account_locks (
    user_id text primary key,
    created_at timestamp without time zone not null default current_timestamp
);

-- The browser and Supabase anon/authenticated roles must not access these
-- tables. The gateway uses the private PostgreSQL connection only.
alter table public.firestore_documents enable row level security;
alter table public.system_events enable row level security;
alter table public.operation_records enable row level security;
alter table public.account_locks enable row level security;
