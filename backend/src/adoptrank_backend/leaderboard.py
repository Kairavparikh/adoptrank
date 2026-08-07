import asyncio
from collections import defaultdict
from datetime import UTC, timedelta
import json
import math

import asyncpg


FEATURE_VERSION = "leaderboard-v1"
MODEL_VERSION = "qwen3-infonce-ranknet-v2"
WINDOWS = (1, 7, 30, 90)


def percentile_ranks(values: list[float]) -> list[float]:
    """Return stable tie-aware percentile ranks in [0, 1]."""
    if not values:
        return []
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    result = [0.5] * len(values)
    cursor = 0
    denominator = max(1, len(values) - 1)
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and math.isclose(ordered[end][1], ordered[cursor][1]):
            end += 1
        percentile = ((cursor + end - 1) / 2) / denominator if len(values) > 1 else 0.5
        for position in range(cursor, end):
            result[ordered[position][0]] = percentile
        cursor = end
    return result


def growth_signal(observations: list[dict], window_days: int) -> tuple[float, dict]:
    if len(observations) < 2:
        return 0.0, {"elapsed_hours": 0.0, "stars": 0, "forks": 0, "downloads": 0}
    latest = observations[-1]
    target = latest["observed_at"] - timedelta(days=window_days)
    eligible = [item for item in observations[:-1] if item["observed_at"] <= target]
    previous = eligible[-1] if eligible else observations[0]
    elapsed_hours = max(1.0, (latest["observed_at"] - previous["observed_at"]).total_seconds() / 3600)
    star_delta = max(0, (latest["stars"] or 0) - (previous["stars"] or 0))
    fork_delta = max(0, (latest["forks"] or 0) - (previous["forks"] or 0))
    download_delta = max(0, (latest["downloads_30d"] or 0) - (previous["downloads_30d"] or 0))
    daily_stars = star_delta * 24 / elapsed_hours
    daily_forks = fork_delta * 24 / elapsed_hours
    relative_stars = star_delta / max(25, previous["stars"] or 0)
    raw = math.log1p(daily_stars + 2.5 * daily_forks + download_delta / 1000) + 4 * relative_stars
    coverage = min(1.0, elapsed_hours / (window_days * 24))
    return raw * (0.35 + 0.65 * coverage), {
        "elapsed_hours": round(elapsed_hours, 2),
        "stars": star_delta,
        "forks": fork_delta,
        "downloads": download_delta,
    }


def classify(scores: dict[str, float], archived: bool) -> str:
    if archived or scores["maintenance"] < 0.24:
        return "At risk"
    if scores["adoption"] >= 0.62 and scores["attention"] < 0.48:
        return "Hidden gem"
    if scores["attention"] >= 0.72 and scores["adoption"] < 0.34:
        return "Overhyped"
    if scores["adoption"] >= 0.58:
        return "Emerging"
    return "Durable"


async def materialize_leaderboard(database_url: str) -> dict[str, int | str]:
    connection = await asyncpg.connect(database_url)
    try:
        rows = await connection.fetch(
            """
            select r.id, r.full_name, r.language, r.license_spdx, r.is_archived,
                   r.github_updated_at, r.stars as current_stars, r.forks as current_forks,
                   o.observed_at, o.stars, o.forks, o.downloads_30d, o.open_issues,
                   coalesce(e.evidence_count, 0) as evidence_count,
                   coalesce(e.test_count, 0) as test_count,
                   coalesce(v.vector_count, 0) as vector_count
            from repositories r
            join repository_observations o on o.repository_id = r.id and o.source = 'github'
            left join (
              select repository_id, count(*) as evidence_count,
                     count(*) filter (where evidence_type = 'test') as test_count
              from code_evidence group by repository_id
            ) e on e.repository_id = r.id
            left join (
              select repository_id, count(*) as vector_count
              from code_chunk_embeddings group by repository_id
            ) v on v.repository_id = r.id
            where o.observed_at >= (
              select max(observed_at) - interval '91 days'
              from repository_observations
              where source = 'github'
            )
            order by r.id, o.observed_at
            """
        )
        histories: dict[str, list[dict]] = defaultdict(list)
        repositories: dict[str, dict] = {}
        for record in rows:
            item = dict(record)
            repository_id = str(item["id"])
            histories[repository_id].append(item)
            repositories[repository_id] = item
        if not histories:
            raise RuntimeError("Cannot build a leaderboard without real observations")

        repository_ids = sorted(histories, key=lambda item: repositories[item]["full_name"].lower())
        raw_growth: dict[int, list[float]] = {window: [] for window in WINDOWS}
        evidence: dict[str, dict[int, dict]] = defaultdict(dict)
        attention_raw: list[float] = []
        for repository_id in repository_ids:
            history = histories[repository_id]
            for window in WINDOWS:
                value, details = growth_signal(history, window)
                raw_growth[window].append(value)
                evidence[repository_id][window] = details
            latest = history[-1]
            attention_raw.append(math.log1p((latest["stars"] or 0) + 2 * (latest["forks"] or 0)))

        adoption = {window: percentile_ranks(raw_growth[window]) for window in WINDOWS}
        attention = percentile_ranks(attention_raw)
        ranked_rows = []
        watermark = max(histories[repository_id][-1]["observed_at"] for repository_id in repository_ids)
        # Anchor recency to the data watermark, not wall-clock execution time.
        # Re-materializing the same observation window must produce identical scores.
        now = watermark if watermark.tzinfo else watermark.replace(tzinfo=UTC)
        for index, repository_id in enumerate(repository_ids):
            repo = repositories[repository_id]
            latest = histories[repository_id][-1]
            pushed_at = repo["github_updated_at"] or latest["observed_at"]
            if pushed_at.tzinfo is None:
                pushed_at = pushed_at.replace(tzinfo=UTC)
            recency = math.exp(-max(0.0, (now - pushed_at).total_seconds() / 86_400) / 75)
            issue_pressure = min(1.0, (latest["open_issues"] or 0) / max(25, (latest["stars"] or 0) * 0.05))
            maintenance = max(0.0, recency * (1 - 0.35 * issue_pressure) * (not repo["is_archived"]))
            licensed = repo["license_spdx"] not in (None, "", "NOASSERTION", "OTHER")
            has_code = repo["evidence_count"] > 0 or repo["vector_count"] > 0
            quality = min(1.0, 0.2 + 0.25 * licensed + 0.25 * has_code + 0.3 * min(1, repo["test_count"] / 4))
            depth = min(1.0, 0.12 + 0.5 * (1 - math.exp(-repo["vector_count"] / 18)) + 0.38 * (1 - math.exp(-repo["evidence_count"] / 8)))
            originality = min(1.0, 0.55 * (1 - attention[index]) + 0.45 * depth)
            confidence = min(1.0, 0.3 + 0.12 * min(3, len(histories[repository_id])) + 0.2 * has_code + 0.1 * licensed)
            scores = {
                "adoption": adoption[30][index],
                "maintenance": maintenance,
                "quality": quality,
                "depth": depth,
                "originality": originality,
                "attention": attention[index],
            }
            security = 0.5
            base = (
                0.35 * scores["adoption"]
                + 0.2 * maintenance
                + 0.15 * quality
                + 0.12 * depth
                + 0.1 * originality
                + 0.05 * security
                + 0.03 * attention[index]
            )
            global_score = base * (0.8 + 0.2 * confidence)
            label = classify(scores, repo["is_archived"])
            explanation = {
                "window_deltas": {str(window): evidence[repository_id][window] for window in WINDOWS},
                "observation_count": len(histories[repository_id]),
                "code_evidence": repo["evidence_count"],
                "vector_chunks": repo["vector_count"],
                "method": FEATURE_VERSION,
            }
            ranked_rows.append(
                {
                    "repository_id": repository_id,
                    "full_name": repo["full_name"],
                    "global_score": global_score,
                    "adoption": {window: adoption[window][index] for window in WINDOWS},
                    "maintenance": maintenance,
                    "security": security,
                    "quality": quality,
                    "depth": depth,
                    "originality": originality,
                    "attention": attention[index],
                    "confidence": confidence,
                    "label": label,
                    "explanation": explanation,
                }
            )
        ranked_rows.sort(key=lambda item: (-item["global_score"], item["full_name"].lower()))

        async with connection.transaction():
            snapshot_id = await connection.fetchval(
                """
                insert into ranking_snapshots(model_version, feature_version, data_watermark)
                values($1,$2,$3)
                on conflict(feature_version, data_watermark) do update set model_version=excluded.model_version
                returning id
                """,
                MODEL_VERSION,
                FEATURE_VERSION,
                watermark,
            )
            await connection.execute("delete from ranking_results where snapshot_id=$1", snapshot_id)
            await connection.executemany(
                """
                insert into ranking_results(
                  snapshot_id, repository_id, global_score, adoption_score, maintenance_score,
                  security_score, confidence, label, explanation, global_rank,
                  adoption_1d, adoption_7d, adoption_30d, adoption_90d,
                  quality_score, depth_score, originality_score, attention_score
                ) values($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                """,
                [
                    (
                        snapshot_id,
                        item["repository_id"],
                        item["global_score"],
                        item["adoption"][30],
                        item["maintenance"],
                        item["security"],
                        item["confidence"],
                        item["label"],
                        json.dumps(item["explanation"]),
                        rank,
                        item["adoption"][1],
                        item["adoption"][7],
                        item["adoption"][30],
                        item["adoption"][90],
                        item["quality"],
                        item["depth"],
                        item["originality"],
                        item["attention"],
                    )
                    for rank, item in enumerate(ranked_rows, 1)
                ],
            )
            await connection.execute(
                "delete from repository_observations where observed_at < now() - interval '90 days'"
            )
            await connection.execute(
                """
                with redundant as (
                  select id, row_number() over (
                    partition by repository_id, source, date_trunc('day', observed_at)
                    order by observed_at desc
                  ) as recency
                  from repository_observations
                  where observed_at < now() - interval '30 days'
                    and observed_at >= now() - interval '90 days'
                )
                delete from repository_observations
                where id in (select id from redundant where recency > 1)
                """
            )
        return {
            "repositories": len(ranked_rows),
            "snapshot_id": str(snapshot_id),
            "data_watermark": watermark.isoformat(),
        }
    finally:
        await connection.close()


def materialize(database_url: str) -> dict[str, int | str]:
    return asyncio.run(materialize_leaderboard(database_url))
