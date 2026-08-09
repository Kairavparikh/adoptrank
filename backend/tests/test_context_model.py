import torch

from adoptrank_backend.context_model import (
    ContextValueRanker,
    context_infonce_loss,
    context_ranknet_loss,
)


def test_context_ranker_and_losses_are_trainable() -> None:
    model = ContextValueRanker(embedding_dimension=16, projection_dimension=8)
    query = torch.randn(3, 16)
    positive = torch.randn(3, 16)
    negative = torch.randn(3, 16)
    features = torch.zeros(3, 4)
    positive_scores = model(query, positive, features)
    negative_scores = model(query, negative, features)
    loss = context_ranknet_loss(positive_scores, negative_scores) + context_infonce_loss(
        model.query_projection(query),
        model.code_projection(positive),
        model.code_projection(negative),
    )
    loss.backward()
    assert positive_scores.shape == (3,)
    assert model.query_projection[0].weight.grad is not None
