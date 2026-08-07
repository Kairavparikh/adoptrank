from functools import cached_property

import numpy as np

from .config import settings

RERANK_INSTRUCTION = (
    "Rank open-source repositories by whether their actual implementation, architecture, dependencies, "
    "quality, and maintenance satisfy the developer's requirement"
)


class QwenReranker:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.reranker_model

    @cached_property
    def model(self):
        from sentence_transformers import CrossEncoder

        kwargs = {"device": settings.qwen_device or "cpu"}
        return CrossEncoder(
            self.model_name,
            max_length=2048,
            prompts={"adoptrank": RERANK_INSTRUCTION},
            default_prompt_name="adoptrank",
            **kwargs,
        )

    def score(self, query: str, documents: list[str]) -> np.ndarray:
        if not documents:
            return np.asarray([], dtype=np.float32)
        values = self.model.predict([(query, document) for document in documents], batch_size=4)
        scores = np.asarray(values, dtype=np.float32)
        return np.nan_to_num(scores, nan=-20.0, posinf=20.0, neginf=-20.0)
