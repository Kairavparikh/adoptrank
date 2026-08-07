create table if not exists public.code_chunk_embeddings (
  repository_id uuid not null references public.repositories(id) on delete cascade,
  commit_sha text not null,
  path text not null,
  chunk_index integer not null,
  content_hash text not null,
  model_version text not null,
  embedding vector(1024) not null,
  summary text not null,
  embedded_at timestamptz not null default now(),
  primary key(repository_id, commit_sha, path, chunk_index, model_version)
);

create index if not exists code_chunk_embeddings_hnsw_idx
  on public.code_chunk_embeddings using hnsw (embedding vector_cosine_ops);

create or replace function public.semantic_code_candidates(query_embedding vector(1024), result_limit integer default 100)
returns table(full_name text, path text, semantic_score real)
language sql stable as $$
  select r.full_name, e.path, max(1 - (e.embedding <=> query_embedding))::real as semantic_score
  from code_chunk_embeddings e join repositories r on r.id=e.repository_id
  where not r.is_archived
  group by r.full_name, e.path
  order by semantic_score desc
  limit greatest(1, least(result_limit, 500));
$$;
