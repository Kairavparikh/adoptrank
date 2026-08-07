"""Modal deployment for the production AdoptRank ranking API.

Deploy from the repository root with:
    modal deploy deploy/modal_app.py
"""

from pathlib import Path

import modal


APP_NAME = "adoptrank-ranker"
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def download_qwen_models() -> None:
    """Bake immutable public Qwen model snapshots into the serving image."""
    from huggingface_hub import snapshot_download

    for model_name in (EMBEDDING_MODEL, RERANKER_MODEL):
        snapshot_download(repo_id=model_name)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_pyproject(str(BACKEND_ROOT / "pyproject.toml"))
    .env(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "MODEL_DIR": "/models/qwen",
            "EMBEDDING_MODEL": EMBEDDING_MODEL,
            "RERANKER_MODEL": RERANKER_MODEL,
            "QWEN_DEVICE": "cuda",
            "RERANK_CANDIDATES": "50",
            "WARM_MODELS": "true",
        }
    )
    .run_function(download_qwen_models, timeout=60 * 30)
    .env({"HF_HUB_OFFLINE": "1"})
    .add_local_dir(
        str(BACKEND_ROOT / "src" / "adoptrank_backend"),
        "/root/adoptrank_backend",
        copy=True,
    )
    .add_local_dir(
        str(BACKEND_ROOT / "artifacts" / "qwen"),
        "/models/qwen",
        copy=True,
    )
)

collector_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "asyncpg==0.30.0",
        "httpx==0.28.1",
        "pydantic==2.12.5",
        "pydantic-settings==2.12.0",
    )
    .env(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    .add_local_dir(
        str(BACKEND_ROOT / "src" / "adoptrank_backend"),
        "/root/adoptrank_backend",
        copy=True,
    )
    .add_local_file(
        str(BACKEND_ROOT / "seed_queries.txt"),
        "/app/seed_queries.txt",
        copy=True,
    )
)

app = modal.App(APP_NAME)


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=180,
    scaledown_window=300,
    max_containers=3,
    secrets=[modal.Secret.from_name("adoptrank-production")],
)
@modal.concurrent(max_inputs=1)
@modal.asgi_app()
def ranking_api():
    """Expose the existing FastAPI application without a second API layer."""
    from adoptrank_backend.service import app as fastapi_app

    return fastapi_app


@app.function(
    image=collector_image,
    cpu=1.0,
    memory=2_048,
    timeout=20 * 60,
    schedule=modal.Cron("17 */6 * * *"),
    secrets=[
        modal.Secret.from_name("adoptrank-database"),
        modal.Secret.from_name("adoptrank-github"),
    ],
)
def collect_live_repositories() -> dict[str, int | str]:
    """Poll real GitHub/PyPI signals and persist an immutable Neon observation."""
    import asyncio
    from datetime import UTC, datetime
    from pathlib import Path

    from adoptrank_backend.collectors import collect_queries

    captured_at = datetime.now(UTC)
    output = Path("/tmp") / f"adoptrank-{captured_at:%Y%m%dT%H%M%SZ}.jsonl"
    count = asyncio.run(collect_queries(Path("/app/seed_queries.txt"), output, per_query=25))
    return {
        "repositories": count,
        "captured_at": captured_at.isoformat(),
    }


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=20 * 60,
    secrets=[modal.Secret.from_name("adoptrank-database")],
)
def index_production_vectors() -> dict[str, int | str]:
    """Rebuild Neon code vectors with the same GPU model used for serving."""
    import asyncio
    from pathlib import Path

    from adoptrank_backend.config import settings
    from adoptrank_backend.vector_index import populate_pgvector

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    count = asyncio.run(
        populate_pgvector(settings.database_url, Path("/models/qwen/repositories.jsonl"))
    )
    return {
        "embedded_chunks": count,
        "model": settings.embedding_model,
    }
