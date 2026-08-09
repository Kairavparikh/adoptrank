import json
import subprocess

import pytest

from adoptrank_backend.claude_benchmark import (
    _parse_stream,
    _provider_failure,
    run_claude_benchmark,
    _summary,
    _usage,
)


def test_claude_usage_includes_cached_input() -> None:
    usage = _usage(
        {
            "total_cost_usd": 0.12,
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 300,
                "output_tokens": 50,
            },
        }
    )
    assert usage["total_input_tokens"] == 600
    assert usage["output_tokens"] == 50
    assert usage["cost_usd"] == 0.12


def test_one_successful_pair_cannot_approve_pivot() -> None:
    run = {
        "task_success": True,
        "total_input_tokens": 1000,
        "cost_usd": 0.1,
        "retrieval_file_recall": None,
        "context_latency_ms": 0.0,
    }
    adoptrank = run | {
        "total_input_tokens": 600,
        "cost_usd": 0.06,
        "retrieval_file_recall": 1.0,
        "context_latency_ms": 20.0,
    }
    summary = _summary(
        [{"runs": [run | {"condition": "baseline"}, adoptrank | {"condition": "adoptrank"}]}]
    )
    assert summary["processed_input_token_reduction"] == 0.4
    assert summary["pivot_approved"] is False
    assert summary["gates"]["at_least_30_controlled_tasks"] is False
    assert summary["unique_controlled_tasks"] == 1


def test_stream_parser_measures_repository_tool_output() -> None:
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "read-1",
                        "name": "Read",
                        "input": {"file_path": "/repo/payments.py"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "read-1",
                        "content": "def process_webhook(event):\n    return event",
                    }
                ]
            },
        },
        {
            "type": "result",
            "result": "done",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    ]
    result, trace = _parse_stream("\n".join(json.dumps(event) for event in events))
    assert result["result"] == "done"
    assert trace["repository_tool_output_estimated_tokens"] > 0
    assert trace["unique_files_read"] == ["/repo/payments.py"]
    assert trace["tool_calls"] == {"Read": 1}


def test_provider_billing_failure_is_not_scored() -> None:
    completed = subprocess.CompletedProcess(
        args=["claude"], returncode=1, stdout="", stderr=""
    )
    assert _provider_failure(completed, {"result": "Credit balance is too low"}) == (
        "Credit balance is too low"
    )

    valid = {
        "condition": "baseline",
        "benchmark_valid": True,
        "task_success": True,
        "total_input_tokens": 100,
        "cost_usd": 0.01,
        "context_latency_ms": 0.0,
    }
    invalid = valid | {
        "condition": "adoptrank",
        "benchmark_valid": False,
        "provider_failure": "Credit balance is too low",
    }
    summary = _summary([{"task_id": "billing-failure", "runs": [valid, invalid]}])
    assert summary["attempted_paired_tasks"] == 1
    assert summary["paired_tasks"] == 0
    assert summary["scored_tasks"] == 0
    assert summary["pivot_approved"] is False


def test_legacy_nonzero_exit_pair_is_not_scored() -> None:
    base = {
        "condition": "baseline",
        "exit_code": 0,
        "task_success": True,
        "total_input_tokens": 100,
        "cost_usd": 0.01,
        "context_latency_ms": 0.0,
    }
    failed = base | {"condition": "adoptrank", "exit_code": 1}
    summary = _summary([{"task_id": "legacy", "runs": [base, failed]}])
    assert summary["attempted_paired_tasks"] == 1
    assert summary["paired_tasks"] == 0


def test_benchmark_checkpoints_each_condition_and_resumes(tmp_path, monkeypatch) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        "\n".join(
            json.dumps({"task_id": f"task-{index}", "query": f"task {index}"})
            for index in range(2)
        )
        + "\n"
    )
    output = tmp_path / "report.json"
    calls = []

    def fake_run(task, condition, *args, **kwargs):
        calls.append((task["task_id"], condition))
        if len(calls) == 3:
            raise RuntimeError("transient reranker failure")
        return {
            "condition": condition,
            "benchmark_valid": True,
            "task_success": True,
            "total_input_tokens": 100,
            "repository_tool_output_estimated_tokens": 50,
            "context_estimated_tokens": 10 if condition == "adoptrank" else 0,
            "cost_usd": 0.01,
            "retrieval_file_recall": 1.0 if condition == "adoptrank" else None,
            "retrieval_abstained": False,
            "context_latency_ms": 10.0 if condition == "adoptrank" else 0.0,
        }

    monkeypatch.setattr("adoptrank_backend.claude_benchmark._run_condition", fake_run)
    with pytest.raises(RuntimeError, match="transient reranker"):
        run_claude_benchmark(tasks, output, max_tasks=2, max_budget_usd=0.01)

    checkpoint = json.loads(output.read_text())
    assert checkpoint["completed_pair_count"] == 1
    assert checkpoint["benchmark_complete"] is False
    assert checkpoint["stopped_early"] is True
    assert len(checkpoint["results"][0]["runs"]) == 2

    def resumed_run(task, condition, *args, **kwargs):
        calls.append((task["task_id"], condition))
        return fake_run(task, condition, *args, **kwargs)

    monkeypatch.setattr("adoptrank_backend.claude_benchmark._run_condition", resumed_run)
    report = run_claude_benchmark(
        tasks, output, max_tasks=2, max_budget_usd=0.01, resume=True
    )
    assert report["completed_pair_count"] == 2
    assert report["benchmark_complete"] is True
    assert report["stopped_early"] is False
    assert report["maximum_additional_authorized_cost_usd"] == 0
    assert calls[:2] == [("task-0", "baseline"), ("task-0", "adoptrank")]


def test_resume_discards_invalid_provider_condition(tmp_path, monkeypatch) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps({"task_id": "task-0", "query": "fix behavior"}) + "\n")
    output = tmp_path / "report.json"
    calls = []

    def run_once(task, condition, *args, **kwargs):
        calls.append(condition)
        return {
            "condition": condition,
            "benchmark_valid": len(calls) == 1,
            "provider_failure": None if len(calls) == 1 else "Credit balance is too low",
            "task_success": True,
            "total_input_tokens": 100,
            "repository_tool_output_estimated_tokens": 50,
            "context_estimated_tokens": 0,
            "cost_usd": 0.01 if len(calls) == 1 else 0,
            "retrieval_file_recall": None,
            "retrieval_abstained": False,
            "context_latency_ms": 0.0,
        }

    monkeypatch.setattr("adoptrank_backend.claude_benchmark._run_condition", run_once)
    partial = run_claude_benchmark(tasks, output, max_budget_usd=0.01)
    assert partial["benchmark_complete"] is False

    def valid_run(task, condition, *args, **kwargs):
        calls.append(condition)
        return run_once(task, condition, *args, **kwargs) | {
            "benchmark_valid": True,
            "provider_failure": None,
        }

    monkeypatch.setattr("adoptrank_backend.claude_benchmark._run_condition", valid_run)
    resumed = run_claude_benchmark(
        tasks, output, max_budget_usd=0.01, resume=True
    )
    assert resumed["benchmark_complete"] is True
    assert resumed["completed_pair_count"] == 1
    assert [run["condition"] for run in resumed["results"][0]["runs"]] == [
        "baseline",
        "adoptrank",
    ]


def test_abstention_reuses_baseline_without_second_call(tmp_path, monkeypatch) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps({"task_id": "bump", "query": "Bump package from 1 to 2"}) + "\n")
    output = tmp_path / "report.json"
    calls = []

    def baseline(task, condition, *args, **kwargs):
        calls.append(condition)
        return {
            "condition": condition,
            "benchmark_valid": True,
            "task_success": True,
            "total_input_tokens": 100,
            "repository_tool_output_estimated_tokens": 50,
            "context_estimated_tokens": 0,
            "cost_usd": 0.01,
            "retrieval_file_recall": None,
            "retrieval_abstained": False,
            "context_latency_ms": 0.0,
        }

    monkeypatch.setattr("adoptrank_backend.claude_benchmark._run_condition", baseline)
    report = run_claude_benchmark(tasks, output, max_budget_usd=0.01)
    assert calls == ["baseline"]
    assert report["results"][0]["runs"][1]["reused_baseline"] is True
    assert report["summary"]["retrieval_abstention_rate"] == 1.0
