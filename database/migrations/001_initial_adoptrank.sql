create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists public.repositories (
  id uuid primary key default gen_random_uuid(),
  github_node_id text unique,
  full_name text not null unique,
  owner text not null,
  name text not null,
  description text,
  language text,
  license_spdx text,
  default_branch text,
  is_archived boolean not null default false,
  stars integer not null default 0,
  forks integer not null default 0,
  topics text[] not null default '{}',
  search_document tsvector generated always as (
    setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
    setweight(to_tsvector('simple', array_to_string(topics, ' ')), 'B')
  ) stored,
  github_updated_at timestamptz,
  indexed_commit_sha text,
  indexed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists repositories_search_idx on public.repositories using gin(search_document);
create index if not exists repositories_language_idx on public.repositories(language);

create table if not exists public.repository_embeddings (
  repository_id uuid not null references public.repositories(id) on delete cascade,
  commit_sha text not null,
  model_version text not null,
  embedding vector(768) not null,
  embedded_at timestamptz not null default now(),
  primary key(repository_id, commit_sha, model_version)
);

create index if not exists repository_embeddings_hnsw_idx
  on public.repository_embeddings using hnsw (embedding vector_cosine_ops);

create table if not exists public.repository_observations (
  id bigint generated always as identity primary key,
  repository_id uuid not null references public.repositories(id) on delete cascade,
  source text not null check (source in ('github', 'pypi', 'npm', 'deps_dev', 'osv', 'hn')),
  observed_at timestamptz not null,
  stars integer,
  forks integer,
  downloads_30d bigint,
  reverse_dependents integer,
  returning_contributors integer,
  open_issues integer,
  closed_issues_30d integer,
  releases_90d integer,
  payload jsonb not null default '{}',
  unique(repository_id, source, observed_at)
);

create index if not exists repository_observations_lookup_idx
  on public.repository_observations(repository_id, observed_at desc);

create table if not exists public.code_evidence (
  id bigint generated always as identity primary key,
  repository_id uuid not null references public.repositories(id) on delete cascade,
  commit_sha text not null,
  path text not null,
  symbol text,
  evidence_type text not null check (evidence_type in ('implementation', 'test', 'example', 'interface', 'dependency')),
  summary text not null,
  confidence real not null check (confidence between 0 and 1),
  extracted_at timestamptz not null default now(),
  unique(repository_id, commit_sha, path, evidence_type, summary)
);

create table if not exists public.ranking_snapshots (
  id uuid primary key default gen_random_uuid(),
  model_version text not null,
  feature_version text not null,
  data_watermark timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists public.ranking_results (
  snapshot_id uuid not null references public.ranking_snapshots(id) on delete cascade,
  repository_id uuid not null references public.repositories(id) on delete cascade,
  global_score real not null,
  adoption_score real not null,
  maintenance_score real not null,
  security_score real not null,
  confidence real not null check (confidence between 0 and 1),
  label text check (label in ('Emerging', 'Durable', 'Hidden gem', 'Overhyped', 'At risk')),
  explanation jsonb not null default '{}',
  primary key(snapshot_id, repository_id)
);

create index if not exists ranking_results_repo_idx on public.ranking_results(repository_id, global_score desc);

create or replace function public.search_repositories(search_query text, result_limit integer default 20)
returns table(full_name text, rank_score real, observed_at timestamptz)
language sql
stable
security definer
set search_path = public
as $$
  with latest_snapshot as (
    select id, data_watermark from ranking_snapshots order by created_at desc limit 1
  )
  select
    r.full_name,
    (
      0.55 * coalesce(ts_rank_cd(r.search_document, websearch_to_tsquery('english', search_query)), 0) +
      0.45 * coalesce(rr.global_score, 0)
    )::real as rank_score,
    ls.data_watermark as observed_at
  from repositories r
  left join latest_snapshot ls on true
  left join ranking_results rr on rr.snapshot_id = ls.id and rr.repository_id = r.id
  where not r.is_archived
    and r.search_document @@ websearch_to_tsquery('english', search_query)
  order by rank_score desc, r.stars desc
  limit greatest(1, least(result_limit, 100));
$$;

create or replace function public.semantic_repository_candidates(query_embedding vector(768), result_limit integer default 100)
returns table(full_name text, semantic_score real)
language sql
stable
as $$
  select r.full_name, (1 - (e.embedding <=> query_embedding))::real as semantic_score
  from repository_embeddings e
  join repositories r on r.id = e.repository_id
  where not r.is_archived
  order by e.embedding <=> query_embedding
  limit greatest(1, least(result_limit, 500));
$$;
