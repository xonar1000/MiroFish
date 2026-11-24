"""LLM-backed semantic extraction into the local SQLite graph.

This service is deliberately opt-in: it requires a configured OpenAI-compatible
LLM endpoint. It does not claim that storing source chunks alone creates entities.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

try:
    from .local_graph_adapter import LocalGraphAdapter
except ImportError:
    from local_graph_adapter import LocalGraphAdapter


class LocalSemanticExtractor:
    """Extract ontology-constrained entities and relationships from stored chunks."""

    def __init__(self, adapter: LocalGraphAdapter | None = None, llm_client: Any = None):
        self.adapter = adapter or LocalGraphAdapter()
        if llm_client is None:
            try:
                from ..utils.llm_client import LLMClient
            except ImportError:
                from utils.llm_client import LLMClient
            llm_client = LLMClient()
        self.llm_client = llm_client

    @staticmethod
    def _key(value: str) -> str:
        return " ".join(value.casefold().split())

    @staticmethod
    def _validate_ontology(ontology: dict[str, Any]) -> tuple[set[str], set[str]]:
        if not isinstance(ontology, dict):
            raise ValueError("ontology must be an object")
        entity_types = {
            str(item.get("name", "")).strip()
            for item in ontology.get("entity_types", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        }
        edge_types = {
            str(item.get("name", "")).strip()
            for item in ontology.get("edge_types", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        }
        if not entity_types:
            raise ValueError("ontology must define at least one entity type")
        if not edge_types:
            raise ValueError("ontology must define at least one edge type")
        return entity_types, edge_types

    def _extract_chunk(self, content: str, ontology: dict[str, Any]) -> dict[str, Any]:
        schema = {
            "entities": [
                {"name": "exact entity name", "type": "one ontology entity type",
                 "summary": "short evidence-based description", "attributes": {}}
            ],
            "relationships": [
                {"source": "entity name", "target": "entity name",
                 "type": "one ontology edge type", "fact": "evidence-based relationship",
                 "attributes": {}}
            ],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract only explicitly supported entities and relationships from the source. "
                    "Use only the supplied ontology type names. Do not invent facts or entities. "
                    "Return one JSON object matching the requested keys; use empty arrays when none."
                ),
            },
            {
                "role": "user",
                "content": (
                    "ONTOLOGY:\n" + json.dumps(ontology, ensure_ascii=False) +
                    "\nOUTPUT SHAPE:\n" + json.dumps(schema, ensure_ascii=False) +
                    "\nSOURCE TEXT:\n" + content
                ),
            },
        ]
        result = self.llm_client.chat_json(
            messages=messages, temperature=0.0, max_tokens=None, max_attempts=2
        )
        if not isinstance(result, dict):
            raise ValueError("LLM extraction response must be a JSON object")
        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        if not isinstance(entities, list) or not isinstance(relationships, list):
            raise ValueError("LLM extraction must contain entity and relationship arrays")
        return {"entities": entities, "relationships": relationships}

    def extract_graph(self, graph_id: str, ontology: dict[str, Any]) -> dict[str, Any]:
        graph = self.adapter.get_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph not found: {graph_id}")
        entity_types, edge_types = self._validate_ontology(ontology)
        chunks = self.adapter.store.list_document_chunks(graph_id)
        if not chunks:
            raise ValueError("Graph has no stored source chunks")

        nodes_by_key: dict[str, dict[str, Any]] = {}
        for node in self.adapter.list_nodes(graph_id):
            nodes_by_key[self._key(node["name"])] = node

        pending_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        processed_chunks = 0
        for chunk in chunks:
            extracted = self._extract_chunk(chunk["content"], ontology)
            chunk_index = int(chunk.get("chunk_index", processed_chunks + 1))
            for item in extracted["entities"]:
                if not isinstance(item, dict):
                    raise ValueError("Each extracted entity must be an object")
                name = str(item.get("name", "")).strip()
                entity_type = str(item.get("type", "")).strip()
                if not name or entity_type not in entity_types:
                    continue
                key = self._key(name)
                if not key:
                    continue
                node = nodes_by_key.get(key)
                if node is None:
                    node = {
                        "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"mirofish:{graph_id}:{key}")),
                        "name": name,
                        "labels": ["Entity", entity_type],
                        "summary": str(item.get("summary", "")).strip(),
                        "attributes": dict(item.get("attributes") or {}),
                    }
                    node["attributes"]["source_chunk_indexes"] = [chunk_index]
                    nodes_by_key[key] = node
                else:
                    indexes = node.setdefault("attributes", {}).setdefault("source_chunk_indexes", [])
                    if chunk_index not in indexes:
                        indexes.append(chunk_index)
                    if not node.get("summary") and item.get("summary"):
                        node["summary"] = str(item["summary"]).strip()

            for item in extracted["relationships"]:
                if not isinstance(item, dict):
                    raise ValueError("Each extracted relationship must be an object")
                source_key = self._key(str(item.get("source", "")))
                target_key = self._key(str(item.get("target", "")))
                edge_type = str(item.get("type", "")).strip()
                if (not source_key or not target_key or source_key == target_key
                        or edge_type not in edge_types
                        or source_key not in nodes_by_key or target_key not in nodes_by_key):
                    continue
                identity = (source_key, target_key, edge_type)
                fact = str(item.get("fact", "")).strip()
                if identity not in pending_edges:
                    pending_edges[identity] = {
                        "uuid": str(uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"mirofish:{graph_id}:{source_key}:{target_key}:{edge_type}",
                        )),
                        "name": edge_type,
                        "fact": fact,
                        "source_node_uuid": nodes_by_key[source_key]["uuid"],
                        "target_node_uuid": nodes_by_key[target_key]["uuid"],
                        "attributes": dict(item.get("attributes") or {}),
                    }
                elif fact and fact not in pending_edges[identity]["fact"]:
                    pending_edges[identity]["fact"] += " | " + fact
            processed_chunks += 1

        nodes = list(nodes_by_key.values())
        edges = list(pending_edges.values())
        # Upsert nodes before edges so endpoint validation is deterministic.
        self.adapter.upsert_nodes(graph_id, nodes)
        self.adapter.upsert_edges(graph_id, edges)
        graph = self.adapter.get_graph(graph_id)
        metadata = dict(graph.get("metadata") or {})
        metadata["semantic_extraction"] = {
            "status": "completed",
            "chunks_processed": processed_chunks,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "ontology_sha256": hashlib.sha256(
                json.dumps(ontology, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
        }
        self.adapter.store.update_graph_metadata(graph_id, metadata)
        return {
            "graph_id": graph_id,
            "chunks_processed": processed_chunks,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "status": "semantic_extraction_completed",
        }
