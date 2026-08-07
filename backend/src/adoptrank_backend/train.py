import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .dataset import read_pairs
from .features import FEATURE_NAMES, repository_text, structured_features
from .model import AdoptRankModel


def _batch(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def train_model(dataset_path: Path, model_dir: Path, epochs: int = 18, batch_size: int = 32, seed: int = 17) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    pairs = read_pairs(dataset_path)
    if len(pairs) < 12:
        raise ValueError("At least 12 real ranking pairs are required for training")

    pairs.sort(key=lambda pair: (pair.observed_at, pair.positive.full_name))
    split = max(1, int(len(pairs) * 0.8))
    train_pairs, validation_pairs = pairs[:split], pairs[split:]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AdoptRankModel(structured_features=len(FEATURE_NAMES)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss(reduction="none")

    history: list[dict] = []
    for epoch in range(epochs):
        random.shuffle(train_pairs)
        model.train()
        losses: list[float] = []
        for items in _batch(train_pairs, batch_size):
            queries = [item.query for item in items]
            positive_text = [repository_text(item.positive) for item in items]
            negative_text = [repository_text(item.negative) for item in items]
            positive_features = torch.tensor(np.stack([structured_features(item.positive) for item in items]), device=device)
            negative_features = torch.tensor(np.stack([structured_features(item.negative) for item in items]), device=device)
            positive_score, adoption_logits = model(queries, positive_text, positive_features)
            negative_score, _ = model(queries, negative_text, negative_features)
            pairwise_loss = torch.nn.functional.softplus(-(positive_score - negative_score)).mean()

            mask = torch.tensor([item.adoption_target is not None for item in items], dtype=torch.float32, device=device)
            targets = torch.tensor([item.adoption_target or 0.0 for item in items], dtype=torch.float32, device=device)
            adoption_loss = (bce(adoption_logits, targets) * mask).sum() / mask.sum().clamp_min(1.0)
            loss = pairwise_loss + (0.35 * adoption_loss if mask.sum() else 0.0)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))

        accuracy, ndcg = evaluate(model, validation_pairs or train_pairs[-min(20, len(train_pairs)):], device)
        history.append({"epoch": epoch + 1, "loss": sum(losses) / len(losses), "pair_accuracy": accuracy, "ndcg": ndcg})

    model_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "feature_names": FEATURE_NAMES}, model_dir / "ranker.pt")
    metrics = {
        "model_version": "pytorch-ranknet-v1",
        "training_pairs": len(train_pairs),
        "validation_pairs": len(validation_pairs),
        "real_adoption_labels": sum(pair.adoption_target is not None for pair in pairs),
        "device": str(device),
        "history": history,
        "final": history[-1],
    }
    (model_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


@torch.no_grad()
def evaluate(model: AdoptRankModel, pairs: list, device: torch.device) -> tuple[float, float]:
    model.eval()
    correct = 0
    discounts = []
    for pair in pairs:
        features = torch.tensor(np.stack([structured_features(pair.positive), structured_features(pair.negative)]), device=device)
        scores, _ = model(
            [pair.query, pair.query],
            [repository_text(pair.positive), repository_text(pair.negative)],
            features,
        )
        is_correct = float(scores[0] > scores[1])
        correct += int(is_correct)
        discounts.append(1.0 if is_correct else 1.0 / math.log2(3.0))
    return correct / max(1, len(pairs)), sum(discounts) / max(1, len(discounts))
