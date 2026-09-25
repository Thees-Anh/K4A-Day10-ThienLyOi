from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from core.config import load_settings
from core.utils import write_json, write_text


phase1 = importlib.import_module("pipelines.phase1")
corruption_flow = importlib.import_module("pipelines.corruption_flow")


def sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "paper_id": "10.1000/example",
                "title": "Example paper",
                "summary": "A sufficiently descriptive abstract for pipeline testing.",
                "published": "2026-01-01",
                "age_days": 10,
                "authors_joined": "Ada Lovelace",
                "categories_joined": "Computer Science",
                "text_for_embedding": "Example paper and its abstract.",
                "abs_url": "https://example.test/paper",
                "pdf_url": "https://example.test/paper.pdf",
            }
        ]
    )


def touch_json(path: Path, payload=None) -> None:
    write_json(path, {} if payload is None else payload)


def install_baseline_mocks(monkeypatch, settings, events, quality_success=True) -> None:
    clean_df = sample_dataframe()
    records = [object()]
    touch_json(settings.paths.raw_records_json, [{"paper_id": "raw"}])

    monkeypatch.setattr(
        phase1,
        "load_raw_records",
        lambda path: events.append("load_raw") or records,
    )
    monkeypatch.setattr(
        phase1,
        "build_clean_dataframe",
        lambda loaded, run_date: events.append("clean") or clean_df,
    )

    def quality(df, configured_settings, report_name):
        events.append("quality")
        touch_json(settings.paths.baseline_quality_report, {"success": quality_success})
        return {"success": quality_success}

    def freshness(df, configured_settings, report_path):
        events.append("freshness")
        touch_json(report_path, {"is_fresh": True})
        return {"is_fresh": True}

    def build_index(df, configured_settings, output_path):
        events.append("index")
        touch_json(output_path)
        return object()

    def build_test_set(df, output_path):
        events.append("testset")
        touch_json(output_path, [{"id": "q1"}])
        return [{"id": "q1"}]

    def evaluate(configured_settings, index, testset_path, metrics_path, answers_path):
        events.append("evaluate")
        metrics = {"retrieval_hit_rate": 1.0, "mean_token_f1": 0.9}
        touch_json(metrics_path, metrics)
        touch_json(answers_path, [])
        return SimpleNamespace(summary=metrics)

    def report(report_path, source, metrics, quality_result, freshness_result):
        events.append("report")
        write_text(report_path, "# Baseline\n")

    monkeypatch.setattr(phase1, "run_data_quality_checks", quality)
    monkeypatch.setattr(phase1, "build_freshness_report", freshness)
    monkeypatch.setattr(phase1.LocalEmbeddingIndex, "build", build_index)
    monkeypatch.setattr(phase1, "build_test_set", build_test_set)
    monkeypatch.setattr(phase1, "evaluate_pipeline", evaluate)
    monkeypatch.setattr(phase1, "generate_phase1_report", report)


def test_phase1_orchestrates_clean_pipeline_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(tmp_path)
    events: list[str] = []
    install_baseline_mocks(monkeypatch, settings, events)

    result = phase1.main(settings)

    assert events == [
        "load_raw",
        "clean",
        "quality",
        "freshness",
        "index",
        "testset",
        "evaluate",
        "report",
    ]
    assert result.metrics["retrieval_hit_rate"] == 1.0
    assert settings.paths.baseline_report.is_file()


def test_phase1_blocks_indexing_when_quality_gate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(tmp_path)
    events: list[str] = []
    install_baseline_mocks(monkeypatch, settings, events, quality_success=False)

    with pytest.raises(RuntimeError, match="quality gate failed"):
        phase1.main(settings)

    assert "index" not in events
    assert "evaluate" not in events


def test_corruption_flow_orchestrates_degradation_and_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(tmp_path)
    clean_df = sample_dataframe()
    events: list[str] = []
    touch_json(settings.paths.clean_json, clean_df.to_dict(orient="records"))
    touch_json(
        settings.paths.baseline_metrics,
        {"retrieval_hit_rate": 1.0, "mean_token_f1": 0.9},
    )
    touch_json(settings.paths.eval_testset, [{"id": "q1"}])
    touch_json(settings.paths.raw_records_json, [{"paper_id": "raw"}])
    touch_json(settings.paths.baseline_quality_report, {"success": True})
    touch_json(
        settings.paths.freshness_report,
        {"is_fresh": True, "stale_rows": 0, "total_rows": 1},
    )

    def corrupt(df, log_path):
        events.append("corrupt")
        touch_json(log_path, [{"type": "blank_summary"}])
        return clean_df.copy()

    def quality(df, configured_settings, report_name):
        events.append(f"quality:{report_name}")
        report_path = (
            settings.paths.corrupted_quality_report
            if report_name == "corrupted"
            else settings.paths.repaired_quality_report
        )
        success = report_name == "repaired"
        touch_json(report_path, {"success": success})
        return {"success": success}

    def freshness(df, configured_settings, report_path):
        state = "corrupted" if "corrupted" in report_path.name else "repaired"
        events.append(f"freshness:{state}")
        touch_json(report_path, {"is_fresh": state == "repaired"})
        return {"is_fresh": state == "repaired"}

    def build_index(df, configured_settings, output_path):
        state = "corrupted" if "corrupted" in output_path.name else "repaired"
        events.append(f"index:{state}")
        touch_json(output_path)
        return state

    def evaluate(configured_settings, index, testset_path, metrics_path, answers_path):
        state = "corrupted" if "corrupted" in metrics_path.name else "repaired"
        events.append(f"evaluate:{state}")
        metrics = {
            "retrieval_hit_rate": 0.2 if state == "corrupted" else 1.0,
            "mean_token_f1": 0.1 if state == "corrupted" else 0.9,
        }
        touch_json(metrics_path, metrics)
        touch_json(answers_path, [])
        return SimpleNamespace(summary=metrics)

    def load_raw(path):
        events.append("load_raw")
        return [object()]

    def clean(records, run_date):
        events.append("clean")
        return clean_df.copy()

    def report(report_path, *args):
        events.append("report")
        write_text(report_path, "# Comparison\n")

    monkeypatch.setattr(corruption_flow, "corrupt_clean_dataframe", corrupt)
    monkeypatch.setattr(corruption_flow, "run_data_quality_checks", quality)
    monkeypatch.setattr(corruption_flow, "build_freshness_report", freshness)
    monkeypatch.setattr(corruption_flow.LocalEmbeddingIndex, "build", build_index)
    monkeypatch.setattr(corruption_flow, "evaluate_pipeline", evaluate)
    monkeypatch.setattr(corruption_flow, "load_raw_records", load_raw)
    monkeypatch.setattr(corruption_flow, "build_clean_dataframe", clean)
    monkeypatch.setattr(corruption_flow, "generate_corruption_report", report)

    result = corruption_flow.main(settings)

    assert events == [
        "corrupt",
        "quality:corrupted",
        "freshness:corrupted",
        "index:corrupted",
        "evaluate:corrupted",
        "load_raw",
        "clean",
        "quality:repaired",
        "freshness:repaired",
        "index:repaired",
        "evaluate:repaired",
        "report",
    ]
    assert result.corrupted_metrics["retrieval_hit_rate"] == 0.2
    assert result.repaired_metrics == result.baseline_metrics
    assert settings.paths.comparison_report.is_file()

    first_run_events = events.copy()
    events.clear()
    second_result = corruption_flow.main(settings)

    assert events == first_run_events
    assert second_result == result
