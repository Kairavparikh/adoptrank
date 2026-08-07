alter table public.ranking_results
  add column if not exists global_rank integer,
  add column if not exists adoption_1d real not null default 0,
  add column if not exists adoption_7d real not null default 0,
  add column if not exists adoption_30d real not null default 0,
  add column if not exists adoption_90d real not null default 0,
  add column if not exists quality_score real not null default 0,
  add column if not exists depth_score real not null default 0,
  add column if not exists originality_score real not null default 0,
  add column if not exists attention_score real not null default 0;

create unique index if not exists ranking_snapshots_watermark_idx
  on public.ranking_snapshots(feature_version, data_watermark);

create index if not exists ranking_results_snapshot_rank_idx
  on public.ranking_results(snapshot_id, global_rank);

create index if not exists ranking_results_snapshot_label_idx
  on public.ranking_results(snapshot_id, label, global_score desc);

create index if not exists repositories_owner_lower_idx
  on public.repositories(lower(owner));

create index if not exists repositories_license_lower_idx
  on public.repositories(lower(license_spdx));

create or replace function public.leaderboard_repositories(
  owner_filter text default null,
  language_filter text default null,
  license_filter text default null,
  label_filter text default null,
  window_days integer default 30,
  sort_by text default 'overall',
  page_limit integer default 25,
  page_offset integer default 0
)
returns table(
  full_name text,
  owner text,
  name text,
  description text,
  language text,
  license_spdx text,
  topics text[],
  stars integer,
  forks integer,
  github_updated_at timestamptz,
  score real,
  adoption_score real,
  maintenance_score real,
  quality_score real,
  depth_score real,
  originality_score real,
  attention_score real,
  confidence real,
  label text,
  global_rank integer,
  rank_delta integer,
  score_delta real,
  data_watermark timestamptz,
  total_count bigint,
  explanation jsonb
)
language sql
stable
security definer
set search_path = public
as $$
  with snapshots as (
    select id, data_watermark, row_number() over (order by data_watermark desc, created_at desc) as recency
    from ranking_snapshots
    where feature_version = 'leaderboard-v1'
  ),
  current_snapshot as (
    select id, data_watermark from snapshots where recency = 1
  ),
  previous_snapshot as (
    select id from snapshots where recency = 2
  ),
  candidates as (
    select
      r.full_name,
      r.owner,
      r.name,
      coalesce(r.description, '') as description,
      coalesce(r.language, 'Unknown') as language,
      coalesce(r.license_spdx, 'NOASSERTION') as license_spdx,
      r.topics,
      r.stars,
      r.forks,
      r.github_updated_at,
      rr.global_score as score,
      case greatest(1, least(window_days, 90))
        when 1 then rr.adoption_1d
        when 7 then rr.adoption_7d
        when 90 then rr.adoption_90d
        else rr.adoption_30d
      end as adoption_score,
      rr.maintenance_score,
      rr.quality_score,
      rr.depth_score,
      rr.originality_score,
      rr.attention_score,
      rr.confidence,
      rr.label,
      rr.global_rank,
      case when prior.global_rank is null then null else prior.global_rank - rr.global_rank end as rank_delta,
      case when prior.global_score is null then null else rr.global_score - prior.global_score end as score_delta,
      current_snapshot.data_watermark,
      rr.explanation
    from current_snapshot
    join ranking_results rr on rr.snapshot_id = current_snapshot.id
    join repositories r on r.id = rr.repository_id
    left join previous_snapshot on true
    left join ranking_results prior
      on prior.snapshot_id = previous_snapshot.id and prior.repository_id = rr.repository_id
    where not r.is_archived
      and (nullif(trim(owner_filter), '') is null or lower(r.owner) = lower(trim(owner_filter)))
      and (nullif(trim(language_filter), '') is null or lower(r.language) = lower(trim(language_filter)))
      and (nullif(trim(license_filter), '') is null or lower(r.license_spdx) = lower(trim(license_filter)))
      and (nullif(trim(label_filter), '') is null or lower(rr.label) = lower(trim(label_filter)))
  ),
  counted as (
    select candidates.*, count(*) over() as total_count
    from candidates
  )
  select
    full_name, owner, name, description, language, license_spdx, topics, stars, forks,
    github_updated_at, score, adoption_score, maintenance_score, quality_score,
    depth_score, originality_score, attention_score, confidence, label, global_rank,
    rank_delta, score_delta, data_watermark, total_count, explanation
  from counted
  order by
    case when sort_by = 'adoption' then adoption_score end desc nulls last,
    case when sort_by = 'maintenance' then maintenance_score end desc nulls last,
    case when sort_by = 'quality' then quality_score end desc nulls last,
    case when sort_by = 'depth' then depth_score end desc nulls last,
    case when sort_by = 'originality' then originality_score end desc nulls last,
    case when sort_by = 'attention' then attention_score end desc nulls last,
    case when sort_by = 'momentum' then rank_delta end desc nulls last,
    case when sort_by = 'stars' then stars end desc nulls last,
    case when sort_by not in ('adoption','maintenance','quality','depth','originality','attention','momentum','stars') then score end desc nulls last,
    full_name
  limit greatest(1, least(page_limit, 100))
  offset greatest(0, page_offset);
$$;

grant execute on function public.leaderboard_repositories(text,text,text,text,integer,text,integer,integer)
  to public;
