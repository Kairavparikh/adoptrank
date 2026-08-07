import ast
import asyncio
import re
from collections import Counter
from pathlib import Path, PurePosixPath

import httpx

from .config import settings
from .schemas import RepositorySnapshot

SOURCE_EXTENSIONS = {
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".kt",
    ".swift",
    ".rb",
    ".cpp",
    ".cc",
    ".c",
    ".h",
}
LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c",
}
SKIP_PARTS = {"node_modules", "vendor", "dist", "build", ".venv", "venv", "target", "generated"}
DEPENDENCY_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "gemfile",
}
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
GENERIC_SYMBOL = re.compile(
    r"(?:def|class|function|fn|func|interface|struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
GENERIC_IMPORT = re.compile(
    r"(?:import|from|require\s*\(|use|package)\s*[('\"]?([A-Za-z0-9_@./:-]+)", re.MULTILINE
)
STOP_WORDS = {
    "const",
    "return",
    "self",
    "this",
    "from",
    "import",
    "class",
    "function",
    "public",
    "private",
    "string",
    "number",
    "true",
    "false",
    "none",
    "async",
    "await",
    "with",
    "that",
    "tests",
    "test",
}


def _is_source(path: str) -> bool:
    item = PurePosixPath(path.lower())
    return item.suffix in SOURCE_EXTENSIONS and not (set(item.parts) & SKIP_PARTS)


def _priority(path: str) -> tuple[int, int, str]:
    lowered = path.lower()
    is_test = "test" in PurePosixPath(lowered).parts or PurePosixPath(lowered).name.startswith("test")
    is_example = any(
        part in {"example", "examples", "demo", "demos"} for part in PurePosixPath(lowered).parts
    )
    return (0 if is_test else 1 if is_example else 2, lowered.count("/"), lowered)


def _extract_python(content: str) -> tuple[list[str], list[str]]:
    symbols: list[str] = []
    dependencies: list[str] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return symbols, dependencies
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            dependencies.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            dependencies.append(node.module.split(".")[0])
    return symbols, dependencies


def _tree_sitter_extract(path: str, content: str) -> tuple[list[str], list[str], list[str]]:
    from tree_sitter_language_pack import get_parser

    language = LANGUAGE_BY_EXTENSION.get(PurePosixPath(path.lower()).suffix)
    if not language:
        return [], [], []
    tree = get_parser(language).parse(content.encode("utf-8", errors="ignore"))
    symbols: list[str] = []
    imports: list[str] = []
    chunks: list[str] = []
    stack = [tree.root_node]
    symbol_types = {
        "function_definition",
        "function_declaration",
        "method_definition",
        "class_definition",
        "class_declaration",
        "struct_item",
        "enum_item",
        "trait_item",
        "function_item",
    }
    import_types = {"import_statement", "import_declaration", "use_declaration", "use_list", "package_clause"}
    source = content.encode("utf-8", errors="ignore")
    while stack:
        node = stack.pop()
        if node.type in symbol_types:
            name = node.child_by_field_name("name")
            if name:
                symbols.append(source[name.start_byte : name.end_byte].decode("utf-8", errors="ignore"))
            snippet = source[node.start_byte : min(node.end_byte, node.start_byte + 2400)].decode(
                "utf-8", errors="ignore"
            )
            chunks.append(f"File: {path}\n{snippet}")
        elif node.type in import_types:
            imports.extend(
                IDENTIFIER.findall(source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore"))
            )
        stack.extend(reversed(node.children))
    return symbols, imports, chunks


def extract_code_evidence(files: list[tuple[str, str]], all_paths: list[str], commit_sha: str) -> dict:
    symbols: list[str] = []
    dependencies: list[str] = []
    chunks: list[str] = []
    terms: Counter[str] = Counter()
    for path, content in files:
        try:
            file_symbols, file_dependencies, file_chunks = _tree_sitter_extract(path, content)
        except Exception:
            file_chunks = []
            if path.lower().endswith(".py"):
                file_symbols, file_dependencies = _extract_python(content)
            else:
                file_symbols = GENERIC_SYMBOL.findall(content)
                file_dependencies = GENERIC_IMPORT.findall(content)
        symbols.extend(file_symbols)
        dependencies.extend(file_dependencies)
        chunks.extend(file_chunks)
        terms.update(
            token.lower()
            for token in IDENTIFIER.findall(" ".join([path, *file_symbols, *file_dependencies]))
            if token.lower() not in STOP_WORDS
        )
    source_paths = [path for path in all_paths if _is_source(path)]
    test_paths = [path for path in source_paths if "test" in path.lower()]
    example_paths = [path for path in source_paths if any(x in path.lower() for x in ("example", "demo"))]
    evidence_paths = [path for path, _ in files]
    architecture = (
        f"{len(source_paths)} source files; {len(test_paths)} test files; {len(example_paths)} examples; "
        f"key symbols: {', '.join(list(dict.fromkeys(symbols))[:15])}; dependencies: "
        f"{', '.join(list(dict.fromkeys(dependencies))[:15])}"
    )
    return {
        "indexed_commit_sha": commit_sha,
        "source_file_count": len(source_paths),
        "test_file_count": len(test_paths),
        "example_file_count": len(example_paths),
        "dependency_count": len(set(dependencies)),
        "symbol_count": len(set(symbols)),
        "code_terms": [term for term, _ in terms.most_common(60)],
        "code_evidence_paths": evidence_paths,
        "architecture_summary": architecture,
        "code_chunks": chunks[:40],
        "quality_score": min(
            1.0, (len(test_paths) / max(1, len(source_paths))) * 4 + (0.2 if example_paths else 0.0)
        ),
        "depth_score": min(1.0, len(set(symbols)) / max(10, len(files) * 8)),
        "originality_score": min(1.0, len(set(terms)) / 80.0),
    }


class GitHubCodeAnalyzer:
    def __init__(self, token: str | None = None) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AdoptRank/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(base_url=settings.github_api_url, headers=headers, timeout=30)
        self.raw = httpx.AsyncClient(timeout=30, headers={"User-Agent": "AdoptRank/0.1"})

    async def close(self) -> None:
        await self.client.aclose()
        await self.raw.aclose()

    async def analyze(self, repo: RepositorySnapshot, file_budget: int = 8) -> RepositorySnapshot:
        metadata = await self.client.get(f"/repos/{repo.full_name}")
        metadata.raise_for_status()
        branch = metadata.json()["default_branch"]
        branch_response = await self.client.get(f"/repos/{repo.full_name}/branches/{branch}")
        branch_response.raise_for_status()
        commit_sha = branch_response.json()["commit"]["sha"]
        tree_response = await self.client.get(
            f"/repos/{repo.full_name}/git/trees/{commit_sha}", params={"recursive": "1"}
        )
        tree_response.raise_for_status()
        paths = [item["path"] for item in tree_response.json().get("tree", []) if item.get("type") == "blob"]
        candidates = sorted((path for path in paths if _is_source(path)), key=_priority)
        test_candidates = [path for path in candidates if "test" in path.lower()]
        example_candidates = [
            path
            for path in candidates
            if any(
                part in {"example", "examples", "demo", "demos"} for part in PurePosixPath(path.lower()).parts
            )
        ]
        core_candidates = [path for path in candidates if path not in {*test_candidates, *example_candidates}]
        manifests = [path for path in paths if PurePosixPath(path.lower()).name in DEPENDENCY_FILES]
        selected_sources = [
            *test_candidates[: min(2, file_budget)],
            *example_candidates[: min(2, max(0, file_budget - 2))],
            *core_candidates[: max(0, file_budget - 4)],
        ]
        if len(selected_sources) < file_budget:
            selected_sources.extend(path for path in candidates if path not in selected_sources)
        selected = list(dict.fromkeys([*selected_sources[:file_budget], *manifests[:2]]))

        async def fetch(path: str) -> tuple[str, str] | None:
            url = f"https://raw.githubusercontent.com/{repo.full_name}/{commit_sha}/{path}"
            response = await self.raw.get(url)
            if response.status_code != 200 or len(response.content) > 250_000:
                return None
            return path, response.text[:250_000]

        fetched = [item for item in await asyncio.gather(*(fetch(path) for path in selected)) if item]
        return repo.model_copy(update=extract_code_evidence(fetched, paths, commit_sha))


async def enrich_snapshot_file(source: Path, output: Path, limit: int, files_per_repo: int) -> int:
    with source.open() as handle:
        snapshots = [RepositorySnapshot.model_validate_json(line) for line in handle if line.strip()]
    previous: dict[str, RepositorySnapshot] = {}
    if output.exists() and output.resolve() != source.resolve():
        with output.open() as handle:
            previous = {
                snapshot.full_name: snapshot
                for line in handle
                if line.strip()
                for snapshot in [RepositorySnapshot.model_validate_json(line)]
            }
    prioritized = sorted(snapshots, key=lambda item: (item.stars, item.pypi_downloads_30d or 0), reverse=True)
    selected = {item.full_name for item in prioritized[:limit]}
    analyzer = GitHubCodeAnalyzer(settings.github_token)
    indexed = 0
    enriched: list[RepositorySnapshot] = []
    try:
        for repo in snapshots:
            if repo.full_name not in selected:
                enriched.append(repo)
                continue
            try:
                enriched.append(await analyzer.analyze(repo, files_per_repo))
                indexed += 1
            except httpx.HTTPError:
                enriched.append(previous.get(repo.full_name, repo))
    finally:
        await analyzer.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        for repo in enriched:
            handle.write(repo.model_dump_json() + "\n")
    if settings.database_url:
        from .storage import persist_code_analysis

        await persist_code_analysis(settings.database_url, enriched)
    return indexed
