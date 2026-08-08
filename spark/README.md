# Spark historical data jobs

Spark is for replaying large immutable event histories, not API requests or
request-time ranking. It consumes the same `repository-event.v1` JSONL emitted
by Python and the Rust shadow worker.

```bash
# First create a Python reference event file.
cd backend
adoptrank export-events --snapshots data/snapshots/latest.jsonl --output /tmp/events.jsonl

# With Spark installed and PYTHONPATH at the repository's spark directory:
PYTHONPATH=./spark spark-submit spark/jobs/build_features.py \
  --input /tmp/events.jsonl --output /tmp/adoptrank-features
PYTHONPATH=./spark spark-submit spark/jobs/adoption_backtest.py \
  --input /tmp/events.jsonl --output /tmp/adoptrank-backtest --horizon-days 30
```

`build_features.py` uses only event-time fields. `adoption_backtest.py` chooses
the first observation at or after the selected horizon, preserving point-in-time
validity. Run these jobs in shadow mode and compare row counts, null masks, and
sampled feature values with the Python reference before any cutover.
