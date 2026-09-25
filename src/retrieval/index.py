from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
import pandas as pd

from core.config import Settings
from core.utils import read_json, safe_slug, write_json
from retrieval.embeddings import MiniLMEmbeddings


@dataclass(frozen=True)
class SearchResult:
    paper_id: str
    title: str
    score: float
    content: str
    metadata: dict[str, Any]


class LocalEmbeddingIndex:
    def __init__(
        self,
        settings: Settings,
        collection_name: str,
        documents: list[dict[str, Any]] | None = None,
        persist_path: Path | str | None = None,
    ):
        self.settings = settings
        self.collection_name = collection_name
        self.persist_path = Path(persist_path or settings.paths.chroma_dir).resolve()
        self.embedding_backend = "chroma"
        self.embedding_model = MiniLMEmbeddings(settings.embedding_model)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
        )
        self._set_documents(documents or [])

    def _set_documents(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.documents_by_paper_id = {
            document["paper_id"].lower(): document for document in documents
        }
        self.documents_by_title = {
            document["title"].lower(): document for document in documents
        }

    @staticmethod
    def _build_documents(df: pd.DataFrame) -> list[dict[str, Any]]:
        required_columns = {
            "paper_id",
            "title",
            "text_for_embedding",
            "published",
            "authors_joined",
            "categories_joined",
            "summary",
            "abs_url",
            "pdf_url",
        }
        missing_columns = sorted(required_columns.difference(df.columns))
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise ValueError(f"Clean dataframe is missing required columns: {missing}")
        if df.empty:
            raise ValueError("Cannot build an embedding index from an empty dataframe.")

        documents: list[dict[str, Any]] = []
        for index, row in enumerate(df.to_dict(orient="records")):
            paper_id = str(row["paper_id"])
            title = str(row["title"])
            content = str(row["text_for_embedding"])
            if not paper_id.strip() or not title.strip() or not content.strip():
                raise ValueError(
                    f"Record {index} has an empty paper_id, title, or text_for_embedding."
                )
            documents.append(
                {
                    "record_id": f"{paper_id}::{index}",
                    "paper_id": paper_id,
                    "title": title,
                    "content": content,
                    "metadata": {
                        "paper_id": paper_id,
                        "title": title,
                        "published": str(row["published"]),
                        "authors_joined": str(row["authors_joined"]),
                        "categories_joined": str(row["categories_joined"]),
                        "summary": str(row["summary"]),
                        "abs_url": str(row["abs_url"]),
                        "pdf_url": str(row["pdf_url"]),
                    },
                }
            )
        return documents

    @staticmethod
    def _derive_collection_name(
        settings: Settings,
        embeddings_output_path: Path | str | None,
    ) -> str:
        if embeddings_output_path is None:
            return settings.baseline_collection_name

        output_path = Path(embeddings_output_path)
        name_map = {
            settings.paths.embeddings_json.resolve(): settings.baseline_collection_name,
            settings.paths.corrupted_embeddings_json.resolve(): settings.corrupted_collection_name,
            settings.paths.repaired_embeddings_json.resolve(): settings.repaired_collection_name,
        }
        resolved_path = output_path.resolve()
        if resolved_path in name_map:
            return name_map[resolved_path]
        return safe_slug(output_path.stem)

    def _default_manifest_path(self) -> Path:
        known_paths = {
            self.settings.baseline_collection_name: self.settings.paths.embeddings_json,
            self.settings.corrupted_collection_name: self.settings.paths.corrupted_embeddings_json,
            self.settings.repaired_collection_name: self.settings.paths.repaired_embeddings_json,
        }
        if self.collection_name in known_paths:
            return known_paths[self.collection_name]
        filename = f"{safe_slug(self.collection_name)}.json"
        return self.settings.paths.chroma_dir.parent / "embeddings" / filename

    def _write_manifest(self, manifest_path: Path) -> None:
        write_json(
            manifest_path,
            {
                "backend": self.embedding_backend,
                "embedding_model": self.settings.embedding_model,
                "persist_path": str(self.persist_path),
                "collection_name": self.collection_name,
                "documents": self.documents,
            },
        )

    def _build_from_dataframe(
        self,
        df: pd.DataFrame,
        manifest_path: Path,
    ) -> "LocalEmbeddingIndex":
        documents = self._build_documents(df)
        embeddings = self.embedding_model.embed_documents(
            [document["content"] for document in documents]
        )

        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass

        collection = self.client.create_collection(
            name=self.collection_name,
            configuration={"hnsw": {"space": "cosine"}},
        )
        collection.add(
            ids=[document["record_id"] for document in documents],
            embeddings=embeddings,
            documents=[document["content"] for document in documents],
            metadatas=[document["metadata"] for document in documents],
        )

        self.collection = collection
        self._set_documents(documents)
        self._write_manifest(manifest_path)
        return self

    @classmethod
    def build(
        cls,
        df: pd.DataFrame,
        settings: Settings,
        embeddings_output_path: Path | str | None = None,
    ) -> "LocalEmbeddingIndex":
        collection_name = cls._derive_collection_name(settings, embeddings_output_path)
        index = cls(settings=settings, collection_name=collection_name)
        manifest_path = embeddings_output_path or index._default_manifest_path()
        return index._build_from_dataframe(df, Path(manifest_path))

    @classmethod
    def load(
        cls,
        settings: Settings,
        embeddings_path: Path | str | None = None,
    ) -> "LocalEmbeddingIndex":
        payload = read_json(Path(embeddings_path or settings.paths.embeddings_json))
        return cls(
            settings=settings,
            collection_name=payload["collection_name"],
            documents=payload["documents"],
            persist_path=Path(payload["persist_path"]),
        )

    def build_from_clean(self, clean_path: Path | str | None = None) -> "LocalEmbeddingIndex":
        """Load the configured clean JSON file and replace this collection."""

        path = Path(clean_path) if clean_path is not None else self.settings.paths.clean_json
        if not path.exists():
            raise FileNotFoundError(f"Clean dataset not found: {path}")
        dataframe = pd.read_json(path)
        return self._build_from_dataframe(dataframe, self._default_manifest_path())

    def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        requested_results = top_k if top_k is not None else self.settings.top_k
        if requested_results <= 0:
            raise ValueError("top_k must be greater than zero.")
        if not query.strip():
            raise ValueError("query must not be empty.")

        document_count = self.collection.count()
        if document_count == 0:
            return []

        query_embedding = self.embedding_model.embed_query(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(requested_results, document_count),
            include=["documents", "metadatas", "distances"],
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        scored: list[SearchResult] = []
        for record_id, content, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
            strict=False,
        ):
            if not record_id or not metadata or not content:
                continue
            similarity = max(0.0, min(1.0, 1.0 - float(distance or 0.0)))
            scored.append(
                SearchResult(
                    paper_id=str(metadata["paper_id"]),
                    title=str(metadata["title"]),
                    score=similarity,
                    content=str(content),
                    metadata=dict(metadata),
                )
            )
        return scored

    def semantic_search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Public smoke-test API for vector retrieval."""

        return self.search(query, top_k=top_k)

    def lookup(self, value: str) -> dict[str, Any] | None:
        needle = value.strip().lower()
        if needle in self.documents_by_paper_id:
            return self.documents_by_paper_id[needle]
        if needle in self.documents_by_title:
            return self.documents_by_title[needle]
        return None
