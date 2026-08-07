import numpy as np
import torch

from adoptrank_backend.features import FEATURE_NAMES
from adoptrank_backend.model import AdoptRankModel


def test_ranker_forward_shapes_and_gradients() -> None:
    model = AdoptRankModel(structured_features=len(FEATURE_NAMES))
    features = torch.tensor(np.zeros((2, len(FEATURE_NAMES)), dtype=np.float32))
    relevance, adoption = model(
        ["streaming anomaly detection", "payment retry library"],
        ["python online anomaly detector", "typescript idempotent payment retries"],
        features,
    )
    assert relevance.shape == (2,)
    assert adoption.shape == (2,)
    (relevance.mean() + adoption.mean()).backward()
    assert model.text.embedding.weight.grad is not None
