import argparse
import asyncio
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="adoptrank-backend")
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

        count = asyncio.run(enrich_snapshot_file(args.snapshots, args.output, args.limit, args.files_per_repo))
        print(f"code_indexed={count} output={args.output}")
    elif args.command == "train":
        from .train import train_model

        args.model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.snapshots, args.model_dir / "repositories.jsonl")
        metrics = train_model(args.dataset, args.model_dir, args.epochs)
        print(f"model={args.model_dir} pair_accuracy={metrics['final']['pair_accuracy']:.4f}")
    elif args.command == "serve":
        import os

        import uvicorn

        os.environ["MODEL_DIR"] = str(args.model_dir)
        uvicorn.run("adoptrank_backend.service:app", host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
