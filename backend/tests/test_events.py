from datetime import UTC, datetime

from adoptrank_backend.events import EVENT_SCHEMA_VERSION, snapshot_event, snapshot_from_event
from adoptrank_backend.parity import compare_events
from adoptrank_backend.schemas import RepositorySnapshot


def _snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        full_name="acme/engine",
        html_url="https://github.com/acme/engine",
        captured_at=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        stars=42,
        source_query="matching engine",
    )


def test_snapshot_event_is_deterministic_and_round_trips() -> None:
    first = snapshot_event(_snapshot())
    second = snapshot_event(_snapshot())
    assert first.schema_version == EVENT_SCHEMA_VERSION
    assert first.event_id == second.event_id
    assert snapshot_from_event(first).full_name == "acme/engine"


def test_parity_requires_identical_ids_and_payloads() -> None:
    event = snapshot_event(_snapshot())
    report = compare_events([event], [event])
    assert report.passed
    assert report.matching_payloads == 1
