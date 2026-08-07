import json
from pathlib import Path

from adoptrank_backend.context_benchmark import run_context_benchmark
from adoptrank_backend.context_pack import (
    build_context_pack,
    estimate_tokens,
    render_context_pack,
    route_context,
)
from adoptrank_backend.schemas import ExternalRepositoryEvidence


def _project(root: Path) -> None:
    (root / "payments").mkdir()
    (root / "tests").mkdir()
    (root / "payments" / "webhooks.py").write_text(
        "def claim_event(event_id):\n    return event_id\n\n"
        "def process_stripe_webhook(event):\n    return claim_event(event['id'])\n"
    )
    (root / "payments" / "checkout.py").write_text(
        "def create_checkout_session(customer):\n    return customer\n"
    )
    (root / "tests" / "test_webhooks.py").write_text(
        "from payments.webhooks import process_stripe_webhook\n\n"
        "def test_duplicate_stripe_webhook():\n    assert process_stripe_webhook({'id': 'evt_1'})\n"
    )
    (root / ".env").write_text("STRIPE_SECRET=never-include")
    (root / "hardcoded.py").write_text('API_KEY = "never-include-hardcoded"\n')


def test_context_pack_is_relevant_safe_and_budgeted(tmp_path: Path) -> None:
    _project(tmp_path)
    external = [
        ExternalRepositoryEvidence(
            full_name="example/stripe-worker",
            url="https://github.com/example/stripe-worker",
            reason="implements idempotent webhook retries",
            score=0.9,
            code_evidence=["workers/stripe.py"],
            estimated_tokens=30,
        ),
        ExternalRepositoryEvidence(
            full_name="example/unrelated-dashboard",
            url="https://github.com/example/unrelated-dashboard",
            reason="visualizes analytics",
            score=0.4,
            code_evidence=["ui/chart.tsx"],
            estimated_tokens=25,
        ),
    ]
    pack = build_context_pack(
        tmp_path,
        "add idempotent Stripe webhook retries",
        budget=700,
        external=external,
    )
    assert pack.estimated_tokens <= pack.budget
    assert pack.snippets[0].path in {"payments/webhooks.py", "tests/test_webhooks.py"}
    assert "never-include" not in pack.model_dump_json()
    assert "hardcoded.py" not in {item.path for item in pack.snippets}
    assert pack.external_repositories[0].full_name == "example/stripe-worker"
    assert len(pack.external_repositories) == 1
    assert estimate_tokens(render_context_pack(pack)) <= pack.budget
    assert all(snippet.score > 0 for snippet in pack.snippets)
    assert max(
        sum(other.path == snippet.path for other in pack.snippets) for snippet in pack.snippets
    ) <= 2


def test_narrow_operational_task_uses_small_context_route(tmp_path: Path) -> None:
    _project(tmp_path)
    route = route_context("Install development extras in CI", 8000)
    pack = build_context_pack(tmp_path, "Install development extras in CI", budget=8000)

    assert route.name == "narrow-local"
    assert route.local_budget == 900
    assert len([item for item in pack.snippets if item.source == "local"]) <= 2
    assert estimate_tokens(render_context_pack(pack)) < 1500


def test_repository_wide_task_keeps_multi_file_route() -> None:
    route = route_context("Upgrade all GitHub Actions workflows to Node 24", 8000)
    assert route.name == "multi-file"
    assert route.max_local_snippets == 12


def test_candidate_reranker_controls_second_stage_order(tmp_path: Path) -> None:
    _project(tmp_path)

    def prefer_checkout(query: str, documents: list[str]) -> list[float]:
        assert query
        return [10.0 if "checkout.py" in document else 0.0 for document in documents]

    pack = build_context_pack(
        tmp_path,
        "improve checkout processing",
        budget=800,
        candidate_reranker=prefer_checkout,
    )
    assert pack.snippets[0].path == "payments/checkout.py"


def test_benchmark_never_approves_without_controlled_results(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _project(repo)
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        json.dumps(
            {
                "task_id": "stripe-retry",
                "query": "add idempotent Stripe webhook retries",
                "repository_path": str(repo),
                "expected_files": ["payments/webhooks.py"],
            }
        )
        + "\n"
    )
    report = run_context_benchmark(tasks, tmp_path / "report.json", budget=700)
    assert report["mean_file_recall"] == 1.0
    assert report["pivot_approved"] is False
    assert report["token_reduction"] is None


def test_benchmark_approves_only_when_all_gates_pass(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _project(repo)
    tasks = tmp_path / "controlled.jsonl"
    tasks.write_text(
        json.dumps(
            {
                "task_id": "controlled-stripe-retry",
                "query": "add idempotent Stripe webhook retries",
                "repository_path": str(repo),
                "expected_files": ["payments/webhooks.py"],
                "baseline_repository_tokens": 4000,
                "baseline_task_success": True,
                "adoptrank_task_success": True,
            }
        )
        + "\n"
    )
    report = run_context_benchmark(tasks, tmp_path / "controlled-report.json", budget=700)
    assert report["token_reduction"] >= 0.30
    assert report["pivot_approved"] is True
