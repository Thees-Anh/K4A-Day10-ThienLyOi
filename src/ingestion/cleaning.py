from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import pandas as pd

from ingestion.crossref import PaperRecord, normalize_doi, strip_markup
_CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "abs_url",
    "pdf_url",
    "comment",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "text_for_embedding",
    "age_days",
]


def _strip_markup(value: Any) -> str:
    if _is_missing_scalar(value):
        return ""
    return strip_markup(value)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: list[Any] = [value]
    elif isinstance(value, Mapping):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, Mapping):
            item = item.get("name") or item.get("title") or item.get("term") or ""
        text = _strip_markup(item)
        if not text:
            continue
        key = text.casefold()
        if key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _record_value(record: Any, field: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(field, default)
    return getattr(record, field, default)


def _is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _date_only(value: Any) -> date | None:
    if _is_missing_scalar(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = float(value)
            if numeric.is_integer() and 1 <= int(numeric) <= 9999:
                return date(int(numeric), 1, 1)
        except (TypeError, ValueError, OverflowError):
            pass
    text = str(value).strip()
    if not text or text.casefold() in {"nat", "none", "<na>"}:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except (ValueError, OverflowError):
        try:
            return date.fromisoformat(text[:10])
        except (ValueError, OverflowError):
            try:
                parsed = pd.to_datetime(value, errors="coerce")
                if pd.isna(parsed) or not hasattr(parsed, "date"):
                    return None
                return parsed.date()
            except (TypeError, ValueError, OverflowError, NotImplementedError):
                return None


def _timestamp(value: Any) -> pd.Timestamp | None:
    if _is_missing_scalar(value):
        return None
    if isinstance(value, datetime):
        return pd.Timestamp(value)
    if isinstance(value, date):
        return pd.Timestamp(datetime.combine(value, datetime.min.time()))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = float(value)
            if numeric.is_integer() and 1 <= int(numeric) <= 9999:
                return pd.Timestamp(datetime(int(numeric), 1, 1))
        except (TypeError, ValueError, OverflowError):
            pass
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        return pd.Timestamp(datetime.fromisoformat(text))
    except (ValueError, OverflowError):
        try:
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed) or not hasattr(parsed, "date"):
                return None
            timestamp = pd.Timestamp(parsed)
            timestamp.date()
            return timestamp
        except (TypeError, ValueError, OverflowError, NotImplementedError):
            return None


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Normalize raw records into the dataframe consumed by the RAG pipeline.

    The function deliberately keeps short or empty summaries in the dataframe
    so the quality gate can detect them.  Only records without a DOI, title,
    or publication date are removed as structurally unusable; duplicate DOIs
    are then removed with the first occurrence retained.
    """

    run_timestamp = _timestamp(run_date)
    if run_timestamp is None:
        raise ValueError("run_date must be a valid date or datetime.")
    run_day = run_timestamp.date()
    rows: list[dict[str, Any]] = []

    for record in records or []:
        paper_id = normalize_doi(_record_value(record, "paper_id"))
        title = _strip_markup(_record_value(record, "title"))
        summary = _strip_markup(_record_value(record, "summary"))
        authors = _as_list(_record_value(record, "authors", []))
        categories = _as_list(_record_value(record, "categories", []))

        published_value = _record_value(record, "published")
        published_timestamp = _timestamp(published_value)
        published_day = _date_only(published_value)
        updated_day = _date_only(_record_value(record, "updated"))
        if not paper_id or not title or published_day is None or published_timestamp is None:
            continue

        if run_timestamp.tzinfo is not None and published_timestamp.tzinfo is None:
            published_timestamp = published_timestamp.tz_localize(run_timestamp.tzinfo)
        elif run_timestamp.tzinfo is None and published_timestamp.tzinfo is not None:
            published_timestamp = published_timestamp.tz_convert("UTC").tz_localize(None)
        elif run_timestamp.tzinfo is not None and published_timestamp.tzinfo is not None:
            published_timestamp = published_timestamp.tz_convert(run_timestamp.tzinfo)

        published = published_day.isoformat()
        updated = (updated_day or published_day).isoformat()
        authors_joined = ", ".join(authors)
        categories_joined = ", ".join(categories)
        primary_category = _strip_markup(_record_value(record, "primary_category")) or (
            categories[0] if categories else ""
        )
        text_for_embedding = "\n".join(
            [
                f"Title: {title}",
                f"Authors: {authors_joined}",
                f"Published: {published}",
                f"Categories: {categories_joined}",
                f"Summary: {summary}",
            ]
        )
        age_days = int((run_timestamp - published_timestamp).days)

        rows.append(
            {
                "paper_id": paper_id,
                "title": title,
                "summary": summary,
                "authors": authors,
                "categories": categories,
                "primary_category": primary_category,
                "published": published,
                "updated": updated,
                "abs_url": _strip_markup(_record_value(record, "abs_url")),
                "pdf_url": _strip_markup(_record_value(record, "pdf_url")),
                "comment": _strip_markup(_record_value(record, "comment")),
                "authors_joined": authors_joined,
                "categories_joined": categories_joined,
                "summary_chars": len(summary),
                "text_for_embedding": text_for_embedding,
                "age_days": age_days,
            }
        )

    dataframe = pd.DataFrame(rows, columns=_CLEAN_COLUMNS)
    if dataframe.empty:
        dataframe["age_days"] = pd.Series(dtype="int64")
        return dataframe

    dataframe = dataframe.drop_duplicates(subset=["paper_id"], keep="first")
    dataframe = dataframe.sort_values(
        by=["published", "paper_id"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)
    return dataframe
