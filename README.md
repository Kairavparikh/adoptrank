# AdoptRank

AdoptRank finds open-source repositories that fit a developer's actual project. It combines functional relevance, sustained adoption, code evidence, and compatibility instead of ranking by stars alone.

## Current vertical slice

- Natural-language repository search
- Evidence panel with code paths and adoption signals
- Emerging, Durable, and Hidden Gem discovery views
- Side-by-side repository comparison
- Terminal and local-project integration concept
- PostgreSQL + pgvector search API with a resilient preview fallback
- Vercel-ready Next.js application
- FastAPI model service with live GitHub/PyPI ingestion
- PyTorch pairwise learning-to-rank model with a masked adoption head

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
- Weakly supervised pair construction with same-language hard negatives
- A PyTorch RankNet relevance objective
- A masked adoption objective trained only on observed labels
- BM25 candidate generation, explicit language filters, and neural reranking
- FastAPI `/health` and `/v1/search` endpoints

The first bootstrap run collected 76 real repositories and produced 217 ranking pairs. See `backend/MODEL_CARD.md` and `backend/reports/bootstrap-2026-08-06.json` for honest metrics and limitations.

Configure the Vercel application to call a deployed model service with:

```text
RANKER_API_URL=https://your-ranker-service.example
RANKER_API_KEY=...
```
