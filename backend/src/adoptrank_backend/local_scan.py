import json
import os
import re
import tomllib
from collections import Counter
from pathlib import Path

import pathspec

from .code_analysis import LANGUAGE_BY_EXTENSION, _tree_sitter_extract
from .schemas import ProjectContext

DENIED_NAMES = {".env", ".npmrc", ".pypirc", "credentials", "credentials.json", "id_rsa", "id_ed25519"}
DENIED_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", ".next", "vendor"}
SECRET_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|password|token|private[_-]?key)\s*[:=]\s*"
    r"(?:['\"][^'\"\n]{8,}['\"]|(?:ghp_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_-]{8,})",
    re.I,
)
MANIFESTS = {"pyproject.toml", "package.json", "requirements.txt", "cargo.toml", "go.mod"}


def _ignored(root: Path):
    gitignore = root / ".gitignore"
    lines = gitignore.read_text(errors="ignore").splitlines() if gitignore.exists() else []
    return pathspec.GitIgnoreSpec.from_lines(lines)


def scan_project(root: Path, max_files: int = 120, max_bytes: int = 1_000_000) -> ProjectContext:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Project root does not exist: {root}")
    ignored = _ignored(root)
    languages = Counter()
    dependencies = set()
    frameworks = set()
    symbols = []
    consumed = 0
    scanned = 0
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [
            d
            for d in dirs
            if d not in DENIED_PARTS
            and not ignored.match_file(str((current_path / d).relative_to(root)) + "/")
        ]
        for name in sorted(files):
            path = current_path / name
            relative = str(path.relative_to(root))
            if scanned >= max_files or consumed >= max_bytes:
                break
            if name.lower() in DENIED_NAMES or name.startswith(".env") or ignored.match_file(relative):
                continue
            extension = path.suffix.lower()
            is_manifest = name.lower() in MANIFESTS
            if extension not in LANGUAGE_BY_EXTENSION and not is_manifest:
                continue
            if path.stat().st_size > 100_000:
                continue
            content = path.read_text(errors="ignore")
            consumed += len(content.encode())
            scanned += 1
            if SECRET_PATTERN.search(content):
                continue
            if extension in LANGUAGE_BY_EXTENSION:
                language = LANGUAGE_BY_EXTENSION[extension]
                languages[language] += 1
                try:
                    file_symbols, imports, _ = _tree_sitter_extract(relative, content)
                except Exception:
                    file_symbols, imports = [], []
                symbols.extend(file_symbols[:20])
                dependencies.update(
                    dependency
                    for dependency in imports
                    if dependency.lower() not in {"from", "import", "include", "require", "use"}
                )
            if name == "package.json":
                try:
                    package = json.loads(content)
                    dependencies.update((package.get("dependencies") or {}).keys())
                    dependencies.update((package.get("devDependencies") or {}).keys())
                except json.JSONDecodeError:
                    pass
            elif name == "pyproject.toml":
                try:
                    project = tomllib.loads(content).get("project", {})
                    dependencies.update(
                        str(x).split(" ")[0].split(">=")[0] for x in project.get("dependencies", [])
                    )
                except tomllib.TOMLDecodeError:
                    pass
            elif name == "requirements.txt":
                dependencies.update(
                    line.split("==")[0].split(">=")[0].strip()
                    for line in content.splitlines()
                    if line and not line.startswith("#")
                )
    framework_names = {
        "next",
        "react",
        "fastapi",
        "django",
        "flask",
        "torch",
        "tensorflow",
        "spark",
        "kafka",
        "redis",
    }
    frameworks.update(dep for dep in dependencies if dep.lower().strip("@") in framework_names)
    summary = f"Local project with {scanned} safe files; primary languages: {', '.join(x for x, _ in languages.most_common(4))}; dependencies: {', '.join(sorted(dependencies)[:30])}"
    return ProjectContext(
        root_name=root.name,
        languages=[x for x, _ in languages.most_common()],
        frameworks=sorted(frameworks),
        dependencies=sorted(dependencies)[:100],
        symbols=list(dict.fromkeys(symbols))[:100],
        summary=summary,
    )
