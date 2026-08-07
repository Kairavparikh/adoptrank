import json
from pathlib import Path

from adoptrank_backend.context_dataset import build_context_pairs


def test_context_pairs_use_changed_files_and_hard_negatives(tmp_path: Path) -> None:
    (tmp_path / "webhooks.py").write_text(
        "def process_stripe_webhook(event):\n    return claim_event(event['id'])\n"
    )
    (tmp_path / "checkout.py").write_text(
        "def retry_stripe_checkout(customer):\n    return customer\n"
    )
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        json.dumps(
            {
                "task_id": "stripe",
                "query": "make Stripe webhook processing idempotent",
                "repository_path": str(tmp_path),
                "expected_files": ["webhooks.py"],
            }
        )
        + "\n"
    )
    pairs = build_context_pairs(tasks, tmp_path / "pairs.jsonl", pairs_per_task=2)
    assert pairs
    assert all(pair["positive"]["path"] == "webhooks.py" for pair in pairs)
    assert all(pair["negative"]["path"] == "checkout.py" for pair in pairs)
