# AdoptRank PyTorch ranker: model card

## Purpose

`pytorch-ranknet-v1` reranks repositories retrieved with BM25. It is not an LLM judge. A trainable hashed text tower represents the query and repository, a structured tower represents real adoption and maintenance signals, and an interaction network produces the relevance score.

## Objectives

- Pairwise RankNet loss: a real positive repository should outrank a hard negative for the generated query.
- Masked adoption loss: the adoption head learns only from an observed PyPI acceleration label or a later point-in-time snapshot.

Missing adoption labels contribute no adoption gradient. Inference returns `null` when the checkpoint has no observed adoption labels.

## Bootstrap result

The first run used 76 repositories collected from GitHub and PyPI, producing 217 pairs. The chronological/deterministic split contained 173 training and 44 validation pairs. Pair accuracy and pair NDCG were both 1.0 after 18 epochs; this is a pipeline-validation result because the weak-label task is easier than a blinded human benchmark.

Only 12 examples had real PyPI acceleration labels. The adoption head is therefore experimental until repeated snapshots, package dependent growth, and a larger point-in-time dataset are available.

The machine-readable report is in `reports/bootstrap-2026-08-06.json`.

## Serving

Retrieval and ranking are deliberately hybrid:

1. BM25 retrieves up to 100 candidates.
2. Explicit language constraints apply as hard filters when enough matches exist.
3. The PyTorch model scores query–repository interactions.
4. Normalized BM25, neural score, and query coverage are fused for the final result.

Every served result contains the GitHub URL, model version, data watermark, and concise evidence.
