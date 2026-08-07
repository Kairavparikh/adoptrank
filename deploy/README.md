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
