# Retrieval Benchmark Report

Generated from 2 benchmark row(s).

## Global Summary

| Metric | Value |
| --- | ---: |
| High-stakes query count | 0 |
| Temporal fallback rate (%) | 100 |
| Mean temporal seed discovery (ms) | 0.15 |
| Mean temporal bridge time (ms) | 0 |
| Mean temporal hydration time (ms) | 0.01 |

## Mode Summary

| Mode | Mean Latency (ms) | P95 Latency (ms) | Mean Tokens | Mean Results | MRR@10 | NDCG@10 | Success@5 (%) | Recall@10 (%) | Rerank Applied (%) | Rerank Abstained (%) | Rerank Fallback (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 0.55 | 0.93 | 42 | 2 | 1 | 1 | 100 | 100 | 0 | 0 | 0 |
| Temporal / Structural | 0 | 0 | 42 | 2 | 1 | 1 | 100 | 100 | 0 | 0 | 0 |
| Baseline + Rerank | 0.55 | 0.93 | 42 | 2 | 1 | 1 | 100 | 100 | 0 | 0 | 100 |
| Temporal + Rerank | 0 | 0 | 42 | 2 | 1 | 1 | 100 | 100 | 0 | 0 | 100 |

## Query Rows

| Query ID | Domain | High Stakes | Temporal Fallback | Baseline Hit Rank | Temporal Hit Rank | Baseline+Rerank Hit Rank | Temporal+Rerank Hit Rank |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| q-001 | conversation | no | yes | 1 | 1 | 1 | 1 |
| q-002 | research | no | yes | 1 | 1 | 1 | 1 |
