"""Language-neutral, replayable ingestion events shared by Python, Rust, and Spark."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from .schemas import RepositorySnapshot


EVENT_SCHEMA_VERSION = "adoptrank.repository-event.v1"
EventType = Literal[
    "RepositoryDiscovered",
    "RepositorySnapshotCaptured",
    "CommitObserved",
    "FileDiffExtracted",
    "SymbolChanged",
    "CodeChunkIndexed",
    "IndexInvalidated",
]


class RepositoryIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    html_url: HttpUrl
    commit_sha: str | None = None


class EventProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    producer: str
    query: str | None = None


class RepositoryEvent(BaseModel):
    """Stable envelope. ``event_id`` is content-addressed for idempotent replay."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["adoptrank.repository-event.v1"] = EVENT_SCHEMA_VERSION
    event_type: EventType
    event_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime
    repository: RepositoryIdentity
    payload: dict[str, object]
    provenance: EventProvenance

    @model_validator(mode="after")
    def ensure_utc(self) -> "RepositoryEvent":
        if self.observed_at.tzinfo is None:
            self.observed_at = self.observed_at.replace(tzinfo=UTC)
        return self


def _canonical_json(value: object) -> str:
    # Keep Unicode literal so Python matches serde_json's default encoding.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def event_id_for(
    event_type: EventType,
    observed_at: datetime,
    full_name: str,
    payload: dict[str, object],
) -> str:
    """Create the same deterministic id in every worker runtime."""
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    body = {
        "event_type": event_type,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "repository": full_name.lower(),
        "payload": payload,
    }
    return hashlib.sha256(_canonical_json(body).encode()).hexdigest()


def snapshot_event(snapshot: RepositorySnapshot, producer: str = "python-collector") -> RepositoryEvent:
    payload = snapshot.model_dump(mode="json")
    observed_at = snapshot.captured_at
    return RepositoryEvent(
        event_type="RepositorySnapshotCaptured",
        event_id=event_id_for("RepositorySnapshotCaptured", observed_at, snapshot.full_name, payload),
        observed_at=observed_at,
        repository=RepositoryIdentity(
            full_name=snapshot.full_name,
            html_url=snapshot.html_url,
            commit_sha=snapshot.indexed_commit_sha,
        ),
        payload=payload,
        provenance=EventProvenance(source="github", producer=producer, query=snapshot.source_query or None),
    )


def snapshot_from_event(event: RepositoryEvent) -> RepositorySnapshot:
    if event.event_type != "RepositorySnapshotCaptured":
        raise ValueError(f"Expected RepositorySnapshotCaptured, got {event.event_type}")
    return RepositorySnapshot.model_validate(event.payload)


def write_events(events: list[RepositoryEvent], output: str) -> None:
    with open(output, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(event.model_dump_json() + "\n")
