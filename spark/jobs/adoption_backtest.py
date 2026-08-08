"""Produce future-only adoption labels from immutable snapshot events."""

from __future__ import annotations

import argparse

from adoptrank_spark.features import snapshot_events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--horizon-days", type=int, choices=(30, 90), default=30)
    args = parser.parse_args()
    from pyspark.sql import SparkSession, Window
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("adoptrank-adoption-backtest").getOrCreate()
    events = snapshot_events(spark, args.input).select(
        "event_id", "observed_at", F.col("payload.full_name").alias("full_name"),
        F.col("payload.stars").alias("stars"), F.col("payload.forks").alias("forks"),
        F.col("payload.pypi_downloads_30d").alias("downloads_30d"),
    )
    # The earliest observation at/after the horizon is selected, preventing future leakage.
    future = events.select(
        F.col("full_name").alias("future_name"), F.col("observed_at").alias("future_at"),
        F.col("stars").alias("future_stars"), F.col("forks").alias("future_forks"),
        F.col("downloads_30d").alias("future_downloads"),
    )
    joined = events.join(
        future,
        (events.full_name == future.future_name)
        & (future.future_at >= events.observed_at + F.expr(f"INTERVAL {args.horizon_days} DAYS")),
        "left",
    )
    closest = Window.partitionBy("event_id").orderBy(F.col("future_at").asc_nulls_last())
    labeled = joined.withColumn("future_rank", F.row_number().over(closest)).filter("future_rank = 1")
    elapsed = F.greatest(F.lit(1.0), (F.unix_timestamp("future_at") - F.unix_timestamp("observed_at")) / 86400.0)
    velocity = F.greatest(F.lit(0.0), (F.col("future_stars") - F.col("stars")) / elapsed) + 2 * F.greatest(F.lit(0.0), (F.col("future_forks") - F.col("forks")) / elapsed)
    labeled.select(
        "event_id", "full_name", "observed_at", "future_at",
        F.when(F.col("future_at").isNull(), F.lit(None).cast("double"))
        .otherwise(F.lit(1.0) - F.exp(-F.log1p(velocity) / F.lit(2.0))).alias("adoption_target"),
    ).write.mode("overwrite").parquet(args.output)


if __name__ == "__main__":
    main()
