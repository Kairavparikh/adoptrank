import json
import subprocess
from pathlib import Path

from adoptrank_backend.benchmark_corpus import prepare_public_benchmark


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_public_benchmark_namespaces_tasks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "benchmark@example.com")
    _git(source, "config", "user.name", "Benchmark")
    code = source / "engine.py"
    code.write_text("def run():\n    return 1\n")
    _git(source, "add", "engine.py")
    _git(source, "commit", "-m", "add engine")
    code.write_text("def run():\n    return 2\n")
    _git(source, "add", "engine.py")
    _git(source, "commit", "-m", "improve engine")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"repositories": [{"full_name": "example/engine", "url": str(source)}]})
    )
    tasks = prepare_public_benchmark(
        manifest,
        tmp_path / "cache",
        tmp_path / "tasks.jsonl",
        depth=20,
        enrich_pull_requests=False,
    )

    assert len(tasks) == 1
    assert tasks[0]["task_id"].startswith("example/engine@")
    assert tasks[0]["source_repository"] == "example/engine"
