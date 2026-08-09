import math
import re
from collections.abc import Callable

from .context_pack import context_terms, estimate_tokens
from .schemas import ExternalCodeExcerpt, RankedRepository, RepositorySnapshot

PATH_HEADER = re.compile(r"^File:\s*([^\n]+)\n", re.MULTILINE)


def _split_chunk(chunk: str) -> tuple[str, str]:
    match = PATH_HEADER.match(chunk)
    if not match:
        return "unknown", chunk
    return match.group(1).strip(), chunk[match.end() :]


def _lexical_score(query: str, path: str, content: str) -> float:
    query_terms = context_terms(query)
    if not query_terms:
        return 0.0
    path_terms = context_terms(path)
    content_terms = context_terms(content[:8000])
    return (3.0 * len(query_terms & path_terms) + len(query_terms & content_terms)) / math.sqrt(
        max(1, len(query_terms))
    )


def select_external_code(
    query: str,
    ranked: list[RankedRepository],
    repositories: dict[str, RepositorySnapshot],
    token_budget: int,
    rerank: Callable[[str, list[str]], list[float]] | None = None,
) -> list[ExternalCodeExcerpt]:
    candidates: list[tuple[RankedRepository, RepositorySnapshot, str, str, float]] = []
    for result in ranked:
        repo = repositories.get(result.full_name)
        if repo is None or not repo.indexed_commit_sha:
            continue
        for chunk in repo.code_chunks:
            path, content = _split_chunk(chunk)
            lexical = _lexical_score(query, path, content)
            if lexical > 0:
                candidates.append((result, repo, path, content, lexical))

    candidates.sort(key=lambda item: (-(item[4] + item[0].score), item[1].full_name, item[2]))
    candidates = candidates[:40]
    cross_scores = [0.0] * len(candidates)
    if rerank and candidates:
        cross_scores = rerank(
            query,
            [f"Repository: {repo.full_name}\nFile: {path}\n{content}" for _, repo, path, content, _ in candidates],
        )

    rescored = []
    for candidate, cross in zip(candidates, cross_scores, strict=True):
        result, repo, path, content, lexical = candidate
        tokens = estimate_tokens(path + content) + 20
        relevance = 0.30 * result.score + 0.25 * min(1.0, lexical / 4.0) + 0.45 * float(cross)
        value_per_token = relevance / math.sqrt(max(1, tokens))
        rescored.append((value_per_token, relevance, tokens, result, repo, path, content))
    rescored.sort(key=lambda item: (-item[0], -item[1], item[4].full_name, item[5]))

    selected: list[ExternalCodeExcerpt] = []
    used = 0
    per_repository: dict[str, int] = {}
    for _, relevance, tokens, result, repo, path, content in rescored:
        if used + tokens > token_budget or per_repository.get(repo.full_name, 0) >= 3:
            continue
        sha = repo.indexed_commit_sha or ""
        selected.append(
            ExternalCodeExcerpt(
                repository=repo.full_name,
                repository_url=repo.html_url,
                commit_sha=sha,
                license=repo.license_spdx,
                path=path,
                source_url=f"{repo.html_url}/blob/{sha}/{path}",
                content=content,
                score=relevance,
                estimated_tokens=tokens,
            )
        )
        used += tokens
        per_repository[repo.full_name] = per_repository.get(repo.full_name, 0) + 1
    return selected
