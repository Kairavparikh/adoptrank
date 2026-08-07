import hashlib
import difflib
import json
import random
import subprocess
import time
from pathlib import Path

from .context_pack import build_context_pack, estimate_tokens, render_context_pack
from .historical_tasks import materialize_task_repository


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        relative = str(path.relative_to(root))
        if any(part in {".git", "node_modules", ".venv", "dist", "build"} for part in path.parts):
            continue
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _text_files(root: Path) -> dict[str, str]:
    contents: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 200_000:
            continue
        relative = str(path.relative_to(root))
        if any(part in {".git", "node_modules", ".venv", "dist", "build"} for part in path.parts):
            continue
        try:
            contents[relative] = path.read_text()
        except UnicodeDecodeError:
            continue
    return contents


def _usage(payload: dict) -> dict[str, int | float | None]:
    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "total_input_tokens": input_tokens + cache_creation + cache_read,
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cost_usd": payload.get("total_cost_usd"),
    }


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _parse_stream(output: str) -> tuple[dict, dict]:
    result: dict = {}
    tool_uses: dict[str, dict] = {}
    file_reads: list[str] = []
    repository_tool_tokens = 0
    tool_calls: dict[str, int] = {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
        message = event.get("message") or {}
        blocks = message.get("content") or []
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                tool_uses[str(block.get("id", ""))] = {
                    "name": name,
                    "input": block.get("input") or {},
                }
                tool_calls[name] = tool_calls.get(name, 0) + 1
            elif block.get("type") == "tool_result":
                tool = tool_uses.get(str(block.get("tool_use_id", "")), {})
                name = tool.get("name")
                if name not in {"Read", "Grep", "Glob"}:
                    continue
                text = _content_text(block.get("content"))
                repository_tool_tokens += estimate_tokens(text)
                tool_input = tool.get("input") or {}
                path = tool_input.get("file_path") or tool_input.get("path")
                if name == "Read" and path:
                    file_reads.append(str(path))
    return result, {
        "repository_tool_output_estimated_tokens": repository_tool_tokens,
        "file_reads": file_reads,
        "unique_files_read": sorted(set(file_reads)),
        "tool_calls": tool_calls,
    }


def _run_task_evaluator(root: Path, task: dict) -> tuple[bool | None, str]:
    command = task.get("test_command")
    if command:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=600)
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output[-6000:]
    contracts = task.get("patch_contract") or []
    if contracts:
        failures = []
        for contract in contracts:
            path = root / contract["path"]
            content = path.read_text(errors="ignore") if path.exists() else ""
            missing = [line for line in contract.get("required_lines", []) if line not in content]
            retained = [line for line in contract.get("forbidden_lines", []) if line in content]
            if missing or retained:
                failures.append(
                    {"path": contract["path"], "missing": missing, "retained": retained}
                )
        return not failures, json.dumps({"contract_failures": failures})
    if not command:
        return None, "No task-specific test command was supplied."
    raise AssertionError("unreachable")


def _run_condition(
    task: dict,
    condition: str,
    context_budget: int,
    model: str,
    max_budget_usd: float,
    max_turns: int,
    candidate_reranker=None,
) -> dict:
    with materialize_task_repository(
        Path(task["repository_path"]), task.get("base_commit")
    ) as root:
        before = _file_hashes(root)
        before_text = _text_files(root)
        context_text = ""
        context_estimate = 0
        context_latency_ms = 0.0
        retrieved_files: list[str] = []
        retrieval_file_recall = None
        if condition == "adoptrank":
            started = time.perf_counter()
            pack = build_context_pack(
                root,
                task["query"],
                context_budget,
                candidate_reranker=candidate_reranker,
            )
            context_latency_ms = (time.perf_counter() - started) * 1000
            context_text = render_context_pack(pack)
            # Measure exactly what is injected, not metadata retained only in
            # the structured ContextPack response.
            context_estimate = estimate_tokens(context_text)
            retrieved_files = sorted(
                {snippet.path for snippet in pack.snippets if snippet.source == "local"}
            )
            retrieval_file_recall = len(
                set(task.get("expected_files", [])) & set(retrieved_files)
            ) / max(1, len(task.get("expected_files", [])))
        prompt = (
            f"Implement this task in the current repository: {task['query']}\n\n"
            "Make the smallest correct change. Do not merely explain the solution. "
            "Do not access the network. Finish after editing the implementation."
        )
        if context_text:
            prompt += (
                "\n\nThe following evidence was generated from this exact checked-out commit. "
                "Treat included lines as current. Do not re-read an included file unless the edit "
                "requires lines that are absent from the excerpt; use repository tools only to fill "
                "a specific missing fact.\n\n"
                + context_text
            )
        command = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            model,
            "--max-budget-usd",
            str(max_budget_usd),
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read,Edit,Glob,Grep",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
        ]
        completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=1800)
        payload, trace = _parse_stream(completed.stdout)
        after = _file_hashes(root)
        after_text = _text_files(root)
        changed_files = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )
        test_success, test_output = _run_task_evaluator(root, task)
        patches = {}
        for path in changed_files:
            if path not in before_text and path not in after_text:
                continue
            patch = "".join(
                difflib.unified_diff(
                    before_text.get(path, "").splitlines(keepends=True),
                    after_text.get(path, "").splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            patches[path] = patch[-12_000:]
        return {
            "condition": condition,
            "exit_code": completed.returncode,
            "claude_result": payload.get("result", ""),
            "claude_error": completed.stderr[-4000:],
            "changed_files": changed_files,
            "patches": patches,
            "expected_file_recall": (
                len(set(task.get("expected_files", [])) & set(changed_files))
                / max(1, len(task.get("expected_files", [])))
            ),
            "task_success": test_success,
            "test_output": test_output,
            "context_estimated_tokens": context_estimate,
            "context_latency_ms": context_latency_ms,
            "retrieved_files": retrieved_files,
            "retrieval_file_recall": retrieval_file_recall,
            **trace,
            **_usage(payload),
        }


def _summary(results: list[dict]) -> dict:
    paired_results = []
    for result in results:
        by_condition = {run["condition"]: run for run in result["runs"]}
        if "baseline" in by_condition and "adoptrank" in by_condition:
            paired_results.append(
                (
                    str(result.get("task_id")),
                    by_condition["baseline"],
                    by_condition["adoptrank"],
                )
            )
    pairs = [(baseline, adoptrank) for _, baseline, adoptrank in paired_results]
    scored = [pair for pair in pairs if all(run["task_success"] is not None for run in pair)]
    scored_task_ids = {
        task_id
        for task_id, baseline, adoptrank in paired_results
        if baseline["task_success"] is not None and adoptrank["task_success"] is not None
    }
    baseline_tokens = sum(pair[0]["total_input_tokens"] for pair in pairs)
    adoptrank_tokens = sum(pair[1]["total_input_tokens"] for pair in pairs)
    baseline_repository_tokens = sum(
        int(pair[0].get("repository_tool_output_estimated_tokens") or 0) for pair in pairs
    )
    adoptrank_repository_tokens = sum(
        int(pair[1].get("repository_tool_output_estimated_tokens") or 0)
        + int(pair[1].get("context_estimated_tokens") or 0)
        for pair in pairs
    )
    baseline_cost = sum(float(pair[0]["cost_usd"] or 0) for pair in pairs)
    adoptrank_cost = sum(float(pair[1]["cost_usd"] or 0) for pair in pairs)
    retrieval_recalls = [
        pair[1]["retrieval_file_recall"]
        for pair in pairs
        if pair[1]["retrieval_file_recall"] is not None
    ]
    latencies = sorted(pair[1]["context_latency_ms"] for pair in pairs)
    p95_latency = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    baseline_success = (
        sum(bool(pair[0]["task_success"]) for pair in scored) / len(scored) if scored else None
    )
    adoptrank_success = (
        sum(bool(pair[1]["task_success"]) for pair in scored) / len(scored) if scored else None
    )
    token_reduction = 1 - adoptrank_tokens / baseline_tokens if baseline_tokens else None
    repository_token_reduction = (
        1 - adoptrank_repository_tokens / baseline_repository_tokens
        if baseline_repository_tokens
        else None
    )
    cost_reduction = 1 - adoptrank_cost / baseline_cost if baseline_cost else None
    mean_recall = sum(retrieval_recalls) / len(retrieval_recalls) if retrieval_recalls else None

    repository_reduction_ci95 = None
    grouped_pairs: dict[str, list[tuple[dict, dict]]] = {}
    for task_id, baseline, adoptrank in paired_results:
        grouped_pairs.setdefault(task_id, []).append((baseline, adoptrank))
    if len(grouped_pairs) >= 2:
        rng = random.Random(17)
        bootstrap_reductions = []
        task_ids = sorted(grouped_pairs)
        for _ in range(2000):
            sampled_task_ids = [task_ids[rng.randrange(len(task_ids))] for _ in task_ids]
            sample = [pair for task_id in sampled_task_ids for pair in grouped_pairs[task_id]]
            sample_baseline = sum(
                int(pair[0].get("repository_tool_output_estimated_tokens") or 0)
                for pair in sample
            )
            sample_adoptrank = sum(
                int(pair[1].get("repository_tool_output_estimated_tokens") or 0)
                + int(pair[1].get("context_estimated_tokens") or 0)
                for pair in sample
            )
            if sample_baseline:
                bootstrap_reductions.append(1 - sample_adoptrank / sample_baseline)
        if bootstrap_reductions:
            bootstrap_reductions.sort()
            repository_reduction_ci95 = [
                bootstrap_reductions[int(len(bootstrap_reductions) * 0.025)],
                bootstrap_reductions[min(len(bootstrap_reductions) - 1, int(len(bootstrap_reductions) * 0.975))],
            ]
    gates = {
        "at_least_30_controlled_tasks": len(scored_task_ids) >= 30,
        "repository_token_reduction_at_least_0_30": (
            repository_token_reduction is not None and repository_token_reduction >= 0.30
        ),
        "task_success_within_0_05": (
            baseline_success is not None
            and adoptrank_success is not None
            and adoptrank_success >= baseline_success - 0.05
        ),
        "retrieval_file_recall_at_least_0_80": mean_recall is not None and mean_recall >= 0.80,
        "context_p95_below_3000_ms": p95_latency is not None and p95_latency < 3000,
        "repository_token_reduction_ci95_above_zero": (
            repository_reduction_ci95 is not None and repository_reduction_ci95[0] > 0
        ),
    }
    return {
        "paired_tasks": len(pairs),
        "scored_tasks": len(scored),
        "unique_controlled_tasks": len(scored_task_ids),
        "baseline_task_success": baseline_success,
        "adoptrank_task_success": adoptrank_success,
        "processed_input_token_reduction": token_reduction,
        "repository_context_token_reduction": repository_token_reduction,
        "repository_context_token_reduction_ci95": repository_reduction_ci95,
        "estimated_cost_reduction": cost_reduction,
        "mean_retrieval_file_recall": mean_recall,
        "context_p95_latency_ms": p95_latency,
        "gates": gates,
        "pivot_approved": all(gates.values()),
    }


def run_claude_benchmark(
    tasks_path: Path,
    output_path: Path,
    condition: str = "both",
    max_tasks: int = 1,
    context_budget: int = 8000,
    model: str = "sonnet",
    max_budget_usd: float = 1.0,
    max_turns: int = 12,
    repetitions: int = 1,
    candidate_reranker=None,
    context_model: str = "lexical-bm25-ast",
) -> dict:
    tasks = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]
    selected_conditions = ["baseline", "adoptrank"] if condition == "both" else [condition]
    results = []
    if repetitions < 1 or repetitions > 5:
        raise ValueError("repetitions must be between 1 and 5")
    for task_index, task in enumerate(tasks[:max_tasks]):
        for repetition in range(repetitions):
            ordered_conditions = list(selected_conditions)
            if len(ordered_conditions) == 2 and (task_index + repetition) % 2:
                ordered_conditions.reverse()
            task_results = [
                _run_condition(
                    task,
                    selected,
                    context_budget,
                    model,
                    max_budget_usd,
                    max_turns,
                    candidate_reranker,
                )
                for selected in ordered_conditions
            ]
            results.append(
                {
                    "task_id": task.get("task_id"),
                    "query": task["query"],
                    "repetition": repetition + 1,
                    "runs": task_results,
                }
            )
    report = {
        "task_count": min(max_tasks, len(tasks)),
        "run_pair_count": len(results),
        "repetitions": repetitions,
        "condition": condition,
        "model": model,
        "context_model": context_model,
        "maximum_authorized_cost_usd": len(results) * len(selected_conditions) * max_budget_usd,
        "results": results,
        "summary": _summary(results),
        "warning": (
            "A passing repository test command is the task-success signal. "
            "Runs without task-specific tests remain unscored."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
