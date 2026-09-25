# Day 10 — Corruption and Repair Report

## Performance comparison

| Metric | Baseline | Corrupted | Repaired |
| --- | ---: | ---: | ---: |
| `retrieval_hit_rate` | 1.0000 | 0.8000 | 1.0000 |
| `mean_token_f1` | 1.0000 | 0.8788 | 1.0000 |
| `judge_accuracy` | 1.0000 | 0.9000 | 1.0000 |
| `mean_judge_score` | 5 | 4.4000 | 5 |

## Quality and freshness

| State | Quality | Freshness | Stale rows | Total rows |
| --- | --- | --- | ---: | ---: |
| Baseline | Pass | Pass | 1 | 24 |
| Corrupted | Fail | Pass | 2 | 21 |
| Repaired | Pass | Pass | 1 | 24 |
