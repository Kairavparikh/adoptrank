from datetime import UTC, datetime

import asyncpg

from .code_analysis import GitHubCodeAnalyzer
from .schemas import RepositorySnapshot
from .storage import persist_code_analysis


def snapshot_from_catalog_row(row) -> RepositorySnapshot:
    return RepositorySnapshot(
        full_name=row["full_name"],
        html_url=f"https://github.com/{row['full_name']}",
        captured_at=datetime.now(UTC),
        description=row["description"] or "",
        language=row["language"] or "Unknown",
        license_spdx=row["license_spdx"] or "NOASSERTION",
        topics=list(row["topics"] or []),
        stars=row["stars"] or 0,
        forks=row["forks"] or 0,
        archived=bool(row["is_archived"]),
        pushed_at=row["github_updated_at"],
    )


async def select_deep_index_candidates(
    database_url: str, limit: int = 25
) -> list[RepositorySnapshot]:
    """Select a language-diverse incremental indexing batch from the live catalog."""
    connection = await asyncpg.connect(database_url)
    try:
        rows = await connection.fetch(
            """
            with eligible as (
              select r.*,
                     row_number() over (
                       partition by coalesce(r.language, 'Unknown')
                       order by r.stars desc, r.github_updated_at desc nulls last
                     ) as language_rank
              from repositories r
              where not r.is_archived
                and (
                  r.indexed_commit_sha is null
                  or r.indexed_at is null
                  or r.github_updated_at > r.indexed_at
                )
            )
            select full_name, description, language, license_spdx, topics, stars, forks,
                   is_archived, github_updated_at
            from eligible
            order by language_rank, stars desc, github_updated_at desc nulls last, full_name
            limit $1
            """,
            max(1, min(limit, 500)),
        )
    finally:
        await connection.close()
    return [snapshot_from_catalog_row(row) for row in rows]


async def deep_index_catalog(
    database_url: str,
    github_token: str | None,
    *,
    limit: int = 25,
    files_per_repository: int = 12,
) -> dict[str, int]:
    """Analyze changed repositories and immediately add their Qwen vectors."""
    from .vector_index import populate_pgvector_snapshots

    candidates = await select_deep_index_candidates(database_url, limit)
    analyzer = GitHubCodeAnalyzer(github_token)
    enriched: list[RepositorySnapshot] = []
    failures = 0
    try:
        for repository in candidates:
            try:
                enriched.append(await analyzer.analyze(repository, files_per_repository))
            except Exception:
                failures += 1
    finally:
        await analyzer.close()
    evidence = await persist_code_analysis(database_url, enriched)
    vectors = await populate_pgvector_snapshots(database_url, enriched)
    return {
        "selected": len(candidates),
        "indexed": len(enriched),
        "failures": failures,
        "evidence": evidence,
        "embedded_chunks": vectors,
    }
