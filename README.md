# AdoptRank

AdoptRank finds open-source repositories that fit a developer's actual project. It combines functional relevance, sustained adoption, code evidence, and compatibility instead of ranking by stars alone.

The maintained product specification is in [docs/PRD.md](docs/PRD.md).

## Current vertical slice

- Natural-language repository search
- Live overall and per-owner leaderboards with adoption windows and rank movement
- Evidence panel with code paths and adoption signals
- Emerging, Durable, and Hidden Gem discovery views
- Side-by-side repository comparison
- Safe terminal local-project scanner and VS Code integration
- PostgreSQL + pgvector search API with a resilient preview fallback
- Vercel-ready Next.js application
- FastAPI model service with live GitHub/PyPI ingestion
- Incremental commit-pinned code indexing from Neon into Qwen/pgvector every six hours
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

## Public CLI

The `adoptrank` command uses the public Vercel API by default. Vercel supplies the
private Modal credential server-side, so users never need an AdoptRank API key.
Install the published CLI with `pipx`:

```bash
pipx install adoptrank
```

The GitHub source-install fallback is
`pipx install "git+https://github.com/Kairavparikh/adoptrank.git#subdirectory=backend"`.

Then search from any project or inspect the live leaderboard:

```bash
cd your-project
adoptrank find "a streaming anomaly detector that fits this codebase"
adoptrank leaderboard --language Python --sort momentum
adoptrank leaderboard --owner openai --window 7
```

The local scanner reads languages, dependencies, frameworks, and symbols to
improve project compatibility. It skips ignored paths, dependency/build
directories, known credential files, and files matching secret patterns. Use
`adoptrank find "..." --dry-run` to inspect the exact search payload.

The public deployment at <https://adoptrank.vercel.app> is connected to the
checked-in Modal GPU service and returns Qwen/PyTorch rankings. The backend also
collects GitHub/PyPI data, writes point-in-time PostgreSQL observations, and
produces reproducible PyTorch checkpoints.

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
- Hourly, non-overlapping GitHub/PyPI collection with 90-day history retention

The current Qwen run uses 76 real repositories and 217 preference pairs. Its held-out pair accuracy is 0.659 and NDCG is 0.874; see `backend/MODEL_CARD.md` for limitations.

Configure the Vercel application to call a deployed model service with:

```text
RANKER_API_URL=https://your-ranker-service.example
RANKER_API_KEY=...
```

Production deployment and verification commands are in
[`deploy/README.md`](deploy/README.md).
