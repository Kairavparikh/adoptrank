# AdoptRank Qwen ranker model card

## Model

`qwen3-infonce-ranknet-v2` combines Qwen3-Embedding-0.6B, a trainable PyTorch projection/multi-head network, and Qwen3-Reranker-0.6B. Production deployments may select the 4B members through environment variables without changing contracts.

## Data

The current run contains 76 real GitHub/PyPI repository snapshots, eight commit-pinned Tree-sitter source indexes, 240 syntax-aware code chunks, and 217 mined preference pairs. No simulated repositories or invented adoption observations are used.

## Objectives

- InfoNCE contrastive loss over positive and hard-negative repositories.
- Pairwise logistic RankNet relevance loss.
- Masked adoption loss only where a real package acceleration/future observation exists.
- Auxiliary depth, quality, maintenance, and originality regression heads.

## Evaluation

The deterministic time-ordered split contains 173 training and 44 validation pairs. After eight epochs, held-out pair accuracy is 0.659 and pair NDCG is 0.874. These are bootstrap weak-label metrics, not claims of human-level repository understanding; a manually judged benchmark and temporal adoption backtest remain required for publishable results.

## Retrieval and serving

1. BM25 and Qwen dense similarity retrieve 50 candidates.
2. The PyTorch relevance head scores all candidates.
3. Qwen3-Reranker cross-encodes the best configurable subset (20 by default; 50 on an appropriate GPU).
4. Relevance, adoption, technical depth, quality, maintenance, and originality are returned separately.
5. Every result includes a direct GitHub URL, indexed commit evidence, model version, and data watermark.

## Safety and limitations

- Source analysis is bounded and can miss behavior outside selected files.
- Test/example ratios are quality proxies, not proof of correctness.
- Adoption labels are sparse and experimental.
- CPU cross-encoding is supported for validation but does not meet the interactive production SLA; use a GPU or disable only the cross-encoder fallback.
- Licenses and vulnerability signals are informational, not legal or security guarantees.
