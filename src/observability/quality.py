from __future__ import annotations

import json
from pathlib import Path

import great_expectations as gx
import pandas as pd
from great_expectations.expectations import (
    ExpectColumnValueLengthsToBeBetween,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToNotBeNull,
    ExpectTableRowCountToBeBetween,
)

from core.config import Settings


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_freshness_report(df: pd.DataFrame, settings: Settings) -> dict:
    total_count = int(len(df))

    if "age_days" not in df.columns or total_count == 0:
        return {
            "is_fresh": False,
            "stale_ratio": 1.0,
            "stale_count": total_count,
            "total_count": total_count,
            "threshold_days": settings.freshness_threshold_days,
            "max_allowed_stale_ratio": 0.25,
        }

    stale_mask = df["age_days"] > settings.freshness_threshold_days
    stale_count = int(stale_mask.sum())
    stale_ratio = stale_count / total_count if total_count else 1.0

    return {
        "is_fresh": stale_ratio <= 0.25,
        "stale_ratio": stale_ratio,
        "stale_count": stale_count,
        "total_count": total_count,
        "threshold_days": settings.freshness_threshold_days,
        "max_allowed_stale_ratio": 0.25,
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, label: str) -> dict:
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": df})

    expectations = [
        ExpectTableRowCountToBeBetween(min_value=5, max_value=5000),
        ExpectColumnValuesToNotBeNull(column="paper_id"),
        ExpectColumnValuesToNotBeNull(column="title"),
        ExpectColumnValuesToNotBeNull(column="text_for_embedding"),
        ExpectColumnValuesToBeUnique(column="paper_id"),
        ExpectColumnValueLengthsToBeBetween(column="summary", min_value=30),
    ]

    expectation_results = []

    for expectation in expectations:
        validation = batch.validate(expectation)
        expectation_results.append(validation.to_json_dict())

    gx_success = all(result["success"] for result in expectation_results)
    freshness = build_freshness_report(df, settings)

    report = {
        "label": label,
        "success": bool(gx_success and freshness["is_fresh"]),
        "gx_success": bool(gx_success),
        "freshness_success": bool(freshness["is_fresh"]),
        "row_count": int(len(df)),
        "freshness": freshness,
        "expectation_results": expectation_results,
    }

    if label in {"baseline", "test"}:
        report_path = settings.paths.baseline_quality_report
    elif label == "corrupted":
        report_path = settings.paths.corrupted_quality_report
    else:
        report_path = settings.paths.quality_dir / f"{label}_quality_report.json"

    _write_json(settings.paths.freshness_report, freshness)
    _write_json(report_path, report)

    return report
