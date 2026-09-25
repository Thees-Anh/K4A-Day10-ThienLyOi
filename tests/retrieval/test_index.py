from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from core.config import load_settings
from retrieval.index import LocalEmbeddingIndex


def sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "paper_id": "10.1000/rag-1",
                "title": "Reliable Retrieval Augmented Generation",
                "text_for_embedding": "A paper about reliable retrieval augmented generation.",
                "published": "2026-01-10",
                "authors_joined": "Ada Nguyen",
                "categories_joined": "Artificial Intelligence",
                "summary": "This paper studies reliable retrieval for grounded answers.",
            },
            {
                "paper_id": "10.1000/agent-2",
                "title": "Tool-Using Language Model Agents",
                "text_for_embedding": "A paper about language model agents that use tools.",
                "published": "2026-02-15",
                "authors_joined": "Minh Tran",
                "categories_joined": "Machine Learning",
                "summary": "This paper evaluates language model agents using external tools.",
            },
        ]
    )


def test_build_documents_accepts_optional_urls_and_normalizes_metadata() -> None:
    documents = LocalEmbeddingIndex._build_documents(sample_dataframe())

    assert len(documents) == 2
    assert documents[0]["paper_id"] == "10.1000/rag-1"
    assert documents[0]["metadata"]["abs_url"] == ""
    assert documents[0]["metadata"]["pdf_url"] == ""


def test_build_documents_reports_missing_schema() -> None:
    dataframe = sample_dataframe().drop(columns=["text_for_embedding", "summary"])

    with pytest.raises(ValueError, match="summary, text_for_embedding"):
        LocalEmbeddingIndex._build_documents(dataframe)


def test_build_documents_rejects_empty_dataframe() -> None:
    with pytest.raises(ValueError, match="empty dataframe"):
        LocalEmbeddingIndex._build_documents(sample_dataframe().iloc[0:0])


def test_build_documents_rejects_null_required_values() -> None:
    dataframe = sample_dataframe()
    dataframe.loc[0, "paper_id"] = None

    with pytest.raises(ValueError, match="null paper_id"):
        LocalEmbeddingIndex._build_documents(dataframe)


def test_build_search_and_portable_load(tmp_path, monkeypatch) -> None:
    class FakeMiniLMEmbeddings:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if "retrieval" in text else [0.0, 1.0] for text in texts]

        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0] if "retrieval" in text else [0.0, 1.0]

    monkeypatch.setattr("retrieval.index.MiniLMEmbeddings", FakeMiniLMEmbeddings)
    settings = load_settings(project_dir=tmp_path)
    settings = replace(settings, top_k=4)

    index = LocalEmbeddingIndex.build(sample_dataframe(), settings)
    results = index.search("retrieval", top_k=10)

    assert len(results) == 2
    assert results[0].paper_id == "10.1000/rag-1"
    assert index.lookup("Reliable Retrieval Augmented Generation") is not None

    loaded = LocalEmbeddingIndex.load(settings)
    assert loaded.persist_path == settings.paths.chroma_dir
    assert loaded.search("agents", top_k=1)[0].paper_id == "10.1000/agent-2"


def test_search_validates_query_and_top_k(tmp_path, monkeypatch) -> None:
    class FakeMiniLMEmbeddings:
        def __init__(self, model_name: str):
            pass

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0]

    monkeypatch.setattr("retrieval.index.MiniLMEmbeddings", FakeMiniLMEmbeddings)
    index = LocalEmbeddingIndex.build(sample_dataframe(), load_settings(project_dir=tmp_path))

    with pytest.raises(ValueError, match="must not be empty"):
        index.search(" ")
    with pytest.raises(ValueError, match="greater than zero"):
        index.search("retrieval", top_k=0)
