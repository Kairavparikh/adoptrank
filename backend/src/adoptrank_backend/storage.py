from collections.abc import Iterable
import json

import asyncpg

from .schemas import RepositorySnapshot


async def persist_snapshots(database_url: str, snapshots: Iterable[RepositorySnapshot]) -> int:
    connection = await asyncpg.connect(database_url)
    written = 0
    try:
        async with connection.transaction():
            for repo in snapshots:
                repository_id = await connection.fetchval(
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
                    returning id
                    """,
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
                await connection.execute(
                    """
                    insert into repository_observations (
                      repository_id, source, observed_at, stars, forks, pypi_downloads_1d,
                      pypi_downloads_7d, downloads_30d, open_issues, payload
                    ) values ($1,'github',$2,$3,$4,$5,$6,$7,$8,$9)
                    on conflict (repository_id, source, observed_at) do nothing
                    """,
                    repository_id,
                    repo.captured_at,
                    repo.stars,
                    repo.forks,
                    repo.pypi_downloads_1d,
                    repo.pypi_downloads_7d,
                    repo.pypi_downloads_30d,
                    repo.open_issues,
                    json.dumps({"source_query": repo.source_query, "pypi_package": repo.pypi_package}),
                )
                written += 1
    finally:
        await connection.close()
    return written
