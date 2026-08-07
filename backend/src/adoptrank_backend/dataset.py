import json
from collections import defaultdict
from pathlib import Path

from .features import adoption_growth, observed_adoption_acceleration, repository_text, tokenize
from .schemas import RepositorySnapshot, TrainingPair

STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "open", "source", "library", "framework"}


def load_snapshots(paths: list[Path]) -> list[RepositorySnapshot]:
    snapshots: list[RepositorySnapshot] = []
    for path in paths:
        with path.open() as handle:
            snapshots.extend(RepositorySnapshot.model_validate_json(line) for line in handle if line.strip())
    return snapshots


def query_from_repo(repo: RepositorySnapshot) -> str:
    topic_tokens = [token for topic in repo.topics[:5] for token in tokenize(topic)]
    description_tokens = [token for token in tokenize(repo.description) if token not in STOPWORDS][:8]
    terms = list(dict.fromkeys(topic_tokens + description_tokens + [repo.language.lower()]))
    return " ".join(terms[:12])


def overlap(query: str, repo: RepositorySnapshot) -> float:
    query_tokens = set(tokenize(query))
    repo_tokens = set(tokenize(repository_text(repo)))
    return len(query_tokens & repo_tokens) / max(1, len(query_tokens | repo_tokens))


def build_pairs(snapshots: list[RepositorySnapshot]) -> list[TrainingPair]:
    by_repo: dict[str, list[RepositorySnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        by_repo[snapshot.full_name.lower()].append(snapshot)
    latest = [sorted(values, key=lambda value: value.captured_at)[-1] for values in by_repo.values()]
    if len(latest) < 3:
        raise ValueError("At least three real repositories are required to build ranking pairs")

    pairs: list[TrainingPair] = []
    for positive in latest:
        query = query_from_repo(positive)
        if len(tokenize(query)) < 2:
            continue
        negatives = [repo for repo in latest if repo.full_name != positive.full_name and not repo.archived]
        same_language = [repo for repo in negatives if repo.language == positive.language]
        pool = same_language or negatives
        pool.sort(key=lambda repo: overlap(query, repo), reverse=True)

        history = sorted(by_repo[positive.full_name.lower()], key=lambda value: value.captured_at)
        adoption_target = observed_adoption_acceleration(positive)
        if len(history) > 1 and (history[-1].captured_at - history[0].captured_at).days >= 7:
            adoption_target = adoption_growth(history[0], history[-1])

        for negative in pool[:3]:
            pairs.append(
                TrainingPair(
                    query=query,
                    positive=positive,
                    negative=negative,
                    adoption_target=adoption_target,
                    observed_at=positive.captured_at,
                )
            )
    return pairs


def write_pairs(pairs: list[TrainingPair], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        for pair in pairs:
            handle.write(pair.model_dump_json() + "\n")


def read_pairs(path: Path) -> list[TrainingPair]:
    with path.open() as handle:
        return [TrainingPair.model_validate(json.loads(line)) for line in handle if line.strip()]
