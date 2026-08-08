# Rust ingestion worker

`adoptrank-ingest` is a shadow-mode GitHub collector. It emits the versioned
`RepositorySnapshotCaptured` JSONL contract, never writes production database
tables directly, and can therefore be replayed and compared safely.

```bash
cd rust
GITHUB_TOKEN=... cargo run -p adoptrank-ingest -- \
  --query "language:Rust stars:>20" --limit 50 --output /tmp/rust-events.jsonl

cd ../backend
adoptrank validate-event-parity \
  --python-events /tmp/python-events.jsonl \
  --candidate-events /tmp/rust-events.jsonl
```

The cutover gate is zero unmatched event ids and zero differing payload hashes
on an equivalent, commit-pinned replay. The Python collector remains live until
that gate and the rate/cost SLOs are met.

The worker has no database credentials by design. A later canary consumer may
write accepted events after the shared parity checker approves a replay.

Use `--observed-at 2026-08-08T12:00:00Z` to pin a capture time for an
equivalent shadow replay.
