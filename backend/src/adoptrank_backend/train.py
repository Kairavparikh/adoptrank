import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .config import settings
from .dataset import read_pairs
from .embeddings import QwenEmbedder
from .features import FEATURE_NAMES, repository_text, structured_features
from .model import AdoptRankModel, info_nce_loss


def _batch(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def train_model(
    dataset_path: Path, model_dir: Path, epochs: int = 18, batch_size: int = 16, seed: int = 17
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    pairs = read_pairs(dataset_path)
    if len(pairs) < 12:
        raise ValueError("At least 12 real ranking pairs are required for training")
    pairs.sort(key=lambda pair: (pair.observed_at, pair.positive.full_name))
    split = max(1, int(len(pairs) * 0.8))
    train_pairs, validation_pairs = pairs[:split], pairs[split:]
    embedder = QwenEmbedder()
    queries = list(dict.fromkeys(pair.query for pair in pairs))
    repo_texts = list(
        dict.fromkeys(repository_text(repo) for pair in pairs for repo in (pair.positive, pair.negative))
    )
    query_vectors = dict(zip(queries, embedder.encode_queries(queries), strict=True))
    repo_vectors = dict(zip(repo_texts, embedder.encode_documents(repo_texts), strict=True))
    device = torch.device(
        "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    )
    model = AdoptRankModel(len(FEATURE_NAMES), settings.embedding_dimension).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss(reduction="none")
    mse = nn.MSELoss()
    history = []
    for epoch in range(epochs):
        random.shuffle(train_pairs)
        model.train()
        losses = []
        for items in _batch(train_pairs, batch_size):
            q = torch.tensor(np.stack([query_vectors[x.query] for x in items]), device=device)
            pt = [repository_text(x.positive) for x in items]
            nt = [repository_text(x.negative) for x in items]
            p = torch.tensor(np.stack([repo_vectors[x] for x in pt]), device=device)
            n = torch.tensor(np.stack([repo_vectors[x] for x in nt]), device=device)
            pf = torch.tensor(np.stack([structured_features(x.positive) for x in items]), device=device)
            nf = torch.tensor(np.stack([structured_features(x.negative) for x in items]), device=device)
            po = model(q, p, pf)
            no = model(q, n, nf)
            pair_loss = torch.nn.functional.softplus(-(po["relevance"] - no["relevance"])).mean()
            contrastive = info_nce_loss(po["query"], po["repo"], no["repo"].unsqueeze(1))
            mask = torch.tensor(
                [x.adoption_target is not None for x in items], dtype=torch.float32, device=device
            )
            targets = torch.tensor([x.adoption_target or 0.0 for x in items], device=device)
            adoption = (bce(po["adoption"], targets) * mask).sum() / mask.sum().clamp_min(1)
            auxiliary = sum(
                mse(
                    torch.sigmoid(po[name]),
                    torch.tensor(
                        [
                            getattr(x.positive, f"{name}_score", 0.0)
                            if name != "maintenance"
                            else structured_features(x.positive)[3]
                            for x in items
                        ],
                        device=device,
                    ),
                )
                for name in ("depth", "quality", "maintenance", "originality")
            )
            loss = pair_loss + 0.35 * contrastive + 0.2 * adoption + 0.1 * auxiliary
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        accuracy, ndcg = evaluate(
            model, validation_pairs or train_pairs[-20:], query_vectors, repo_vectors, device
        )
        history.append(
            {"epoch": epoch + 1, "loss": sum(losses) / len(losses), "pair_accuracy": accuracy, "ndcg": ndcg}
        )
    model_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "feature_names": FEATURE_NAMES,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
        },
        model_dir / "ranker.pt",
    )
    np.savez_compressed(
        model_dir / "embedding_cache.npz",
        texts=np.asarray(repo_texts),
        vectors=np.stack([repo_vectors[text] for text in repo_texts]),
    )
    metrics = {
        "model_version": "qwen3-infonce-ranknet-v2",
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "training_pairs": len(train_pairs),
        "validation_pairs": len(validation_pairs),
        "real_adoption_labels": sum(x.adoption_target is not None for x in pairs),
        "device": str(device),
        "history": history,
        "final": history[-1],
    }
    (model_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


@torch.no_grad()
def evaluate(model, pairs, query_vectors, repo_vectors, device):
    model.eval()
    correct = 0
    discounts = []
    for pair in pairs:
        q = torch.tensor(np.stack([query_vectors[pair.query]] * 2), device=device)
        texts = [repository_text(pair.positive), repository_text(pair.negative)]
        r = torch.tensor(np.stack([repo_vectors[x] for x in texts]), device=device)
        f = torch.tensor(
            np.stack([structured_features(pair.positive), structured_features(pair.negative)]), device=device
        )
        scores = model(q, r, f)["relevance"]
        ok = float(scores[0] > scores[1])
        correct += int(ok)
        discounts.append(1.0 if ok else 1 / math.log2(3))
    return correct / max(1, len(pairs)), sum(discounts) / max(1, len(discounts))
