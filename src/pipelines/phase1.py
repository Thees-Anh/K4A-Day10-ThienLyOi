from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from core.config import Settings, load_settings
from core.utils import now_utc
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records, load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from pipelines._common import (
    require_artifacts,
    require_clean_dataframe,
    require_metrics,
    require_quality_success,
    save_dataframe,
)
from retrieval.index import LocalEmbeddingIndex


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Phase1Result:
    source_summary: dict[str, Any]
    metrics: dict[str, Any]
    quality: dict[str, Any]
    freshness: dict[str, Any]


def _load_source_records(settings: Settings):
    raw_path = settings.paths.raw_records_json
    if settings.refresh_source or not raw_path.is_file():
        LOGGER.info("Fetching source records (with offline fallback when available).")
        return fetch_source_records(settings), "fetch_or_fallback"
    LOGGER.info("Loading raw records from %s", raw_path)
    return load_raw_records(raw_path), "cached_raw"


def _ensure_test_set(settings: Settings, clean_df) -> None:
    if settings.refresh_test_set or not settings.paths.eval_testset.is_file():
        LOGGER.info("Building evaluation test set.")
        build_test_set(clean_df, settings.paths.eval_testset)
    else:
        LOGGER.info("Reusing evaluation test set at %s", settings.paths.eval_testset)


def main(settings: Settings | None = None) -> Phase1Result:
    """Run the clean-data pipeline and return its observable results."""
    settings = settings or load_settings()
    records, source_mode = _load_source_records(settings)
    if not records:
        raise RuntimeError("Source ingestion returned no records.")

    run_at = now_utc()
    clean_df = build_clean_dataframe(records, run_at)
    require_clean_dataframe(clean_df, "baseline cleaning")
    save_dataframe(clean_df, settings.paths.clean_csv, settings.paths.clean_json)

    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    require_quality_success(quality, "baseline")

    index = LocalEmbeddingIndex.build(clean_df, settings, settings.paths.embeddings_json)
    _ensure_test_set(settings, clean_df)
    evaluation = evaluate_pipeline(
        settings,
        index,
        settings.paths.eval_testset,
        settings.paths.baseline_metrics,
        settings.paths.baseline_answers,
    )
    metrics = dict(evaluation.summary)
    require_metrics(metrics, "baseline")

    source_summary = {
        "source": settings.source_api,
        "mode": source_mode,
        "query": settings.source_query,
        "filter": settings.source_filter,
        "raw_records": len(records),
        "clean_records": len(clean_df),
        "max_results": settings.max_results,
        "run_at": run_at.isoformat(),
    }
    generate_phase1_report(
        settings.paths.baseline_report,
        source_summary,
        metrics,
        quality,
        freshness,
    )

    require_artifacts(
        [
            settings.paths.raw_records_json,
            settings.paths.clean_csv,
            settings.paths.clean_json,
            settings.paths.embeddings_json,
            settings.paths.eval_testset,
            settings.paths.baseline_metrics,
            settings.paths.baseline_answers,
            settings.paths.baseline_quality_report,
            settings.paths.freshness_report,
            settings.paths.baseline_report,
        ],
        "baseline pipeline",
    )
    print(
        "Baseline complete: "
        f"{len(clean_df)} records, "
        f"hit_rate={metrics['retrieval_hit_rate']:.3f}, "
        f"token_f1={metrics['mean_token_f1']:.3f}"
    )
    return Phase1Result(source_summary, metrics, quality, freshness)
