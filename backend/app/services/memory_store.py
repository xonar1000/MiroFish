"""Backend-agnostic graph memory store for local development and tests.

This module is intentionally not wired into the production routes yet. It provides
a small SQLite implementation whose contract can be tested before replacing Zep.
SQLite on Render Free is ephemeral; configure a durable volume/database before
using this adapter for production data.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class MemoryStoreError(RuntimeError):
    """Raised when a memory-store operation cannot be completed."""


class SQLiteMemoryStore:
    """SQLite-backed graph, entity, relation, and simulation-activity store."""

    def __init__(self, database_path: str | os.PathLike[str] | None = None):
        configured = database_path or os.environ.get("MIROFISH_MEMORY_DB")
        raw_path = str(configured or Path(__file__).resolve().parents[2] / "uploads" / "mirofish_memory.sqlite3")
        self._is_memory = raw_path == ":memory:"
        self.database_path = Path(raw_path) if not self._is_memory else None
        self._database_target = (
            f"file:mirofish-memory-{id(self)}?mode=memory&cache=shared"
            if self._is_memory else str(self.database_path)
        )
        self._anchor = None
        if self._is_memory:
            self._anchor = sqlite3.connect(self._database_target, uri=True, timeout=30)
        else:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._database_target, uri=self._is_memory, timeout=30
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS graphs (
                    graph_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    graph_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '',
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (graph_id, node_id),
                    FOREIGN KEY (graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS edges (
                    graph_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (graph_id, edge_id),
                    FOREIGN KEY (graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS activities (
                    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    simulation_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    round_num INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    activity_json TEXT NOT NULL,
                    FOREIGN KEY (graph_id) REFERENCES graphs(graph_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_activities_simulation
                    ON activities(simulation_id, activity_id);
                """
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(row: sqlite3.Row, json_fields: tuple[str, ...]) -> dict[str, Any]:
        result = dict(row)
        for field in json_fields:
            result[field.removesuffix("_json")] = json.loads(result.pop(field))
        return result

    def create_graph(self, name: str, metadata: dict[str, Any] | None = None,
                     graph_id: str | None = None) -> str:
        graph_id = graph_id or str(uuid.uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO graphs(graph_id, name, metadata_json) VALUES (?, ?, ?)",
                (graph_id, name, self._json(metadata or {})),
            )
        return graph_id

    def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()
        return self._decode(row, ("metadata_json",)) if row else None

    def delete_graph(self, graph_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM graphs WHERE graph_id = ?", (graph_id,))
        return cursor.rowcount > 0

    def upsert_nodes(self, graph_id: str, nodes: list[dict[str, Any]]) -> int:
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone():
                raise MemoryStoreError(f"Graph not found: {graph_id}")
            for node in nodes:
                node_id = str(node.get("uuid") or node.get("node_id") or "")
                if not node_id:
                    raise ValueError("Each node requires uuid or node_id")
                db.execute(
                    """INSERT INTO nodes
                    (graph_id, node_id, name, labels_json, summary, attributes_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(graph_id, node_id) DO UPDATE SET
                    name=excluded.name, labels_json=excluded.labels_json,
                    summary=excluded.summary, attributes_json=excluded.attributes_json""",
                    (graph_id, node_id, node.get("name", ""),
                     self._json(node.get("labels", [])), node.get("summary", ""),
                     self._json(node.get("attributes", {}))),
                )
        return len(nodes)

    def upsert_edges(self, graph_id: str, edges: list[dict[str, Any]]) -> int:
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone():
                raise MemoryStoreError(f"Graph not found: {graph_id}")
            for edge in edges:
                edge_id = str(edge.get("uuid") or edge.get("edge_id") or "")
                source = str(edge.get("source_node_uuid") or edge.get("source_id") or "")
                target = str(edge.get("target_node_uuid") or edge.get("target_id") or "")
                if not edge_id or not source or not target:
                    raise ValueError("Each edge requires an id, source_id, and target_id")
                db.execute(
                    """INSERT INTO edges
                    (graph_id, edge_id, source_id, target_id, name, attributes_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(graph_id, edge_id) DO UPDATE SET
                    source_id=excluded.source_id, target_id=excluded.target_id,
                    name=excluded.name, attributes_json=excluded.attributes_json""",
                    (graph_id, edge_id, source, target, edge.get("name", ""),
                     self._json(edge.get("attributes", {}))),
                )
        return len(edges)

    def list_nodes(self, graph_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM nodes WHERE graph_id = ? ORDER BY node_id", (graph_id,)
            ).fetchall()
        return [self._decode(row, ("labels_json", "attributes_json")) for row in rows]

    def list_edges(self, graph_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM edges WHERE graph_id = ? ORDER BY edge_id", (graph_id,)
            ).fetchall()
        return [self._decode(row, ("attributes_json",)) for row in rows]

    def append_activity(self, simulation_id: str, graph_id: str,
                        round_num: int, occurred_at: str,
                        activity: dict[str, Any]) -> int:
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO activities
                (simulation_id, graph_id, round_num, occurred_at, activity_json)
                VALUES (?, ?, ?, ?, ?)""",
                (simulation_id, graph_id, round_num, occurred_at, self._json(activity)),
            )
        return int(cursor.lastrowid)

    def list_activities(self, simulation_id: str, limit: int = 500) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM activities WHERE simulation_id = ?
                ORDER BY activity_id LIMIT ?""",
                (simulation_id, limit),
            ).fetchall()
        return [self._decode(row, ("activity_json",)) for row in rows]
