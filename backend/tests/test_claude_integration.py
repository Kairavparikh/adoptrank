import json
from pathlib import Path

from adoptrank_backend.claude_integration import build_claude_launch, run_claude_launch


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
