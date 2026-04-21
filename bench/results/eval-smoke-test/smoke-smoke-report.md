# Retrieval Eval Report

- Backend: `smoke`
- Profile: `smoke`
- Pool limit: `10`

## Aggregates

### Code

| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.07 | 0.13 | 0.00% | 100.00% | 0.00% |
| graph | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.18 | 0.26 | 0.00% | 100.00% | 0.00% |
| graph_rerank | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.22 | 0.26 | 100.00% | 0.00% | 0.00% |

### Conversation

| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.18 | 0.22 | 0.00% | 100.00% | 0.00% |
| temporal | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.09 | 0.21 | 0.00% | 100.00% | 0.00% |
| temporal_rerank | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.11 | 0.12 | 100.00% | 0.00% | 0.00% |

### Research

| Mode | Queries | Recall@10 | Recall@Pool | MRR@10 | NDCG@10 | Success@5 | p50 ms | p95 ms | Rerank Applied | Rerank Fallback | Rerank Abstained |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.20 | 0.39 | 0.00% | 100.00% | 0.00% |
| temporal | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.09 | 0.13 | 0.00% | 100.00% | 0.00% |
| temporal_rerank | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.10 | 0.13 | 100.00% | 0.00% | 0.00% |
