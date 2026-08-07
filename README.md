# AdoptRank

AdoptRank finds open-source repositories that fit a developer's actual project. It combines functional relevance, sustained adoption, code evidence, and compatibility instead of ranking by stars alone.

The maintained product specification is in [docs/PRD.md](docs/PRD.md).

## Current vertical slice

- Natural-language repository search
- Evidence panel with code paths and adoption signals
- Emerging, Durable, and Hidden Gem discovery views
- Side-by-side repository comparison
- Safe terminal local-project scanner and VS Code integration
- PostgreSQL + pgvector search API with a resilient preview fallback
- Vercel-ready Next.js application
- FastAPI model service with live GitHub/PyPI ingestion
- Qwen3 embeddings and cross-encoder reranking with PyTorch InfoNCE, pairwise ranking, and multi-objective heads

## Local development

Requires Node.js 22.

```bash
npm install
cp .env.example .env.local
npm run dev
```

Apply `database/migrations/001_initial_adoptrank.sql` to a PostgreSQL database with pgvector, then set:

```text
DATABASE_URL=postgresql://...
```

The database URL is server-only and must never use a `NEXT_PUBLIC_` prefix.

## Validation

```bash
npm run lint
npm test
```

The public Vercel deployment still uses the preview corpus until a hosted model-service URL is configured. The backend itself already collects GitHub/PyPI data, writes point-in-time PostgreSQL observations, and produces reproducible PyTorch checkpoints.

## Ranking backend

The Python backend lives in `backend/`. It now supports:

- Real GitHub and PyPI snapshot collection
- Optional PostgreSQL persistence during every collection
- Tree-sitter source, test, example, symbol, dependency, and syntax-aware chunk extraction
- Qwen3 code/repository embeddings persisted in pgvector
- Hard-negative mining with InfoNCE and pairwise RankNet objectives
- Masked adoption plus depth, quality, maintenance, and originality heads
- BM25 + dense top-50 retrieval followed by bounded Qwen3 cross-encoder reranking
- FastAPI `/health` and `/v1/search` endpoints

The current Qwen run uses 76 real repositories and 217 preference pairs. Its held-out pair accuracy is 0.659 and NDCG is 0.874; see `backend/MODEL_CARD.md` for limitations.

Configure the Vercel application to call a deployed model service with:

```text
RANKER_API_URL=https://your-ranker-service.example
RANKER_API_KEY=...
```
