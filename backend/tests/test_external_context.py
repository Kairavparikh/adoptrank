from datetime import UTC, datetime

from adoptrank_backend.external_context import select_external_code
from adoptrank_backend.schemas import RankedRepository, RepositorySnapshot


def test_external_context_is_pinned_relevant_and_budgeted() -> None:
    repo = RepositorySnapshot(
        full_name="example/stripe-worker",
        html_url="https://github.com/example/stripe-worker",
        captured_at=datetime.now(UTC),
        description="Stripe webhook worker",
        language="Python",
        license_spdx="MIT",
        indexed_commit_sha="abc123",
        code_chunks=[
            "File: workers/stripe.py\ndef retry_webhook(event_id):\n    return claim_once(event_id)",
            "File: ui/chart.py\ndef render_chart(points):\n    return points",
        ],
    )
    ranked = [
        RankedRepository(
            full_name=repo.full_name,
            url=repo.html_url,
            description=repo.description,
            score=0.9,
            adoption_probability=0.8,
            reason="implements Stripe webhook retries",
            language="Python",
            license="MIT",
            updated_at=None,
        )
    ]
    evidence = select_external_code(
        "add Stripe webhook retries", ranked, {repo.full_name: repo}, token_budget=200
    )
    assert len(evidence) == 1
    assert evidence[0].path == "workers/stripe.py"
    assert evidence[0].commit_sha == "abc123"
    assert evidence[0].source_url.endswith("/blob/abc123/workers/stripe.py")
    assert sum(item.estimated_tokens for item in evidence) <= 200
