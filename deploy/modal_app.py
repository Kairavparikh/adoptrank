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
            "HF_HUB_OFFLINE": "1",
            "MODEL_DIR": "/models/qwen",
            "EMBEDDING_MODEL": EMBEDDING_MODEL,
            "RERANKER_MODEL": RERANKER_MODEL,
            "QWEN_DEVICE": "cuda",
            "RERANK_CANDIDATES": "50",
            "WARM_MODELS": "true",
        }
    )
    .run_function(download_qwen_models, timeout=60 * 30)
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
