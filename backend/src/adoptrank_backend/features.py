import math
import re
from datetime import UTC, datetime

import numpy as np

from .schemas import RepositorySnapshot

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_+.-]{1,}")
FEATURE_NAMES = (
    "log_stars",
    "log_forks",
    "issue_pressure",
    "push_recency",
    "has_license",
    "is_archived",
    "topic_density",
    "description_density",
    "release_recency",
    "log_pypi_downloads",
    "log_contributors",
    "repository_age",
    "has_code_index",
    "test_coverage_proxy",
    "example_coverage_proxy",
    "dependency_density",
    "symbol_density",
    "quality_score",
    "depth_score",
    "originality_score",
)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def repository_text(repo: RepositorySnapshot) -> str:
    return " ".join(
        part
        for part in [
            repo.full_name.replace("/", " "),
            repo.description,
            " ".join(repo.topics),
            repo.language,
            " ".join(repo.code_terms),
            " ".join(repo.code_evidence_paths),
            repo.architecture_summary,
        ]
        if part
    )


def _recency(value: datetime | None, observed_at: datetime, half_life_days: float) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    age_days = max(0.0, (observed_at - value).total_seconds() / 86_400)
    return math.exp(-age_days / half_life_days)


def structured_features(repo: RepositorySnapshot, observed_at: datetime | None = None) -> np.ndarray:
    observed_at = observed_at or repo.captured_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age_days = max(0.0, (observed_at - (repo.created_at or observed_at)).total_seconds() / 86_400)
    values = [
        math.log1p(repo.stars) / 12.0,
        math.log1p(repo.forks) / 10.0,
        min(1.0, repo.open_issues / max(25.0, repo.stars * 0.05)),
        _recency(repo.pushed_at, observed_at, 45.0),
        float(repo.license_spdx not in {"", "NOASSERTION", "OTHER"}),
        float(repo.archived),
        min(1.0, len(repo.topics) / 12.0),
        min(1.0, len(tokenize(repo.description)) / 80.0),
        _recency(repo.latest_release_at, observed_at, 120.0),
        math.log1p(repo.pypi_downloads_30d or 0) / 18.0,
        math.log1p(repo.contributors_sampled) / 6.0,
        min(1.0, age_days / 3650.0),
        float(bool(repo.indexed_commit_sha)),
        min(1.0, repo.test_file_count / max(1.0, repo.source_file_count * 0.35)),
        min(1.0, repo.example_file_count / max(1.0, repo.source_file_count * 0.15)),
        min(1.0, repo.dependency_count / 80.0),
        min(1.0, repo.symbol_count / max(20.0, repo.source_file_count * 30.0)),
        repo.quality_score,
        repo.depth_score,
        repo.originality_score,
    ]
    return np.asarray(values, dtype=np.float32)


def adoption_growth(previous: RepositorySnapshot, future: RepositorySnapshot) -> float:
    """Observed growth target in [0, 1], derived only from later real measurements."""
    elapsed_days = max(1.0, (future.captured_at - previous.captured_at).total_seconds() / 86_400)
    star_velocity = max(0.0, future.stars - previous.stars) / elapsed_days
    fork_velocity = max(0.0, future.forks - previous.forks) / elapsed_days
    download_growth = 0.0
    if previous.pypi_downloads_30d and future.pypi_downloads_30d:
        download_growth = max(0.0, future.pypi_downloads_30d / previous.pypi_downloads_30d - 1.0)
    raw = math.log1p(star_velocity + 2.0 * fork_velocity + 10.0 * download_growth)
    return float(1.0 - math.exp(-raw / 2.0))


def observed_adoption_acceleration(repo: RepositorySnapshot) -> float | None:
    """Real PyPI acceleration: recent daily downloads versus the preceding part of the month."""
    if repo.pypi_downloads_7d is None or repo.pypi_downloads_30d is None:
        return None
    recent_daily = repo.pypi_downloads_7d / 7.0
    previous_daily = max(0, repo.pypi_downloads_30d - repo.pypi_downloads_7d) / 23.0
    if repo.pypi_downloads_30d == 0:
        return 0.0
    relative_change = (recent_daily - previous_daily) / max(1.0, previous_daily)
    return float(1.0 / (1.0 + math.exp(-2.0 * relative_change)))
