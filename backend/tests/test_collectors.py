import asyncio

from adoptrank_backend.collectors import GitHubCollector


def _item(index: int) -> dict:
    return {
        "full_name": f"example/repo-{index}",
        "html_url": f"https://github.com/example/repo-{index}",
        "description": "example",
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "stargazers_count": index,
        "forks_count": 1,
        "open_issues_count": 0,
        "size": 10,
    }


def test_shallow_search_paginates_without_hydration(monkeypatch) -> None:
    collector = GitHubCollector()
    pages: list[int] = []

    async def fake_get(path: str, **params):
        assert path == "/search/repositories"
        pages.append(params["page"])
        start = (params["page"] - 1) * 100
        return {"items": [_item(index) for index in range(start, start + params["per_page"])]}

    async def forbidden_hydrate(*args, **kwargs):
        raise AssertionError("shallow discovery must not hydrate repositories")

    monkeypatch.setattr(collector, "_get", fake_get)
    monkeypatch.setattr(collector, "hydrate", forbidden_hydrate)
    try:
        snapshots = asyncio.run(
            collector.search("vector database", per_query=250, hydrate_signals=False)
        )
    finally:
        asyncio.run(collector.close())

    assert len(snapshots) == 250
    assert pages == [1, 2, 3]
    assert snapshots[-1].full_name == "example/repo-249"
