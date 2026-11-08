-- Run once in the project's Supabase SQL editor. Only the server key can access this table.
create table if not exists public.exam_results (
  id uuid primary key,
  session_id uuid not null,
  created_at timestamptz not null default now(),
  result jsonb not null check (jsonb_typeof(result) = 'object')
);
alter table public.exam_results enable row level security;
revoke all on table public.exam_results from anon, authenticated;
grant select, insert, update on table public.exam_results to service_role;
-- No public policies, no chat history or original file storage.
