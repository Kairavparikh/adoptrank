"""Spark-side schema for the repository-event.v1 envelope."""

from __future__ import annotations


def event_schema():
    """Return a Spark schema lazily so importing this package needs no PySpark."""
    from pyspark.sql.types import (
        ArrayType,
        BooleanType,
        DoubleType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    payload = StructType(
        [
            StructField("full_name", StringType()),
            StructField("html_url", StringType()),
            StructField("captured_at", TimestampType()),
            StructField("description", StringType()),
            StructField("language", StringType()),
            StructField("license_spdx", StringType()),
            StructField("topics", ArrayType(StringType())),
            StructField("stars", LongType()),
            StructField("forks", LongType()),
            StructField("open_issues", LongType()),
            StructField("watchers", LongType()),
            StructField("size_kb", LongType()),
            StructField("archived", BooleanType()),
            StructField("fork", BooleanType()),
            StructField("pushed_at", TimestampType()),
            StructField("created_at", TimestampType()),
            StructField("latest_release_at", TimestampType()),
            StructField("contributors_sampled", IntegerType()),
            StructField("pypi_downloads_1d", LongType()),
            StructField("pypi_downloads_7d", LongType()),
            StructField("pypi_downloads_30d", LongType()),
            StructField("indexed_commit_sha", StringType()),
            StructField("source_file_count", IntegerType()),
            StructField("test_file_count", IntegerType()),
            StructField("example_file_count", IntegerType()),
            StructField("dependency_count", IntegerType()),
            StructField("symbol_count", IntegerType()),
            StructField("quality_score", DoubleType()),
            StructField("depth_score", DoubleType()),
            StructField("originality_score", DoubleType()),
        ]
    )
    return StructType(
        [
            StructField("schema_version", StringType(), False),
            StructField("event_type", StringType(), False),
            StructField("event_id", StringType(), False),
            StructField("observed_at", TimestampType(), False),
            StructField(
                "repository",
                StructType(
                    [
                        StructField("full_name", StringType(), False),
                        StructField("html_url", StringType(), False),
                        StructField("commit_sha", StringType()),
                    ]
                ),
                False,
            ),
            StructField("payload", payload, False),
            StructField(
                "provenance",
                StructType(
                    [
                        StructField("source", StringType(), False),
                        StructField("producer", StringType(), False),
                        StructField("query", StringType()),
                    ]
                ),
                False,
            ),
        ]
    )
