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


def _require_baseline(settings: Settings) -> tuple[dict[str, Any], Any]:
    try:
        baseline_metrics = load_mapping(settings.paths.baseline_metrics, "baseline metrics")
        clean_df = load_dataframe(settings.paths.clean_json, "baseline clean data")
    except FileNotFoundError as exc:
        raise RuntimeError("Baseline artifacts are missing; run script/run_phase1.py first.") from exc
    if not settings.paths.eval_testset.is_file():
        raise RuntimeError("Evaluation test set is missing; run script/run_phase1.py first.")
    require_metrics(baseline_metrics, "baseline")
    return baseline_metrics, clean_df


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
    baseline_metrics, clean_df = _require_baseline(settings)

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

    print("[4/6] Đang xây dựng index và đánh giá repaired dataset...")
    repaired_index = _build_or_load_index(
        repaired_df,
        settings,
        settings.paths.repaired_embeddings_json,
    )
    repaired_evaluation = evaluate_pipeline(
        settings=settings,
        index=repaired_index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.repaired_metrics,
        answers_output_path=settings.paths.repaired_answers,
    )
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = repaired_quality["freshness"]

    print("[5/6] Đang sinh báo cáo đối chiếu...")
    baseline_for_report = dict(baseline_metrics)
    baseline_for_report["quality_success"] = baseline_quality["success"]
    baseline_for_report["freshness_success"] = baseline_freshness["is_fresh"]
    baseline_for_report["stale_rows"] = baseline_freshness["stale_rows"]
    baseline_for_report["total_rows"] = baseline_freshness["total_rows"]
    generate_corruption_report(
        settings.paths.comparison_report,
        baseline_for_report,
        corrupted_evaluation.summary,
        repaired_evaluation.summary,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
    )

    print("[6/6] Hoàn tất corruption/repair flow.")
    print(
        "Tín hiệu hoàn thành: "
        f"corrupted_rows={len(corrupted_df)}, "
        f"repaired_rows={len(repaired_df)}, "
        f"corrupted_hit_rate={corrupted_evaluation.summary['retrieval_hit_rate']:.4f}, "
        f"repaired_hit_rate={repaired_evaluation.summary['retrieval_hit_rate']:.4f}"
    )
