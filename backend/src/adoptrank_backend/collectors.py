import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import settings
from .schemas import RepositorySnapshot


class GitHubCollector:
    def __init__(self, token: str | None = None) -> None:
        self.authenticated = bool(token)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AdoptRank/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(
            base_url=settings.github_api_url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
        )
        self.pypi = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds, headers={"User-Agent": "AdoptRank/0.1"}
        )

    async def close(self) -> None:
        await self.client.aclose()
        await self.pypi.aclose()

    async def _get(self, path: str, **params: object) -> dict | list:
        response = await self.client.get(path, params=params)
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            reset = response.headers.get("x-ratelimit-reset", "unknown")
            raise RuntimeError(f"GitHub API rate limit exhausted; reset={reset}")
        response.raise_for_status()
        return response.json()

    async def search(
        self,
        query: str,
        per_query: int = 25,
        sort: str = "stars",
        *,
        hydrate_signals: bool = True,
        page_delay_seconds: float = 0.0,
    ) -> list[RepositorySnapshot]:
        if sort not in {"stars", "updated"}:
            raise ValueError(f"Unsupported GitHub repository sort: {sort}")
        requested = min(max(1, per_query), 1000)
        items: list[dict] = []
        page = 1
        while len(items) < requested:
            page_size = min(100, requested - len(items))
            payload = await self._get(
                "/search/repositories",
                q=query,
                sort=sort,
                order="desc",
                per_page=page_size,
                page=page,
            )
            assert isinstance(payload, dict)
            batch = payload.get("items", [])
            items.extend(batch)
            if len(batch) < page_size or len(items) >= requested:
                break
            page += 1
            if page_delay_seconds:
                await asyncio.sleep(page_delay_seconds)

        if not hydrate_signals:
            return [self._snapshot(item, query) for item in items]
        semaphore = asyncio.Semaphore(8)

        async def hydrate(item: dict) -> RepositorySnapshot:
            async with semaphore:
                return await self.hydrate(item, query)

        return await asyncio.gather(*(hydrate(item) for item in items))

    @staticmethod
    def _snapshot(
        item: dict,
        source_query: str,
        *,
        latest_release_at: str | None = None,
        contributors_sampled: int = 0,
        package_name: str | None = None,
        downloads_1d: int | None = None,
        downloads_7d: int | None = None,
        downloads_30d: int | None = None,
        pypi_release: str | None = None,
    ) -> RepositorySnapshot:
        license_data = item.get("license") or {}
        return RepositorySnapshot(
            full_name=item["full_name"],
            html_url=item["html_url"],
            captured_at=datetime.now(UTC),
            description=item.get("description") or "",
            language=item.get("language") or "Unknown",
            license_spdx=license_data.get("spdx_id") or "NOASSERTION",
            topics=item.get("topics") or [],
            stars=item.get("stargazers_count") or 0,
            forks=item.get("forks_count") or 0,
            open_issues=item.get("open_issues_count") or 0,
            watchers=item.get("subscribers_count") or item.get("watchers_count") or 0,
            size_kb=item.get("size") or 0,
            archived=bool(item.get("archived")),
            fork=bool(item.get("fork")),
            pushed_at=item.get("pushed_at"),
            created_at=item.get("created_at"),
            latest_release_at=latest_release_at,
            contributors_sampled=contributors_sampled,
            pypi_package=package_name,
            pypi_downloads_1d=downloads_1d,
            pypi_downloads_7d=downloads_7d,
            pypi_downloads_30d=downloads_30d,
            pypi_latest_release=pypi_release,
            source_query=source_query,
        )

    async def hydrate(self, item: dict, source_query: str) -> RepositorySnapshot:
        full_name = item["full_name"]
        latest_release_at = None
        contributors: list = []
        if self.authenticated:
            release_task = self.client.get(f"/repos/{full_name}/releases/latest")
            contributors_task = self.client.get(
                f"/repos/{full_name}/contributors", params={"per_page": 30, "anon": "true"}
            )
            release_response, contributors_response = await asyncio.gather(release_task, contributors_task)
            if release_response.status_code == 200:
                latest_release_at = release_response.json().get("published_at")
            contributors = contributors_response.json() if contributors_response.status_code == 200 else []
        package_name, downloads_1d, downloads_7d, downloads_30d, pypi_release = await self._pypi_signals(
            full_name.split("/")[-1]
        )

        return self._snapshot(
            item,
            source_query,
            latest_release_at=latest_release_at,
            contributors_sampled=len(contributors) if isinstance(contributors, list) else 0,
            package_name=package_name,
            downloads_1d=downloads_1d,
            downloads_7d=downloads_7d,
            downloads_30d=downloads_30d,
            pypi_release=pypi_release,
        )

    async def _pypi_signals(
        self, repository_name: str
    ) -> tuple[str | None, int | None, int | None, int | None, str | None]:
        candidates = [repository_name, repository_name.replace("_", "-"), repository_name.replace("-", "_")]
        for candidate in dict.fromkeys(candidates):
            metadata = await self.pypi.get(f"https://pypi.org/pypi/{candidate}/json")
            if metadata.status_code != 200:
                continue
            recent = await self.pypi.get(f"https://pypistats.org/api/packages/{candidate}/recent")
            downloads_1d = downloads_7d = downloads_30d = None
            if recent.status_code == 200:
                recent_data = recent.json().get("data", {})
                downloads_1d = recent_data.get("last_day")
                downloads_7d = recent_data.get("last_week")
                downloads_30d = recent_data.get("last_month")
            info = metadata.json().get("info", {})
            return candidate, downloads_1d, downloads_7d, downloads_30d, info.get("upload_time")
        return None, None, None, None, None


async def collect_queries(
    query_file: Path,
    output: Path,
    per_query: int = 25,
    *,
    hydrate_signals: bool = True,
    page_delay_seconds: float = 0.0,
    query_limit: int | None = None,
    query_offset: int = 0,
) -> int:
    all_queries = [
        line.strip()
        for line in query_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if query_limit is not None and query_limit < 1:
        raise ValueError("query_limit must be positive when provided")
    if not all_queries:
        return 0
    if query_limit is None or query_limit >= len(all_queries):
        queries = all_queries
    else:
        start = query_offset % len(all_queries)
        queries = [all_queries[(start + index) % len(all_queries)] for index in range(query_limit)]
    collector = GitHubCollector(settings.github_token)
    unique: dict[str, RepositorySnapshot] = {}
    try:
        for query in queries:
            for sort in ("stars", "updated"):
                for repo in await collector.search(
                    query,
                    per_query=per_query,
                    sort=sort,
                    hydrate_signals=hydrate_signals,
                    page_delay_seconds=page_delay_seconds,
                ):
                    current = unique.get(repo.full_name.lower())
                    if current is None or repo.captured_at > current.captured_at:
                        unique[repo.full_name.lower()] = repo
    finally:
        await collector.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        for repo in sorted(unique.values(), key=lambda value: value.full_name.lower()):
            handle.write(repo.model_dump_json() + "\n")
    if settings.database_url:
        from .storage import persist_snapshots

        await persist_snapshots(settings.database_url, unique.values())
    return len(unique)
