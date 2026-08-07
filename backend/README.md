# AdoptRank ranking backend

This service collects real public repository signals, creates weakly supervised query/repository pairs, trains a PyTorch neural learning-to-rank model, and serves ranked results through FastAPI.

No simulated repositories or generated adoption labels are used. Query relevance is bootstrapped from real repository topics and descriptions. The adoption head is trained only when two point-in-time snapshots provide an observed future change.

```bash
adoptrank-backend collect --queries seed_queries.txt --output data/snapshots/latest.jsonl
adoptrank-backend dataset --snapshots data/snapshots/*.jsonl --output data/training/pairs.jsonl
adoptrank-backend train --dataset data/training/pairs.jsonl --snapshots data/snapshots/latest.jsonl --model-dir artifacts/current
adoptrank-backend serve --model-dir artifacts/current
```
