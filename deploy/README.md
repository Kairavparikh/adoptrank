# Hosted ranking deployment

The production inference service runs the existing FastAPI application on a
scale-to-zero Modal L4 GPU. Both Qwen3 model snapshots, the trained PyTorch
heads, the real repository corpus, and the embedding cache are baked into the
image. Runtime requests therefore do not depend on Hugging Face availability.

## One-time setup

```bash
backend/.venv/bin/pip install modal
backend/.venv/bin/modal setup
```

Generate a long random `RANKER_API_KEY`, then create the Modal secret without
checking it into a file:

```bash
backend/.venv/bin/modal secret create adoptrank-production RANKER_API_KEY=<value>
```

The scheduled collector uses two additional Modal secrets:

- `adoptrank-database` with `DATABASE_URL` for the production Neon database.
- `adoptrank-github` with a fine-grained, read-only `GITHUB_TOKEN`.

## Deploy

```bash
backend/.venv/bin/modal deploy deploy/modal_app.py
```

The command prints the stable `https://...modal.run` endpoint. Keep the trailing
path off `RANKER_API_URL`; the Vercel proxy adds `/v1/search`.

## Connect Vercel

Set the Modal URL and the same API key as production environment variables, then
redeploy:

```bash
vercel env add RANKER_API_URL production
vercel env add RANKER_API_KEY production
vercel --prod
```

Never use `NEXT_PUBLIC_` for either value.

## Polling and vector maintenance

`collect_live_repositories` runs at minute 17 every six hours. It polls the real
GitHub and PyPI APIs and writes a new point-in-time observation to Neon. Run and
verify it manually with:

```bash
backend/.venv/bin/modal run deploy/modal_app.py::collect_live_repositories
```

Rebuild production code vectors on the same L4/Qwen stack used by inference:

```bash
backend/.venv/bin/modal run deploy/modal_app.py::index_production_vectors
```
