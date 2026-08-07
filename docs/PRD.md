# AdoptRank Product Requirements Document

Status: Active build  
Last updated: August 6, 2026  
Owner: Kairav Parikh

## 1. Product summary

AdoptRank finds the open-source repository that best fits what a developer is trying to build. It ranks real repositories using source-code evidence, project compatibility, maintenance health, and measured adoption—not stars alone—and returns simple results containing a repository link and a short explanation.

The product has two surfaces:

1. A web search bar for natural-language discovery.
2. A terminal and IDE workflow that can read the current local project and use its context automatically.

## 2. Problem

GitHub search and trending primarily expose keyword matches and current attention. A developer still has to open many repositories and determine whether each one implements the required capability, fits the project's language and dependencies, is maintained, and is genuinely being adopted.

The central user question is simple: **“Which repository should I use for this project, and why?”**

## 3. Goals

- Return relevant repositories for an implementation goal, not merely a topic name.
- Inspect repository source code at a pinned commit and use that evidence in ranking.
- incorporate real, continuously refreshed adoption and maintenance signals.
- Support both zero-context web search and context-aware local project search.
- Make every result understandable: link, score, compatibility, evidence, and risks.
- Train and evaluate a genuine learning-to-rank model on historical real-world observations.
- Demonstrate production-oriented MLE, data, backend, and systems engineering.

## 4. Non-goals

- Hosting or installing third-party repositories for the user.
- Generating arbitrary code as the primary product.
- Claiming that stars, downloads, or an LLM judgment alone measure quality.
- Reading private repositories without explicit authorization.
- Building an autonomous dependency-upgrade agent in the first release.

## 5. Primary users and jobs

### Exploring developer

The user enters “best Python algorithm for detecting anomalies in live Bitcoin prices” and receives a ranked list of repositories with direct links and concise evidence.

### Developer inside a project

The user runs `adoptrank find "streaming anomaly detection"`. AdoptRank reads a bounded local-project manifest, language, dependencies, and selected source structure, then ranks repositories compatible with that project.

### ML/data engineer

The user wants to compare promising libraries by actual adoption trajectory, maintenance, release quality, tests, examples, security, and source-level capabilities.

## 6. User experience

### Web

1. User enters a plain-language goal.
2. Search responds progressively, with useful results targeted below two seconds from the existing index.
3. Each result shows:
   - repository name and clickable GitHub link;
   - one-sentence reason;
   - fit score and adoption classification;
   - language, license, and last update;
   - source files that support the match;
   - compatibility warnings when relevant.
4. The user can open the repository and judge it directly.

### Terminal

```text
adoptrank find "anomaly detection for this price stream"
```

By default the CLI reads only bounded, non-secret context:

- language and framework manifests;
- dependency names and versions;
- file tree and selected symbols;
- README/project description;
- optional user-selected source paths.

It ignores secret files, `.env`, credentials, build output, dependencies, and files excluded by `.gitignore`. Before transmitting context it supports `--dry-run`, and local context can be disabled with `--no-context`.

### IDE

The first IDE integration is a thin VS Code extension over the same CLI and API contracts. Commands include “Find repository for selection,” “Find repository for workspace,” and “Explain this match.” Results open in a side panel and deep-link to GitHub; the extension does not contain separate ranking logic.

## 7. Ranking system

### Candidate retrieval

- Normalize the goal into capability, language, framework, runtime, license, and deployment constraints.
- Retrieve candidates using lexical BM25 and dense code/repository embeddings.
- Apply explicit hard filters before neural reranking.
- Preserve enough diverse candidates for hard-negative learning.

### Code-aware analysis

For indexed repositories, AdoptRank:

1. Pins the default branch to an immutable commit SHA.
2. Reads the Git tree and rejects vendored, generated, dependency, and build directories.
3. Selects representative implementation, test, example, and manifest files under byte/file budgets.
4. Extracts imports, public symbols, capabilities, dependency declarations, test/example presence, and file-level evidence.
5. Stores the commit SHA and evidence paths so a result is reproducible and explainable.

The system does not send an unlimited repository to a chat model. Parsing and feature extraction are deterministic; learned encoders operate on bounded representations.

### PyTorch learning-to-rank model

The model is a multi-tower ranker:

- query tower: developer intent;
- repository/code tower: metadata plus code-derived terms and symbols;
- structured tower: maintenance, compatibility, tests, examples, security, and adoption signals;
- relevance head: pairwise ranking score;
- adoption head: probability of sustained future adoption.

Training uses pairwise RankNet loss with real search-derived hard negatives. The adoption head is trained only where later observations provide a real label; missing outcomes are masked rather than invented.

Final ranking combines retrieval relevance, model score, explicit constraint satisfaction, code-evidence coverage, and calibrated adoption probability. An explanation layer cites the strongest observed evidence instead of generating unsupported claims.

### Evaluation

- NDCG@10 and precision@10 on time-split relevance judgments.
- Pairwise accuracy on difficult negatives.
- Calibration and Brier score for 30/90-day adoption predictions.
- Code-evidence precision from a manually reviewed benchmark.
- Retrieval and end-to-end latency.
- Ablations for metadata, code, and adoption feature groups.

Bootstrap metrics derived from weak labels are labeled as bootstrap diagnostics, not production-quality claims.

## 8. Live data

### Sources

- GitHub: repository metadata, commits, contributors, releases, issues, tree, and source files.
- PyPI and public download data: release and download behavior.
- npm: package releases and downloads.
- deps.dev: dependency and reverse-dependency graphs.
- OSV: vulnerabilities and remediation history.
- OpenSSF: security and maintenance signals.
- Hacker News and Stack Overflow: attention and developer-friction signals.
- Hugging Face: model, dataset, and Space activity for ML projects.

No simulated observations are used in production datasets.

### Refresh strategy

- Search/repository discovery: incremental polling throughout the day.
- High-change repositories: refresh every 1–6 hours.
- Normal repositories: daily refresh.
- Low-change repositories: adaptive backoff up to weekly.
- Source analysis: rerun only when the indexed commit changes.
- Immutable hourly observations support point-in-time training and backtests;
  observations older than 30 days compact to daily resolution through day 90.
- Queue retries use exponential backoff, rate-limit awareness, idempotency keys, and dead-letter storage.

The UI always displays a data watermark. Stale sources degrade independently rather than blocking all search.

## 9. Architecture and stack

- Web: Next.js, TypeScript, React, Tailwind-compatible CSS, deployed on Vercel.
- API: FastAPI and Pydantic.
- ML: PyTorch, RankNet-style learning-to-rank, MLflow-compatible experiment artifacts.
- Primary store: PostgreSQL with `pgvector`.
- Analytics/search store at scale: ClickHouse plus object storage for immutable snapshots.
- Cache and work coordination: Redis.
- Streaming/event layer at scale: Redpanda/Kafka and Spark Structured Streaming.
- Workflow orchestration: Airflow or Dagster.
- Observability: OpenTelemetry, structured logs, metrics, and traces.
- Serving: Modal scale-to-zero L4 GPU with both Qwen model snapshots and trained
  artifacts baked into the image.
- Packaging: Docker remains a portable fallback; Kubernetes is a scale milestone,
  not required for the first demo.

Vercel hosts the web application. Modal hosts the PyTorch/Qwen FastAPI inference
service behind `RANKER_API_URL`; scheduled collection and training remain separate
from request-time serving.

## 10. Core API

`POST /v1/search`

```json
{
  "query": "streaming bitcoin anomaly detection",
  "limit": 10,
  "project_context": {
    "languages": ["Python"],
    "dependencies": ["pandas", "websockets"]
  }
}
```

The response includes a model version, data watermark, and ranked results with direct repository URLs and code-evidence paths.

## 11. Data safety

- Repository source is fetched only from public repositories unless the user explicitly connects a private source.
- Local project scanning is bounded and denylist-based, with `.gitignore` support.
- Secrets and raw local files are not persisted by default.
- Every indexed code record includes its source URL and commit SHA.
- Licenses and security findings appear as evidence, not legal or security guarantees.

## 12. Delivery milestones

### M1 — Working vertical slice

- Real GitHub and PyPI collection.
- PostgreSQL/pgvector schema.
- BM25 retrieval plus PyTorch reranking.
- FastAPI search endpoint.
- Next.js web search on Vercel.

### M2 — Code-aware ranking

- Commit-pinned tree and source ingestion.
- Multi-language code evidence extraction.
- Code features included in training and inference.
- Evidence paths shown in API, web, and CLI.

### M3 — Local developer workflow

- Installable `adoptrank` CLI.
- Safe project-context scanner and dry run.
- Context-aware search API.
- VS Code extension using the same contracts.

### M4 — Robust adoption prediction

- Repeated real observations and point-in-time feature store.
- deps.dev, npm, OSV, OpenSSF, and discussion signals.
- Time-based training/validation/backtests.
- Calibrated 30/90-day adoption labels and model registry.

### M5 — Production-quality demo

- Adaptive polling, queues, caching, monitoring, and failure recovery.
- Public benchmark and ablation report.
- Hosted model API connected to the Vercel UI.
- Recorded terminal/IDE and live-ranking demonstration.

## 13. Success criteria

- A new user understands the product in one sentence.
- The top ten results always contain usable direct repository links.
- A reviewed benchmark shows clear improvement over GitHub stars/search baselines.
- Code-aware ranking improves NDCG@10 over the metadata-only ablation.
- The same query becomes more precise when safe local-project context is supplied.
- All displayed predictions identify model version, data watermark, and supporting evidence.

## 14. Current implementation status

M1–M3 are implemented: the Vercel UI, FastAPI service, hourly real-data polling, commit-pinned Tree-sitter analysis, Qwen3/pgvector retrieval, InfoNCE and pairwise PyTorch training, multi-head scoring, safe CLI scanner, and VS Code integration are in the repository and verified end to end. M4 has a real 76-repository/217-pair training bootstrap plus 901 live repositories and 1,223 temporal observations, but still requires longer-horizon labels and a human relevance benchmark. M5's hosted path is live: the Modal L4 service loads both Qwen models and the trained PyTorch artifacts, `adoptrank.vercel.app` returns authenticated model results through its server-side proxy, Neon stores real observation/vector/ranking tables, and the deployed Modal cron polls GitHub/PyPI hourly. Two production leaderboard snapshots now demonstrate real rank movement.
