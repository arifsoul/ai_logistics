-- Keep Supabase Free Tier project active from GitHub Actions.
--
-- Run this in the Supabase SQL editor (Dashboard -> SQL Editor -> New query)
-- BEFORE relying on .github/workflows/keep_alive.yml.
--
-- Why: the workflow pings the REST API with the `anon` key. If Row Level
-- Security is enabled on `orders` (Supabase's default for new tables) and no
-- SELECT policy exists for `anon`, the request fails with 401/403 and no
-- database activity is recorded -- so the project is still paused.
--
-- This grants read-only access to the `orders` table. No write, update or
-- delete access is given, and the anon key remains publicly shareable because
-- it can only ever see this one table.

alter table public.orders enable row level security;

drop policy if exists "anon can read orders" on public.orders;

create policy "anon can read orders"
  on public.orders
  for select
  to anon
  using (true);

-- The REST API also requires the table-level GRANT; RLS alone is not enough.
grant select on table public.orders to anon;
