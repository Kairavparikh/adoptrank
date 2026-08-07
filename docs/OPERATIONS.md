# AdoptRank production operations

## Runtime topology

- `adoptrank.vercel.app`: Next.js UI and authenticated server-side proxy.
- Ranking container: FastAPI, Qwen3 embedding/reranking, and the trained PyTorch heads.
- PostgreSQL with pgvector: observations, code evidence, 1,024-dimensional Qwen code chunks, and HNSW indexes.
- GitHub Actions: six-hour real-data collection/code refresh and weekly Qwen head retraining.

## Required secrets

The ranking host requires `RANKER_API_KEY`. Vercel requires the same `RANKER_API_KEY` plus `RANKER_API_URL`. Collection workflows require `DATABASE_URL`; their built-in `GITHUB_TOKEN` is used for public GitHub API capacity.

Never expose these through a `NEXT_PUBLIC_` variable.

## Deployment

The ranking service is a Docker Space-compatible bundle rooted at `backend/`. Its README contains the required Docker Space metadata, and the trained checkpoint, repository corpus, and embedding cache ship under `backend/artifacts/qwen/`.

```bash
hf repos create Kairav1234/adoptrank-ranker --repo-type space --space-sdk docker --public --flavor cpu-basic
hf upload Kairav1234/adoptrank-ranker backend . --repo-type space --exclude '.venv/**' --exclude 'data/**' --exclude 'tests/**'
hf spaces secrets add Kairav1234/adoptrank-ranker -s RANKER_API_KEY
hf spaces variables add Kairav1234/adoptrank-ranker -e RERANK_CANDIDATES=20 -e WARM_MODELS=true
```

Docker Spaces currently require a Hugging Face PRO or organization compute entitlement. For the interactive 20–50 candidate cross-encoder SLA, use a GPU-flavored Space; CPU-basic is useful for functional validation but not the target latency profile.

After the Space is healthy, configure Vercel and redeploy:

```bash
vercel env add RANKER_API_URL production
vercel env add RANKER_API_KEY production
vercel --prod
```

## Verification

```bash
curl https://<ranker-host>/health
curl -H "x-adoptrank-key: $RANKER_API_KEY" \
  "https://<ranker-host>/v1/search?query=streaming%20anomaly%20detection&limit=3"
```

The production response must report `qwen3-infonce-ranknet-v2`, a non-null data watermark, direct GitHub URLs, and separate relevance/adoption/depth/quality/maintenance/originality scores.

## Failure behavior

- Vercel falls back to PostgreSQL and then to the clearly marked preview corpus if the ranker is unavailable.
- Missing adoption observations remain null/masked during training rather than becoming zeros.
- Source analysis is commit-pinned; failed refreshes preserve prior evidence.
- Collector workflow concurrency prevents overlapping pollers.
- Model startup warms Qwen before accepting traffic, and Docker health checks allow a three-minute start period.
