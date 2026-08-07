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

The current repository records are a product-preview corpus. The next milestone connects GitHub and PyPI collectors, writes point-in-time observations to Supabase, and produces the first reproducible ranking snapshot.
