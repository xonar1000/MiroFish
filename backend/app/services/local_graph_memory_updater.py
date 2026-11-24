"""SQLite-backed simulation activity recorder compatible with runner hooks.

This module is intentionally isolated. It records raw agent actions durably in
the configured SQLite store; it does not claim to perform semantic extraction
or mutate graph entities from natural language.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any

try:
    from .memory_store import SQLiteMemoryStore
except ImportError:
    from memory_store import SQLiteMemoryStore


class LocalGraphMemoryUpdater:
    def __init__(self, graph_id: str, simulation_id: str,
                 store: SQLiteMemoryStore | None = None):
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.store = store or SQLiteMemoryStore()
        self._running = False
        self._total_activities = 0
        self._skipped_count = 0
        self._lock = RLock()

    def start(self):
        with self._lock:
            self._running = True

    def add_activity_from_dict(self, data: dict[str, Any], platform: str):
        if "event_type" in data or data.get("success") is False:
            self._skipped_count += 1
            return
        action_type = str(data.get("action_type", ""))
        if not action_type or action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        activity = {
            "platform": platform,
            "agent_id": data.get("agent_id", 0),
            "agent_name": data.get("agent_name", ""),
            "action_type": action_type,
            "action_args": data.get("action_args", {}),
            "round": data.get("round", 0),
            "timestamp": data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if not self._running:
                raise RuntimeError("Local graph updater is not running")
            self.store.append_activity(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                round_num=int(activity["round"] or 0),
                occurred_at=str(activity["timestamp"]),
                activity=activity,
            )
            self._total_activities += 1

    def stop(self):
        with self._lock:
            self._running = False

    def get_stats(self):
        return {
            "graph_id": self.graph_id,
            "simulation_id": self.simulation_id,
            "total_activities": self._total_activities,
            "skipped_count": self._skipped_count,
            "queue_size": 0,
            "running": self._running,
            "backend": "sqlite",
        }


class LocalGraphMemoryManager:
    _updaters: dict[str, LocalGraphMemoryUpdater] = {}
    _lock = RLock()

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str):
        with cls._lock:
            previous = cls._updaters.pop(simulation_id, None)
            if previous:
                previous.stop()
            updater = LocalGraphMemoryUpdater(graph_id, simulation_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str):
        with cls._lock:
            return cls._updaters.get(simulation_id)

    @classmethod
    def get_simulation_ids_for_graph(cls, graph_id: str):
        with cls._lock:
            return sorted(k for k, v in cls._updaters.items() if v.graph_id == graph_id)

    @classmethod
    def get_simulation_ids(cls):
        with cls._lock:
            return sorted(cls._updaters)

    @classmethod
    def discard_inactive_updater(cls, simulation_id: str):
        with cls._lock:
            updater = cls._updaters.get(simulation_id)
            if updater is None:
                return False
            if updater._running:
                return False
            cls._updaters.pop(simulation_id, None)
            return True

    @classmethod
    def stop_updater(cls, simulation_id: str):
        with cls._lock:
            updater = cls._updaters.pop(simulation_id, None)
        if updater:
            updater.stop()

    @classmethod
    def stop_all(cls):
        with cls._lock:
            items = list(cls._updaters.values())
            cls._updaters.clear()
        for updater in items:
            updater.stop()

    @classmethod
    def get_all_stats(cls):
        with cls._lock:
            return {key: updater.get_stats() for key, updater in cls._updaters.items()}
