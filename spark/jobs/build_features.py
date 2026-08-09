"""Batch or streaming event-time feature materialization.

Example:
  spark-submit --py-files spark/adoptrank_spark.zip spark/jobs/build_features.py \
    --input events.jsonl --output warehouse/features --format parquet
"""

from __future__ import annotations

import argparse

from adoptrank_spark.features import build_feature_frame, snapshot_events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--format", choices=("parquet", "delta"), default="parquet")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--checkpoint")
    args = parser.parse_args()

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("adoptrank-feature-materialization").getOrCreate()
    features = build_feature_frame(snapshot_events(spark, args.input, stream=args.stream))
    if args.stream:
        if not args.checkpoint:
            raise SystemExit("--checkpoint is required with --stream")
        (
            features.writeStream.format(args.format)
            .option("checkpointLocation", args.checkpoint)
            .outputMode("append")
            .start(args.output)
            .awaitTermination()
        )
    else:
        features.withColumn("observed_date", F.to_date("observed_at")).write.format(args.format).mode(
            "append"
        ).partitionBy("observed_date").save(args.output)


if __name__ == "__main__":
    main()
