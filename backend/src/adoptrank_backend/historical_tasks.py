import io
import json
import re
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .code_analysis import SOURCE_EXTENSIONS

LOW_SIGNAL_SUBJECT = re.compile(
    r"(?:\btypo\b|\bformatter\b|\bformatting\b|\blint(?:ing)?\b|^chore:|^docs?:|^ci:\s*(?:fix|bump))",
    re.IGNORECASE,
)


def _git(repo: Path, *args: str, text: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def _patch_contract(repo: Path, parent: str, commit: str, paths: list[str]) -> list[dict]:
    """Build a hidden, deterministic behavior proxy from distinctive changed lines."""
    contracts = []
    for path in paths:
        diff = _git(repo, "diff", "--unified=0", parent, commit, "--", path)
        required: list[str] = []
        forbidden: list[str] = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                candidate = line[1:].strip()
                target = required
            elif line.startswith("-") and not line.startswith("---"):
                candidate = line[1:].strip()
                target = forbidden
            else:
                continue
            if (
                8 <= len(candidate) <= 200
                and not candidate.startswith(("#", "//", "/*", "*"))
                and candidate not in target
            ):
                target.append(candidate)
        if required:
            contracts.append(
                {
                    "path": path,
                    "required_lines": required[:5],
                    "forbidden_lines": forbidden[:3],
                }
            )
    return contracts


def generate_historical_tasks(repo: Path, output: Path, limit: int = 50) -> list[dict]:
    repo = repo.resolve()
    commits = _git(repo, "rev-list", "--no-merges", "HEAD").splitlines()
    tasks: list[dict] = []
    for commit in commits:
        if len(tasks) >= limit:
            break
        parents = _git(repo, "show", "-s", "--format=%P", commit).strip().split()
        if len(parents) != 1:
            continue
        parent = parents[0]
        subject = _git(repo, "show", "-s", "--format=%s", commit).strip()
        if len(subject) < 12 or LOW_SIGNAL_SUBJECT.search(subject):
            continue
        changes = _git(repo, "diff", "--name-status", parent, commit).splitlines()
        expected_files: list[str] = []
        changed_files: list[str] = []
        created_files: list[str] = []
        for line in changes:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0], parts[-1]
            if Path(path).suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            changed_files.append(path)
            if status.startswith("A"):
                created_files.append(path)
            elif not status.startswith("D"):
                expected_files.append(path)
        if not expected_files or len(changed_files) > 30:
            continue
        patch_contract = _patch_contract(repo, parent, commit, expected_files)
        if not patch_contract:
            continue
        tasks.append(
            {
                "task_id": commit[:12],
                "query": subject,
                "repository_path": str(repo),
                "base_commit": parent,
                "target_commit": commit,
                "expected_files": expected_files,
                "changed_files": changed_files,
                "created_files": created_files,
                "patch_contract": patch_contract,
                "label_source": "hidden_historical_diff_contract",
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(task) + "\n" for task in tasks))
    return tasks


@contextmanager
def materialize_task_repository(repo: Path, commit: str | None):
    if not commit:
        yield repo
        return
    archive = _git(repo, "archive", "--format=tar", commit, text=False)
    with tempfile.TemporaryDirectory(prefix="adoptrank-benchmark-") as directory:
        root = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(root, filter="data")
        yield root
