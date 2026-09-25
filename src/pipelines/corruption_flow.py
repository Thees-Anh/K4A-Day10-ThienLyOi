from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import load_settings
from core.utils import read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex


def _build_or_load_index(
    dataframe,
    settings,
    manifest_path: Path,
) -> LocalEmbeddingIndex:
    try:
        return LocalEmbeddingIndex.build(
            dataframe,
            settings,
            embeddings_output_path=manifest_path,
        )
    except Exception as build_error:
        if not manifest_path.exists():
            raise RuntimeError(
                f"Unable to build embedding index at {manifest_path}."
            ) from build_error
        try:
            index = LocalEmbeddingIndex.load(settings, embeddings_path=manifest_path)
            if index.collection.count() >= len(dataframe):
                return index
        except Exception:
            pass
        raise RuntimeError(f"Unable to build or load index at {manifest_path}.") from build_error


def _save_dataframe(dataframe, csv_path: Path, json_path: Path) -> None:
    write_csv(dataframe, csv_path)
    write_json(json_path, dataframe.to_dict(orient="records"))


def _load_baseline_metrics(settings) -> dict[str, Any]:
    if not settings.paths.baseline_metrics.exists():
        raise FileNotFoundError(
            "Baseline metrics chưa tồn tại. Hãy chạy python script/run_phase1.py trước."
        )
    return read_json(settings.paths.baseline_metrics)


def main() -> None:
    """Run corruption, evaluation, repair, and three-state comparison."""

    settings = load_settings()
    run_at = datetime.now(timezone.utc)
    baseline_metrics = _load_baseline_metrics(settings)

    baseline_path = settings.paths.clean_json
    if not baseline_path.exists():
        raise FileNotFoundError(
            f"Clean baseline dataset chưa tồn tại: {baseline_path}. Chạy phase1 trước."
        )
    baseline_df = pd.read_json(baseline_path)
    baseline_quality = run_data_quality_checks(baseline_df, settings, "baseline")
    baseline_freshness = baseline_quality["freshness"]

    print("[1/6] Đang tạo dữ liệu bị nhiễm 6 lỗi...")
    corrupted_df = corrupt_clean_dataframe(baseline_df, settings.paths.corruption_log)
    _save_dataframe(
        corrupted_df,
        settings.paths.corrupted_clean_csv,
        settings.paths.corrupted_clean_json,
    )

    print("[2/6] Đang xây dựng index và đánh giá corrupted baseline...")
    corrupted_index = _build_or_load_index(
        corrupted_df,
        settings,
        settings.paths.corrupted_embeddings_json,
    )
    corrupted_evaluation = evaluate_pipeline(
        settings=settings,
        index=corrupted_index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.corrupted_metrics,
        answers_output_path=settings.paths.corrupted_answers,
    )
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = corrupted_quality["freshness"]

    print("[3/6] Đang phục hồi dữ liệu từ raw snapshot...")
    raw_records = load_raw_records(settings.paths.raw_records_json)
    repaired_df = build_clean_dataframe(raw_records, run_at)
    _save_dataframe(
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
