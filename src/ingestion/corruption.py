from __future__ import annotations

from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import write_json


_SCENARIOS = (
    "drop_latest_records",
    "blank_summary",
    "inject_noise",
    "truncate_title",
    "stale_date",
    "duplicate_rows",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _joined(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if _text(item))
    return _text(value)


def _rebuild_embedding_text(row: pd.Series) -> str:
    return "\n".join(
        [
            f"Title: {_text(row.get('title'))}",
            f"Authors: {_text(row.get('authors_joined')) or _joined(row.get('authors'))}",
            f"Published: {_text(row.get('published'))}",
            f"Categories: {_text(row.get('categories_joined')) or _joined(row.get('categories'))}",
            f"Summary: {_text(row.get('summary'))}",
        ]
    )


def _recalculate_ages(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty or "published" not in dataframe.columns:
        return dataframe
    run_date = pd.Timestamp.now(tz="UTC").date()
    ages: list[int] = []
    for value in dataframe["published"]:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            ages.append(0)
        else:
            ages.append((run_date - parsed.date()).days)
    dataframe["age_days"] = ages
    return dataframe


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path) -> pd.DataFrame:
    """Inject six deterministic corruption scenarios into a clean dataframe."""

    corrupted = df.copy(deep=True)
    if corrupted.empty:
        log = {
            "scenarios": [],
            "corruptions": [],
            "input_rows": 0,
            "output_rows": 0,
        }
        write_json(Path(output_log_path), log)
        return corrupted

    input_rows = len(corrupted)
    details: list[dict[str, Any]] = []

    # 1. Drop approximately 20% of the newest records.  The clean frame is
    # sorted newest-first, while the timestamp fallback keeps this meaningful
    # for custom frames as well.
    drop_count = max(1, math.ceil(input_rows * 0.20))
    drop_count = min(drop_count, max(0, input_rows - 1))
    dropped_ids = corrupted.head(drop_count)["paper_id"].astype(str).tolist()
    corrupted = corrupted.iloc[drop_count:].reset_index(drop=True)
    details.append(
        {
            "scenario": "drop_latest_records",
            "affected_rows": drop_count,
            "paper_ids": dropped_ids,
        }
    )

    def target(offset: int) -> int | None:
        return offset if offset < len(corrupted) else None

    # 2. Blank a summary.
    row_index = target(0)
    if row_index is not None:
        corrupted.at[row_index, "summary"] = ""
        corrupted.at[row_index, "summary_chars"] = 0
        details.append(
            {
                "scenario": "blank_summary",
                "affected_rows": 1,
                "paper_id": _text(corrupted.at[row_index, "paper_id"]),
            }
        )

    # 3. Inject a deterministic noise marker.
    row_index = target(1)
    if row_index is not None:
        noise = " [CORRUPTION_NOISE: invalid-token-9137]"
        corrupted.at[row_index, "summary"] = (
            f"{_text(corrupted.at[row_index, 'summary'])}{noise}"
        )
        corrupted.at[row_index, "summary_chars"] = len(
            _text(corrupted.at[row_index, "summary"])
        )
        details.append(
            {
                "scenario": "inject_noise",
                "affected_rows": 1,
                "paper_id": _text(corrupted.at[row_index, "paper_id"]),
                "noise": noise,
            }
        )

    # 4. Truncate a title below the eight-character corruption threshold.
    row_index = target(2)
    if row_index is not None:
        corrupted.at[row_index, "title"] = _text(corrupted.at[row_index, "title"])[:7]
        details.append(
            {
                "scenario": "truncate_title",
                "affected_rows": 1,
                "paper_id": _text(corrupted.at[row_index, "paper_id"]),
            }
        )

    # 5. Move one publication date into the stale window.
    row_index = target(3)
    if row_index is not None:
        stale_date = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)).date().isoformat()
        corrupted.at[row_index, "published"] = stale_date
        corrupted.at[row_index, "updated"] = stale_date
        details.append(
            {
                "scenario": "stale_date",
                "affected_rows": 1,
                "paper_id": _text(corrupted.at[row_index, "paper_id"]),
                "published": stale_date,
            }
        )

    # Rebuild the embedding text after all field-level edits.
    for index in corrupted.index:
        corrupted.at[index, "text_for_embedding"] = _rebuild_embedding_text(corrupted.loc[index])

    # 6. Duplicate rows to create a non-unique paper_id key.
    duplicate_count = min(2, len(corrupted))
    duplicated = corrupted.head(duplicate_count).copy()
    corrupted = pd.concat([corrupted, duplicated], ignore_index=True)
    details.append(
        {
            "scenario": "duplicate_rows",
            "affected_rows": duplicate_count,
            "paper_ids": duplicated["paper_id"].astype(str).tolist(),
        }
    )

    corrupted = _recalculate_ages(corrupted)
    for index in corrupted.index:
        corrupted.at[index, "text_for_embedding"] = _rebuild_embedding_text(corrupted.loc[index])

    output_rows = len(corrupted)
    log = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_rows": input_rows,
        "output_rows": output_rows,
        "scenarios": list(_SCENARIOS),
        "corruptions": details,
    }
    write_json(Path(output_log_path), log)
    return corrupted
