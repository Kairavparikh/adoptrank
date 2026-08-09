from functools import cached_property

import numpy as np

from .config import settings

RETRIEVAL_INSTRUCTION = (
    "Retrieve open-source repositories whose implemented code, architecture, dependencies, and operational "
    "properties satisfy the developer's project requirement"
)


class QwenEmbedder:
    """Lazy Qwen3 embedding adapter; loading happens only in workers that need it."""

    def __init__(self, model_name: str | None = None, dimension: int | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self.dimension = dimension or settings.embedding_dimension

    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer

        kwargs = {"device": settings.qwen_device or "cpu"}
        model = SentenceTransformer(self.model_name, **kwargs)
        model.max_seq_length = 2048
        return model

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        vectors = np.asarray(
            self.model.encode(
                texts,
                prompt_name="query",
                normalize_embeddings=True,
                truncate_dim=self.dimension,
                batch_size=4,
            ),
            dtype=np.float32,
        )
        if not np.isfinite(vectors).all():
            raise RuntimeError("Qwen query embeddings contained non-finite values")
        return vectors

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        vectors = np.asarray(
            self.model.encode(
                texts,
                normalize_embeddings=True,
                truncate_dim=self.dimension,
                batch_size=16,
            ),
            dtype=np.float32,
        )
        if not np.isfinite(vectors).all():
            raise RuntimeError("Qwen document embeddings contained non-finite values")
        return vectors
