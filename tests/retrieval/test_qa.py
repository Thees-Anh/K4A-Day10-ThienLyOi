from __future__ import annotations

from retrieval.index import SearchResult
from retrieval.qa import _extract_answer


def result() -> SearchResult:
    return SearchResult(
        paper_id="10.1000/rag-1",
        title="Reliable RAG",
        score=1.0,
        content="Document content",
        metadata={
            "authors_joined": "Ada Nguyen",
            "published": "2026-01-10",
            "categories_joined": "Artificial Intelligence",
            "summary": "First sentence. Second sentence.",
        },
    )


def test_extracts_structured_answers() -> None:
    top_result = result()

    assert _extract_answer("Who authored this paper?", top_result) == "Ada Nguyen"
    assert _extract_answer("When was it published?", top_result) == "2026-01-10"
    assert _extract_answer("What categories cover it?", top_result) == "Artificial Intelligence"
    assert _extract_answer("Summarize this paper", top_result) == "First sentence."
