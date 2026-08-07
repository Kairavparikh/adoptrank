import math
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from .config import settings
from .embeddings import QwenEmbedder
from .features import FEATURE_NAMES, repository_text, structured_features, tokenize
from .model import AdoptRankModel
from .reranker import QwenReranker
from .schemas import ProjectContext, RankedRepository, RepositorySnapshot


class RankingIndex:
    def __init__(self, model_dir: Path) -> None:
        self.repositories = self._load_repositories(model_dir / "repositories.jsonl")
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        )
        checkpoint = torch.load(model_dir / "ranker.pt", map_location=self.device, weights_only=True)
        self.embedding_dimension = checkpoint.get("embedding_dimension", settings.embedding_dimension)
        self.embedder = QwenEmbedder(checkpoint.get("embedding_model"), self.embedding_dimension)
        self.model = AdoptRankModel(len(FEATURE_NAMES), self.embedding_dimension).to(self.device)
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()
        self.reranker = None if settings.disable_reranker else QwenReranker()
        self.texts = [repository_text(repo) for repo in self.repositories]
        cache_path = model_dir / "embedding_cache.npz"
        cache = np.load(cache_path, allow_pickle=False) if cache_path.exists() else None
        if cache is not None:
            cached = dict(zip(cache["texts"].tolist(), cache["vectors"], strict=True))
            missing = [text for text in self.texts if text not in cached]
            if missing:
                cached.update(zip(missing, self.embedder.encode_documents(missing), strict=True))
            self.repo_embeddings = np.stack([cached[text] for text in self.texts]).astype(np.float32)
        else:
            self.repo_embeddings = self.embedder.encode_documents(self.texts)
        self.repo_embeddings = np.nan_to_num(self.repo_embeddings, nan=0.0, posinf=0.0, neginf=0.0)
        self.repo_embeddings /= np.linalg.norm(self.repo_embeddings, axis=1, keepdims=True).clip(1e-8)
        self.documents = [tokenize(text) for text in self.texts]
        self.df = Counter(token for doc in self.documents for token in set(doc))
        self.avg = sum(map(len, self.documents)) / max(1, len(self.documents))
        if settings.warm_models:
            self.embedder.encode_queries(["open-source repository search"])
            if self.reranker and self.texts:
                self.reranker.score("open-source repository search", [self.texts[0][:2000]])

    @staticmethod
    def _load_repositories(path):
        with path.open() as handle:
            return [RepositorySnapshot.model_validate_json(line) for line in handle if line.strip()]

    def _bm25(self, query):
        terms = tokenize(query)
        total = len(self.documents)
        scores = []
        for i, doc in enumerate(self.documents):
            counts = Counter(doc)
            score = 0.0
            for term in terms:
                f = counts[term]
                if f:
                    score += (
                        math.log(1 + (total - self.df[term] + 0.5) / (self.df[term] + 0.5))
                        * f
                        * 2.2
                        / (f + 1.2 * (0.25 + 0.75 * len(doc) / max(1, self.avg)))
                    )
            scores.append(score)
        return np.asarray(scores, dtype=np.float32)

    @torch.no_grad()
    def search(self, query: str, limit: int = 10, context: ProjectContext | None = None):
        context_text = ""
        if context:
            context_text = " Project context: " + " ".join(
                [
                    *context.languages,
                    *context.frameworks,
                    *context.dependencies,
                    *context.symbols,
                    context.summary,
                ]
            )
        full_query = query + context_text
        lexical = self._bm25(full_query)
        qvec = self.embedder.encode_queries([full_query])[0]
        qvec = np.nan_to_num(qvec, nan=0.0, posinf=0.0, neginf=0.0)
        qvec /= max(1e-8, float(np.linalg.norm(qvec)))
        dense = self.repo_embeddings @ qvec
        hybrid = 0.45 * (lexical / max(1e-6, float(lexical.max()))) + 0.55 * ((dense + 1) / 2)
        candidate_ids = np.argsort(-hybrid)[:50]
        candidates = [self.repositories[i] for i in candidate_ids]
        texts = [self.texts[i] for i in candidate_ids]
        q = torch.tensor(np.stack([qvec] * len(candidates)), device=self.device)
        r = torch.tensor(self.repo_embeddings[candidate_ids], device=self.device)
        f = torch.tensor(np.stack([structured_features(x) for x in candidates]), device=self.device)
        outputs = self.model(q, r, f)
        learned = torch.sigmoid(outputs["relevance"]).cpu().numpy()
        cross = learned.copy()
        if self.reranker:
            count = min(settings.rerank_candidates, len(texts))
            cross[:count] = self.reranker.score(full_query, texts[:count])
        if len(cross):
            cross = 1 / (1 + np.exp(-np.clip(cross, -20, 20)))
        final = 0.25 * hybrid[candidate_ids] + 0.25 * learned + 0.50 * cross
        order = np.argsort(-final)[:limit]
        results = []
        for j in order:
            repo = candidates[j]
            heads = {
                name: float(torch.sigmoid(outputs[name][j]).cpu())
                for name in ("adoption", "depth", "quality", "maintenance", "originality")
            }
            results.append(
                RankedRepository(
                    full_name=repo.full_name,
                    url=repo.html_url,
                    description=repo.description,
                    score=float(final[j]),
                    adoption_probability=heads["adoption"],
                    reason=self._reason(repo),
                    language=repo.language,
                    license=repo.license_spdx,
                    updated_at=repo.pushed_at,
                    source="qwen3-hybrid",
                    code_evidence=repo.code_evidence_paths[:3],
                    relevance_score=float(learned[j]),
                    depth_score=heads["depth"],
                    quality_score=heads["quality"],
                    maintenance_score=heads["maintenance"],
                    originality_score=heads["originality"],
                )
            )
        return results

    @staticmethod
    def _reason(repo):
        evidence = [
            f"implements {', '.join(repo.topics[:2])}" if repo.topics else "source-level capability match"
        ]
        if repo.code_evidence_paths:
            evidence.append(f"verified in {', '.join(repo.code_evidence_paths[:2])}")
        return "; ".join(evidence)
