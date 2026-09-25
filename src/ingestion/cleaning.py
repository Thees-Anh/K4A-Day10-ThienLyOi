from __future__ import annotations

from datetime import datetime

import pandas as pd

from ingestion.crossref import PaperRecord


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _parse_date(value: str) -> pd.Timestamp:
    return pd.to_datetime(value, errors="coerce", utc=True)


def _run_timestamp(run_date: datetime) -> pd.Timestamp:
    run_ts = pd.Timestamp(run_date)

    if run_ts.tzinfo is None:
        return run_ts.tz_localize("UTC")

    return run_ts.tz_convert("UTC")


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    rows: list[dict] = []
    run_ts = _run_timestamp(run_date)

    for record in records:
        paper_id = _clean_text(record.paper_id).lower()
        title = _clean_text(record.title)
        summary = _clean_text(record.summary)

        if not paper_id or not title or not summary:
            continue

        published_ts = _parse_date(record.published)
        updated_ts = _parse_date(record.updated)

        if pd.isna(published_ts):
            continue

        if pd.isna(updated_ts):
            updated_ts = published_ts

        authors = [
            _clean_text(author)
            for author in record.authors
            if _clean_text(author)
        ]

        categories = [
            _clean_text(category)
            for category in record.categories
            if _clean_text(category)
        ]

        authors_joined = ", ".join(authors)
        categories_joined = ", ".join(categories)

        published = published_ts.date().isoformat()
        updated = updated_ts.date().isoformat()
        age_days = int((run_ts - published_ts).days)

        text_for_embedding = (
            f"Title: {title}\n"
            f"Authors: {authors_joined}\n"
            f"Published: {published}\n"
            f"Categories: {categories_joined}\n"
            f"Summary: {summary}"
        )

        rows.append(
            {
                "paper_id": paper_id,
                "title": title,
                "summary": summary,
                "authors": authors,
                "categories": categories,
                "primary_category": _clean_text(record.primary_category),
                "published": published,
                "updated": updated,
                "age_days": age_days,
                "authors_joined": authors_joined,
                "categories_joined": categories_joined,
                "summary_chars": len(summary),
                "text_for_embedding": text_for_embedding,
                "abs_url": _clean_text(record.abs_url),
                "pdf_url": _clean_text(record.pdf_url),
                "comment": _clean_text(record.comment),
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["paper_id"], keep="first")
    df = df.sort_values(["published", "paper_id"], ascending=[False, True])
    df = df.reset_index(drop=True)

    return df
