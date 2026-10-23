-- Sasayaki cloud schema. Run once in Supabase: Dashboard → SQL Editor → paste → Run.
-- Everything is private to the signed-in user (row-level security); nothing is public.

create table if not exists public.collections (
    id          uuid primary key,
    user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
    name        text not null,
    description text not null default '',
    glossary    jsonb not null default '[]',
    cover_path  text,                                  -- path inside the "covers" bucket
    updated_at  timestamptz not null default now()
);

create table if not exists public.tracks (
    id            uuid primary key,
    user_id       uuid not null default auth.uid() references auth.users(id) on delete cascade,
    collection_id uuid not null references public.collections(id) on delete cascade,
    title         text not null,
    audio_path    text,                                -- path inside the "audio" bucket; null until uploaded
    audio_bytes   bigint,
    duration_ms   integer not null default 0,
    src_lang      text not null default 'auto',
    sort_order    integer not null default 0,
    context_card  jsonb,
    updated_at    timestamptz not null default now()
);
create index if not exists tracks_collection_idx on public.tracks(collection_id, sort_order);

create table if not exists public.cues (
    track_id  uuid not null references public.tracks(id) on delete cascade,
    idx       integer not null,
    user_id   uuid not null default auth.uid() references auth.users(id) on delete cascade,
    start_ms  integer not null,
    end_ms    integer not null,
    src_text  text not null default '',
    en_text   text not null default '',
    primary key (track_id, idx)
);

create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists collections_touch on public.collections;
create trigger collections_touch before update on public.collections for each row execute function public.touch_updated_at();
drop trigger if exists tracks_touch on public.tracks;
create trigger tracks_touch before update on public.tracks for each row execute function public.touch_updated_at();

-- Row-level security: a user only ever sees and changes their own rows.
alter table public.collections enable row level security;
alter table public.tracks      enable row level security;
alter table public.cues        enable row level security;

drop policy if exists "own collections" on public.collections;
create policy "own collections" on public.collections for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "own tracks" on public.tracks;
create policy "own tracks" on public.tracks for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "own cues" on public.cues;
create policy "own cues" on public.cues for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Private storage buckets. Files live under "<user id>/…" and only that user can touch them.
insert into storage.buckets (id, name, public) values ('audio', 'audio', false) on conflict (id) do nothing;
insert into storage.buckets (id, name, public) values ('covers', 'covers', false) on conflict (id) do nothing;

drop policy if exists "own audio files" on storage.objects;
create policy "own audio files" on storage.objects for all to authenticated
    using (bucket_id = 'audio' and (storage.foldername(name))[1] = auth.uid()::text)
    with check (bucket_id = 'audio' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "own cover files" on storage.objects;
create policy "own cover files" on storage.objects for all to authenticated
    using (bucket_id = 'covers' and (storage.foldername(name))[1] = auth.uid()::text)
    with check (bucket_id = 'covers' and (storage.foldername(name))[1] = auth.uid()::text);

-- Make the API notice the new tables immediately.
notify pgrst, 'reload schema';
