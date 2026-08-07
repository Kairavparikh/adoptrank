# AdoptRank production operations

## Runtime topology

- `adoptrank.vercel.app`: Next.js UI and authenticated server-side proxy.
- Modal L4 ranker: FastAPI, Qwen3 embedding/reranking, and the trained PyTorch heads.
- Neon PostgreSQL with pgvector: observations, code evidence, 1,024-dimensional Qwen code chunks, and HNSW indexes.
- Modal schedule: hourly real GitHub/PyPI polling into Neon at minute 17.
- GitHub Actions: manual portable collection/code refresh and weekly Qwen head retraining when the repository is published.

## Required secrets

The ranking host requires `RANKER_API_KEY`. Vercel requires the same
`RANKER_API_KEY` plus `RANKER_API_URL`. Modal stores the Neon URL in the
`adoptrank-database` secret and the read-only GitHub token in
`adoptrank-github`. Collection workflows require `DATABASE_URL`; GitHub-hosted
workflows can use their built-in `GITHUB_TOKEN`.

Never expose these through a `NEXT_PUBLIC_` variable.

## Deployment

### Production: Modal serverless GPU

The checked-in deployment definition is `deploy/modal_app.py`. It bakes both
Qwen model snapshots, the trained PyTorch heads, repository corpus, and embedding
cache into one image, serves the existing FastAPI app on an L4 GPU, permits one
inference at a time per container, and scales idle containers to zero after five
minutes. Modal setup, secret creation, deployment, and Vercel connection commands
are documented in `deploy/README.md`.

The deployment requires a Modal secret named `adoptrank-production` containing
`RANKER_API_KEY`. The runtime has no Hugging Face token requirement because both
models are public and downloaded into the image during its build.

Current production endpoints:

- Web and server-side proxy: `https://adoptrank.vercel.app`
- Ranking API: `https://kairav-parikh01--adoptrank-ranker-ranking-api.modal.run`
- PostgreSQL resource: Vercel Marketplace Neon resource `adoptrank-pgvector`

The ranking endpoint is public at the network layer but `/v1/search` requires the
private `x-adoptrank-key` shared only by Modal and Vercel. `/health` intentionally
contains no secret or repository data and remains available for health checks.

The collector schedule is `17 * * * *` UTC. Each run searches both established
and recently updated repositories, deduplicates them, writes immutable observations,
and materializes the leaderboard. Hourly observations are retained for 30 days,
compacted to one daily observation from days 30–90, and removed after 90 days.
The initial hosted run persisted 246 repositories. The widened hourly verification
on 2026-08-07 grew production to 901 repositories and 1,223 observations, created
two leaderboard snapshots with 1,147 total ranking rows, and advanced the watermark
to `2026-08-07T05:28:34Z`. Of the first 100 current results, 25 had measurable
rank movement and 74 entered the expanded catalog. The production pgvector table
contains 241 Qwen code chunks from the commit-pinned bootstrap corpus.

### Alternative: Hugging Face Docker Space

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
- Leaderboard snapshots are idempotent by observation watermark and use deterministic tie-breaking.
- Model startup warms Qwen before accepting traffic, and Docker health checks allow a three-minute start period.
