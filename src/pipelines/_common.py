from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import read_json, write_csv, write_json


REQUIRED_CLEAN_COLUMNS = frozenset(
    {
        "paper_id",
        "title",
        "summary",
        "published",
        "age_days",
        "authors_joined",
        "categories_joined",
        "text_for_embedding",
        "abs_url",
        "pdf_url",
    }
)
REQUIRED_METRICS = frozenset({"retrieval_hit_rate", "mean_token_f1"})


def require_clean_dataframe(df: pd.DataFrame, stage: str) -> None:
    if df.empty:
        raise RuntimeError(f"{stage} produced an empty dataframe.")
    missing = sorted(REQUIRED_CLEAN_COLUMNS - set(df.columns))
    if missing:
        raise RuntimeError(f"{stage} dataframe is missing required columns: {', '.join(missing)}")


def save_dataframe(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    write_csv(df, csv_path)
    payload = json.loads(df.to_json(orient="records", date_format="iso"))
    write_json(json_path, payload)


def load_dataframe(path: Path, stage: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {stage} artifact: {path}")
    payload = read_json(path)
    if not isinstance(payload, list):
        raise RuntimeError(f"{stage} artifact must contain a JSON list: {path}")
    df = pd.DataFrame(payload)
    require_clean_dataframe(df, stage)
    return df


def load_mapping(path: Path, stage: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {stage} artifact: {path}")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{stage} artifact must contain a JSON object: {path}")
    return payload


def require_metrics(metrics: Mapping[str, Any], stage: str) -> None:
    missing = sorted(REQUIRED_METRICS - set(metrics))
    if missing:
        raise RuntimeError(f"{stage} metrics are missing required keys: {', '.join(missing)}")


def require_quality_success(quality: Mapping[str, Any], stage: str) -> None:
    if "success" not in quality:
        raise RuntimeError(f"{stage} quality report is missing the 'success' field.")
    if quality["success"] is not True:
        raise RuntimeError(f"{stage} quality gate failed; vector indexing was blocked.")


def require_artifacts(paths: Sequence[Path], stage: str) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        joined = "\n- ".join(missing)
        raise RuntimeError(f"{stage} completed without required artifacts:\n- {joined}")
