from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


DEFAULT_SOURCE_API = "https://api.crossref.org/works"
DEFAULT_SOURCE_QUERY = "agentic retrieval augmented generation large language model"
SUPPORTED_LLM_PROVIDERS = frozenset(
    {"anthropic", "custom", "gemini", "mock", "ollama", "openai", "openrouter"}
)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


@dataclass(frozen=True)
class Paths:
    project_dir: Path
    workspace_dir: Path
    raw_api_response: Path
    raw_records_json: Path
    clean_csv: Path
    clean_json: Path
    chroma_dir: Path
    embeddings_json: Path
    corrupted_clean_csv: Path
    corrupted_clean_json: Path
    corrupted_embeddings_json: Path
    repaired_clean_csv: Path
    repaired_clean_json: Path
    repaired_embeddings_json: Path
    eval_testset: Path
    baseline_metrics: Path
    baseline_answers: Path
    demo_answers: Path
    quality_dir: Path
    gx_dir: Path
    baseline_quality_report: Path
    corrupted_quality_report: Path
    repaired_quality_report: Path
    freshness_report: Path
    corrupted_freshness_report: Path
    repaired_freshness_report: Path
    baseline_report: Path
    corruption_log: Path
    corrupted_metrics: Path
    corrupted_answers: Path
    repaired_metrics: Path
    repaired_answers: Path
    comparison_report: Path

    def create_artifact_directories(self) -> None:
        """Create every directory written by the two data pipelines."""
        directories = {
            self.raw_api_response.parent,
            self.clean_csv.parent,
            self.chroma_dir,
            self.embeddings_json.parent,
            self.eval_testset.parent,
            self.baseline_metrics.parent,
            self.quality_dir,
            self.gx_dir,
            self.baseline_report.parent,
        }
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    model_name: str
    google_api_key: str | None
    openai_api_key: str | None
    anthropic_api_key: str | None
    openrouter_api_key: str | None
    openrouter_base_url: str
    ollama_base_url: str
    custom_llm_api_key: str | None
    custom_llm_base_url: str | None
    embedding_model: str
    baseline_collection_name: str
    corrupted_collection_name: str
    repaired_collection_name: str
    source_api: str
    source_query: str
    source_filter: str
    max_results: int
    top_k: int
    freshness_threshold_days: int
    refresh_source: bool
    refresh_test_set: bool
    paths: Paths


def _read_environment(root: Path) -> dict[str, str]:
    """Load workspace/project dotenv files, with process variables taking precedence."""
    workspace_values = dotenv_values(root.parent / ".env")
    project_values = dotenv_values(root / ".env")
    combined = {**workspace_values, **project_values, **os.environ}
    return {key: str(value).strip() for key, value in combined.items() if value is not None}


def _optional_env(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _env_or_default(env: Mapping[str, str], name: str, default: str) -> str:
    return _optional_env(env, name) or default


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw_value = env.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw_value!r}.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}.")
    return value


def _boolean(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw_value = env.get(name, str(default)).strip().lower()
    if raw_value in _TRUE_VALUES:
        return True
    if raw_value in _FALSE_VALUES:
        return False
    expected = ", ".join(sorted(_TRUE_VALUES | _FALSE_VALUES))
    raise ValueError(f"{name} must be one of: {expected}; got {raw_value!r}.")


def load_settings(project_dir: Path | None = None) -> Settings:
    root = (project_dir or Path(__file__).resolve().parents[2]).resolve()
    workspace = root.parent
    env = _read_environment(root)
    freshness_threshold_days = _positive_int(env, "FRESHNESS_THRESHOLD_DAYS", 180)
    source_from_date = (
        datetime.now(UTC).date() - timedelta(days=freshness_threshold_days)
    ).isoformat()

    data_dir = root / "data"
    paths = Paths(
        project_dir=root,
        workspace_dir=workspace,
        raw_api_response=data_dir / "raw" / "crossref_response.json",
        raw_records_json=data_dir / "raw" / "crossref_records.json",
        clean_csv=data_dir / "clean" / "papers_clean.csv",
        clean_json=data_dir / "clean" / "papers_clean.json",
        chroma_dir=data_dir / "chroma",
        embeddings_json=data_dir / "embeddings" / "papers_embeddings.json",
        corrupted_clean_csv=data_dir / "clean" / "papers_clean_corrupted.csv",
        corrupted_clean_json=data_dir / "clean" / "papers_clean_corrupted.json",
        corrupted_embeddings_json=data_dir / "embeddings" / "papers_embeddings_corrupted.json",
        repaired_clean_csv=data_dir / "clean" / "papers_clean_repaired.csv",
        repaired_clean_json=data_dir / "clean" / "papers_clean_repaired.json",
        repaired_embeddings_json=data_dir / "embeddings" / "papers_embeddings_repaired.json",
        eval_testset=data_dir / "eval" / "test_set.json",
        baseline_metrics=data_dir / "results" / "baseline_metrics.json",
        baseline_answers=data_dir / "results" / "baseline_answers.json",
        demo_answers=data_dir / "results" / "agent_demo_answers.json",
        quality_dir=data_dir / "quality",
        gx_dir=data_dir / "quality" / "gx",
        baseline_quality_report=data_dir / "quality" / "baseline_quality_report.json",
        corrupted_quality_report=data_dir / "quality" / "corrupted_quality_report.json",
        repaired_quality_report=data_dir / "quality" / "repaired_quality_report.json",
        freshness_report=data_dir / "quality" / "freshness_report.json",
        corrupted_freshness_report=data_dir / "quality" / "corrupted_freshness_report.json",
        repaired_freshness_report=data_dir / "quality" / "repaired_freshness_report.json",
        baseline_report=data_dir / "reports" / "phase1_report.md",
        corruption_log=data_dir / "results" / "corruption_log.json",
        corrupted_metrics=data_dir / "results" / "corrupted_metrics.json",
        corrupted_answers=data_dir / "results" / "corrupted_answers.json",
        repaired_metrics=data_dir / "results" / "repaired_metrics.json",
        repaired_answers=data_dir / "results" / "repaired_answers.json",
        comparison_report=data_dir / "reports" / "corruption_report.md",
    )

    settings = Settings(
        llm_provider=_env_or_default(env, "LLM_PROVIDER", "gemini"),
        model_name=_env_or_default(env, "LLM_MODEL", "gemini-2.5-flash"),
        google_api_key=_optional_env(env, "GOOGLE_API_KEY"),
        openai_api_key=_optional_env(env, "OPENAI_API_KEY"),
        anthropic_api_key=_optional_env(env, "ANTHROPIC_API_KEY"),
        openrouter_api_key=_optional_env(env, "OPENROUTER_API_KEY"),
        openrouter_base_url=_env_or_default(
            env, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        ollama_base_url=_env_or_default(env, "OLLAMA_BASE_URL", "http://localhost:11434"),
        custom_llm_api_key=_optional_env(env, "CUSTOM_LLM_API_KEY"),
        custom_llm_base_url=_optional_env(env, "CUSTOM_LLM_BASE_URL"),
        embedding_model=_env_or_default(
            env,
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        baseline_collection_name=_env_or_default(
            env, "BASELINE_COLLECTION_NAME", "papers-baseline"
        ),
        corrupted_collection_name=_env_or_default(
            env, "CORRUPTED_COLLECTION_NAME", "papers-corrupted"
        ),
        repaired_collection_name=_env_or_default(
            env, "REPAIRED_COLLECTION_NAME", "papers-repaired"
        ),
        source_api=_env_or_default(env, "SOURCE_API", DEFAULT_SOURCE_API),
        source_query=_env_or_default(env, "SOURCE_QUERY", DEFAULT_SOURCE_QUERY),
        source_filter=_env_or_default(
            env,
            "SOURCE_FILTER", f"from-pub-date:{source_from_date},has-abstract:true"
        ),
        max_results=_positive_int(env, "MAX_RESULTS", 24),
        top_k=_positive_int(env, "TOP_K", 4),
        freshness_threshold_days=freshness_threshold_days,
        refresh_source=_boolean(env, "REFRESH_SOURCE"),
        refresh_test_set=_boolean(env, "REFRESH_TEST_SET"),
        paths=paths,
    )
    normalized_provider(settings)
    settings.paths.create_artifact_directories()
    return settings


def normalized_provider(settings: Settings) -> str:
    provider = (
        settings.llm_provider.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    )
    aliases = {
        "anthorpic": "anthropic",
        "customllm": "custom",
        "google": "gemini",
        "googlegenai": "gemini",
        "googlegenerativeai": "gemini",
    }
    provider = aliases.get(provider, provider)
    if provider not in SUPPORTED_LLM_PROVIDERS:
        expected = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
        raise ValueError(f"Unsupported LLM_PROVIDER {settings.llm_provider!r}. Expected: {expected}.")
    return provider


def require_llm_credentials(settings: Settings) -> None:
    provider = normalized_provider(settings)
    if provider == "gemini":
        if settings.google_api_key:
            return
        raise RuntimeError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini.")
    if provider == "openai":
        if settings.openai_api_key:
            return
        raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")
    if provider == "anthropic":
        if settings.anthropic_api_key:
            return
        raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic.")
    if provider == "openrouter":
        if settings.openrouter_api_key:
            return
        raise RuntimeError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter.")
    if provider in {"mock", "ollama"}:
        return
    if provider == "custom":
        if settings.custom_llm_base_url:
            return
        raise RuntimeError("CUSTOM_LLM_BASE_URL is required when LLM_PROVIDER=custom.")
    raise AssertionError(f"Unhandled normalized provider: {provider}")
