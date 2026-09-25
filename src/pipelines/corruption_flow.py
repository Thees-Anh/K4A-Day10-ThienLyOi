from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from core.config import Settings, load_settings
from core.utils import now_utc
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from pipelines._common import (
    load_dataframe,
    load_mapping,
    require_artifacts,
    require_clean_dataframe,
    require_metrics,
    require_quality_success,
    save_dataframe,
)
from retrieval.index import LocalEmbeddingIndex


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorruptionFlowResult:
    baseline_metrics: dict[str, Any]
    corrupted_metrics: dict[str, Any]
    repaired_metrics: dict[str, Any]
    corrupted_quality: dict[str, Any]
    repaired_quality: dict[str, Any]


def _require_baseline(
    settings: Settings,
) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any]]:
    try:
        baseline_metrics = load_mapping(settings.paths.baseline_metrics, "baseline metrics")
        clean_df = load_dataframe(settings.paths.clean_json, "baseline clean data")
        baseline_quality = load_mapping(
            settings.paths.baseline_quality_report, "baseline quality report"
        )
        baseline_freshness = load_mapping(
            settings.paths.freshness_report, "baseline freshness report"
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Baseline artifacts are missing; run script/run_phase1.py first.") from exc
    if not settings.paths.eval_testset.is_file():
        raise RuntimeError("Evaluation test set is missing; run script/run_phase1.py first.")
    require_metrics(baseline_metrics, "baseline")
    return baseline_metrics, clean_df, baseline_quality, baseline_freshness


def _evaluate_state(settings: Settings, df, embeddings_path, metrics_path, answers_path):
    index = LocalEmbeddingIndex.build(df, settings, embeddings_path)
    bundle = evaluate_pipeline(
        settings,
        index,
        settings.paths.eval_testset,
        metrics_path,
        answers_path,
    )
    metrics = dict(bundle.summary)
    require_metrics(metrics, metrics_path.stem)
    return metrics


def main(settings: Settings | None = None) -> CorruptionFlowResult:
    """Run corruption, degradation measurement, idempotent repair, and comparison."""
    settings = settings or load_settings()
    baseline_metrics, clean_df, baseline_quality, baseline_freshness = _require_baseline(
        settings
    )

    corrupted_df = corrupt_clean_dataframe(clean_df.copy(deep=True), settings.paths.corruption_log)
    require_clean_dataframe(corrupted_df, "corruption")
    save_dataframe(
        corrupted_df,
        settings.paths.corrupted_clean_csv,
        settings.paths.corrupted_clean_json,
    )
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_df,
        settings,
        settings.paths.corrupted_freshness_report,
    )
    if corrupted_quality.get("success") is True:
        LOGGER.warning("Corrupted data unexpectedly passed the quality gate.")
    else:
        LOGGER.info("Corrupted data was correctly detected by the quality gate.")
    corrupted_metrics = _evaluate_state(
        settings,
        corrupted_df,
        settings.paths.corrupted_embeddings_json,
        settings.paths.corrupted_metrics,
        settings.paths.corrupted_answers,
    )

    if not settings.paths.raw_records_json.is_file():
        raise RuntimeError("Trusted raw records are missing; cannot perform idempotent repair.")
    repaired_records = load_raw_records(settings.paths.raw_records_json)
    if not repaired_records:
        raise RuntimeError("Trusted raw snapshot contains no records; repair was aborted.")
    repaired_df = build_clean_dataframe(repaired_records, now_utc())
    require_clean_dataframe(repaired_df, "repair")
    save_dataframe(
        repaired_df,
        settings.paths.repaired_clean_csv,
        settings.paths.repaired_clean_json,
    )
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = build_freshness_report(
        repaired_df,
        settings,
        settings.paths.repaired_freshness_report,
    )
    require_quality_success(repaired_quality, "repaired")
    repaired_metrics = _evaluate_state(
        settings,
        repaired_df,
        settings.paths.repaired_embeddings_json,
        settings.paths.repaired_metrics,
        settings.paths.repaired_answers,
    )

    baseline_for_report = dict(baseline_metrics)
    baseline_for_report["quality_success"] = baseline_quality.get("success", False)
    baseline_for_report["freshness_success"] = baseline_freshness.get("is_fresh", False)
    baseline_for_report["stale_rows"] = baseline_freshness.get("stale_rows", 0)
    baseline_for_report["total_rows"] = baseline_freshness.get("total_rows", 0)
    generate_corruption_report(
        settings.paths.comparison_report,
        baseline_for_report,
        corrupted_metrics,
        repaired_metrics,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
    )

    require_artifacts(
        [
            settings.paths.corruption_log,
            settings.paths.corrupted_clean_csv,
            settings.paths.corrupted_clean_json,
            settings.paths.corrupted_embeddings_json,
            settings.paths.corrupted_metrics,
            settings.paths.corrupted_answers,
            settings.paths.corrupted_quality_report,
            settings.paths.corrupted_freshness_report,
            settings.paths.repaired_clean_csv,
            settings.paths.repaired_clean_json,
            settings.paths.repaired_embeddings_json,
            settings.paths.repaired_metrics,
            settings.paths.repaired_answers,
            settings.paths.repaired_quality_report,
            settings.paths.repaired_freshness_report,
            settings.paths.comparison_report,
        ],
        "corruption and repair pipeline",
    )
    print("State       Hit Rate   Token F1")
    print(
        f"Baseline    {baseline_metrics['retrieval_hit_rate']:.3f}      "
        f"{baseline_metrics['mean_token_f1']:.3f}"
    )
    print(
        f"Corrupted   {corrupted_metrics['retrieval_hit_rate']:.3f}      "
        f"{corrupted_metrics['mean_token_f1']:.3f}"
    )
    print(
        f"Repaired    {repaired_metrics['retrieval_hit_rate']:.3f}      "
        f"{repaired_metrics['mean_token_f1']:.3f}"
    )
    return CorruptionFlowResult(
        baseline_metrics,
        corrupted_metrics,
        repaired_metrics,
        corrupted_quality,
        repaired_quality,
    )
