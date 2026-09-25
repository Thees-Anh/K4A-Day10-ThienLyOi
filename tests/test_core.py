from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.config import load_settings, normalized_provider, require_llm_credentials
from core.utils import read_json, write_json


CONFIG_ENV_KEYS = (
    "BASELINE_COLLECTION_NAME",
    "CORRUPTED_COLLECTION_NAME",
    "EMBEDDING_MODEL",
    "FRESHNESS_THRESHOLD_DAYS",
    "GOOGLE_API_KEY",
    "LLM_MODEL",
    "LLM_PROVIDER",
    "MAX_RESULTS",
    "REFRESH_SOURCE",
    "REFRESH_TEST_SET",
    "REPAIRED_COLLECTION_NAME",
    "SOURCE_API",
    "SOURCE_FILTER",
    "SOURCE_QUERY",
    "TOP_K",
)


@pytest.fixture(autouse=True)
def clear_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_settings_builds_paths_and_directories(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)

    assert settings.source_api == "https://api.crossref.org/works"
    assert settings.max_results == 24
    assert settings.paths.project_dir == tmp_path.resolve()
    assert settings.paths.clean_csv == tmp_path / "data" / "clean" / "papers_clean.csv"
    assert settings.paths.comparison_report.parent.is_dir()
    assert settings.paths.chroma_dir.is_dir()


def test_project_dotenv_is_overridden_by_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=mock\nMAX_RESULTS=12\nREFRESH_SOURCE=yes\nSOURCE_FILTER=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAX_RESULTS", "30")

    settings = load_settings(tmp_path)

    assert settings.llm_provider == "mock"
    assert settings.max_results == 30
    assert settings.refresh_source is True
    assert settings.source_filter.startswith("from-pub-date:")


@pytest.mark.parametrize("name", ["MAX_RESULTS", "TOP_K", "FRESHNESS_THRESHOLD_DAYS"])
def test_positive_integer_configuration_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValueError, match=name):
        load_settings(tmp_path)


def test_boolean_configuration_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRESH_SOURCE", "sometimes")

    with pytest.raises(ValueError, match="REFRESH_SOURCE"):
        load_settings(tmp_path)


def test_provider_alias_and_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "google-genai")
    settings = load_settings(tmp_path)

    assert normalized_provider(settings) == "gemini"
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        require_llm_credentials(settings)

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    require_llm_credentials(load_settings(tmp_path))


def test_unknown_provider_fails_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "unknown-provider")

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        load_settings(tmp_path)


def test_json_helpers_support_pipeline_values(tmp_path: Path) -> None:
    @dataclass
    class Payload:
        output: Path
        created_at: datetime

    output = Path("data/output.json")
    path = tmp_path / "nested" / "payload.json"
    write_json(path, Payload(output, datetime(2026, 1, 2, tzinfo=UTC)))

    assert read_json(path) == {
        "output": str(output),
        "created_at": "2026-01-02T00:00:00+00:00",
    }
