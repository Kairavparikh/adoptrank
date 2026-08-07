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

        count = asyncio.run(collect_queries(args.queries, args.output, args.per_query))
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
