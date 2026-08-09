import json
import hashlib
import math
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch

from .context_model import ContextValueRanker, context_infonce_loss, context_ranknet_loss
from .embeddings import QwenEmbedder


def _features(item: dict) -> list[float]:
    path = item["path"].lower()
    return [
        float(item.get("lexical_score", 0.0)),
        math.log1p(item.get("estimated_tokens", 0)) / 10.0,
        float("test" in path or "spec" in path),
        1.0 / math.log2(float(item.get("candidate_rank", 100)) + 2.0),
    ]


def train_context_ranker(
    pairs_path: Path,
    output_path: Path,
    epochs: int = 12,
    embedding_dimension: int = 1024,
    max_pairs: int | None = None,
    embedder=None,
    validation_fraction: float = 0.20,
    seed: int = 17,
    validation_group_prefix: str | None = None,
) -> dict:
    pairs = [json.loads(line) for line in pairs_path.read_text().splitlines() if line.strip()]
    if max_pairs is not None:
        pairs = pairs[:max_pairs]
    if len(pairs) < 4:
        raise ValueError("At least four context pairs are required")
    if not 0.0 < validation_fraction < 0.5:
        raise ValueError("validation_fraction must be between 0 and 0.5")
    torch.manual_seed(seed)
    np.random.seed(seed)

    groups = sorted({str(pair.get("task_id") or pair["query"]) for pair in pairs})
    if validation_group_prefix:
        validation_groups = {
            group
            for group in groups
            if group == validation_group_prefix or group.startswith(validation_group_prefix + "@")
        }
        if not validation_groups:
            raise ValueError("validation_group_prefix did not match any task group")
    else:
        validation_group_count = (
            max(1, round(len(groups) * validation_fraction)) if len(groups) > 1 else 0
        )
        generator = np.random.default_rng(seed)
        shuffled_groups = list(groups)
        generator.shuffle(shuffled_groups)
        validation_groups = set(shuffled_groups[:validation_group_count])
    validation_indices = [
        index
        for index, pair in enumerate(pairs)
        if str(pair.get("task_id") or pair["query"]) in validation_groups
    ]
    train_indices = [index for index in range(len(pairs)) if index not in set(validation_indices)]
    if not train_indices:
        raise ValueError("Task-grouped split left no training pairs")
    embedder = embedder or QwenEmbedder(dimension=embedding_dimension)
    queries = [pair["query"] for pair in pairs]
    positives = [pair["positive"]["path"] + "\n" + pair["positive"]["content"] for pair in pairs]
    negatives = [pair["negative"]["path"] + "\n" + pair["negative"]["content"] for pair in pairs]
    query_embeddings = torch.tensor(embedder.encode_queries(queries), dtype=torch.float32)
    positive_embeddings = torch.tensor(embedder.encode_documents(positives), dtype=torch.float32)
    negative_embeddings = torch.tensor(embedder.encode_documents(negatives), dtype=torch.float32)
    positive_features = torch.tensor(
        np.asarray([_features(pair["positive"]) for pair in pairs]), dtype=torch.float32
    )
    negative_features = torch.tensor(
        np.asarray([_features(pair["negative"]) for pair in pairs]), dtype=torch.float32
    )
    model = ContextValueRanker(embedding_dimension)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-3)
    history = []
    best_state = deepcopy(model.state_dict())
    best_validation_accuracy = -1.0
    best_epoch = 0

    train_index = torch.tensor(train_indices, dtype=torch.long)
    validation_index = torch.tensor(validation_indices, dtype=torch.long)
    for _ in range(epochs):
        optimizer.zero_grad()
        positive_scores = model(
            query_embeddings[train_index],
            positive_embeddings[train_index],
            positive_features[train_index],
        )
        negative_scores = model(
            query_embeddings[train_index],
            negative_embeddings[train_index],
            negative_features[train_index],
        )
        rank_loss = context_ranknet_loss(positive_scores, negative_scores)
        contrastive_loss = context_infonce_loss(
            model.query_projection(query_embeddings),
            model.code_projection(positive_embeddings),
            model.code_projection(negative_embeddings),
        )
        loss = rank_loss + 0.25 * contrastive_loss
        loss.backward()
        optimizer.step()
        accuracy = float((positive_scores > negative_scores).float().mean())
        with torch.no_grad():
            if validation_indices:
                validation_positive = model(
                    query_embeddings[validation_index],
                    positive_embeddings[validation_index],
                    positive_features[validation_index],
                )
                validation_negative = model(
                    query_embeddings[validation_index],
                    negative_embeddings[validation_index],
                    negative_features[validation_index],
                )
                validation_accuracy = float(
                    (validation_positive > validation_negative).float().mean()
                )
            else:
                validation_accuracy = accuracy
        history.append(
            {
                "loss": float(loss.detach()),
                "pair_accuracy": accuracy,
                "validation_pair_accuracy": validation_accuracy,
            }
        )
        if validation_accuracy >= best_validation_accuracy:
            best_validation_accuracy = validation_accuracy
            best_epoch = len(history)
            best_state = deepcopy(model.state_dict())

    model.load_state_dict(best_state)
    with torch.no_grad():
        if validation_indices:
            margins = (
                model(
                    query_embeddings[validation_index],
                    positive_embeddings[validation_index],
                    positive_features[validation_index],
                )
                - model(
                    query_embeddings[validation_index],
                    negative_embeddings[validation_index],
                    negative_features[validation_index],
                )
            ).cpu().numpy()
            positive_margins = margins[margins > 0]
            abstention_margin = float(np.quantile(positive_margins, 0.10)) if len(positive_margins) else 0.0
        else:
            abstention_margin = 0.0
    dataset_fingerprint = hashlib.sha256(pairs_path.read_bytes()).hexdigest()
    final = history[best_epoch - 1]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": best_state,
            "embedding_dimension": embedding_dimension,
            "training_pairs": len(pairs),
            "train_pairs": len(train_indices),
            "validation_pairs": len(validation_indices),
            "training_task_groups": len(groups) - len(validation_groups),
            "validation_task_groups": len(validation_groups),
            "training_group_ids": sorted(set(groups) - validation_groups),
            "validation_group_ids": sorted(validation_groups),
            "epochs": epochs,
            "best_epoch": best_epoch,
            "final": final,
            "abstention_margin": abstention_margin,
            "dataset_sha256": dataset_fingerprint,
            "seed": seed,
        },
        output_path,
    )
    return {
        "training_pairs": len(pairs),
        "train_pairs": len(train_indices),
        "validation_pairs": len(validation_indices),
        "task_groups": len(groups),
        "training_group_ids": sorted(set(groups) - validation_groups),
        "validation_group_ids": sorted(validation_groups),
        "epochs": epochs,
        "best_epoch": best_epoch,
        "abstention_margin": abstention_margin,
        "dataset_sha256": dataset_fingerprint,
        "final": final,
    }
