import hashlib

import torch
from torch import Tensor, nn

from .features import tokenize


class HashedTextEncoder(nn.Module):
    def __init__(self, buckets: int = 65_536, dimension: int = 96) -> None:
        super().__init__()
        self.buckets = buckets
        self.embedding = nn.EmbeddingBag(buckets, dimension, mode="mean")
        nn.init.normal_(self.embedding.weight, std=0.02)

    def token_id(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode(), digest_size=8, person=b"adoptrank").digest()
        return int.from_bytes(digest, "little") % self.buckets

    def forward(self, texts: list[str], device: torch.device) -> Tensor:
        token_ids: list[int] = []
        offsets: list[int] = []
        for text in texts:
            offsets.append(len(token_ids))
            ids = [self.token_id(token) for token in tokenize(text)] or [0]
            token_ids.extend(ids)
        return self.embedding(
            torch.tensor(token_ids, dtype=torch.long, device=device),
            torch.tensor(offsets, dtype=torch.long, device=device),
        )


class AdoptRankModel(nn.Module):
    def __init__(self, structured_features: int = 12, embedding_dimension: int = 96) -> None:
        super().__init__()
        self.text = HashedTextEncoder(dimension=embedding_dimension)
        self.structured = nn.Sequential(
            nn.Linear(structured_features, 64),
            nn.LayerNorm(64),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(64, 64),
            nn.GELU(),
        )
        combined = embedding_dimension * 4 + 64
        self.ranker = nn.Sequential(
            nn.Linear(combined, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(256, 96),
            nn.GELU(),
            nn.Linear(96, 1),
        )
        self.adoption_head = nn.Sequential(
            nn.Linear(embedding_dimension + 64, 96),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(96, 1),
        )

    def forward(self, queries: list[str], repositories: list[str], features: Tensor) -> tuple[Tensor, Tensor]:
        device = features.device
        query = self.text(queries, device)
        repository = self.text(repositories, device)
        structured = self.structured(features)
        interaction = torch.cat([query, repository, query * repository, torch.abs(query - repository), structured], dim=1)
        relevance = self.ranker(interaction).squeeze(1)
        adoption = self.adoption_head(torch.cat([repository, structured], dim=1)).squeeze(1)
        return relevance, adoption
