from collections.abc import Iterable
import json

import asyncpg

from .schemas import RepositorySnapshot


async def corpus_stats(database_url: str) -> dict[str, int | str | None]:
    connection = await asyncpg.connect(database_url)
    try:
        row = await connection.fetchrow(
            """
            select
              (select count(*) from repositories) as repositories,
              (select count(*) from repository_observations) as observations,
              (select count(*) from repositories where indexed_commit_sha is not null) as deeply_indexed,
              (select count(distinct repository_id) from code_chunk_embeddings) as vectorized_repositories,
              (select count(*) from code_chunk_embeddings) as vector_chunks,
              (select max(indexed_at) from repositories where indexed_commit_sha is not null) as last_deep_indexed_at
            """
        )
    finally:
        await connection.close()
    return {
        "repositories": int(row["repositories"]),
        "observations": int(row["observations"]),
        "deeply_indexed": int(row["deeply_indexed"]),
        "vectorized_repositories": int(row["vectorized_repositories"]),
        "vector_chunks": int(row["vector_chunks"]),
        "last_deep_indexed_at": (
            row["last_deep_indexed_at"].isoformat() if row["last_deep_indexed_at"] else None
        ),
    }


async def persist_snapshots(database_url: str, snapshots: Iterable[RepositorySnapshot]) -> int:
    snapshots = list(snapshots)
    if not snapshots:
        return 0
    connection = await asyncpg.connect(database_url)
    try:
        async with connection.transaction():
            await connection.executemany(
                """
                    insert into repositories (
                      full_name, owner, name, description, language, license_spdx, is_archived,
                      stars, forks, topics, github_updated_at, indexed_at, updated_at
                    ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,now())
                    on conflict (full_name) do update set
                      description=excluded.description, language=excluded.language,
                      license_spdx=excluded.license_spdx, is_archived=excluded.is_archived,
                      stars=excluded.stars, forks=excluded.forks, topics=excluded.topics,
                      github_updated_at=excluded.github_updated_at, indexed_at=excluded.indexed_at,
                      updated_at=now()
                """,
                [
                    (
                        repo.full_name,
                        repo.full_name.split("/", 1)[0],
                        repo.full_name.split("/", 1)[-1],
                        repo.description,
                        repo.language,
                        repo.license_spdx,
                        repo.archived,
                        repo.stars,
                        repo.forks,
                        repo.topics,
                        repo.pushed_at,
                        repo.captured_at,
                    )
                    for repo in snapshots
                ],
            )
            id_rows = await connection.fetch(
                "select id, full_name from repositories where full_name=any($1::text[])",
                [repo.full_name for repo in snapshots],
            )
            repository_ids = {row["full_name"]: row["id"] for row in id_rows}
            await connection.executemany(
                """
                    insert into repository_observations (
                      repository_id, source, observed_at, stars, forks, pypi_downloads_1d,
                      pypi_downloads_7d, downloads_30d, open_issues, payload
                    ) values ($1,'github',$2,$3,$4,$5,$6,$7,$8,$9)
                    on conflict (repository_id, source, observed_at) do nothing
                """,
                [
                    (
                        repository_ids[repo.full_name],
                        repo.captured_at,
                        repo.stars,
                        repo.forks,
                        repo.pypi_downloads_1d,
                        repo.pypi_downloads_7d,
                        repo.pypi_downloads_30d,
                        repo.open_issues,
                        json.dumps(
                            {
                                "source_query": repo.source_query,
                                "pypi_package": repo.pypi_package,
                            }
                        ),
                    )
                    for repo in snapshots
                    if repo.full_name in repository_ids
                ],
            )
    finally:
        await connection.close()
    return len(snapshots)


async def persist_code_analysis(database_url: str, snapshots: Iterable[RepositorySnapshot]) -> int:
    connection = await asyncpg.connect(database_url)
    written = 0
    try:
        async with connection.transaction():
            for repo in snapshots:
                if not repo.indexed_commit_sha:
                    continue
                repository_id = await connection.fetchval(
                    """
                    update repositories
                    set indexed_commit_sha=$2, indexed_at=$3, updated_at=now()
                    where full_name=$1
                    returning id
                    """,
                    repo.full_name,
                    repo.indexed_commit_sha,
                    repo.captured_at,
                )
                if repository_id is None:
                    continue
                for path in repo.code_evidence_paths:
                    lowered = path.lower()
                    evidence_type = (
                        "test"
                        if "test" in lowered
                        else "example"
                        if "example" in lowered or "demo" in lowered
                        else "dependency"
                        if lowered.endswith(
                            ("pyproject.toml", "requirements.txt", "package.json", "cargo.toml", "go.mod")
                        )
                        else "implementation"
                    )
                    await connection.execute(
                        """
                        insert into code_evidence (
                          repository_id, commit_sha, path, evidence_type, summary, confidence
                        ) values ($1,$2,$3,$4,$5,$6)
                        on conflict (repository_id, commit_sha, path, evidence_type, summary) do nothing
                        """,
                        repository_id,
                        repo.indexed_commit_sha,
                        path,
                        evidence_type,
                        f"Selected {evidence_type} file used by deterministic source analysis",
                        0.8,
                    )
                    written += 1
    finally:
        await connection.close()
    return written
