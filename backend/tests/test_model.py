import numpy as np
import torch

from adoptrank_backend.features import FEATURE_NAMES
from adoptrank_backend.model import AdoptRankModel


def test_ranker_forward_shapes_and_gradients() -> None:
    model = AdoptRankModel(structured_features=len(FEATURE_NAMES), embedding_dimension=32)
    features = torch.tensor(np.zeros((2, len(FEATURE_NAMES)), dtype=np.float32))
    outputs = model(torch.randn(2, 32), torch.randn(2, 32), features)
    assert outputs["relevance"].shape == (2,)
    assert outputs["adoption"].shape == (2,)
    (outputs["relevance"].mean() + outputs["adoption"].mean()).backward()
    assert model.query_projection[0].weight.grad is not None
