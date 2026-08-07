# AdoptRank CLI

AdoptRank finds open-source repositories that fit the project you are actually
building and exposes a live adoption leaderboard backed by real GitHub and PyPI
observations.

## Install

```bash
pipx install adoptrank
```

Python 3.11–3.14 is supported for the CLI. The optional model-serving stack uses
Python 3.12 in production.

## Context-aware search

Run the command inside a local project:

```bash
adoptrank find "a streaming anomaly detector that fits this codebase"
```

The scanner sends only a bounded structured summary of languages, dependencies,
frameworks, and symbols. It skips ignored paths, build/dependency directories,
known credential files, and files matching secret patterns. Inspect the exact
payload without sending it with:

```bash
adoptrank find "your query" --dry-run
```

## Live leaderboard

```bash
adoptrank leaderboard --language Python --sort momentum
adoptrank leaderboard --owner openai --window 7
```

Results contain simple direct GitHub links. The hosted Vercel proxy supplies the
private model-service credential, so CLI users do not need an AdoptRank API key.

Web application: <https://adoptrank.vercel.app>

Source and documentation: <https://github.com/Kairavparikh/adoptrank>
