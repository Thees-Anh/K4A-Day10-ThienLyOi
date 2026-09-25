from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import time

import requests

from core.config import Settings


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(item) for item in value if item)
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _date_from_crossref(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("date-time"):
        return str(value["date-time"])[:10]

    date_parts = value.get("date-parts")
    if not date_parts or not isinstance(date_parts, list) or not date_parts[0]:
        return ""

    parts = list(date_parts[0])
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    day = int(parts[2]) if len(parts) > 2 else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _authors_from_crossref(item: dict) -> list[str]:
    authors: list[str] = []
    for author in item.get("author", []) or []:
        if not isinstance(author, dict):
            continue
        name = _normalize_text(" ".join(part for part in [author.get("given"), author.get("family")] if part))
        if name:
            authors.append(name)
    return authors


def _pdf_url_from_crossref(item: dict, fallback_url: str) -> str:
    for link in item.get("link", []) or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("URL", ""))
        content_type = str(link.get("content-type", "")).lower()
        if url and ("pdf" in content_type or url.lower().endswith(".pdf")):
            return url
    return fallback_url


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """TODO(student): parse Crossref payload thanh list PaperRecord.

    Pseudo-code:
    1. Duyet `payload["message"]["items"]`.
    2. Lay DOI, title, abstract, authors, subject, dates, URLs.
    3. Chuan hoa text va bo record khong hop le.
    4. Tra ve list `PaperRecord`.
    """
    records: list[PaperRecord] = []
    seen_ids: set[str] = set()

    items = payload.get("message", {}).get("items", [])

    for item in items:
        if not isinstance(item, dict):
            continue

        paper_id = _normalize_text(item.get("DOI")).lower()
        title = _normalize_text(item.get("title"))
        summary = _normalize_text(item.get("abstract"))

        published = _date_from_crossref(
            item.get("published")
            or item.get("published-print")
            or item.get("created")
        )

        if not paper_id or not title or not summary or not published:
            continue

        if paper_id in seen_ids:
            continue

        authors = _authors_from_crossref(item)

        categories = [
            _normalize_text(category)
            for category in item.get("subject", []) or []
        ]
        categories = [category for category in categories if category]

        abs_url = _normalize_text(item.get("URL")) or f"https://doi.org/{paper_id}"

        updated = (
            _date_from_crossref(
                item.get("updated")
                or item.get("deposited")
                or item.get("created")
            )
            or published
        )

        record = PaperRecord(
            paper_id=paper_id,
            title=title,
            summary=summary,
            authors=authors,
            categories=categories,
            primary_category=categories[0] if categories else "",
            published=published,
            updated=updated,
            abs_url=abs_url,
            pdf_url=_pdf_url_from_crossref(item, abs_url),
            comment=f"Crossref record {paper_id}",
        )

        records.append(record)
        seen_ids.add(paper_id)

    return records

def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """TODO(student): goi source API, luu raw response, parse thanh records.

    Pseudo-code:
    1. Tao params tu `settings.source_query`, `settings.source_filter`, `settings.max_results`.
    2. Goi API voi retry cho cac status code nhu 429/503.
    3. Luu raw response vao `settings.paths.raw_api_response`.
    4. Parse payload bang `parse_crossref_payload`.
    5. Luu records vao `settings.paths.raw_records_json`.
    """
    settings.paths.raw_api_response.parent.mkdir(parents=True, exist_ok=True)
    settings.paths.raw_records_json.parent.mkdir(parents=True, exist_ok=True)

    payload: dict | None = None
    use_local_snapshot = (
        settings.paths.raw_api_response.exists()
        and not settings.refresh_source
    )

    if use_local_snapshot:
        with settings.paths.raw_api_response.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    else:
        params = {
            "query": settings.source_query,
            "filter": settings.source_filter,
            "rows": settings.max_results,
        }

        last_error: Exception | None = None

        for attempt in range(3):
            try:
                response = requests.get(
                    "https://api.crossref.org/works",
                    params=params,
                    timeout=20,
                )
                response.raise_for_status()

                payload = response.json()

                with settings.paths.raw_api_response.open("w", encoding="utf-8") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)

                break

            except requests.RequestException as exc:
                last_error = exc

                if attempt < 2:
                    time.sleep(2**attempt)

        if payload is None:
            if settings.paths.raw_api_response.exists():
                with settings.paths.raw_api_response.open("r", encoding="utf-8") as file:
                    payload = json.load(file)
            else:
                raise RuntimeError(
                    "Could not fetch Crossref data and no local snapshot exists."
                ) from last_error

    records = parse_crossref_payload(payload)

    with settings.paths.raw_records_json.open("w", encoding="utf-8") as file:
        json.dump(
            [asdict(record) for record in records],
            file,
            ensure_ascii=False,
            indent=2,
        )

    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """TODO(student): doc JSON snapshot va map thanh `PaperRecord`."""
    with path.open("r", encoding="utf-8") as file:
        raw_records = json.load(file)
    return [PaperRecord(**record) for record in raw_records]
