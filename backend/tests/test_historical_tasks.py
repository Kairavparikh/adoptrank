import subprocess
from pathlib import Path

from adoptrank_backend.context_benchmark import run_context_benchmark
from adoptrank_backend.claude_benchmark import _run_task_evaluator
from adoptrank_backend.historical_tasks import generate_historical_tasks, materialize_task_repository


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_generates_and_replays_parent_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "benchmark@example.com")
    _git(repo, "config", "user.name", "Benchmark")
    source = repo / "payments.py"
    source.write_text("def process_webhook(event):\n    return event\n")
    _git(repo, "add", "payments.py")
    _git(repo, "commit", "-m", "Add webhook processing")
    source.write_text(
        "def process_webhook(event):\n    return claim_idempotency_key(event['id'])\n"
    )
    _git(repo, "add", "payments.py")
    _git(repo, "commit", "-m", "Make webhook processing idempotent")

    tasks_path = tmp_path / "tasks.jsonl"
    tasks = generate_historical_tasks(repo, tasks_path, limit=5)
    assert len(tasks) == 1
    assert tasks[0]["expected_files"] == ["payments.py"]
    assert tasks[0]["patch_contract"][0]["required_lines"]
    with materialize_task_repository(repo, tasks[0]["base_commit"]) as parent:
        success, score, assertions, _ = _run_task_evaluator(parent, tasks[0])
        assert success is False
        assert score is not None and score < 1
        assert assertions > 0
    with materialize_task_repository(repo, tasks[0]["target_commit"]) as target:
        success, score, assertions, _ = _run_task_evaluator(target, tasks[0])
        assert success is True
        assert score == 1
        assert assertions > 0
    report = run_context_benchmark(tasks_path, tmp_path / "report.json", budget=700)
    assert report["task_count"] == 1
    assert report["results"][0]["file_recall"] == 1.0
