"""Local graph adapter exposing the graph-shaped contract over SQLite.

This is an isolated adapter, not yet wired into Flask routes or OASIS. It keeps
Zep-shaped node/edge dictionaries at the boundary so callers can migrate in
small, testable steps.
"""
from __future__ import annotations

import uuid
from typing import Any

try:\n    from .memory_store import SQLiteMemoryStore, MemoryStoreError\nexcept ImportError:  # direct-file loading in isolated unit tests\n    from memory_store import SQLiteMemoryStore, MemoryStoreError


class LocalGraphAdapter:
    """Graph lifecycle and read/write operations backed by SQLite."""

    def __init__(self, store: SQLiteMemoryStore | None = None):
        self.store = store or SQLiteMemoryStore()

    def create_graph(self, name: str, graph_id: str | None = None,
                     metadata: dict[str, Any] | None = None) -> str:
        return self.store.create_graph(
            name=name, metadata=metadata or {}, graph_id=graph_id
        )

    def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        return self.store.get_graph(graph_id)

    def delete_graph(self, graph_id: str) -> bool:
        return self.store.delete_graph(graph_id)

    def upsert_nodes(self, graph_id: str, nodes: list[dict[str, Any]]) -> int:
        normalized = []
        for item in nodes:
            node = dict(item)
            node.setdefault("uuid", node.get("node_id") or str(uuid.uuid4()))
            node.setdefault("labels", ["Entity"])
            node.setdefault("summary", "")
            node.setdefault("attributes", {})
            normalized.append(node)
        return self.store.upsert_nodes(graph_id, normalized)

    def upsert_edges(self, graph_id: str, edges: list[dict[str, Any]]) -> int:
        existing_ids = {node["node_id"] for node in self.store.list_nodes(graph_id)}
        normalized = []
        for item in edges:
            edge = dict(item)
            source = str(edge.get("source_node_uuid") or edge.get("source_id") or "")
            target = str(edge.get("target_node_uuid") or edge.get("target_id") or "")
            if source not in existing_ids or target not in existing_ids:
                raise ValueError("Edge endpoints must exist in the same graph")
            edge.setdefault("uuid", edge.get("edge_id") or str(uuid.uuid4()))
            edge.setdefault("name", edge.get("fact_type") or "RELATED_TO")
            attrs = dict(edge.get("attributes") or {})
            if edge.get("fact") is not None:
                attrs["fact"] = edge["fact"]
            edge["attributes"] = attrs
            normalized.append(edge)
        return self.store.upsert_edges(graph_id, normalized)

    def list_nodes(self, graph_id: str) -> list[dict[str, Any]]:
        rows = self.store.list_nodes(graph_id)
        return [{
            "uuid": row["node_id"],
            "name": row["name"],
            "labels": row["labels"],
            "summary": row["summary"],
            "attributes": row["attributes"],
        } for row in rows]

    def list_edges(self, graph_id: str) -> list[dict[str, Any]]:
        rows = self.store.list_edges(graph_id)
        result = []
        for row in rows:
            attributes = dict(row["attributes"])
            fact = attributes.pop("fact", "")
            result.append({
                "uuid": row["edge_id"],
                "name": row["name"],
                "fact": fact,
                "source_node_uuid": row["source_id"],
                "target_node_uuid": row["target_id"],
                "attributes": attributes,
            })
        return result

    def graph_info(self, graph_id: str) -> dict[str, Any]:
        if self.get_graph(graph_id) is None:
            raise MemoryStoreError(f"Graph not found: {graph_id}")
        nodes = self.list_nodes(graph_id)
        edges = self.list_edges(graph_id)
        types = sorted({
            label for node in nodes for label in node["labels"]
            if label not in {"Entity", "Node"}
        })
        return {
            "graph_id": graph_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_types": types,
        }

    def graph_data(self, graph_id: str) -> dict[str, Any]:
        if self.get_graph(graph_id) is None:
            raise MemoryStoreError(f"Graph not found: {graph_id}")
        nodes = self.list_nodes(graph_id)
        edges = self.list_edges(graph_id)
        node_names = {node["uuid"]: node["name"] for node in nodes}
        detailed_edges = [{
            **edge,
            "fact_type": edge["name"],
            "source_node_name": node_names.get(edge["source_node_uuid"], ""),
            "target_node_name": node_names.get(edge["target_node_uuid"], ""),
            "created_at": None,
            "valid_at": None,
            "invalid_at": None,
            "expired_at": None,
            "episodes": [],
        } for edge in edges]
        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": detailed_edges,
            "node_count": len(nodes),
            "edge_count": len(detailed_edges),
        }
