from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import unquote

import requests

from core.config import Settings
from core.utils import normalize_whitespace, write_json


CROSSREF_WORKS_URL = "https://api.crossref.org/works"
_MAX_RETRIES = 3
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_DOI_PREFIX_RE = re.compile(r"^doi\s*:\s*", re.IGNORECASE)
_DOI_URL_RE = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_NETLOC_RE = re.compile(r"^//(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_VALUE_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


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


class _MarkupTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        self.fragments.append(data)


def _is_missing_scalar(value: Any) -> bool:
    if value is None or type(value).__name__ in {"NAType", "NaTType"}:
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        pass
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False


def strip_markup(value: Any) -> str:
    """Remove XML/HTML tags while preserving ordinary angle-bracket text."""

    if _is_missing_scalar(value):
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(part) for part in value if part is not None)
    text = unescape(str(value))
    parser = _MarkupTextExtractor()
    try:
        parser.feed(text)
        parser.close()
        return normalize_whitespace("".join(parser.fragments))
    except (TypeError, ValueError, AssertionError):
        return normalize_whitespace(text)


def _text(value: Any) -> str:
    """Convert a scalar value to normalized text without producing ``None``."""

    if _is_missing_scalar(value):
        return ""
    return normalize_whitespace(str(value))


def _strip_markup(value: Any) -> str:
    """Remove HTML/JATS tags and decode entities from a text field."""

    return strip_markup(value)


def normalize_doi(value: Any) -> str:
    """Return a canonical, bare DOI suitable for use as ``paper_id``.

    Crossref can return a DOI as a bare value, a ``doi:`` URI, or a resolver
    URL.  DOI comparison is case-insensitive, so the canonical form is
    lower-case and has no resolver/query/fragment prefix.
    """

    if value is None:
        return ""

    doi = _text(value)
    doi = _DOI_PREFIX_RE.sub("", doi)
    doi = _DOI_URL_RE.sub("", doi)
    doi = _DOI_NETLOC_RE.sub("", doi)
    # Split URL components before unquoting so an encoded DOI suffix such as
    # ``%23`` is not mistaken for a fragment delimiter.
    doi = doi.split("?", 1)[0].split("#", 1)[0]
    doi = unquote(doi)
    doi = doi.strip().strip("/")
    if not _DOI_VALUE_RE.fullmatch(doi):
        return ""
    return doi.lower()


def _as_list(value: Any) -> list[str]:
    """Normalize a Crossref list-like field into a list of non-empty strings."""

    if value is None:
        return []
    if isinstance(value, str):
        values: Iterable[Any] = [value]
    elif isinstance(value, Mapping):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, Mapping):
            # Some APIs wrap subject entries in an object rather than using a
            # plain string.  Prefer the common label/name fields.
            item = item.get("name") or item.get("title") or item.get("term") or ""
        normalized = _text(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _author_name(author: Any) -> str:
    if not isinstance(author, Mapping):
        return _text(author)

    explicit_name = author.get("name")
    if explicit_name:
        return _text(explicit_name)

    given = _text(author.get("given") or author.get("firstName"))
    family = _text(author.get("family") or author.get("lastName") or author.get("surname"))
    suffix = _text(author.get("suffix"))
    if family and given:
        name = f"{given} {family}"
    else:
        name = given or family
    if suffix:
        name = f"{name} {suffix}"
    return _text(name)


def _parse_date(value: Any) -> str:
    """Parse Crossref date structures into an ISO-8601 calendar date."""

    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Mapping):
        if value.get("date-parts") is not None:
            value = value["date-parts"]
        elif value.get("date-time") is not None:
            value = value["date-time"]
        elif value.get("date") is not None:
            value = value["date"]
        else:
            return ""

    if isinstance(value, (list, tuple)):
        # Crossref uses [[year, month, day]].  Be liberal with providers
        # returning a flat [year, month, day] list as well.
        parts: Any = value
        if value and isinstance(value[0], (list, tuple)):
            parts = value[0]
        if not isinstance(parts, (list, tuple)) or not parts:
            return ""
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1
            return date(year, month, day).isoformat()
        except (TypeError, ValueError, OverflowError):
            return ""

    text = _text(value)
    if not text:
        return ""
    # datetime.fromisoformat understands offsets, but not a trailing Z on all
    # supported Python versions.  Normalize it first.
    iso_text = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(iso_text).date().isoformat()
    except (ValueError, OverflowError):
        # A date-only value is still valid even on Python versions that reject
        # it for an unexpected trailing timezone suffix.  ISO-8601 also permits
        # reduced precision (year or year-month), which Crossref occasionally
        # emits when a day is unknown.
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except (ValueError, OverflowError):
            if re.fullmatch(r"\d{4}", text):
                try:
                    return date(int(text), 1, 1).isoformat()
                except (ValueError, OverflowError):
                    return ""
            if re.fullmatch(r"\d{4}-\d{1,2}", text):
                try:
                    year, month = (int(part) for part in text.split("-"))
                    return date(year, month, 1).isoformat()
                except (ValueError, OverflowError):
                    return ""
            return ""


def _parse_authors(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return _as_list(value)

    authors: list[str] = []
    for author in value:
        name = _author_name(author)
        if name and name.casefold() not in {item.casefold() for item in authors}:
            authors.append(name)
    return authors


def _first_date(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        parsed = _parse_date(item.get(key))
        if parsed:
            return parsed
    return ""


def _first_link(item: Mapping[str, Any], content_type: str | None = None) -> str:
    links = item.get("link", [])
    if isinstance(links, Mapping):
        links = [links]
    if not isinstance(links, (list, tuple)):
        return ""
    for link in links:
        if not isinstance(link, Mapping):
            continue
        if content_type and str(link.get("content-type", "")).lower() != content_type.lower():
            continue
        url = _text(link.get("URL") or link.get("url"))
        if url:
            return url
    return ""


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse a Crossref ``works`` response into normalized ``PaperRecord``s.

    Crossref's payload has changed slightly between API versions, so this
    parser accepts both the regular response envelope (``message.items``) and
    a bare item list.  Items without a DOI or title are ignored because they
    cannot form a usable paper record; optional fields are kept as empty
    strings and can be surfaced by the quality gate.
    """

    if isinstance(payload, Mapping):
        message = payload.get("message")
        if isinstance(message, Mapping):
            items = message.get("items", [])
        else:
            items = payload.get("items", [])
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    if not isinstance(items, (list, tuple)):
        return []

    records: list[PaperRecord] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue

        doi = normalize_doi(item.get("DOI") or item.get("doi") or item.get("URL"))
        if not doi:
            continue

        title_value = item.get("title")
        if isinstance(title_value, (list, tuple)):
            title = _strip_markup(next((part for part in title_value if _text(part)), ""))
        else:
            title = _strip_markup(title_value)
        title = normalize_whitespace(title)
        if not title:
            continue

        authors = _parse_authors(item.get("author") or item.get("authors") or [])
        categories = _as_list(item.get("subject") or item.get("categories") or item.get("category"))
        primary_category = categories[0] if categories else ""
        published = _first_date(item, "published", "published-online", "published-print", "issued")
        updated = _first_date(item, "updated", "deposited", "created") or published
        abs_url = _text(item.get("URL") or item.get("url") or f"https://doi.org/{doi}")
        pdf_url = _first_link(item, "application/pdf") or _first_link(item) or abs_url
        comment = _text(item.get("comment") or item.get("note"))
        if not comment:
            comment = f"Crossref record {doi}"

        records.append(
            PaperRecord(
                paper_id=doi,
                title=title,
                summary=_strip_markup(item.get("abstract") or item.get("summary")),
                authors=authors,
                categories=categories,
                primary_category=primary_category,
                published=published,
                updated=updated,
                abs_url=abs_url,
                pdf_url=pdf_url,
                comment=comment,
            )
        )
    return records


def _response_payload(response: Any) -> dict:
    """Extract a JSON payload from a requests-like response object."""

    if hasattr(response, "json"):
        payload = response.json()
    else:  # pragma: no cover - useful for very small test doubles
        payload = json.loads(response.text)
    if not isinstance(payload, dict):
        raise ValueError("Crossref response must be a JSON object.")
    return payload


def _load_snapshot(settings: Settings) -> list[PaperRecord]:
    """Load the response snapshot, with the normalized records as a backup."""

    response_path = Path(settings.paths.raw_api_response)
    if response_path.exists():
        try:
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            records = parse_crossref_payload(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            records = []
        if records:
            return records

    records_path = Path(settings.paths.raw_records_json)
    if records_path.exists():
        try:
            records = load_raw_records(records_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            records = []
        if records:
            return records
    return []


def _write_raw_response(path: Path, payload: dict, raw_content: str | bytes | None) -> None:
    if isinstance(raw_content, bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_content)
    elif isinstance(raw_content, str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw_content, encoding="utf-8")
    else:
        write_json(path, payload)


def _write_records(records: list[PaperRecord], path: Path) -> None:
    write_json(path, [asdict(record) for record in records])


def _request_crossref(settings: Settings) -> tuple[dict, str | bytes | None]:
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
    }
    last_error: BaseException | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.get(CROSSREF_WORKS_URL, params=params, timeout=20)
            status_code = int(getattr(response, "status_code", 200))
            if status_code in _RETRY_STATUS_CODES:
                last_error = RuntimeError(f"Crossref returned HTTP {status_code}.")
                if attempt < _MAX_RETRIES - 1:
                    retry_after = (getattr(response, "headers", None) or {}).get("Retry-After")
                    try:
                        delay = min(float(retry_after), 5.0) if retry_after else 0.5 * (2**attempt)
                    except (TypeError, ValueError):
                        delay = 0.5 * (2**attempt)
                    time.sleep(max(delay, 0))
                continue

            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            payload = _response_payload(response)
            raw_content = getattr(response, "content", None)
            if not isinstance(raw_content, bytes) or not raw_content:
                raw_content = getattr(response, "text", None)
            if not isinstance(raw_content, (str, bytes)):
                raw_content = None
            return payload, raw_content
        except (requests.RequestException, ValueError, TypeError) as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.5 * (2**attempt))

    raise RuntimeError("Crossref API request failed after retries.") from last_error

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
    """Fetch Crossref records, falling back to the local snapshot when needed.

    ``REFRESH_SOURCE=true`` enables a live request.  In the default offline
    mode the bundled response is used immediately, which makes lab work
    deterministic.  If a live request is explicitly enabled and fails (most
    commonly with HTTP 429 or a network error), the same local snapshot is
    used automatically.
    """

    use_live_api = bool(getattr(settings, "refresh_source", False))
    if not use_live_api:
        snapshot_records = _load_snapshot(settings)
        if snapshot_records:
            _write_records(snapshot_records, Path(settings.paths.raw_records_json))
            return snapshot_records

    try:
        request_result = _request_crossref(settings)
        if isinstance(request_result, tuple) and len(request_result) == 2:
            payload, raw_content = request_result
        else:  # pragma: no cover - compatibility with injected test doubles
            payload, raw_content = request_result, None
        records = parse_crossref_payload(payload)
        if not records:
            raise ValueError("Crossref response did not contain valid paper records.")
        # Validate the payload before replacing the offline snapshot.  A
        # transient but syntactically valid empty response must not destroy
        # the recovery artifact.
        _write_raw_response(Path(settings.paths.raw_api_response), payload, raw_content)
        _write_records(records, Path(settings.paths.raw_records_json))
        return records
    except (requests.RequestException, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        snapshot_records = _load_snapshot(settings)
        if snapshot_records:
            _write_records(snapshot_records, Path(settings.paths.raw_records_json))
            return snapshot_records
        raise RuntimeError(
            "Unable to fetch Crossref data and no usable offline snapshot is available."
        ) from exc


def _record_from_mapping(item: Mapping[str, Any]) -> PaperRecord:
    authors = _parse_authors(item.get("authors") or item.get("author") or [])
    categories = _as_list(item.get("categories") or item.get("subject") or item.get("category"))
    doi = normalize_doi(item.get("paper_id") or item.get("DOI") or item.get("doi"))
    return PaperRecord(
        paper_id=doi,
        title=_strip_markup(item.get("title")),
        summary=_strip_markup(item.get("summary") or item.get("abstract")),
        authors=authors,
        categories=categories,
        primary_category=_text(item.get("primary_category")) or (categories[0] if categories else ""),
        published=_parse_date(item.get("published")),
        updated=_parse_date(item.get("updated")) or _parse_date(item.get("published")),
        abs_url=_text(item.get("abs_url") or item.get("URL") or f"https://doi.org/{doi}"),
        pdf_url=_text(item.get("pdf_url") or item.get("URL") or f"https://doi.org/{doi}"),
        comment=_text(item.get("comment")),
    )


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load a normalized raw-record JSON snapshot into ``PaperRecord`` objects."""

    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and "message" in payload:
        return parse_crossref_payload(payload)
    if not isinstance(payload, list):
        raise ValueError("Raw records JSON must contain a list of records.")

    records: list[PaperRecord] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        record = _record_from_mapping(item)
        if record.paper_id and record.title:
            records.append(record)
    return records
