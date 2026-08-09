"""Point-in-time feature frame matching the Python feature definitions."""

from __future__ import annotations


def snapshot_events(spark, input_path: str, *, stream: bool = False):
    from pyspark.sql import functions as F

    from .contracts import event_schema

    reader = spark.readStream if stream else spark.read
    events = reader.schema(event_schema()).json(input_path)
    return events.filter(
        (F.col("schema_version") == "adoptrank.repository-event.v1")
        & (F.col("event_type") == "RepositorySnapshotCaptured")
    )


def build_feature_frame(events):
    """Build deterministic features with event-time only; no future leakage."""
    from pyspark.sql import functions as F

    p = F.col("payload")
    observed = F.col("observed_at")
    def recency(timestamp, half_life_days: float):
        age_days = F.greatest(F.lit(0.0), (F.unix_timestamp(observed) - F.unix_timestamp(timestamp)) / 86400.0)
        return F.when(timestamp.isNull(), F.lit(0.0)).otherwise(F.exp(-age_days / F.lit(half_life_days)))

    age_days = F.greatest(F.lit(0.0), (F.unix_timestamp(observed) - F.unix_timestamp(p.created_at)) / 86400.0)
    # Mirrors backend.features.TOKEN_PATTERN: retain identifier characters and
    # ignore one-character terms, rather than using an English tokenizer.
    cleaned_description = F.regexp_replace(
        F.lower(F.coalesce(p.description, F.lit(""))), r"[^a-z0-9_+.\\-]+", " "
    )
    description_tokens = F.size(
        F.filter(F.split(F.trim(cleaned_description), r"\\s+"), lambda term: F.length(term) >= 2)
    )
    return events.select(
        "event_id",
        "observed_at",
        p.full_name.alias("full_name"),
        F.log1p(F.coalesce(p.stars, F.lit(0))) / F.lit(12.0).alias("log_stars"),
        F.log1p(F.coalesce(p.forks, F.lit(0))) / F.lit(10.0).alias("log_forks"),
        F.least(F.lit(1.0), p.open_issues / F.greatest(F.lit(25.0), p.stars * F.lit(0.05))).alias("issue_pressure"),
        recency(p.pushed_at, 45.0).alias("push_recency"),
        (p.license_spdx.isNotNull() & (~p.license_spdx.isin("", "NOASSERTION", "OTHER"))).cast("double").alias("has_license"),
        p.archived.cast("double").alias("is_archived"),
        F.least(F.lit(1.0), F.size(F.coalesce(p.topics, F.array())) / F.lit(12.0)).alias("topic_density"),
        F.least(F.lit(1.0), description_tokens / F.lit(80.0)).alias("description_density"),
        recency(p.latest_release_at, 120.0).alias("release_recency"),
        F.log1p(F.coalesce(p.pypi_downloads_30d, F.lit(0))) / F.lit(18.0).alias("log_pypi_downloads"),
        F.log1p(F.coalesce(p.contributors_sampled, F.lit(0))) / F.lit(6.0).alias("log_contributors"),
        F.least(F.lit(1.0), age_days / F.lit(3650.0)).alias("repository_age"),
        p.indexed_commit_sha.isNotNull().cast("double").alias("has_code_index"),
        F.least(F.lit(1.0), p.test_file_count / F.greatest(F.lit(1.0), p.source_file_count * F.lit(0.35))).alias("test_coverage_proxy"),
        F.least(F.lit(1.0), p.example_file_count / F.greatest(F.lit(1.0), p.source_file_count * F.lit(0.15))).alias("example_coverage_proxy"),
        F.least(F.lit(1.0), p.dependency_count / F.lit(80.0)).alias("dependency_density"),
        F.least(F.lit(1.0), p.symbol_count / F.greatest(F.lit(20.0), p.source_file_count * F.lit(30.0))).alias("symbol_density"),
        F.coalesce(p.quality_score, F.lit(0.0)).alias("quality_score"),
        F.coalesce(p.depth_score, F.lit(0.0)).alias("depth_score"),
        F.coalesce(p.originality_score, F.lit(0.0)).alias("originality_score"),
    )
