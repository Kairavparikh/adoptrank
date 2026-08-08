import json
from pathlib import Path

from adoptrank_backend.claude_integration import _stream_telemetry, build_claude_launch, run_claude_launch


def test_dry_run_builds_bounded_context_and_redacted_audit(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "payments.py").write_text("def retry_payment(key: str):\n    return key\n")
    (tmp_path / "README.md").write_text("Payments API with retry handling")
    audit = tmp_path / "audit.json"

    launch = build_claude_launch(
        "add idempotent payment retries",
        tmp_path,
        budget=700,
        include_external=False,
        audit_path=audit,
    )
    assert "claude" == launch.command[0]
    assert "--append-system-prompt" in launch.command
    assert launch.pack.budget == 700
    assert run_claude_launch(launch, tmp_path, dry_run=True) == 0

    payload = json.loads(audit.read_text())
    assert payload["status"] == "dry-run"
    assert payload["context_estimated_tokens"] <= 700
    assert "retry_payment" not in audit.read_text()


def test_stream_telemetry_keeps_metadata_not_tool_output() -> None:
    output = "\n".join(
        [
            '{"message":{"content":[{"type":"tool_use","id":"read-1","name":"Read","input":{"file_path":"src/payments.py"}}]}}',
            '{"message":{"content":[{"type":"tool_result","tool_use_id":"read-1","content":"private source code"}]}}',
            '{"type":"result","usage":{"input_tokens":100,"cache_read_input_tokens":20,"output_tokens":10},"total_cost_usd":0.03}',
        ]
    )
    telemetry = _stream_telemetry(output)
    assert telemetry["provider_input_tokens"] == 100
    assert telemetry["unique_files_read"] == ["src/payments.py"]
    assert "private source code" not in json.dumps(telemetry)
