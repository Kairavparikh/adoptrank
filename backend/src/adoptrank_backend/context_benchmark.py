import json
import time
from pathlib import Path

from .context_pack import build_context_pack, estimate_tokens, render_context_pack
from .historical_tasks import materialize_task_repository


def _recall(expected: list[str], retrieved: set[str]) -> float:
    if not expected:
        return 1.0
    normalized = {item.replace("\\", "/") for item in retrieved}
    hits = sum(path.replace("\\", "/") in normalized for path in expected)
    return hits / len(expected)


def run_context_benchmark(
    tasks_path: Path,
    output_path: Path,
    budget: int = 8000,
    candidate_reranker=None,
    task_prefix: str | None = None,
) -> dict:
    tasks = [
        json.loads(line)
        for line in tasks_path.read_text().splitlines()
        if line.strip()
    ]
    if task_prefix:
        tasks = [task for task in tasks if str(task.get("task_id", "")).startswith(task_prefix)]
    if not tasks:
        raise ValueError("The benchmark task file is empty")

    results = []
    for index, task in enumerate(tasks, 1):
        required = {"query", "repository_path", "expected_files"}
        missing = required - set(task)
        if missing:
            raise ValueError(f"Task {index} is missing: {', '.join(sorted(missing))}")
        with materialize_task_repository(
            Path(task["repository_path"]), task.get("base_commit")
        ) as repository_root:
            started = time.perf_counter()
            pack = build_context_pack(
                repository_root,
                task["query"],
                budget,
                candidate_reranker=candidate_reranker,
            )
            context_latency_ms = (time.perf_counter() - started) * 1000
        retrieved_files = {snippet.path for snippet in pack.snippets} | set(pack.related_paths)
        results.append(
            {
                "task_id": task.get("task_id", str(index)),
                "query": task["query"],
                "file_recall": (
                    None if pack.abstained else _recall(task["expected_files"], retrieved_files)
                ),
                "abstained": pack.abstained,
                "retrieved_files": sorted(retrieved_files),
                "estimated_context_tokens": estimate_tokens(render_context_pack(pack)),
                "context_latency_ms": context_latency_ms,
                "baseline_repository_tokens": task.get("baseline_repository_tokens"),
                "baseline_task_success": task.get("baseline_task_success"),
                "adoptrank_task_success": task.get("adoptrank_task_success"),
            }
        )

    engaged = [item for item in results if item["file_recall"] is not None]
    mean_recall = sum(item["file_recall"] for item in engaged) / len(engaged) if engaged else 0.0
    abstention_rate = sum(item["abstained"] for item in results) / len(results)
    mean_tokens = sum(item["estimated_context_tokens"] for item in results) / len(results)
    sorted_latencies = sorted(item["context_latency_ms"] for item in results)
    p95_latency_ms = sorted_latencies[
        min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
    ]
    comparable = [
        item
        for item in results
        if item["baseline_repository_tokens"] is not None
        and item["baseline_task_success"] is not None
        and item["adoptrank_task_success"] is not None
    ]
    token_reduction = None
    baseline_success = None
    adoptrank_success = None
    if comparable:
        baseline_tokens = sum(item["baseline_repository_tokens"] for item in comparable)
        context_tokens = sum(item["estimated_context_tokens"] for item in comparable)
        token_reduction = 1.0 - context_tokens / max(1, baseline_tokens)
        baseline_success = sum(bool(item["baseline_task_success"]) for item in comparable) / len(comparable)
        adoptrank_success = sum(bool(item["adoptrank_task_success"]) for item in comparable) / len(comparable)

    gates = {
        "file_recall_at_least_0_80": mean_recall >= 0.80,
        "abstention_at_most_0_25": abstention_rate <= 0.25,
        "context_p95_below_3000_ms": p95_latency_ms < 3000,
        "token_reduction_at_least_0_30": token_reduction is not None and token_reduction >= 0.30,
        "task_success_within_0_05": (
            baseline_success is not None
            and adoptrank_success is not None
            and adoptrank_success >= baseline_success - 0.05
        ),
        "has_controlled_task_results": bool(comparable) and len(comparable) == len(results),
    }
    report = {
        "task_count": len(results),
        "budget": budget,
        "mean_file_recall": mean_recall,
        "abstention_rate": abstention_rate,
        "mean_estimated_context_tokens": mean_tokens,
        "context_p95_latency_ms": p95_latency_ms,
        "token_reduction": token_reduction,
        "baseline_task_success": baseline_success,
        "adoptrank_task_success": adoptrank_success,
        "gates": gates,
        "pivot_approved": all(gates.values()),
        "results": results,
        "limitations": [
            "Token counts are estimates until Claude telemetry supplies provider-reported usage.",
            "Task-success fields must come from controlled Claude Code runs; this harness does not invent them.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
