import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

import httpx

from .code_analysis import LANGUAGE_BY_EXTENSION, _tree_sitter_extract
from .local_scan import (
    DENIED_NAMES,
    DENIED_PARTS,
    SECRET_PATTERN,
    _ignored,
    scan_project,
)
from .schemas import (
    ContextPack,
    ContextSnippet,
    ExternalRepositoryEvidence,
    ExternalCodeExcerpt,
    ProjectContext,
)

WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]*|\d+(?:\.\d+)+")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
STOP_TERMS = {
    "add",
    "build",
    "change",
    "code",
    "create",
    "feature",
    "implement",
    "implementation",
    "make",
    "new",
    "project",
    "support",
    "the",
    "this",
    "use",
    "with",
}


@dataclass(frozen=True)
class _Candidate:
    path: str
    content: str
    score: float
    start_line: int


@dataclass(frozen=True)
class ContextRoute:
    """Deterministic first-stage routing before the learned value-per-token ranker."""

    name: str
    local_budget: int
    max_local_snippets: int
    max_snippets_per_path: int
    snippet_char_limit: int
    max_related_paths: int
    use_model_reranker: bool = True


NARROW_TASK_TERMS = {
    "action",
    "ci",
    "download",
    "enable",
    "install",
    "offline",
    "release",
    "upgrade",
    "workflow",
}
MULTI_SCOPE_TERMS = {"all", "across", "every", "multiple", "repository-wide", "workflows"}
BROAD_CHANGE_TERMS = {
    "deprecat",
    "document",
    "feature",
    "scaffold",
    "support",
    "typing",
}


def estimate_tokens(text: str) -> int:
    """Portable estimate used until provider-specific token accounting is available."""
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def _normalize_term(value: str) -> str:
    value = value.lower()
    if len(value) > 5 and value.endswith("ies"):
        return value[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(value) > len(suffix) + 3 and value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def context_tokens(text: str) -> list[str]:
    terms: list[str] = []
    for raw in WORD.findall(text):
        if re.fullmatch(r"\d+(?:\.\d+)+", raw):
            terms.append(raw)
            continue
        separated = re.sub(r"[_+./-]+", " ", raw)
        for piece in CAMEL_BOUNDARY.sub(" ", separated).split():
            if len(piece) >= 2:
                normalized = _normalize_term(piece)
                if normalized not in STOP_TERMS:
                    terms.append(normalized)
    return terms


def context_terms(text: str) -> set[str]:
    return set(context_tokens(text))


def route_context(query: str, budget: int) -> ContextRoute:
    """Choose the smallest useful pack before expensive model inference.

    Narrow operational edits usually have an obvious configuration target and
    are harmed by a generic multi-thousand-token pack. Explicit repository-wide
    tasks retain the larger budget because recall across files matters more.
    """
    lowered = query.lower()
    terms = context_terms(query)
    is_multi_scope = bool(terms & MULTI_SCOPE_TERMS) or any(
        phrase in lowered for phrase in ("repository wide", "repo-wide", "all github actions")
    )
    narrow_hits = len(terms & NARROW_TASK_TERMS)
    is_routine_maintenance = bool(
        re.search(r"\b(?:bump|pin|upgrade|version)\b", lowered)
    ) and not is_multi_scope
    if is_routine_maintenance:
        return ContextRoute(
            name="abstain-routine",
            local_budget=0,
            max_local_snippets=0,
            max_snippets_per_path=0,
            snippet_char_limit=0,
            max_related_paths=0,
            use_model_reranker=False,
        )
    if not is_multi_scope and narrow_hits >= 2:
        return ContextRoute(
            name="narrow-local",
            local_budget=min(300, budget),
            max_local_snippets=1,
            max_snippets_per_path=1,
            snippet_char_limit=650,
            max_related_paths=2,
            use_model_reranker=False,
        )
    if _query_identifiers(query) and not is_multi_scope:
        return ContextRoute(
            name="precise-symbol",
            local_budget=min(350, budget),
            max_local_snippets=1,
            max_snippets_per_path=1,
            snippet_char_limit=700,
            max_related_paths=4,
        )
    is_broad = is_multi_scope or bool(terms & BROAD_CHANGE_TERMS) or any(
        phrase in lowered
        for phrase in ("drop python", "docs and changelog", "add tests", "default compressible")
    )
    if is_broad:
        return ContextRoute(
            name="multi-file",
            local_budget=min(750, budget),
            max_local_snippets=3,
            max_snippets_per_path=1,
            snippet_char_limit=700,
            max_related_paths=16,
        )
    return ContextRoute(
        name="standard",
        local_budget=min(500, budget),
        max_local_snippets=2,
        max_snippets_per_path=1,
        snippet_char_limit=700,
        max_related_paths=10,
    )


def _candidate_score(query_terms: set[str], path: str, content: str) -> float:
    path_terms = context_terms(path)
    content_terms = context_terms(content[:6000])
    path_overlap = len(query_terms & path_terms)
    content_overlap = len(query_terms & content_terms)
    score = 4.0 * path_overlap + 1.5 * content_overlap
    lowered = path.lower()
    if any(part in lowered for part in ("test", "spec")) and content_overlap:
        score += 0.5
    if any(part in lowered for part in ("vendor/", "generated/", "fixture")):
        score -= 2.0
    return score / max(1.0, math.log2(estimate_tokens(content) + 1))


def _query_identifiers(query: str) -> set[str]:
    quoted = re.findall(r"`([^`\s]{3,80})`", query)
    camel = re.findall(r"\b[A-Z][A-Za-z0-9_]*[A-Z_][A-Za-z0-9_]*\b", query)
    versions = re.findall(r"\b(?:Python|Node|Go|Rust)\s*\d+(?:\.\d+)*\b", query, re.I)
    return {item.strip() for item in [*quoted, *camel, *versions] if item.strip()}


def _routing_boost(query: str, candidate: _Candidate) -> float:
    lowered_query = query.lower()
    lowered_path = candidate.path.lower()
    boost = 0.0
    for identifier in _query_identifiers(query):
        if identifier in candidate.content or identifier.lower() in candidate.content.lower():
            boost += 4.0
        if identifier.lower() in lowered_path:
            boost += 3.0
    if any(term in lowered_query for term in ("workflow", "github actions", " ci ")):
        if ".github/workflows/" in lowered_path:
            boost += 6.0
    if any(term in lowered_query for term in ("dependency", "dependencies", "install")):
        if Path(lowered_path).name in {"pyproject.toml", "package.json", "cargo.toml", "go.mod"}:
            boost += 4.0
    return boost


def _bm25_rerank(query: str, candidates: list[_Candidate]) -> list[_Candidate]:
    if not candidates:
        return []
    query_tokens = context_tokens(query)
    documents = [
        context_tokens(item.path.replace("/", " ") + " " + item.path + " " + item.content)
        for item in candidates
    ]
    document_frequencies: Counter[str] = Counter()
    for document in documents:
        document_frequencies.update(set(document))
    average_length = sum(len(document) for document in documents) / len(documents)
    total = len(documents)
    reranked = []
    for item, document in zip(candidates, documents, strict=True):
        frequencies = Counter(document)
        bm25 = 0.0
        for term in query_tokens:
            frequency = frequencies[term]
            if not frequency:
                continue
            inverse_frequency = math.log(
                1 + (total - document_frequencies[term] + 0.5) / (document_frequencies[term] + 0.5)
            )
            denominator = frequency + 1.2 * (
                0.25 + 0.75 * len(document) / max(1.0, average_length)
            )
            bm25 += inverse_frequency * frequency * 2.2 / denominator
        reranked.append(
            _Candidate(
                path=item.path,
                content=item.content,
                score=item.score + bm25,
                start_line=item.start_line,
            )
        )
    return sorted(reranked, key=lambda item: (-item.score, item.path, item.start_line))


def _safe_source_files(
    root: Path, max_files: int = 400, max_bytes: int = 4_000_000
) -> list[tuple[str, str]]:
    root = root.resolve()
    ignored = _ignored(root)
    files: list[tuple[str, str]] = []
    consumed = 0
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in DENIED_PARTS
            and not ignored.match_file(str((current_path / directory).relative_to(root)) + "/")
        ]
        for name in sorted(names):
            if len(files) >= max_files or consumed >= max_bytes:
                return files
            path = current_path / name
            relative = str(path.relative_to(root))
            if (
                name.lower() in DENIED_NAMES
                or name.startswith(".env")
                or ignored.match_file(relative)
                or path.suffix.lower() not in LANGUAGE_BY_EXTENSION
            ):
                continue
            if path.stat().st_size > 500_000:
                continue
            content = path.read_text(errors="ignore")
            consumed += len(content.encode("utf-8"))
            if SECRET_PATTERN.search(content):
                continue
            files.append((relative, content))
    return files


def _local_candidates(root: Path, query: str) -> list[_Candidate]:
    query_terms = context_terms(query)
    candidates: list[_Candidate] = []
    for path, content in _safe_source_files(root):
        try:
            symbols, imports, raw_chunks = _tree_sitter_extract(path, content)
        except Exception:
            symbols, imports = [], []
            raw_chunks = []
        overview = "\n".join(
            [
                f"File: {path}",
                f"Symbols: {', '.join(symbols[:40])}",
                f"Imports: {', '.join(imports[:40])}",
                content[:1800],
            ]
        )
        overview_score = _candidate_score(query_terms, path, overview)
        if overview_score > 0:
            candidates.append(
                _Candidate(path=path, content=overview, score=overview_score, start_line=1)
            )
        chunks = [chunk.split("\n", 1)[1] for chunk in raw_chunks if "\n" in chunk]
        if not chunks:
            chunks = [content[:4000]]
        for chunk in chunks:
            if not chunk.strip():
                continue
            offset = content.find(chunk[: min(120, len(chunk))])
            start_line = content.count("\n", 0, max(0, offset)) + 1
            score = _candidate_score(query_terms, path, chunk)
            if score > 0:
                candidates.append(
                    _Candidate(
                        path=path,
                        content=chunk,
                        score=score,
                        start_line=start_line,
                    )
                )
    candidates = [
        _Candidate(
            path=item.path,
            content=item.content,
            score=item.score + _routing_boost(query, item),
            start_line=item.start_line,
        )
        for item in candidates
    ]
    return _bm25_rerank(query, candidates)


def search_external_repositories(
    query: str,
    project: ProjectContext,
    api: str,
    limit: int = 5,
) -> list[ExternalRepositoryEvidence]:
    base_url = api.rstrip("/")
    direct_ranker = "modal.run" in base_url or base_url.startswith(
        ("http://127.0.0.1", "http://localhost")
    )
    endpoint = (
        base_url
        if base_url.endswith(("/api/search", "/v1/search"))
        else f"{base_url}/v1/search" if direct_ranker
        else f"{base_url}/api/search"
    )
    headers = {}
    if endpoint.endswith("/v1/search") and os.environ.get("RANKER_API_KEY"):
        headers["x-adoptrank-key"] = os.environ["RANKER_API_KEY"]
    response = httpx.post(
        endpoint,
        json={"query": query, "limit": limit, "project_context": project.model_dump()},
        headers=headers,
        timeout=180,
    )
    response.raise_for_status()
    evidence = []
    for result in response.json().get("results", []):
        text = "\n".join(
            [
                result["full_name"],
                result["url"],
                result.get("reason", ""),
                *result.get("code_evidence", []),
            ]
        )
        evidence.append(
            ExternalRepositoryEvidence(
                full_name=result["full_name"],
                url=result["url"],
                reason=result.get("reason", ""),
                score=float(result.get("score", 0.0)),
                code_evidence=result.get("code_evidence", []),
                estimated_tokens=estimate_tokens(text),
            )
        )
    return evidence


def search_external_code(
    query: str,
    project: ProjectContext,
    api: str,
    token_budget: int,
    limit: int = 5,
) -> list[ExternalCodeExcerpt]:
    base_url = api.rstrip("/")
    direct_ranker = "modal.run" in base_url or base_url.startswith(
        ("http://127.0.0.1", "http://localhost")
    )
    endpoint = (
        base_url
        if base_url.endswith(("/api/context", "/v1/context"))
        else f"{base_url}/v1/context" if direct_ranker
        else f"{base_url}/api/context"
    )
    headers = {}
    if endpoint.endswith("/v1/context") and os.environ.get("RANKER_API_KEY"):
        headers["x-adoptrank-key"] = os.environ["RANKER_API_KEY"]
    response = httpx.post(
        endpoint,
        json={
            "query": query,
            "limit": limit,
            "token_budget": token_budget,
            "project_context": project.model_dump(),
        },
        headers=headers,
        timeout=180,
    )
    response.raise_for_status()
    return [ExternalCodeExcerpt.model_validate(item) for item in response.json().get("evidence", [])]


def build_context_pack(
    root: Path,
    query: str,
    budget: int = 8000,
    external: list[ExternalRepositoryEvidence] | None = None,
    external_code: list[ExternalCodeExcerpt] | None = None,
    candidate_reranker: Callable[[str, list[str]], list[float]] | None = None,
) -> ContextPack:
    if budget < 500:
        raise ValueError("Context budget must be at least 500 estimated tokens")
    project = scan_project(root)
    # Only rendered text counts against the injected context budget. Project
    # metadata remains available in the structured response but is summarized
    # to language/framework names by ``render_context_pack``.
    used = estimate_tokens(query) + 40
    snippets: list[ContextSnippet] = []
    external_selected: list[ExternalRepositoryEvidence] = []

    external_budget = max(0, int(budget * 0.20))
    external_used = 0
    query_terms = context_terms(query)
    for item in sorted(external or [], key=lambda value: (-value.score, value.full_name)):
        evidence_terms = context_terms(
            " ".join([item.full_name, item.reason, *item.code_evidence])
        )
        if item.score < 0.60 and not query_terms.intersection(evidence_terms):
            continue
        if used + item.estimated_tokens > budget or external_used + item.estimated_tokens > external_budget:
            continue
        external_selected.append(item)
        used += item.estimated_tokens
        external_used += item.estimated_tokens

    code_budget = max(0, int(budget * 0.35))
    code_used = 0
    for item in sorted(external_code or [], key=lambda value: (-value.score, value.repository, value.path)):
        if used + item.estimated_tokens > budget or code_used + item.estimated_tokens > code_budget:
            continue
        snippets.append(
            ContextSnippet(
                source="github",
                path=item.path,
                content=item.content,
                score=item.score,
                estimated_tokens=item.estimated_tokens,
                repository=item.repository,
                url=item.source_url,
            )
        )
        used += item.estimated_tokens
        code_used += item.estimated_tokens

    route = route_context(query, budget)
    if route.name == "abstain-routine":
        return ContextPack(
            query=query,
            project=project,
            budget=budget,
            estimated_tokens=0,
            route=route.name,
            abstained=True,
            warnings=[
                "Retrieval abstained because the task is a routine version or dependency edit.",
                "The downstream coding agent receives its unchanged baseline prompt.",
            ],
        )

    candidates = _local_candidates(root, query)
    if candidate_reranker and route.use_model_reranker and candidates:
        candidates_by_path: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            candidates_by_path.setdefault(candidate.path, []).append(candidate)
        rerank_paths = list(candidates_by_path)[:40]
        documents = []
        for path in rerank_paths:
            excerpts = candidates_by_path[path][:3]
            documents.append(
                path
                + "\n"
                + "\n\n".join(excerpt.content for excerpt in excerpts)[:1800]
            )
        scores = None
        for attempt in range(3):
            try:
                scores = candidate_reranker(query, documents)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        assert scores is not None
        if len(scores) != len(rerank_paths):
            raise ValueError("Candidate reranker returned the wrong number of scores")
        path_scores = dict(zip(rerank_paths, scores, strict=True))
        candidates = [
            _Candidate(
                path=item.path,
                content=item.content,
                score=float(path_scores.get(item.path, -1_000_000.0)) + 0.01 * item.score,
                start_line=item.start_line,
            )
            for item in candidates
        ]
        candidates = sorted(
            candidates,
            key=lambda item: (-item.score, item.path, item.start_line),
        )
    selected_per_path: dict[str, int] = {}
    local_used = 0
    local_count = 0
    local_budget = route.local_budget
    for item in candidates:
        if local_count >= route.max_local_snippets:
            break
        if selected_per_path.get(item.path, 0) >= route.max_snippets_per_path:
            continue
        compact_content = item.content[: route.snippet_char_limit].rstrip()
        tokens = estimate_tokens(item.path + compact_content)
        if used + tokens > budget or local_used + tokens > local_budget:
            continue
        snippets.append(
            ContextSnippet(
                source="local",
                path=item.path,
                content=compact_content,
                score=item.score,
                estimated_tokens=tokens,
                start_line=item.start_line,
            )
        )
        used += tokens
        local_used += tokens
        local_count += 1
        selected_per_path[item.path] = selected_per_path.get(item.path, 0) + 1

    selected_keys = {
        (item.path, item.start_line) for item in snippets if item.source == "local"
    }
    related_paths: list[str] = []
    for item in candidates:
        if item.path in related_paths:
            continue
        path_tokens = estimate_tokens(item.path) + 2
        if used + path_tokens > budget:
            break
        related_paths.append(item.path)
        used += path_tokens
        if len(related_paths) >= route.max_related_paths:
            break
    warnings = [
        "Token counts are portable estimates, not provider billing counts.",
        f"Context route: {route.name}.",
    ]
    if not any(item.source == "local" for item in snippets):
        warnings.append("No local source excerpt passed the lexical relevance threshold; retrieval abstained.")
    return ContextPack(
        query=query,
        project=project,
        budget=budget,
        estimated_tokens=used,
        snippets=snippets,
        related_paths=related_paths,
        external_repositories=external_selected,
        excluded_candidates=sum(
            (item.path, item.start_line) not in selected_keys for item in candidates
        ),
        route=route.name,
        warnings=warnings,
    )


def render_context_pack(pack: ContextPack) -> str:
    if pack.abstained:
        return ""
    lines = [
        f"# AdoptRank context: {pack.query}",
        "",
        f"Project: {pack.project.root_name}",
        f"Stack: {', '.join([*pack.project.languages[:4], *pack.project.frameworks[:6]]) or 'unknown'}",
        f"Estimated budget: {pack.estimated_tokens}/{pack.budget} tokens",
        "",
    ]
    if pack.external_repositories:
        lines.extend(["## External implementation evidence", ""])
        for item in pack.external_repositories:
            lines.extend(
                [
                    f"- {item.full_name}: {item.url}",
                    f"  {item.reason}",
                    *(f"  Evidence: {path}" for path in item.code_evidence),
                ]
            )
        lines.append("")
    github_snippets = [item for item in pack.snippets if item.source == "github"]
    local_snippets = [item for item in pack.snippets if item.source == "local"]
    if pack.related_paths:
        lines.extend(["## Ranked local file map", ""])
        lines.extend(f"- {path}" for path in pack.related_paths)
        lines.append("")
    if github_snippets:
        lines.extend(["## GitHub implementation context", ""])
        for item in github_snippets:
            lines.extend(
                [
                    f"### {item.repository}/{item.path} (score={item.score:.3f})",
                    f"Source: {item.url}",
                    "```",
                    item.content.rstrip(),
                    "```",
                    "",
                ]
            )
    lines.extend(["## Local implementation context", ""])
    for item in local_snippets:
        lines.extend(
            [
                f"### {item.path}:{item.start_line or 1} (score={item.score:.3f})",
                "```",
                item.content.rstrip(),
                "```",
                "",
            ]
        )
    lines.extend(["## Accounting", "", f"Excluded candidates: {pack.excluded_candidates}"])
    lines.extend(f"- {warning}" for warning in pack.warnings)
    return "\n".join(lines)
