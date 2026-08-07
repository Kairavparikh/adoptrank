---
title: AdoptRank Qwen Ranking API
emoji: 🔎
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
---

# AdoptRank ranking backend

This service collects real public repository signals, creates weakly supervised query/repository pairs, trains a PyTorch neural learning-to-rank model, and serves ranked results through FastAPI.

No simulated repositories or generated adoption labels are used. Query relevance is bootstrapped from real repository topics and descriptions. The adoption head is trained only when two point-in-time snapshots provide an observed future change.

```bash
adoptrank-backend collect --queries seed_queries.txt --output data/snapshots/latest.jsonl
adoptrank-backend analyze-code --snapshots data/snapshots/latest.jsonl --output data/snapshots/code.jsonl --limit 20
adoptrank-backend dataset --snapshots data/snapshots/code.jsonl --output data/training/pairs.jsonl
adoptrank-backend train --dataset data/training/pairs.jsonl --snapshots data/snapshots/code.jsonl --model-dir artifacts/current
adoptrank-backend serve --model-dir artifacts/current
```

Code analysis pins each repository to a commit, reads a bounded mix of implementation, test, example, and dependency files, and extracts deterministic symbols, imports, and capability terms. If `DATABASE_URL` is configured, both observations and file-level code evidence are persisted to PostgreSQL.
