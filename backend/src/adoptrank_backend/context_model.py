import torch
from torch import Tensor, nn


class ContextValueRanker(nn.Module):
    """Ranks code excerpts by task relevance and estimated utility per token."""

    def __init__(self, embedding_dimension: int = 1024, projection_dimension: int = 256) -> None:
        super().__init__()
        self.query_projection = nn.Sequential(
            nn.Linear(embedding_dimension, projection_dimension),
            nn.LayerNorm(projection_dimension),
        )
        self.code_projection = nn.Sequential(
            nn.Linear(embedding_dimension, projection_dimension),
            nn.LayerNorm(projection_dimension),
        )
        self.feature_head = nn.Sequential(
            nn.Linear(4, 32),
            nn.GELU(),
            nn.Linear(32, 1),
        )

    def forward(
        self,
        query_embeddings: Tensor,
        code_embeddings: Tensor,
        features: Tensor,
    ) -> Tensor:
        query = torch.nn.functional.normalize(self.query_projection(query_embeddings), dim=-1)
        code = torch.nn.functional.normalize(self.code_projection(code_embeddings), dim=-1)
        semantic = (query * code).sum(dim=-1)
        return semantic + self.feature_head(features).squeeze(-1)


def context_ranknet_loss(positive_scores: Tensor, negative_scores: Tensor) -> Tensor:
    return torch.nn.functional.softplus(-(positive_scores - negative_scores)).mean()


def context_infonce_loss(
    query_embeddings: Tensor,
    positive_embeddings: Tensor,
    negative_embeddings: Tensor,
    temperature: float = 0.07,
) -> Tensor:
    query = torch.nn.functional.normalize(query_embeddings, dim=-1)
    positive = torch.nn.functional.normalize(positive_embeddings, dim=-1)
    negative = torch.nn.functional.normalize(negative_embeddings, dim=-1)
    logits = torch.stack(
        [(query * positive).sum(dim=-1), (query * negative).sum(dim=-1)], dim=1
    ) / temperature
    labels = torch.zeros(len(query), dtype=torch.long, device=query.device)
    return torch.nn.functional.cross_entropy(logits, labels)
