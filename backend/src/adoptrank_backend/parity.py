"""Shadow-mode parity checks for Python, Rust, and Spark data products."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .events import RepositoryEvent


@dataclass(frozen=True)
class ParityReport:
    left_rows: int
    right_rows: int
    shared_rows: int
    left_only: int
    right_only: int
    matching_payloads: int
    mismatched_payloads: int

    @property
    def passed(self) -> bool:
        return self.left_only == self.right_only == self.mismatched_payloads == 0

    def to_dict(self) -> dict[str, int | bool]:
        return {**asdict(self), "passed": self.passed}


def _payload_digest(event: RepositoryEvent) -> str:
    canonical = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_events(path: Path) -> list[RepositoryEvent]:
    return [
        RepositoryEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def compare_events(left: Iterable[RepositoryEvent], right: Iterable[RepositoryEvent]) -> ParityReport:
    left_map = {event.event_id: _payload_digest(event) for event in left}
    right_map = {event.event_id: _payload_digest(event) for event in right}
    shared = left_map.keys() & right_map.keys()
    matching = sum(left_map[key] == right_map[key] for key in shared)
    return ParityReport(
        left_rows=len(left_map),
        right_rows=len(right_map),
        shared_rows=len(shared),
        left_only=len(left_map.keys() - right_map.keys()),
        right_only=len(right_map.keys() - left_map.keys()),
        matching_payloads=matching,
        mismatched_payloads=len(shared) - matching,
    )
