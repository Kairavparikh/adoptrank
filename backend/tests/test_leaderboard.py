from datetime import UTC, datetime, timedelta

from adoptrank_backend.leaderboard import classify, growth_signal, percentile_ranks


def test_percentiles_are_tie_aware_and_stable() -> None:
    assert percentile_ranks([10, 10, 30]) == [0.25, 0.25, 1.0]
    assert percentile_ranks([7]) == [0.5]


def test_growth_uses_real_elapsed_observations() -> None:
    now = datetime.now(UTC)
    observations = [
        {"observed_at": now - timedelta(days=7), "stars": 100, "forks": 10, "downloads_30d": 1000},
        {"observed_at": now, "stars": 128, "forks": 14, "downloads_30d": 1600},
    ]
    score, evidence = growth_signal(observations, 7)
    assert score > 0
    assert evidence["stars"] == 28
    assert evidence["forks"] == 4
    assert evidence["downloads"] == 600


def test_labels_distinguish_attention_from_adoption() -> None:
    base = {"maintenance": 0.8, "quality": 0.7, "depth": 0.7, "originality": 0.7}
    assert classify(base | {"adoption": 0.8, "attention": 0.2}, False) == "Hidden gem"
    assert classify(base | {"adoption": 0.2, "attention": 0.9}, False) == "Overhyped"
    assert classify(base | {"adoption": 0.7, "attention": 0.7}, False) == "Emerging"
    assert classify(base | {"adoption": 0.4, "attention": 0.5}, False) == "Durable"
    assert classify(base | {"adoption": 0.8, "attention": 0.2}, True) == "At risk"
