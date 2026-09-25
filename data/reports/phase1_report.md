# Day 10 — Phase 1 Baseline Report

## 1. Source and lineage

| Field | Value |
| --- | --- |
| Source | Crossref REST API |
| Acquisition mode | offline_snapshot |
| Query | agentic retrieval augmented generation large language model |
| Filter | from-pub-date:2026-03-29,has-abstract:true |
| Raw records | 24 |
| Requested maximum | 24 |
| Run timestamp | 2026-09-25T09:14:53.298399+00:00 |

## 2. Data quality gate

**Overall status:** Pass

| Check | Result |
| --- | --- |
| Row count (5–5000) | Pass |
| Required values are non-null/non-blank | Pass |
| paper_id is unique | Pass |
| summary length ≥ 30 characters | Pass |

## 3. Freshness SLA

| Field | Value |
| --- | --- |
| Latest published | 2026-07-22 |
| Oldest published | 2026-03-28 |
| Stale rows | 1 |
| Total rows | 24 |
| Stale ratio | 0.0417 |
| Threshold | 180 days |
| Status | Fresh |

## 4. Evaluation metrics

| Metric | Value |
| --- | ---: |
| `samples` | 10 |
| `retrieval_hit_rate` | 1.0000 |
| `mean_token_f1` | 1.0000 |
| `judge_accuracy` | 1.0000 |
| `mean_judge_score` | 5 |
| `ragas` | {'skipped': 'Set RUN_RAGAS=1 to enable the slower Ragas pass.'} |

## 5. Generated artifacts

- `data/clean/papers_clean.csv`
- `data/clean/papers_clean.json`
- `data/embeddings/papers_embeddings.json`
- `data/eval/test_set.json`
- `data/results/baseline_metrics.json`
- `data/results/baseline_answers.json`
- `data/quality/baseline_quality_report.json`
- `data/quality/freshness_report.json`
