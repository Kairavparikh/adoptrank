import json
import subprocess
import re
from pathlib import Path

import httpx

from .historical_tasks import generate_historical_tasks


def _run(*command: str) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)


def _clean_pull_request_text(value: str) -> str:
    value = re.sub(r"<!--[\s\S]*?-->", "", value)
    value = re.sub(r"<details>[\s\S]*?</details>", "", value, flags=re.IGNORECASE)
    value = re.split(r"^#{1,3}\s*(?:Checklist|Tests?|Test plan)\s*$", value, flags=re.I | re.M)[0]
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()[:1200]


def _enrich_tasks_from_github(
    full_name: str, tasks: list[dict], client: httpx.Client
) -> None:
    for task in tasks:
        match = re.search(r"#(\d+)\)?$", task["query"])
        endpoint = (
            f"/repos/{full_name}/pulls/{match.group(1)}"
            if match
            else f"/repos/{full_name}/commits/{task['target_commit']}/pulls"
        )
        response = client.get(endpoint)
        if response.status_code != 200:
            continue
        payload = response.json()
        pull_request = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(pull_request, dict) or not pull_request.get("title"):
            continue
        body = _clean_pull_request_text(pull_request.get("body") or "")
        task["query"] = pull_request["title"] + (f"\n\n{body}" if body else "")
        task["pull_request_url"] = pull_request.get("html_url")


def prepare_public_benchmark(
    manifest_path: Path,
    cache_dir: Path,
    output_path: Path,
    *,
    tasks_per_repository: int = 10,
    depth: int = 100,
    enrich_pull_requests: bool = True,
) -> list[dict]:
    """Clone public repositories and create commit-pinned hidden-contract tasks."""
    manifest = json.loads(manifest_path.read_text())
    repositories = manifest.get("repositories", [])
    if not repositories:
        raise ValueError("Benchmark manifest has no repositories")
    cache_dir.mkdir(parents=True, exist_ok=True)
    combined: list[dict] = []
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AdoptRank-Benchmark/0.1",
    }
    with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30) as client:
        for repository in repositories:
            full_name = repository["full_name"]
            url = repository.get("url") or f"https://github.com/{full_name}.git"
            destination = cache_dir / full_name.replace("/", "__")
            if not (destination / ".git").exists():
                _run(
                    "git",
                    "clone",
                    "--quiet",
                    "--depth",
                    str(max(20, depth)),
                    url,
                    str(destination),
                )
            tasks_path = cache_dir / f"{full_name.replace('/', '__')}.jsonl"
            tasks = generate_historical_tasks(
                destination,
                tasks_path,
                limit=int(repository.get("task_limit", tasks_per_repository)),
            )
            if enrich_pull_requests and url.startswith("https://github.com/"):
                _enrich_tasks_from_github(full_name, tasks, client)
            for task in tasks:
                task["repository_path"] = str(destination)
                task["source_repository"] = full_name
                task["task_id"] = f"{full_name}@{task['task_id']}"
            combined.extend(tasks)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(json.dumps(task) + "\n" for task in combined))
    return combined
