import math
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from .features import FEATURE_NAMES, repository_text, structured_features, tokenize
from .model import AdoptRankModel
from .schemas import RankedRepository, RepositorySnapshot


class RankingIndex:
    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir
        self.repositories = self._load_repositories(model_dir / "repositories.jsonl")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = AdoptRankModel(structured_features=len(FEATURE_NAMES)).to(self.device)
        checkpoint = torch.load(model_dir / "ranker.pt", map_location=self.device, weights_only=True)
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()
        metrics_path = model_dir / "metrics.json"
        self.adoption_trained = False
        if metrics_path.exists():
            import json

            self.adoption_trained = json.loads(metrics_path.read_text()).get("real_adoption_labels", 0) > 0
        self.documents = [tokenize(repository_text(repo)) for repo in self.repositories]
        self.document_frequency = Counter(token for document in self.documents for token in set(document))
        self.average_length = sum(map(len, self.documents)) / max(1, len(self.documents))

    @staticmethod
    def _load_repositories(path: Path) -> list[RepositorySnapshot]:
        with path.open() as handle:
            return [RepositorySnapshot.model_validate_json(line) for line in handle if line.strip()]

    def _bm25(self, query: str) -> list[tuple[int, float]]:
        terms = tokenize(query)
        scores: list[tuple[int, float]] = []
        total = len(self.documents)
        for index, document in enumerate(self.documents):
            counts = Counter(document)
            score = 0.0
            for term in terms:
                frequency = counts[term]
                if not frequency:
                    continue
                inverse = math.log(1 + (total - self.document_frequency[term] + 0.5) / (self.document_frequency[term] + 0.5))
                denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * len(document) / max(1, self.average_length))
                score += inverse * frequency * 2.2 / denominator
            scores.append((index, score))
        return sorted(scores, key=lambda item: item[1], reverse=True)

    @torch.no_grad()
    def search(self, query: str, limit: int = 10) -> list[RankedRepository]:
        lexical = [(index, score) for index, score in self._bm25(query)[:100] if score > 0]
        if not lexical:
            lexical = self._bm25(query)[:100]
        requested_languages = {
            language
            for language in ("python", "rust", "typescript", "javascript", "java", "go", "kotlin", "swift", "ruby")
            if language in set(tokenize(query))
        }
        if requested_languages:
            filtered = [item for item in lexical if self.repositories[item[0]].language.lower() in requested_languages]
            if len(filtered) >= limit:
                lexical = filtered
        candidates = [index for index, _ in lexical]
        repos = [self.repositories[index] for index in candidates]
        features = torch.tensor(np.stack([structured_features(repo) for repo in repos]), device=self.device)
        scores, adoption = self.model([query] * len(repos), [repository_text(repo) for repo in repos], features)
        neural_scores = scores.cpu().tolist()
        neural_min, neural_max = min(neural_scores), max(neural_scores)
        lexical_max = max(score for _, score in lexical) or 1.0
        query_terms = set(tokenize(query))
        fused_scores = []
        for repo, neural_score, (_, lexical_score) in zip(repos, neural_scores, lexical):
            neural_normalized = (neural_score - neural_min) / max(1e-6, neural_max - neural_min)
            lexical_normalized = lexical_score / lexical_max
            coverage = len(query_terms & set(tokenize(repository_text(repo)))) / max(1, len(query_terms))
            fused_scores.append(0.45 * lexical_normalized + 0.35 * neural_normalized + 0.20 * coverage)
        adoption_values = torch.sigmoid(adoption).cpu().tolist() if self.adoption_trained else [None] * len(repos)
        ranked = sorted(zip(repos, fused_scores, adoption_values), key=lambda item: item[1], reverse=True)
        return [
            RankedRepository(
                full_name=repo.full_name,
                url=repo.html_url,
                description=repo.description,
                score=float(score),
                adoption_probability=float(adoption_probability) if adoption_probability is not None else None,
                reason=self._reason(repo, adoption_probability),
                language=repo.language,
                license=repo.license_spdx,
                updated_at=repo.pushed_at,
            )
            for repo, score, adoption_probability in ranked[:limit]
        ]

    @staticmethod
    def _reason(repo: RepositorySnapshot, adoption_probability: float | None) -> str:
        evidence = []
        if repo.topics:
            evidence.append(f"implements {', '.join(repo.topics[:2])}")
        if repo.pypi_downloads_30d:
            evidence.append(f"{repo.pypi_downloads_30d:,} recent PyPI downloads")
        if adoption_probability is not None and adoption_probability >= 0.6:
            evidence.append("strong learned adoption signals")
        return "; ".join(evidence[:2]) or "matches the requested implementation and repository signals"
