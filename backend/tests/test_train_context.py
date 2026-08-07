import json
from pathlib import Path

import numpy as np

from adoptrank_backend.train_context import train_context_ranker


class DummyEmbedder:
    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    @staticmethod
    def _encode(texts: list[str]) -> np.ndarray:
        rows = []
        for index, text in enumerate(texts):
            row = np.zeros(8, dtype=np.float32)
            row[index % 8] = 1.0
            row[(len(text) + index) % 8] += 0.5
            rows.append(row)
        return np.stack(rows)


def test_context_training_writes_checkpoint(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs.jsonl"
    rows = []
    for index in range(4):
        rows.append(
            {
                "query": f"task {index}",
                "positive": {
                    "path": f"src/right_{index}.py",
                    "content": "def right(): pass",
                    "lexical_score": 1.0,
                    "estimated_tokens": 10,
                    "candidate_rank": 1,
                },
                "negative": {
                    "path": f"src/wrong_{index}.py",
                    "content": "def wrong(): pass",
                    "lexical_score": 0.5,
                    "estimated_tokens": 10,
                    "candidate_rank": index + 2,
                },
            }
        )
    pairs.write_text("".join(json.dumps(row) + "\n" for row in rows))
    output = tmp_path / "ranker.pt"
    metrics = train_context_ranker(
        pairs,
        output,
        epochs=2,
        embedding_dimension=8,
        embedder=DummyEmbedder(),
    )
    assert output.exists()
    assert metrics["training_pairs"] == 4
    assert metrics["train_pairs"] == 3
    assert metrics["validation_pairs"] == 1
    assert metrics["task_groups"] == 4
    assert len(metrics["dataset_sha256"]) == 64
