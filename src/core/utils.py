from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
import json
from os import PathLike
from pathlib import Path
import re
from typing import Any, Iterable


def ensure_parent(path: Path | PathLike[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path | PathLike[str], payload: Any) -> None:
    path = Path(path)
    ensure_parent(path)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path | PathLike[str]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_csv(df, path: Path | PathLike[str]) -> None:
    path = Path(path)
    ensure_parent(path)
    df.to_csv(path, index=False, encoding="utf-8")


def write_text(path: Path | PathLike[str], text: str) -> None:
    path = Path(path)
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def now_utc() -> datetime:
    return datetime.now(UTC)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned or "item"


def compact_join(items: Iterable[str], sep: str = ", ") -> str:
    return sep.join(item for item in items if item)


def first_sentence(text: str) -> str:
    chunks = re.split(r"(?<=[.!?])\s+", normalize_whitespace(text))
    return chunks[0] if chunks else normalize_whitespace(text)
