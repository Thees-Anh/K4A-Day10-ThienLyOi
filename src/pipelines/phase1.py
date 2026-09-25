from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from core.config import load_settings
from core.utils import read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set, load_or_create_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex


def _source_summary(settings, records: list[Any], run_at: datetime) -> dict[str, Any]:
    return {
        "source": settings.source_api,
        "mode": "live_api_with_offline_fallback" if settings.refresh_source else "offline_snapshot",
        "query": settings.source_query,
        "filter": settings.source_filter,
        "raw_records": len(records),
        "max_results": settings.max_results,
        "run_at": run_at.isoformat(),
    }


def _build_or_load_index(df, settings) -> LocalEmbeddingIndex:
    """Build a fresh baseline index, reusing a valid local index on model failure."""

    try:
        return LocalEmbeddingIndex.build(
            df,
            settings,
            embeddings_output_path=settings.paths.embeddings_json,
        )
    except Exception as build_error:
        manifest_path = settings.paths.embeddings_json
        if not manifest_path.exists():
            raise RuntimeError(
                "Unable to build the embedding index and no local manifest is available."
            ) from build_error
        try:
            index = LocalEmbeddingIndex.load(settings, embeddings_path=manifest_path)
            if index.collection.count() >= len(df):
                return index
        except Exception:
            pass
        raise RuntimeError("Unable to build or load the baseline embedding index.") from build_error


def _run_optional_agent_demo(settings, index: LocalEmbeddingIndex) -> None:
    """Run a small agent demo only when explicitly requested by the operator."""

    if os.getenv("RUN_AGENT_DEMO", "").lower() not in {"1", "true", "yes"}:
        return

    from retrieval.agent import build_agent, run_agent_question

    test_set = read_json(settings.paths.eval_testset)
    questions = [item["question"] for item in test_set[:3] if isinstance(item, dict)]
    agent = build_agent(settings, index)
    answers = [
        {"question": question, "answer": run_agent_question(agent, question)}
        for question in questions
    ]
    write_json(settings.paths.demo_answers, answers)


def main() -> None:
    """Run the complete baseline data, quality, vector, and evaluation flow."""

    settings = load_settings()
    run_at = datetime.now(timezone.utc)

    print("[1/8] Đang lấy dữ liệu Crossref (offline snapshot hoặc live API)...")
    records = fetch_source_records(settings)
    if not records:
        raise RuntimeError("Không tải được bản ghi Crossref hợp lệ.")
    source_summary = _source_summary(settings, records, run_at)

    print("[2/8] Đang làm sạch dữ liệu và tính age_days...")
    dataframe = build_clean_dataframe(records, run_at)
    if dataframe.empty:
        raise RuntimeError("Dataframe sạch không có bản ghi hợp lệ.")
    write_csv(dataframe, settings.paths.clean_csv)
    write_json(settings.paths.clean_json, dataframe.to_dict(orient="records"))

    print("[3/8] Đang chạy Great Expectations quality gate...")
    quality = run_data_quality_checks(dataframe, settings, "baseline")
    freshness = quality["freshness"]
    if not quality["success"]:
        raise RuntimeError(
            "Data Quality Gate thất bại; baseline pipeline dừng trước khi đưa dữ liệu vào vector store."
        )

    print("[4/8] Đang tạo hoặc tải evaluation test set...")
    if settings.refresh_test_set:
        build_test_set(dataframe, settings.paths.eval_testset)
    else:
        load_or_create_test_set(dataframe, settings.paths.eval_testset)

    print("[5/8] Đang tạo embedding và ChromaDB index...")
    index = _build_or_load_index(dataframe, settings)

    print("[6/8] Đang đánh giá retrieval trên test set...")
    evaluation = evaluate_pipeline(
        settings=settings,
        index=index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=settings.paths.baseline_metrics,
        answers_output_path=settings.paths.baseline_answers,
    )

    print("[7/8] Đang tạo báo cáo Markdown...")
    generate_phase1_report(
        settings.paths.baseline_report,
        source_summary,
        evaluation.summary,
        quality,
        freshness,
    )

    print("[8/8] Đang chạy agent demo tùy chọn...")
    try:
        _run_optional_agent_demo(settings, index)
    except Exception as exc:
        # Agent demo is optional; a provider failure must not invalidate the
        # reproducible baseline metrics already written to disk.
        print(f"Agent demo bị bỏ qua: {exc}")

    print(
        "Tín hiệu hoàn thành: Baseline pipeline thành công "
        f"({len(dataframe)} tài liệu, quality={quality['success']}, "
        f"retrieval_hit_rate={evaluation.summary['retrieval_hit_rate']:.4f})"
    )
