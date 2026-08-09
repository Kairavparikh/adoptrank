import json
from pathlib import Path

from .context_pack import _local_candidates, estimate_tokens
from .historical_tasks import materialize_task_repository


def build_context_pairs(tasks_path: Path, output_path: Path, pairs_per_task: int = 5) -> list[dict]:
    tasks = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]
    pairs: list[dict] = []
    for task in tasks:
        expected = set(task.get("expected_files", []))
        if not expected:
            continue
        with materialize_task_repository(
            Path(task["repository_path"]), task.get("base_commit")
        ) as root:
            candidates = _local_candidates(root, task["query"])
        best_by_path = {}
        for candidate in candidates:
            best_by_path.setdefault(candidate.path, candidate)
        candidate_ranks = {path: rank for rank, path in enumerate(best_by_path, 1)}
        positives = [best_by_path[path] for path in expected if path in best_by_path]
        negatives = [
            candidate for path, candidate in best_by_path.items() if path not in expected
        ]
        negatives.sort(key=lambda item: (-item.score, item.path))
        for positive in positives[:pairs_per_task]:
            for negative in negatives[:pairs_per_task]:
                pairs.append(
                    {
                        "task_id": task.get("task_id"),
                        "query": task["query"],
                        "base_commit": task.get("base_commit"),
                        "positive": {
                            "path": positive.path,
                            "content": positive.content,
                            "lexical_score": positive.score,
                            "estimated_tokens": estimate_tokens(positive.content),
                            "candidate_rank": candidate_ranks[positive.path],
                        },
                        "negative": {
                            "path": negative.path,
                            "content": negative.content,
                            "lexical_score": negative.score,
                            "estimated_tokens": estimate_tokens(negative.content),
                            "candidate_rank": candidate_ranks[negative.path],
                        },
                        "label_source": "historical_changed_file",
                    }
                )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(json.dumps(pair) + "\n" for pair in pairs))
    return pairs
