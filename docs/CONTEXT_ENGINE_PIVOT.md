# AdoptRank Context Engine Pivot

Status: Stage-gated prototype
Last updated: August 7, 2026
Owner: Kairav Parikh

## Product statement

**AdoptRank gives coding agents the highest-value local and GitHub code context within a fixed token budget.**

Claude Code remains responsible for reasoning, editing, and testing. AdoptRank understands the current
project, ranks compatible public implementations, and prepares the smallest evidence package likely to
help complete the requested feature.

## Why pivot

The existing product answers which open-source repository best fits a developer's project. The proposed
context engine applies that ranking infrastructure to a narrower and more measurable job: choosing what
code a coding agent should read before it writes code.

This is not an immediate replacement of the repository discovery product. It is an experiment that must
prove lower repository-context usage at equal task success before becoming the primary direction.

## User experience

The prototype has one operation:

```bash
cd my-project
adoptrank context "add idempotent Stripe webhook retries" --budget 8000
```

It returns:

- relevant local functions, classes, and tests;
- ranked GitHub repositories with direct links and indexed evidence paths;
- project languages, frameworks, and dependency constraints;
- deterministic context accounting and excluded-candidate counts.

The future Claude Code integration exposes the same operation through MCP:

```text
get_context(task, budget)
```

No separate coding assistant, chat UI, autonomous installer, or code generator is part of this pivot.

## What is implemented now

- `adoptrank context QUERY --budget N` for safe local symbol retrieval.
- Optional external evidence from the deployed AdoptRank repository ranker.
- Project-aware ranking using the existing bounded scanner.
- Deterministic packing that never exceeds its estimated context budget.
- JSON output for future MCP and evaluation integrations.
- `adoptrank benchmark-context` for historical-task retrieval evaluation.
- A hard evaluation rule: missing Claude task-success or baseline-token measurements cannot approve the
  pivot.
- A commit-pinned external excerpt API that returns code, license, SHA, and direct source provenance.
- Historical task generation and safe parent-commit replay without modifying the working tree.
- A capped Claude Code A/B runner that records raw/cache/output usage, cost, changed files, and hidden-test
  outcomes.

Token counts in the prototype are portable estimates. Provider-reported Claude usage is required before
claiming measured savings, and provider-specific tokenization is required before describing a limit as a
billing-token guarantee.

## Existing assets reused

- 901 discovered repositories and 1,223 documented temporal observations.
- Qwen3 embedding and reranking services.
- PyTorch InfoNCE, RankNet, and multi-objective heads.
- Tree-sitter source parsing and syntax-aware chunks.
- PostgreSQL/pgvector evidence storage.
- Hourly GitHub/PyPI ingestion on Modal.
- Public PyPI CLI and Vercel API.

## Production systems architecture

The first context benchmark stays in Python so retrieval behavior can change quickly. Rust and Spark are
planned production components with measured activation gates, not parallel rewrites of unfinished logic.

### Rust ingestion and incremental indexing

Rust will own high-throughput GitHub polling, repository cloning, commit/diff processing, Tree-sitter
coordination, and queue workers when profiling shows Python is the ingestion bottleneck. It is especially
useful once AdoptRank continuously maintains symbol and history indexes across thousands of changing
repositories.

Rust workers must preserve versioned language-neutral contracts:

```text
RepositoryDiscovered
RepositorySnapshotCaptured
CommitObserved
FileDiffExtracted
SymbolChanged
CodeChunkIndexed
IndexInvalidated
```

Every event includes repository identity, immutable commit SHA, schema version, observed timestamp,
idempotency key, and provenance. Payloads use JSON/Protobuf on queues and Parquet for immutable bulk
storage. Python and Rust implementations run in shadow mode until counts, content hashes, extracted
symbols, and failure rates agree.

**Implemented initial vertical slice (August 2026):** `contracts/repository_event.schema.json` defines
`repository-event.v1`; Python can export deterministic snapshot events and compare candidate event IDs
and payload hashes; `rust/adoptrank-ingest` emits the same replayable envelope from GitHub search; and
the Spark jobs consume that envelope for event-time feature materialization and future-only adoption
backtests. The Python collector remains production owner—this is intentionally not a cutover claim.

Rust activation gates:

- Python workers cannot satisfy the repository-refresh service-level objective at the allowed cost;
- parsing or diff coordination is CPU/memory bound rather than GitHub-rate-limit bound;
- at least 95% of production events replay successfully in shadow mode;
- zero unexplained differences in commit identity and content hashes;
- extracted-symbol agreement meets the language-specific benchmark.

### Spark historical feature and training pipeline

Spark Structured Streaming and batch DataFrames will process large historical datasets: commit timelines,
feature generation, pull-request training examples, adoption backtests, and millions of repository
observations. Request-time retrieval and PyTorch inference do not run in Spark.

Planned data flow:

```text
Rust collectors -> Redpanda/Kafka -> object storage/Delta tables
                                      |
                                      v
                              Spark feature jobs
                                      |
                   +------------------+------------------+
                   v                                     v
          point-in-time training sets            backtest/quality tables
                   |                                     |
                   v                                     v
            PyTorch training                       MLflow artifacts
```

Spark activation gates:

- historical joins no longer complete economically on one machine;
- the corpus reaches millions of observations or pull-request/file records;
- point-in-time feature generation requires distributed replay and recovery;
- Spark output matches the Python reference on row counts, null masks, checksums, and sampled features;
- event-time watermarks and late-arrival behavior pass deterministic replay tests.

### Stable boundaries

The Python model and API remain independent of the systems implementation. Rust and Spark emit the same
versioned repository, code-chunk, diff, symbol, and training-example contracts consumed by PostgreSQL,
pgvector, object storage, and PyTorch. Migration follows shadow execution, parity checks, canary traffic,
and gradual cutover rather than replacing all Python code at once.

## Model and data plan

### Gold repository benchmark

Create 300–500 realistic implementation queries. Human judges label candidate repositories from zero
(irrelevant) to three (directly useful). Report NDCG@10, Recall@10, and Precision@10 against GitHub search,
BM25-only, dense-only, and current hybrid baselines.

### Historical pull-request benchmark

For a merged pull request, check out its parent commit and use the issue/PR description as the task. The
files and symbols changed by the real pull request become positives; similar untouched files and symbols
become hard negatives.

Target dataset:

- 30–50 hand-verified tasks for the go/no-go experiment;
- 1,000+ mined pull requests for initial file/symbol training;
- 10,000+ preference examples after filtering bots, formatting-only changes, and low-information tasks.

### Hierarchical retrieval

```text
task
  -> repository retrieval
  -> file retrieval
  -> symbol retrieval
  -> dependency/test expansion
  -> value-per-token reranking
  -> context pack
```

Train repository, file, and symbol retrieval separately. The final selector estimates expected task value
per token instead of treating semantic similarity as sufficient.

### GitHub corpus growth

Do not deeply index every discovered repository. Use a funnel:

1. Continuously collect metadata for broad discovery.
2. Shallow-index README, manifests, tree, and release state for promising repositories.
3. Deep-index symbols, tests, and code chunks only for repositories with query coverage, adoption, and
   maintenance evidence.
4. Reprocess source only when the pinned commit changes.

Initial corpus milestone: 10,000–25,000 discovered repositories and 2,000–5,000 deeply indexed
repositories.

## Commit-history memory milestone

Commit memory follows only after the retrieval benchmark passes. For each new commit, update changed
symbols and their graph neighbors, link the diff to its PR/issue rationale, and version every inferred fact
with commit provenance.

Memories must be invalidatable:

```json
{
  "fact": "Webhook retries run in the queue worker",
  "introduced_by": "f8b671",
  "evidence": ["workers/stripe_events.py"],
  "valid_from": "f8b671",
  "invalidated_by": null,
  "confidence": 0.91
}
```

An unsupported generated summary is not durable project memory.

## Controlled experiment

For every historical task:

1. Check out the parent commit.
2. Run Claude Code normally.
3. Run the same Claude model/settings with an AdoptRank context pack.
4. Repeat both conditions to reduce model variance.
5. Record provider-reported input, cache, and output tokens.
6. Run the repository's tests and task-specific assertions.

Primary metrics:

- task completion and test pass rate;
- changed-file Recall@10;
- changed-symbol Recall@20;
- repository input tokens and cached input tokens;
- unnecessary files read;
- time to first passing patch;
- retrieval latency.

## Go/no-go gates

The context engine becomes the primary product direction only when the controlled benchmark demonstrates:

- at least 30% fewer repository-input tokens;
- AdoptRank task success no more than five percentage points below the baseline;
- at least 80% mean changed-file recall;
- context retrieval below three seconds at the 95th percentile;
- improvement over keyword-only and embedding-only retrieval.

If these gates fail, repository discovery remains the flagship and context selection remains an
experimental research feature.

## Delivery sequence

### Stage 0 — Completed prototype

- Token-budgeted `context` command.
- Safe local code selection.
- External ranked repository evidence.
- JSON contracts and retrieval benchmark harness.

### Stage 1 — Evidence API and benchmark

- Implemented locally: serve indexed external code excerpts, commit SHAs, licenses, and provenance.
- Implemented locally: generate and replay historical tasks at their parent commits.
- Implemented locally: capture Claude Code baseline telemetry, changed files, capped cost, and test outcomes.
- Remaining: deploy the evidence endpoint and build 30–50 human-verified tasks with issue/PR descriptions.
- Remaining: publish the first controlled comparison.

The initial lexical prototype replayed eight usable AdoptRank commits. File-level overviews and path
diversification improved mean changed-file recall from 54.5% to 73.2% at an 8,000 estimated-token budget.
This is a development diagnostic, not the gold metric: terse commit subjects are weaker task descriptions
than the issue/PR text required by the final benchmark.

The first corrected Claude smoke A/B produced passing implementations in both conditions. Adaptive
AdoptRank context used 59,827 processed input tokens versus 73,005 for baseline (18.1% fewer) and an
estimated $0.08896 versus $0.09838 (9.6% lower). This single-task result is preliminary, below the 30%
token gate, and does not approve the pivot. The checked-in report is
`backend/reports/context-smoke-2026-08-07.json`.

Five historical tasks now have behaviorally validated hidden evaluators: each fails on its parent commit
and passes on the real target commit. Path-aware file/symbol ranking reaches 88% mean changed-file recall
at 3,672.6 estimated context tokens. This passes the preliminary recall threshold but remains a
single-repository, five-task result; see `backend/reports/context-retrieval-5-task-2026-08-07.json`.

A second two-task Claude A/B made the measurement problem explicit. Both conditions passed, but the
original AdoptRank pack used 22.0% more repository context overall, despite 6.5% lower estimated cost.
That result rejected the current pack rather than approving the pivot. The resulting narrow-task router
now assigns obvious CI/configuration edits 500–900 local tokens, keeps repository-wide tasks multi-file,
and avoids telling Claude to reread included evidence. On the same five retrieval tasks it preserves 88%
mean changed-file recall while reducing mean rendered context from 3,672.6 to 2,301 tokens; the two narrow
tasks use 320 and 464 tokens.

The context-model pipeline now converts those histories into file/symbol preference pairs with similar
untouched files as hard negatives, then trains a Qwen-embedding/PyTorch value-per-token ranker using
InfoNCE and RankNet objectives. A resource-bounded dummy-embedding test validates checkpoint generation.
Training now splits by task/commit rather than by individual pair, retains the best validation checkpoint,
records a dataset SHA-256, and derives an abstention margin from held-out preferences. The Claude harness
requires 30 unique controlled tasks, alternates condition order, supports repeated runs without counting
repetitions as new tasks, and reports a task-clustered bootstrap confidence interval.
The 0.6B Qwen encoder did not complete local inference within the available process resources, so real
Qwen context training remains assigned to the existing Modal L4 environment rather than silently falling
back to a different model.

The benchmark has since expanded to 40 commit-pinned tasks from five public repositories across Python,
Go, Rust, and JavaScript. Thirty-four tasks use real pull-request titles and descriptions; every generated
task has a hidden diff contract that fails at the parent commit and passes at the target commit. Complete
depth-bounded clones make replay independent of network access.

The cross-project results reject both the original heuristic and an untrained model-name upgrade:

- AST/BM25/exact-identifier baseline: 61.0% changed-file recall at 3,055 mean context tokens.
- Pretrained Qwen3 cross-encoder: 61.1% recall at 2,992 mean context tokens.
- Qwen embeddings plus the task-trained InfoNCE/RankNet head: 81.3% recall at 3,049 mean context tokens.
- Eight held-out task groups: 80.0% recall.
- Entirely unseen `sindresorhus/p-limit` repository: 84.4% recall across eight tasks, versus a 64.6%
  lexical baseline.

The training corpus contains 453 hard-negative pairs across 39 usable task groups. The selected checkpoint
reached 84.8% task-held-out pair accuracy; a separate repository-holdout checkpoint reached 79.2% pair
accuracy without seeing p-limit during optimization. These results pass the retrieval gate but do not
approve the product pivot: at least 30 controlled Claude A/B tasks must still demonstrate 30% repository-
context reduction at comparable task success with a positive task-clustered confidence interval.

An attempted 30-task Claude A/B on 2026-08-07 exhausted the provider credit after 16 valid pairs. Those
valid pairs showed equal 25% hidden-contract success, 17.4% fewer total processed input tokens, 12.0%
lower estimated cost, but 3.3% *more* repository context after counting the injected context pack. The
95% repository-context reduction interval was -33.1% to +14.4%, retrieval recall was 75.4%, and context
p95 latency was 24.7 seconds. This partial result is inconclusive and explicitly does not approve the
pivot. The harness now excludes nonzero/provider-error executions from every metric and stops immediately
on errors such as insufficient credit, preventing an incomplete paid run from appearing as a valid sample.

A subsequent value-aware router separates a low-token ranked file map from one to three compact code
excerpts and deliberately abstains on routine dependency/version edits. Across all 40 public tasks it
retains 81.0% engaged-task changed-file recall with 10% abstention, 355 mean rendered tokens (down 88%
from 3,049), and 2.995-second hosted p95 retrieval latency. Qwen reranking now embeds candidate documents
in GPU batches of 16 and retries transient Modal transport failures.

The next paid run atomically checkpointed 26 valid pairs before the added provider balance was exhausted.
AdoptRank used 19.2% fewer provider-reported processed input tokens, cost 9.5% less, and improved hidden
contract completion from 28.9% to 31.1%, but used 9.6% more one-time repository tool/output context. The
95% repository-context reduction interval still crossed zero. Therefore the 30% token-saving claim remains
unapproved. The benchmark now checkpoints every individual condition, resumes without repeating valid
calls, discards zero-cost provider failures, and reuses the baseline result when the router deliberately
abstains instead of paying for a statistically noisy identical prompt.

### Stage 2 — Retrieval accuracy

- In progress: the live catalog contains 4,967 repositories and 18,812 observations; the first
  incremental pipeline verification produced 32 deeply indexed repositories and 752 Qwen chunks.
- Expand deep source indexing to 2,000–5,000 repositories through the verified six-hour incremental job.
- Train file and symbol retrievers from merged pull requests.
- Add graph expansion for callers, callees, imports, types, and tests.
- Calibrate confidence and abstain when evidence is weak.

### Stage 2.5 — Scalable corpus pipeline

- Current status: Rust and Spark are planned but not implemented. There is currently no `Cargo.toml`,
  `.rs` source, PySpark job, Spark streaming application, or Spark configuration in the repository.
- Implement Rust GitHub polling, cloning, diff, parsing-coordination, and queue workers behind versioned
  event contracts.
- Introduce Redpanda/Kafka and immutable Parquet/Delta storage for replayable source events.
- Add Spark jobs for historical PR examples, point-in-time features, and adoption backtests.
- Shadow Python with Rust/Spark and require count, checksum, feature, and failure-rate parity before
  gradual cutover.
- Activate each component only after its profiling and dataset-size gate is satisfied.

### Stage 3 — Agent integration

- Add a local stdio MCP server using the same context contract.
- Add progressive `expand_context` requests.
- Provide concise Claude Code project instructions.
- Keep private source local by default.

### Stage 4 — Memory and enforcement

- Incrementally index commits and diffs.
- Add versioned, evidence-backed architectural memory.
- Use provider-specific token accounting.
- Add optional strict mode that audits or blocks repository reads beyond the selected budget.

## Product boundaries

Keep:

- one context operation;
- direct evidence and provenance;
- compatibility and quality ranking;
- measurable token budgeting;
- agent-agnostic JSON/MCP contracts.

Do not add:

- another general coding chat interface;
- autonomous copying or installation of external code;
- unsupported architectural summaries;
- leaderboards as the primary context-engine experience;
- token-savings claims before controlled measurement.
