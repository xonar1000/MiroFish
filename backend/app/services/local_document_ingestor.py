"""Local source-document ingestion for SQLite.

This stage stores normalized source chunks and ontology metadata. It deliberately
does not claim semantic entity/relation extraction; that requires an LLM-backed
extractor and a separately validated mapping stage.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

try:
    from .local_graph_adapter import LocalGraphAdapter
except ImportError:
    from local_graph_adapter import LocalGraphAdapter


class LocalDocumentIngestor:
    def __init__(self, adapter: LocalGraphAdapter | None = None):
        self.adapter = adapter or LocalGraphAdapter()

    @staticmethod
    def split_text(text: str, chunk_size: int = 500,
                   chunk_overlap: int = 50) -> list[str]:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size - 1")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []
        step = chunk_size - chunk_overlap
        return [normalized[i:i + chunk_size] for i in range(0, len(normalized), step)]

    def ingest_text(self, text: str, ontology: dict[str, Any],
                    graph_name: str = "MiroFish Local Graph",
                    chunk_size: int = 500, chunk_overlap: int = 50,
                    graph_id: str | None = None) -> dict[str, Any]:
        if not isinstance(ontology, dict):
            raise ValueError("ontology must be an object")
        chunks = self.split_text(text, chunk_size, chunk_overlap)
        if not chunks:
            raise ValueError("source text is empty")
        graph_id = self.adapter.create_graph(
            graph_name, graph_id=graph_id,
            metadata={
                "backend": "sqlite",
                "ontology": ontology,
                "ingestion": "source_chunks_only",
                "semantic_extraction_complete": False,
            },
        )
        rows = []
        for index, content in enumerate(chunks, 1):
            rows.append({
                "chunk_id": hashlib.sha256(
                    f"{graph_id}:{index}:{content}".encode("utf-8")
                ).hexdigest(),
                "document_index": 1,
                "chunk_index": index,
                "content": content,
                "metadata": {"source": "inline_text"},
            })
        self.adapter.store.save_document_chunks(graph_id, rows)
        return {
            "graph_id": graph_id,
            "chunks_processed": len(rows),
            "node_count": 0,
            "edge_count": 0,
            "entity_types": [],
            "semantic_extraction_complete": False,
            "status": "source_chunks_stored",
        }

    def get_source_chunks(self, graph_id: str) -> list[dict[str, Any]]:
        return self.adapter.store.list_document_chunks(graph_id)
