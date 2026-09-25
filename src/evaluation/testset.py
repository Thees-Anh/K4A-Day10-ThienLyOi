from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, normalize_whitespace, write_json


QUESTION_TYPES = ("summary", "authors", "date", "categories")
QUESTION_COUNTS = {
    "summary": 3,
    "authors": 3,
    "date": 2,
    "categories": 2,
}
REQUIRED_SAMPLE_FIELDS = frozenset(
    {"id", "question", "ground_truth", "ground_truth_doc_ids"}
)


@dataclass(frozen=True)
class TestSet:
    """In-memory representation of the benchmark stored as a JSON list."""

    samples: list[dict[str, Any]]

    def __len__(self) -> int:
        return len(self.samples)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        items = [_as_text(item) for item in value]
        return ", ".join(item for item in items if item)
    try:
        missing = pd.isna(value)
        if bool(missing):
            return ""
    except (TypeError, ValueError):
        pass
    return normalize_whitespace(str(value))


def _joined_field(row: dict[str, Any], joined_name: str, list_name: str) -> str:
    joined = _as_text(row.get(joined_name))
    if joined:
        return joined
    values = row.get(list_name)
    if isinstance(values, (list, tuple, set)):
        items = [_as_text(value) for value in values]
        return ", ".join(item for item in items if item)
    return _as_text(values)


def _normalise_records(df: pd.DataFrame) -> list[dict[str, str]]:
    required_columns = {"paper_id", "title", "summary", "published"}
    missing_columns = sorted(required_columns.difference(df.columns))
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Clean dataframe is missing required columns: {missing}")

    records: list[dict[str, str]] = []
    seen_paper_ids: set[str] = set()
    for raw_row in df.to_dict(orient="records"):
        paper_id = _as_text(raw_row.get("paper_id"))
        title = _as_text(raw_row.get("title"))
        summary = _as_text(raw_row.get("summary"))
        published = _as_text(raw_row.get("published"))
        if not paper_id or not title or not summary or not published:
            continue

        paper_key = paper_id.casefold()
        if paper_key in seen_paper_ids:
            continue
        seen_paper_ids.add(paper_key)

        categories = _joined_field(raw_row, "categories_joined", "categories")
        if not categories:
            categories = _as_text(raw_row.get("primary_category"))
        records.append(
            {
                "paper_id": paper_id,
                "title": title,
                "summary": summary,
                "authors": _joined_field(raw_row, "authors_joined", "authors"),
                "published": published,
                "categories": categories,
            }
        )

    if len(records) < len(QUESTION_TYPES):
        raise ValueError(
            f"At least {len(QUESTION_TYPES)} valid, unique papers are required to build the benchmark."
        )
    return records


def _matching_indexes(records: list[dict[str, str]], keywords: tuple[str, ...]) -> list[int]:
    matches: list[int] = []
    for keyword in (value.casefold() for value in keywords):
        keyword_matches = [
            index
            for index, record in enumerate(records)
            if keyword in f"{record['title']} {record['categories']}".casefold()
        ]
        keyword_matches.sort(
            key=lambda index: (
                records[index]["title"].casefold().startswith("advanced perspectives"),
                index,
            )
        )
        for index in keyword_matches:
            if index not in matches:
                matches.append(index)
    return matches


def _choose_records(
    records: list[dict[str, str]],
    keywords: tuple[str, ...],
    count: int,
) -> list[dict[str, str]]:
    """Choose representative records deterministically, with safe fallbacks."""

    candidate_indexes = _matching_indexes(records, keywords)
    candidate_indexes.extend(index for index in range(len(records)) if index not in candidate_indexes)
    selected = [records[index] for index in candidate_indexes[:count]]

    # A small custom corpus may contain fewer than ten papers.  Reusing a
    # grounded record keeps the benchmark schema deterministic instead of
    # failing after the quality gate has already accepted the corpus.
    while len(selected) < count:
        selected.append(records[len(selected) % len(records)])
    return selected


def _question(question_type: str, record: dict[str, str]) -> str:
    title = record["title"]
    if question_type == "summary":
        return f'What is the summary of the paper "{title}"?'
    if question_type == "authors":
        return f'Who are the authors of "{title}"?'
    if question_type == "date":
        return f'When was "{title}" published?'
    return f'What categories does the paper "{title}" belong to?'


def _ground_truth(question_type: str, record: dict[str, str]) -> str:
    if question_type == "summary":
        return first_sentence(record["summary"])
    if question_type == "authors":
        return record["authors"]
    if question_type == "date":
        return record["published"]
    return record["categories"]


def _make_sample(
    sample_number: int,
    question_type: str,
    record: dict[str, str],
) -> dict[str, Any]:
    return {
        "id": f"eval_{sample_number:03d}",
        "question_type": question_type,
        "question": _question(question_type, record),
        "ground_truth": _ground_truth(question_type, record),
        "ground_truth_doc_ids": [record["paper_id"]],
    }


def _validate_samples(samples: Any) -> bool:
    if not isinstance(samples, list) or len(samples) != sum(QUESTION_COUNTS.values()):
        return False

    question_types: set[str] = set()
    sample_ids: set[str] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            return False
        question_type = sample.get("question_type", sample.get("type"))
        if question_type not in QUESTION_TYPES:
            return False
        if not REQUIRED_SAMPLE_FIELDS.issubset(sample):
            return False
        if sample["id"] in sample_ids:
            return False
        sample_ids.add(sample["id"])
        question_types.add(question_type)
        if not all(
            isinstance(sample[field], str) and sample[field].strip()
            for field in ("id", "question", "ground_truth")
        ):
            return False
        doc_ids = sample["ground_truth_doc_ids"]
        if not isinstance(doc_ids, list) or not doc_ids:
            return False
        if not all(isinstance(doc_id, str) and doc_id.strip() for doc_id in doc_ids):
            return False

    return question_types == set(QUESTION_TYPES)


def build_test_set(df: pd.DataFrame, output_path: Path | str) -> list[dict[str, Any]]:
    """Create the deterministic ten-question, four-category benchmark.

    The benchmark intentionally uses ``question_type`` as specified by the
    lab contract.  It remains compatible with older files containing ``type``
    when loading through :func:`load_or_create_test_set`.
    """

    records = _normalise_records(df)
    samples: list[dict[str, Any]] = []
    sample_number = 1
    keywords_by_type = {
        "summary": (
            "agentic retrieval",
            "retrieval-augmented generation",
            "data observability",
            "rag",
        ),
        "authors": (
            "hybrid search",
            "chunking strategies",
            "continuous benchmark",
            "evaluation",
        ),
        "date": (
            "freshness",
            "quality gates",
            "mitigating ghost",
            "multi-agent",
        ),
        "categories": (
            "natural language processing",
            "databases",
            "software engineering",
            "artificial intelligence",
        ),
    }
    for question_type in QUESTION_TYPES:
        selected = _choose_records(
            records,
            keywords_by_type[question_type],
            QUESTION_COUNTS[question_type],
        )
        for record in selected:
            samples.append(_make_sample(sample_number, question_type, record))
            sample_number += 1

    if not _validate_samples(samples):
        raise RuntimeError("Generated benchmark does not satisfy the required schema.")
    if output_path is not None:
        write_json(Path(output_path), samples)
    return samples


def load_or_create_test_set(
    df: pd.DataFrame,
    output_path: Path | str,
    *,
    refresh: bool = False,
) -> TestSet:
    """Load a valid ten-question benchmark or create it from the clean corpus."""

    path = Path(output_path)
    if not refresh and path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if _validate_samples(payload):
                return TestSet(samples=payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    return TestSet(samples=build_test_set(df, path))
