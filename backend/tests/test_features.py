from datetime import UTC, datetime, timedelta

from adoptrank_backend.dataset import build_pairs
from adoptrank_backend.features import adoption_growth, structured_features, tokenize
from adoptrank_backend.schemas import RepositorySnapshot


def repo(name: str, language: str, stars: int, captured: datetime) -> RepositorySnapshot:
    return RepositorySnapshot(
        full_name=f"org/{name}",
        html_url=f"https://github.com/org/{name}",
        captured_at=captured,
        description=f"Production {name} anomaly detection streaming toolkit",
        language=language,
        topics=["anomaly-detection", "streaming"],
        stars=stars,
        forks=max(1, stars // 10),
        pushed_at=captured,
        created_at=captured - timedelta(days=365),
    )


def test_real_feature_shape_and_growth() -> None:
    now = datetime.now(UTC)
    previous = repo("alpha", "Python", 100, now - timedelta(days=30))
    future = repo("alpha", "Python", 160, now)
    assert structured_features(previous).shape == (12,)
    assert 0 < adoption_growth(previous, future) < 1


def test_pair_builder_uses_repository_content() -> None:
    now = datetime.now(UTC)
    snapshots = [repo("alpha", "Python", 100, now), repo("beta", "Python", 50, now), repo("gamma", "Rust", 70, now)]
    pairs = build_pairs(snapshots)
    assert pairs
    assert all(len(tokenize(pair.query)) >= 2 for pair in pairs)
    assert all(pair.positive.full_name != pair.negative.full_name for pair in pairs)
