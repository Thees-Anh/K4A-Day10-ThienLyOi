from __future__ import annotations

from pathlib import Path
from typing import Any

from core.utils import write_text


def _value(payload: dict[str, Any], key: str, default: Any = "N/A") -> Any:
    value = payload.get(key, default)
    return default if value is None else value


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Pass" if value else "Fail"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _quality_checks(quality: dict[str, Any]) -> list[tuple[str, bool]]:
    checks = quality.get("checks")
    if isinstance(checks, dict) and checks:
        labels = {
            "table_row_count": "Row count (5–5000)",
            "required_values": "Required values are non-null/non-blank",
            "paper_id_unique": "paper_id is unique",
            "summary_length": "summary length ≥ 30 characters",
        }
        return [(labels.get(key, key), bool(value)) for key, value in checks.items()]

    results = quality.get("results", quality.get("expectations", []))
    rows: list[tuple[str, bool]] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        config = item.get("expectation_config", {})
        if not isinstance(config, dict):
            continue
        rows.append((str(config.get("type", "expectation")), bool(item.get("success"))))
    return rows


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write a reproducible Markdown report for the baseline pipeline."""

    lines: list[str] = [
        "# Day 10 — Phase 1 Baseline Report",
        "",
        "## 1. Source and lineage",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for key, label in (
        ("source", "Source"),
        ("mode", "Acquisition mode"),
        ("query", "Query"),
        ("filter", "Filter"),
        ("raw_records", "Raw records"),
        ("max_results", "Requested maximum"),
        ("run_at", "Run timestamp"),
    ):
        if key in source_summary:
            lines.append(f"| {label} | {_format_value(source_summary[key])} |")

    lines.extend(
        [
            "",
            "## 2. Data quality gate",
            "",
            f"**Overall status:** {_format_value(bool(quality.get('success')))}",
            "",
            "| Check | Result |",
            "| --- | --- |",
        ]
    )
    for label, passed in _quality_checks(quality) or [("GX validation", bool(quality.get("success")))]:
        lines.append(f"| {label} | {_format_value(passed)} |")

    lines.extend(
        [
            "",
            "## 3. Freshness SLA",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Latest published | {_format_value(freshness.get('latest_published'))} |",
            f"| Oldest published | {_format_value(freshness.get('oldest_published'))} |",
            f"| Stale rows | {_format_value(freshness.get('stale_rows', 0))} |",
            f"| Total rows | {_format_value(freshness.get('total_rows', 0))} |",
            f"| Stale ratio | {_format_value(freshness.get('stale_ratio', 0.0))} |",
            f"| Threshold | {_format_value(freshness.get('threshold_days', 180))} days |",
            f"| Status | {'Fresh' if freshness.get('is_fresh') else 'Stale/Unknown'} |",
        ]
    )
    if freshness.get("warning"):
        lines.extend(["", f"> **Warning:** {freshness['warning']}"])

    lines.extend(
        [
            "",
            "## 4. Evaluation metrics",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
    )
    for key in (
        "samples",
        "retrieval_hit_rate",
        "mean_token_f1",
        "judge_accuracy",
        "mean_judge_score",
    ):
        if key in metrics:
            lines.append(f"| `{key}` | {_format_value(metrics[key])} |")
    ragas = metrics.get("ragas")
    if ragas is not None:
        lines.append(f"| `ragas` | {_format_value(ragas)} |")

    lines.extend(
        [
            "",
            "## 5. Generated artifacts",
            "",
            "- `data/clean/papers_clean.csv`",
            "- `data/clean/papers_clean.json`",
            "- `data/embeddings/papers_embeddings.json`",
            "- `data/eval/test_set.json`",
            "- `data/results/baseline_metrics.json`",
            "- `data/results/baseline_answers.json`",
            "- `data/quality/baseline_quality_report.json`",
            "- `data/quality/freshness_report.json`",
            "",
        ]
    )
    write_text(Path(report_path), "\n".join(lines))


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """Write a compact three-state baseline/corrupted/repaired comparison."""

    metric_names = (
        "retrieval_hit_rate",
        "mean_token_f1",
        "judge_accuracy",
        "mean_judge_score",
    )
    lines = [
        "# Day 10 — Corruption and Repair Report",
        "",
        "## Performance comparison",
        "",
        "| Metric | Baseline | Corrupted | Repaired |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in metric_names:
        lines.append(
            f"| `{key}` | {_format_value(baseline_metrics.get(key))} | "
            f"{_format_value(corrupted_metrics.get(key))} | {_format_value(repaired_metrics.get(key))} |"
        )

    lines.extend(
        [
            "",
            "## Quality and freshness",
            "",
            "| State | Quality | Freshness | Stale rows | Total rows |",
            "| --- | --- | --- | ---: | ---: |",
            f"| Baseline | {_format_value(baseline_metrics.get('quality_success', True))} | "
            f"{_format_value(baseline_metrics.get('freshness_success', True))} | "
            f"{_format_value(baseline_metrics.get('stale_rows', '—'))} | "
            f"{_format_value(baseline_metrics.get('total_rows', '—'))} |",
            f"| Corrupted | {_format_value(corrupted_quality.get('success'))} | "
            f"{_format_value(corrupted_freshness.get('is_fresh'))} | "
            f"{_format_value(corrupted_freshness.get('stale_rows', 0))} | "
            f"{_format_value(corrupted_freshness.get('total_rows', 0))} |",
            f"| Repaired | {_format_value(repaired_quality.get('success'))} | "
            f"{_format_value(repaired_freshness.get('is_fresh'))} | "
            f"{_format_value(repaired_freshness.get('stale_rows', 0))} | "
            f"{_format_value(repaired_freshness.get('total_rows', 0))} |",
            "",
        ]
    )
    write_text(Path(report_path), "\n".join(lines))
