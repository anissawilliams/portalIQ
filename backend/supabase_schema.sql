-- PortalIQ Supabase Schema
-- Run this in your Supabase SQL editor (Database → SQL Editor → New query)
-- =============================================================================

-- ── Schools (tenants) ────────────────────────────────────────────────────────
create table if not exists schools (
    id          uuid primary key default gen_random_uuid(),
    name        text not null unique,          -- "Florida State"
    abbreviation text not null,               -- "FSU"
    conference  text,                          -- "ACC"
    sports      text[] default array['football'], -- ['football','basketball']
    logo_url    text,
    primary_color text default '#CEB888',
    secondary_color text default '#782F40',
    created_at  timestamptz default now(),
    is_active   boolean default true
);

-- ── User roles ───────────────────────────────────────────────────────────────
create type user_role as enum ('admin', 'coach', 'analyst', 'viewer');

-- ── Profiles (extends Supabase auth.users) ───────────────────────────────────
create table if not exists profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    school_id   uuid references schools(id) on delete set null,
    full_name   text,
    title       text,                          -- "Director of Player Personnel"
    role        user_role default 'viewer',
    sport       text default 'football',
    created_at  timestamptz default now(),
    last_login  timestamptz
);

-- ── Portal watchlist ─────────────────────────────────────────────────────────
create table if not exists watchlist (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools(id) on delete cascade,
    added_by        uuid not null references profiles(id) on delete cascade,
    player_name     text not null,
    position        text,
    stars           numeric(2,1),
    origin_school   text,
    sport           text default 'football',
    season          int default 2025,
    status          text default 'tracking',  -- tracking, contacted, offered, signed, passed
    est_nil_cost    numeric,
    notes           text,
    priority        int default 3,            -- 1=high, 2=med, 3=low
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

-- ── Recruit notes ────────────────────────────────────────────────────────────
create table if not exists recruit_notes (
    id          uuid primary key default gen_random_uuid(),
    watchlist_id uuid not null references watchlist(id) on delete cascade,
    author_id   uuid not null references profiles(id) on delete cascade,
    note        text not null,
    created_at  timestamptz default now()
);

-- ── Saved class projections ──────────────────────────────────────────────────
create table if not exists saved_projections (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid not null references schools(id) on delete cascade,
    created_by  uuid not null references profiles(id) on delete cascade,
    name        text not null,               -- "2025 Target Class Scenario A"
    sport       text default 'football',
    season      int,
    budget      numeric,
    players     jsonb,                       -- array of player objects
    projection  jsonb,                       -- projected wins, SP+, grade
    created_at  timestamptz default now()
);

-- =============================================================================
-- ROW LEVEL SECURITY
-- Each school only sees their own data
-- =============================================================================

alter table schools          enable row level security;
alter table profiles         enable row level security;
alter table watchlist        enable row level security;
alter table recruit_notes    enable row level security;
alter table saved_projections enable row level security;

-- Schools: anyone can read (for login school picker)
create policy "schools_read_all" on schools
    for select using (true);

-- Profiles: users see their own profile only
create policy "profiles_own" on profiles
    for all using (auth.uid() = id);

-- Watchlist: school members only
create policy "watchlist_school" on watchlist
    for all using (
        school_id = (
            select school_id from profiles where id = auth.uid()
        )
    );

-- Recruit notes: school members only
create policy "notes_school" on recruit_notes
    for all using (
        exists (
            select 1 from watchlist w
            join profiles p on p.id = auth.uid()
            where w.id = recruit_notes.watchlist_id
            and w.school_id = p.school_id
        )
    );

-- Saved projections: school members only
create policy "projections_school" on saved_projections
    for all using (
        school_id = (
            select school_id from profiles where id = auth.uid()
        )
    );

-- =============================================================================
-- SEED DATA — Initial schools
-- =============================================================================

insert into schools (name, abbreviation, conference, sports, primary_color, secondary_color) values
    ('Florida State',    'FSU',  'ACC',      array['football','basketball'], '#CEB888', '#782F40'),
    ('College of Charleston', 'CofC', 'CAA', array['basketball','soccer'],   '#004B87', '#C1A875'),
    ('Miami',            'UM',   'ACC',      array['football','basketball'], '#F47321', '#005030'),
    ('Clemson',          'CU',   'ACC',      array['football','basketball'], '#F56600', '#522D80'),
    ('Alabama',          'BAMA', 'SEC',      array['football','basketball'], '#9E1B32', '#828A8F'),
    ('Georgia',          'UGA',  'SEC',      array['football','basketball'], '#BA0C2F', '#000000'),
    ('Ohio State',       'OSU',  'Big Ten',  array['football','basketball'], '#BB0000', '#666666'),
    ('Texas',            'UT',   'SEC',      array['football','basketball'], '#BF5700', '#FFFFFF')
on conflict (name) do nothing;

-- =============================================================================
-- HELPER: auto-create profile on signup
-- =============================================================================

create or replace function handle_new_user()
returns trigger as $$
begin
    insert into profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name');
    return new;
end;
$$ language plpgsql security definer;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure handle_new_user();
