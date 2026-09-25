from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import math
from pathlib import Path
import re
from typing import Any

import great_expectations as gx
import pandas as pd
from great_expectations.expectations import (
    ExpectColumnValueLengthsToBeBetween,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToNotBeNull,
    ExpectTableRowCountToBeBetween,
)

from core.config import Settings
from core.utils import write_json


_MAX_STALE_RATIO = 0.25


def _safe_report_name(report_name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(report_name)).strip("_")
    return value or "quality"


def _json_safe(value: Any) -> Any:
    """Convert GX/Pandas scalar values into JSON-serializable values."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    # numpy scalar types expose ``item`` but are not JSON encoders themselves.
    if hasattr(value, "item") and callable(value.item):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _published_dates(df: pd.DataFrame) -> pd.Series:
    if "published" not in df.columns:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    try:
        parsed = pd.to_datetime(df["published"], errors="coerce", utc=True)
    except (TypeError, ValueError, OverflowError, NotImplementedError):
        parsed = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    return parsed


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date, pd.Timestamp)):
        try:
            return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
        except (OverflowError, NotImplementedError):
            return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed) or not hasattr(parsed, "date"):
            return None
        return parsed.date().isoformat()
    except (TypeError, ValueError, OverflowError, NotImplementedError):
        return None


def _usable_age(value: Any) -> bool:
    try:
        if bool(pd.isna(value)):
            return False
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric >= 0


def _blank_value_failures(df: pd.DataFrame) -> dict[str, int | str]:
    """Return columns containing null/blank values that the gate must reject."""

    failures: dict[str, int | str] = {}
    for column in ("paper_id", "title", "text_for_embedding", "summary"):
        if column not in df.columns:
            failures[column] = "missing_column"
            continue
        series = df[column]
        try:
            null_mask = series.isna()
            blank_mask = series.astype("string").fillna("").str.strip().eq("")
            invalid_count = int((null_mask | blank_mask).sum())
        except (TypeError, ValueError):
            invalid_count = int(series.isna().sum())
        if invalid_count:
            failures[column] = invalid_count
    return failures


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Build and persist a freshness report for the supplied dataframe.

    A row is stale when ``age_days`` is strictly greater than the configured
    threshold (180 days by default).  The report is marked stale when the
    stale proportion is greater than 25% or when any row has an unusable age.
    """

    threshold_days = int(getattr(settings, "freshness_threshold_days", 180))
    total_rows = int(len(df))

    if "age_days" in df.columns:
        age_values = pd.to_numeric(df["age_days"], errors="coerce")
    else:
        age_values = pd.Series([float("nan")] * total_rows, index=df.index, dtype="float64")
    valid_age = age_values.map(_usable_age).fillna(False).astype(bool)
    missing_age_rows = int((~valid_age).sum())
    stale_mask = valid_age & (age_values > threshold_days)
    stale_rows = int(stale_mask.sum())
    stale_ratio = stale_rows / total_rows if total_rows else 0.0
    # An unknown age is not evidence of freshness.  Failing closed prevents a
    # malformed age_days column from silently passing the SLA.
    is_fresh = bool(total_rows > 0 and missing_age_rows == 0 and stale_ratio <= _MAX_STALE_RATIO)

    dates = _published_dates(df)
    valid_dates = dates.dropna()
    latest_published = _date_text(valid_dates.max()) if not valid_dates.empty else None
    oldest_published = _date_text(valid_dates.min()) if not valid_dates.empty else None
    warning = None
    if missing_age_rows:
        warning = f"{missing_age_rows} paper(s) have no usable age_days value."
    elif not is_fresh:
        warning = (
            f"{stale_ratio:.1%} of papers are older than {threshold_days} days "
            f"(limit: {_MAX_STALE_RATIO:.0%}); refresh the source with newer papers."
        )

    payload: dict[str, Any] = {
        "latest_published": latest_published,
        "oldest_published": oldest_published,
        "stale_rows": stale_rows,
        "total_rows": total_rows,
        "is_fresh": is_fresh,
        "stale_ratio": float(stale_ratio),
        "stale_percentage": float(stale_ratio * 100),
        "threshold_days": threshold_days,
        "max_stale_ratio": _MAX_STALE_RATIO,
        "known_age_rows": int(valid_age.sum()),
        "missing_age_rows": missing_age_rows,
        "invalid_age_rows": missing_age_rows,
        "warning": warning,
    }
    if report_path is not None:
        write_json(Path(report_path), payload)
    return payload


def _quality_report_path(settings: Settings, report_name: str) -> Path:
    paths = settings.paths
    configured = {
        "baseline": getattr(paths, "baseline_quality_report", None),
        "corrupted": getattr(paths, "corrupted_quality_report", None),
    }.get(str(report_name))
    if configured is not None:
        return Path(configured)
    quality_dir = Path(getattr(paths, "quality_dir", Path("data") / "quality"))
    return quality_dir / f"{_safe_report_name(report_name)}_quality_report.json"


def _run_gx_validation(df: pd.DataFrame, context: Any, report_name: str) -> Any:
    """Create the GX 1.x fluent data source and validate the dataframe."""

    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": df})

    suite = context.suites.add(
        gx.ExpectationSuite(name=f"{_safe_report_name(report_name)}_quality_suite")
    )
    suite.add_expectation(ExpectTableRowCountToBeBetween(min_value=5, max_value=5000))
    for column in ("paper_id", "title", "text_for_embedding"):
        suite.add_expectation(ExpectColumnValuesToNotBeNull(column=column))
    suite.add_expectation(ExpectColumnValuesToBeUnique(column="paper_id"))
    suite.add_expectation(ExpectColumnValueLengthsToBeBetween(column="summary", min_value=30))

    # Batch.validate is the public fluent API in current GX 1.x.  Fall back to
    # ValidationDefinition for early 1.x builds whose Batch facade differs.
    validate = getattr(batch, "validate", None)
    if callable(validate):
        try:
            return validate(suite)
        except (AttributeError, TypeError):  # pragma: no cover - compatibility path
            pass

    validation_definition_type = getattr(gx, "ValidationDefinition", None)
    if validation_definition_type is not None:
        validation_definition = validation_definition_type(
            name=f"{_safe_report_name(report_name)}_validation",
            data=batch_def,
            suite=suite,
        )
        return validation_definition.run(batch_parameters={"dataframe": df})
    raise TypeError("The installed Great Expectations version has no supported validation API.")


def _expectation_check(
    results: list[Any], expectation_type: str, column: str | None = None
) -> bool:
    matches: list[Mapping[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        config = item.get("expectation_config", {})
        if not isinstance(config, Mapping) or config.get("type") != expectation_type:
            continue
        kwargs = config.get("kwargs", {})
        if column is not None and (not isinstance(kwargs, Mapping) or kwargs.get("column") != column):
            continue
        matches.append(item)
    return bool(matches) and all(item.get("success") is True for item in matches)


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Run the four GX quality checks and the freshness SLA for ``df``.

    The returned dictionary is intentionally self-contained: ``success`` is
    the combined gate status, while ``gx_success`` and ``freshness`` can be
    used to distinguish a structural validation failure from a stale-source
    warning.  A JSON report is written below ``data/quality/``.
    """

    freshness_path = getattr(settings.paths, "freshness_report", None)
    freshness = build_freshness_report(df, settings, freshness_path)
    validation_error: str | None = None
    validation_result: dict[str, Any]
    manual_failures = _blank_value_failures(df)
    manual_success = not manual_failures

    try:
        context = gx.get_context(mode="ephemeral")
        gx_result = _run_gx_validation(df, context, report_name)
        gx_success = bool(getattr(gx_result, "success", False))
        if hasattr(gx_result, "to_json_dict"):
            raw_result = gx_result.to_json_dict()
            validation_result = raw_result if isinstance(raw_result, Mapping) else {}
        else:  # pragma: no cover - defensive support for GX test doubles
            raw_results = getattr(gx_result, "results", [])
            if not isinstance(raw_results, (list, tuple)):
                raw_results = []
            normalized_results: list[Any] = []
            for item in raw_results:
                if isinstance(item, Mapping):
                    normalized_results.append(dict(item))
                else:
                    normalized_results.append(
                        {
                            "success": bool(getattr(item, "success", False)),
                            "result": getattr(item, "result", None),
                        }
                    )
            validation_result = {"success": gx_success, "results": normalized_results}
    except Exception as exc:  # A missing column should fail closed, not crash the pipeline.
        gx_success = False
        validation_error = f"{type(exc).__name__}: {exc}"
        validation_result = {"success": False, "results": [], "error": validation_error}

    expectation_results = validation_result.get("results", [])
    if not isinstance(expectation_results, list):
        expectation_results = []
    checks = {
        "table_row_count": _expectation_check(
            expectation_results, "expect_table_row_count_to_be_between"
        ),
        "required_values": manual_success
        and all(
            _expectation_check(expectation_results, "expect_column_values_to_not_be_null", column)
            for column in ("paper_id", "title", "text_for_embedding")
        ),
        "paper_id_unique": _expectation_check(
            expectation_results, "expect_column_values_to_be_unique", "paper_id"
        ),
        "summary_length": _expectation_check(
            expectation_results, "expect_column_value_lengths_to_be_between", "summary"
        )
        and "summary" not in manual_failures,
    }
    overall_success = gx_success and manual_success and freshness["is_fresh"]
    result = {
        "success": bool(overall_success),
        "gx_success": gx_success,
        "manual_success": manual_success,
        "manual_failures": manual_failures,
        "freshness": freshness,
        "freshness_success": freshness["is_fresh"],
        "stale_rows": freshness["stale_rows"],
        "total_rows": freshness["total_rows"],
        "stale_ratio": freshness["stale_ratio"],
        "report_name": str(report_name),
        "checks": checks,
        "validation_result": _json_safe(validation_result),
        "results": _json_safe(expectation_results),
        "expectations": _json_safe(expectation_results),
        "statistics": _json_safe(validation_result.get("statistics", {})),
    }
    if validation_error:
        result["validation_error"] = validation_error

    report_path = _quality_report_path(settings, report_name)
    result["report_path"] = str(report_path)
    write_json(report_path, result)
    return result
