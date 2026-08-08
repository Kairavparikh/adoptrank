import argparse
import asyncio
import os
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="adoptrank")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect")
    collect.add_argument("--queries", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--per-query", type=int, default=25)
    collect.add_argument(
        "--shallow",
        action="store_true",
        help="Skip per-repository release, contributor, and PyPI calls for large catalog backfills",
    )
    collect.add_argument("--page-delay-seconds", type=float, default=0.0)

    dataset = commands.add_parser("dataset")
    dataset.add_argument("--snapshots", type=Path, nargs="+", required=True)
    dataset.add_argument("--output", type=Path, required=True)

    analyze = commands.add_parser("analyze-code")
    analyze.add_argument("--snapshots", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--limit", type=int, default=20)
    analyze.add_argument("--files-per-repo", type=int, default=8)

    train = commands.add_parser("train")
    train.add_argument("--dataset", type=Path, required=True)
    train.add_argument("--snapshots", type=Path, required=True)
    train.add_argument("--model-dir", type=Path, required=True)
    train.add_argument("--epochs", type=int, default=18)

    serve = commands.add_parser("serve")
    serve.add_argument("--model-dir", type=Path, default=Path("artifacts/current"))
    serve.add_argument("--port", type=int, default=8000)

    scan = commands.add_parser("scan")
    scan.add_argument("path", type=Path, nargs="?", default=Path.cwd())

    find = commands.add_parser("find")
    find.add_argument("query")
    find.add_argument("--path", type=Path, default=Path.cwd())
    find.add_argument("--api", default="https://adoptrank.vercel.app")
    find.add_argument("--no-context", action="store_true")
    find.add_argument("--dry-run", action="store_true")
    find.add_argument("--limit", type=int, default=10)

    context = commands.add_parser("context")
    context.add_argument("query")
    context.add_argument("--path", type=Path, default=Path.cwd())
    context.add_argument("--budget", type=int, default=8000)
    context.add_argument("--api", default="https://adoptrank.vercel.app")
    context.add_argument("--no-external", action="store_true")
    context.add_argument("--json", action="store_true")

    benchmark_context = commands.add_parser("benchmark-context")
    benchmark_context.add_argument("--tasks", type=Path, required=True)
    benchmark_context.add_argument("--output", type=Path, required=True)
    benchmark_context.add_argument("--budget", type=int, default=8000)
    benchmark_context.add_argument("--task-prefix")
    benchmark_context.add_argument(
        "--modal-rerank",
        action="store_true",
        help="Explicitly send benchmark candidates to the authenticated Modal Qwen reranker",
    )
    benchmark_context.add_argument("--trained-checkpoint", default="context-ranker.pt")
    benchmark_context.add_argument(
        "--trained-context-rerank",
        action="store_true",
        help="Use the persisted task-trained Qwen/PyTorch context head",
    )

    generate_tasks = commands.add_parser("generate-context-tasks")
    generate_tasks.add_argument("--repo", type=Path, default=Path.cwd())
    generate_tasks.add_argument("--output", type=Path, required=True)
    generate_tasks.add_argument("--limit", type=int, default=50)

    prepare_benchmark = commands.add_parser("prepare-context-benchmark")
    prepare_benchmark.add_argument("--manifest", type=Path, required=True)
    prepare_benchmark.add_argument("--cache", type=Path, required=True)
    prepare_benchmark.add_argument("--output", type=Path, required=True)
    prepare_benchmark.add_argument("--tasks-per-repo", type=int, default=10)
    prepare_benchmark.add_argument("--depth", type=int, default=100)

    claude_benchmark = commands.add_parser("run-claude-benchmark")
    claude_benchmark.add_argument("--tasks", type=Path, required=True)
    claude_benchmark.add_argument("--output", type=Path, required=True)
    claude_benchmark.add_argument(
        "--condition", choices=("baseline", "adoptrank", "both"), default="both"
    )
    claude_benchmark.add_argument("--max-tasks", type=int, default=1)
    claude_benchmark.add_argument("--context-budget", type=int, default=8000)
    claude_benchmark.add_argument("--model", default="sonnet")
    claude_benchmark.add_argument("--max-budget-usd", type=float, default=1.0)
    claude_benchmark.add_argument("--max-turns", type=int, default=12)
    claude_benchmark.add_argument("--repetitions", type=int, choices=range(1, 6), default=1)
    claude_benchmark.add_argument("--trained-context-rerank", action="store_true")
    claude_benchmark.add_argument("--trained-checkpoint", default="context-ranker.pt")
    claude_benchmark.add_argument(
        "--resume",
        action="store_true",
        help="Resume an atomically checkpointed benchmark without repeating completed conditions",
    )

    context_dataset = commands.add_parser("context-dataset")
    context_dataset.add_argument("--tasks", type=Path, required=True)
    context_dataset.add_argument("--output", type=Path, required=True)
    context_dataset.add_argument("--pairs-per-task", type=int, default=5)

    train_context = commands.add_parser("train-context")
    train_context.add_argument("--pairs", type=Path, required=True)
    train_context.add_argument("--output", type=Path, required=True)
    train_context.add_argument("--epochs", type=int, default=12)
    train_context.add_argument("--embedding-dimension", type=int, default=1024)
    train_context.add_argument("--max-pairs", type=int)
    train_context.add_argument("--validation-fraction", type=float, default=0.20)
    train_context.add_argument("--seed", type=int, default=17)

    vectorize = commands.add_parser("vectorize")
    vectorize.add_argument("--snapshots", type=Path, required=True)

    persist = commands.add_parser("persist")
    persist.add_argument("--snapshots", type=Path, required=True)

    leaderboard = commands.add_parser("leaderboard")
    leaderboard.add_argument("--owner", "--username", dest="owner")
    leaderboard.add_argument("--language")
    leaderboard.add_argument("--license")
    leaderboard.add_argument(
        "--status", choices=("emerging", "durable", "hidden-gem", "overhyped", "at-risk")
    )
    leaderboard.add_argument("--window", type=int, choices=(1, 7, 30, 90), default=30)
    leaderboard.add_argument(
        "--sort",
        choices=(
            "overall",
            "adoption",
            "maintenance",
            "quality",
            "depth",
            "originality",
            "attention",
            "momentum",
            "stars",
        ),
        default="overall",
    )
    leaderboard.add_argument("--page", type=int, default=1)
    leaderboard.add_argument("--limit", type=int, default=20)
    leaderboard.add_argument("--api", default="https://adoptrank.vercel.app")

    args = parser.parse_args()
    if args.command == "collect":
        from .collectors import collect_queries

        count = asyncio.run(
            collect_queries(
                args.queries,
                args.output,
                args.per_query,
                hydrate_signals=not args.shallow,
                page_delay_seconds=max(0.0, args.page_delay_seconds),
            )
        )
        print(f"collected={count} output={args.output}")
    elif args.command == "dataset":
        from .dataset import build_pairs, load_snapshots, write_pairs

        pairs = build_pairs(load_snapshots(args.snapshots))
        write_pairs(pairs, args.output)
        print(f"pairs={len(pairs)} output={args.output}")
    elif args.command == "analyze-code":
        from .code_analysis import enrich_snapshot_file

        count = asyncio.run(
            enrich_snapshot_file(args.snapshots, args.output, args.limit, args.files_per_repo)
        )
        print(f"code_indexed={count} output={args.output}")
    elif args.command == "train":
        from .train import train_model

        args.model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.snapshots, args.model_dir / "repositories.jsonl")
        metrics = train_model(args.dataset, args.model_dir, args.epochs)
        print(f"model={args.model_dir} pair_accuracy={metrics['final']['pair_accuracy']:.4f}")
    elif args.command == "serve":
        import uvicorn

        os.environ["MODEL_DIR"] = str(args.model_dir)
        uvicorn.run("adoptrank_backend.service:app", host="0.0.0.0", port=args.port)
    elif args.command == "scan":
        from .local_scan import scan_project

        print(scan_project(args.path).model_dump_json(indent=2))
    elif args.command == "find":
        import json

        import httpx

        from .local_scan import scan_project

        context = None if args.no_context else scan_project(args.path)
        payload = {
            "query": args.query,
            "limit": args.limit,
            "project_context": context.model_dump() if context else None,
        }
        if args.dry_run:
            print(json.dumps(payload, indent=2))
            return
        base_url = args.api.rstrip("/")
        direct_ranker = "modal.run" in base_url or base_url.startswith(
            ("http://127.0.0.1", "http://localhost")
        )
        endpoint = (
            base_url
            if base_url.endswith(("/api/search", "/v1/search"))
            else f"{base_url}/v1/search" if direct_ranker
            else f"{base_url}/api/search"
        )
        headers = {}
        if endpoint.endswith("/v1/search") and os.environ.get("RANKER_API_KEY"):
            headers["x-adoptrank-key"] = os.environ["RANKER_API_KEY"]
        response = httpx.post(endpoint, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        for rank, result in enumerate(response.json()["results"], 1):
            print(
                f"{rank:02d} {result['full_name']}  {result['score']:.3f}\n   {result['url']}\n   {result['reason']}"
            )
    elif args.command == "context":
        import httpx

        from .context_pack import (
            build_context_pack,
            render_context_pack,
            search_external_code,
            search_external_repositories,
        )
        from .local_scan import scan_project

        external = []
        external_code = []
        external_error = None
        if not args.no_external:
            project = scan_project(args.path)
            try:
                external_code = search_external_code(
                    args.query, project, args.api, max(200, int(args.budget * 0.35))
                )
            except httpx.HTTPError as error:
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {404, 405}:
                    try:
                        external = search_external_repositories(args.query, project, args.api)
                    except httpx.HTTPError as fallback_error:
                        external_error = f"External repository evidence unavailable: {fallback_error}"
                else:
                    external_error = f"External code evidence unavailable: {error}"
        pack = build_context_pack(
            args.path, args.query, args.budget, external, external_code
        )
        if external_error:
            pack.warnings.append(external_error)
        print(pack.model_dump_json(indent=2) if args.json else render_context_pack(pack))
    elif args.command == "benchmark-context":
        from .context_benchmark import run_context_benchmark

        candidate_reranker = None
        if args.modal_rerank and args.trained_context_rerank:
            raise SystemExit("Choose only one Modal context reranker")
        if args.modal_rerank or args.trained_context_rerank:
            import modal

            function = modal.Function.from_name(
                "adoptrank-ranker",
                (
                    "rerank_context_candidates_trained"
                    if args.trained_context_rerank
                    else "rerank_context_candidates"
                ),
            )

            def candidate_reranker(query, documents):
                if args.trained_context_rerank:
                    return function.remote(query, documents, args.trained_checkpoint)
                return function.remote(query, documents)

        report = run_context_benchmark(
            args.tasks,
            args.output,
            args.budget,
            candidate_reranker=candidate_reranker,
            task_prefix=args.task_prefix,
        )
        print(
            f"tasks={report['task_count']} file_recall={report['mean_file_recall']:.3f} "
            f"pivot_approved={str(report['pivot_approved']).lower()} output={args.output}"
        )
    elif args.command == "generate-context-tasks":
        from .historical_tasks import generate_historical_tasks

        tasks = generate_historical_tasks(args.repo, args.output, args.limit)
        print(f"tasks={len(tasks)} output={args.output}")
    elif args.command == "prepare-context-benchmark":
        from .benchmark_corpus import prepare_public_benchmark

        tasks = prepare_public_benchmark(
            args.manifest,
            args.cache,
            args.output,
            tasks_per_repository=args.tasks_per_repo,
            depth=args.depth,
        )
        repositories = len({task["source_repository"] for task in tasks})
        print(f"tasks={len(tasks)} repositories={repositories} output={args.output}")
    elif args.command == "run-claude-benchmark":
        from .claude_benchmark import run_claude_benchmark

        candidate_reranker = None
        context_model = "lexical-bm25-ast"
        if args.trained_context_rerank:
            import modal

            function = modal.Function.from_name(
                "adoptrank-ranker", "rerank_context_candidates_trained"
            )

            def candidate_reranker(query, documents):
                return function.remote(query, documents, args.trained_checkpoint)

            context_model = f"qwen3-context-ranknet:{args.trained_checkpoint}"
        report = run_claude_benchmark(
            args.tasks,
            args.output,
            args.condition,
            args.max_tasks,
            args.context_budget,
            args.model,
            args.max_budget_usd,
            args.max_turns,
            args.repetitions,
            candidate_reranker,
            context_model,
            args.resume,
        )
        print(
            f"tasks={report['task_count']} condition={report['condition']} "
            f"maximum_authorized_cost_usd={report['maximum_authorized_cost_usd']:.2f} "
            f"maximum_additional_authorized_cost_usd="
            f"{report['maximum_additional_authorized_cost_usd']:.2f} "
            f"output={args.output}"
        )
    elif args.command == "context-dataset":
        from .context_dataset import build_context_pairs

        pairs = build_context_pairs(args.tasks, args.output, args.pairs_per_task)
        print(f"pairs={len(pairs)} output={args.output}")
    elif args.command == "train-context":
        from .train_context import train_context_ranker

        metrics = train_context_ranker(
            args.pairs,
            args.output,
            args.epochs,
            args.embedding_dimension,
            args.max_pairs,
            validation_fraction=args.validation_fraction,
            seed=args.seed,
        )
        print(
            f"pairs={metrics['training_pairs']} "
            f"pair_accuracy={metrics['final']['pair_accuracy']:.3f} output={args.output}"
        )
    elif args.command == "vectorize":
        from .config import settings
        from .vector_index import populate_pgvector

        if not settings.database_url:
            raise SystemExit("DATABASE_URL is required")
        count = asyncio.run(populate_pgvector(settings.database_url, args.snapshots))
        print(f"embedded_chunks={count}")
    elif args.command == "persist":
        from .config import settings
        from .dataset import load_snapshots
        from .storage import persist_code_analysis, persist_snapshots

        if not settings.database_url:
            raise SystemExit("DATABASE_URL is required")
        snapshots = load_snapshots([args.snapshots])
        observations = asyncio.run(persist_snapshots(settings.database_url, snapshots))
        evidence = asyncio.run(persist_code_analysis(settings.database_url, snapshots))
        print(f"observations={observations} code_evidence={evidence}")
    elif args.command == "leaderboard":
        import httpx

        status_names = {
            "emerging": "Emerging",
            "durable": "Durable",
            "hidden-gem": "Hidden gem",
            "overhyped": "Overhyped",
            "at-risk": "At risk",
        }
        base_url = args.api.rstrip("/")
        endpoint = base_url if base_url.endswith("/api/leaderboard") else f"{base_url}/api/leaderboard"
        response = httpx.get(
            endpoint,
            params={
                key: value
                for key, value in {
                    "owner": args.owner,
                    "language": args.language,
                    "license": args.license,
                    "status": status_names.get(args.status),
                    "window": args.window,
                    "sort": args.sort,
                    "page": max(1, args.page),
                    "limit": max(5, min(50, args.limit)),
                }.items()
                if value is not None
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        print(
            f"AdoptRank leaderboard · {payload['total']} repositories · "
            f"{args.window}d · page {payload['page']}/{payload['totalPages']}"
        )
        for item in payload["items"]:
            delta = item["rankDelta"]
            movement = "new" if delta is None else f"↑{delta}" if delta > 0 else f"↓{abs(delta)}" if delta < 0 else "—"
            print(
                f"{item['globalRank']:04d} {item['fullName']}  {item['score'] * 100:5.1f}  "
                f"{item['status']}  {movement}\n     {item['url']}"
            )


if __name__ == "__main__":
    main()
