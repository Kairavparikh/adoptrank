import json
import subprocess

from adoptrank_backend.claude_benchmark import (
    _parse_stream,
    _provider_failure,
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
