# Retrieval Eval Report

- Backend: `smoke`
- Profile: `smoke`
- Pool limit: `10`

## Aggregates

### Code

| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.10 | 0.26 | 0.00% | 100.00% | 0.00% |
| graph | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.34 | 0.81 | 0.00% | 100.00% | 0.00% |
| graph_rerank | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.48 | 3.72 | 100.00% | 0.00% | 0.00% |

### Conversation

| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.31 | 1.03 | 0.00% | 100.00% | 0.00% |
| temporal | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.29 | 0.00% | 100.00% | 0.00% |
| temporal_rerank | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.15 | 0.42 | 100.00% | 0.00% | 0.00% |

### Research

| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.31 | 0.78 | 0.00% | 100.00% | 0.00% |
| temporal | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.18 | 0.00% | 100.00% | 0.00% |
| temporal_rerank | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.17 | 100.00% | 0.00% | 0.00% |
