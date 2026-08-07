import torch
from torch import Tensor, nn


class AdoptRankModel(nn.Module):
    """Trainable projection and multi-objective heads over frozen Qwen3 embeddings."""

    HEAD_NAMES = ("relevance", "adoption", "depth", "quality", "maintenance", "originality")

    def __init__(
        self, structured_features: int, embedding_dimension: int = 1024, projection_dimension: int = 256
    ) -> None:
        super().__init__()
        self.query_projection = nn.Sequential(
            nn.Linear(embedding_dimension, projection_dimension), nn.LayerNorm(projection_dimension)
        )
        self.repo_projection = nn.Sequential(
            nn.Linear(embedding_dimension, projection_dimension), nn.LayerNorm(projection_dimension)
        )
        self.structured = nn.Sequential(nn.Linear(structured_features, 96), nn.LayerNorm(96), nn.GELU())
        interaction_size = projection_dimension * 4 + 96
        self.interaction = nn.Sequential(nn.Linear(interaction_size, 256), nn.GELU(), nn.Dropout(0.1))
        self.heads = nn.ModuleDict({name: nn.Linear(256, 1) for name in self.HEAD_NAMES})

    def forward(
        self, query_embeddings: Tensor, repo_embeddings: Tensor, features: Tensor
    ) -> dict[str, Tensor]:
        query = torch.nn.functional.normalize(self.query_projection(query_embeddings), dim=1)
        repo = torch.nn.functional.normalize(self.repo_projection(repo_embeddings), dim=1)
        structured = self.structured(features)
        hidden = self.interaction(
            torch.cat([query, repo, query * repo, torch.abs(query - repo), structured], dim=1)
        )
        return {name: head(hidden).squeeze(1) for name, head in self.heads.items()} | {
            "query": query,
            "repo": repo,
        }


def info_nce_loss(query: Tensor, positive: Tensor, negatives: Tensor, temperature: float = 0.07) -> Tensor:
    positive_logit = (query * positive).sum(dim=1, keepdim=True)
    negative_logits = torch.einsum("bd,bnd->bn", query, negatives)
    logits = torch.cat([positive_logit, negative_logits], dim=1) / temperature
    return torch.nn.functional.cross_entropy(
        logits, torch.zeros(len(query), dtype=torch.long, device=query.device)
    )
