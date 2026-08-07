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
    .pip_install_from_pyproject(
        str(BACKEND_ROOT / "pyproject.toml"), optional_dependencies=["ml", "ops"]
    )
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

CONTEXT_PAIRS_PATH = BACKEND_ROOT / "benchmarks" / "public_context_pairs.jsonl"
context_training_image = (
    image.add_local_file(
        str(CONTEXT_PAIRS_PATH),
        "/app/public_context_pairs.jsonl",
        copy=True,
    )
    if CONTEXT_PAIRS_PATH.exists()
    else image
)

context_model_volume = modal.Volume.from_name("adoptrank-models", create_if_missing=True)

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
    timeout=30 * 60,
    max_containers=1,
    schedule=modal.Cron("17 * * * *"),
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
    from adoptrank_backend.config import settings
    from adoptrank_backend.leaderboard import materialize_leaderboard

    captured_at = datetime.now(UTC)
    output = Path("/tmp") / f"adoptrank-{captured_at:%Y%m%dT%H%M%SZ}.jsonl"
    count = asyncio.run(collect_queries(Path("/app/seed_queries.txt"), output, per_query=50))
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    leaderboard = asyncio.run(materialize_leaderboard(settings.database_url))
    return {
        "repositories": count,
        "captured_at": captured_at.isoformat(),
        "leaderboard_snapshot": str(leaderboard["snapshot_id"]),
    }


@app.function(
    image=collector_image,
    cpu=1.0,
    memory=2_048,
    timeout=30 * 60,
    max_containers=1,
    secrets=[
        modal.Secret.from_name("adoptrank-database"),
        modal.Secret.from_name("adoptrank-github"),
    ],
)
def backfill_repository_catalog(per_query: int = 500) -> dict[str, int | str]:
    """Run an explicit shallow backfill without expensive per-repository API fan-out."""
    import asyncio
    from datetime import UTC, datetime
    from pathlib import Path

    from adoptrank_backend.collectors import collect_queries

    captured_at = datetime.now(UTC)
    output = Path("/tmp") / f"adoptrank-backfill-{captured_at:%Y%m%dT%H%M%SZ}.jsonl"
    count = asyncio.run(
        collect_queries(
            Path("/app/seed_queries.txt"),
            output,
            per_query=min(max(1, per_query), 1000),
            hydrate_signals=False,
            page_delay_seconds=2.1,
        )
    )
    return {"repositories": count, "captured_at": captured_at.isoformat()}


@app.function(
    image=collector_image,
    cpu=1.0,
    memory=2_048,
    timeout=10 * 60,
    secrets=[modal.Secret.from_name("adoptrank-database")],
)
def materialize_production_leaderboard() -> dict[str, int | str]:
    """Create an immutable leaderboard snapshot from Neon observations."""
    import asyncio

    from adoptrank_backend.config import settings
    from adoptrank_backend.leaderboard import materialize_leaderboard

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    return asyncio.run(materialize_leaderboard(settings.database_url))


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


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=30 * 60,
    max_containers=1,
    schedule=modal.Cron("47 */6 * * *"),
    secrets=[
        modal.Secret.from_name("adoptrank-database"),
        modal.Secret.from_name("adoptrank-github"),
    ],
)
def deep_index_production_repositories(limit: int = 25) -> dict[str, int]:
    """Incrementally analyze changed live repositories and add Qwen code vectors."""
    import asyncio

    from adoptrank_backend.config import settings
    from adoptrank_backend.corpus import deep_index_catalog

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    return asyncio.run(
        deep_index_catalog(
            settings.database_url,
            settings.github_token,
            limit=min(max(1, limit), 100),
            files_per_repository=12,
        )
    )


@app.function(
    image=collector_image,
    cpu=0.25,
    memory=512,
    timeout=60,
    secrets=[modal.Secret.from_name("adoptrank-database")],
)
def production_corpus_status_v2() -> dict[str, int | str | None]:
    """Return non-secret production corpus counts for operational verification."""
    import asyncio

    from adoptrank_backend.config import settings
    from adoptrank_backend.storage import corpus_stats

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    return asyncio.run(corpus_stats(settings.database_url))


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=10 * 60,
    scaledown_window=300,
    max_containers=1,
)
def rerank_context_candidates(query: str, documents: list[str]) -> list[float]:
    """Authenticated batch cross-encoder used by explicit public-corpus evaluations."""
    from adoptrank_backend.reranker import QwenReranker

    if len(documents) > 50:
        raise ValueError("At most 50 candidate excerpts may be reranked")
    return QwenReranker().score(query, documents).tolist()


@app.function(
    image=context_training_image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=30 * 60,
    max_containers=1,
    volumes={"/trained": context_model_volume},
)
def train_context_production(
    epochs: int = 18, holdout_repository: str | None = None
) -> dict:
    """Train the held-out Qwen/RankNet context head and persist its checkpoint."""
    from pathlib import Path

    from adoptrank_backend.train_context import train_context_ranker

    if not Path("/app/public_context_pairs.jsonl").exists():
        raise RuntimeError(
            "Generate backend/benchmarks/public_context_pairs.jsonl with "
            "`adoptrank context-dataset` before deploying the training job"
        )
    output_name = "context-ranker.pt"
    if holdout_repository:
        output_name = "context-ranker-holdout.pt"
    metrics = train_context_ranker(
        Path("/app/public_context_pairs.jsonl"),
        Path("/trained") / output_name,
        epochs=min(max(1, epochs), 50),
        embedding_dimension=1024,
        validation_fraction=0.20,
        seed=17,
        validation_group_prefix=holdout_repository,
    )
    context_model_volume.commit()
    return metrics


_trained_context_runtime = None


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16_384,
    timeout=10 * 60,
    scaledown_window=300,
    max_containers=1,
    volumes={"/trained": context_model_volume},
)
def rerank_context_candidates_trained(
    query: str,
    documents: list[str],
    checkpoint_name: str = "context-ranker.pt",
) -> list[float]:
    """Score explicit public benchmark files with the trained value-per-token head."""
    import math

    import numpy as np
    import torch

    from adoptrank_backend.context_model import ContextValueRanker
    from adoptrank_backend.context_pack import _candidate_score, context_terms
    from adoptrank_backend.embeddings import QwenEmbedder

    global _trained_context_runtime
    if len(documents) > 50:
        raise ValueError("At most 50 candidate excerpts may be reranked")
    if checkpoint_name not in {"context-ranker.pt", "context-ranker-holdout.pt"}:
        raise ValueError("Unsupported trained context checkpoint")
    if _trained_context_runtime is None or _trained_context_runtime[0] != checkpoint_name:
        checkpoint = torch.load(
            f"/trained/{checkpoint_name}", map_location="cuda", weights_only=True
        )
        model = ContextValueRanker(checkpoint["embedding_dimension"]).to("cuda")
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        _trained_context_runtime = (checkpoint_name, model, QwenEmbedder(dimension=1024))
    _, model, embedder = _trained_context_runtime
    paths = [document.splitlines()[0].lower() if document else "" for document in documents]
    features = np.asarray(
        [
            [
                _candidate_score(context_terms(query), path, document),
                math.log1p(max(1, len(document.encode()) // 4)) / 10.0,
                float("test" in path or "spec" in path),
                1.0 / math.log2(index + 3.0),
            ]
            for index, (path, document) in enumerate(zip(paths, documents, strict=True))
        ],
        dtype=np.float32,
    )
    query_embedding = torch.tensor(
        embedder.encode_queries([query]), dtype=torch.float32, device="cuda"
    )
    query_embeddings = query_embedding.repeat(len(documents), 1)
    document_embeddings = torch.tensor(
        embedder.encode_documents(documents), dtype=torch.float32, device="cuda"
    )
    feature_tensor = torch.tensor(features, dtype=torch.float32, device="cuda")
    with torch.no_grad():
        return model(query_embeddings, document_embeddings, feature_tensor).cpu().tolist()
