"""Tests for SQLite simulation activity updater."""
import importlib.util
from pathlib import Path
import sys
import uuid
import unittest

SERVICE_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
sys.path.insert(0, str(SERVICE_DIR))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


memory = load("updater_memory_store", "memory_store.py")
updater_mod = load("updater_local_module", "local_graph_memory_updater.py")


class LocalUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.store = memory.SQLiteMemoryStore(":memory:")
        self.graph_id = self.store.create_graph("activity graph", graph_id=f"g-{uuid.uuid4()}")
        self.updater = updater_mod.LocalGraphMemoryUpdater(self.graph_id, f"sim-{uuid.uuid4()}", self.store)

    def test_records_activity_and_skips_non_actions(self):
        self.updater.start()
        self.updater.add_activity_from_dict({
            "agent_id": 7, "agent_name": "Ana", "action_type": "CREATE_POST",
            "action_args": {"content": "hello"}, "round": 3,
            "timestamp": "2026-11-24T12:00:00Z",
        }, "twitter")
        self.updater.add_activity_from_dict({"event_type": "round"}, "twitter")
        rows = self.store.list_activities(self.updater.simulation_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["graph_id"], self.graph_id)
        self.assertEqual(rows[0]["round_num"], 3)
        self.assertEqual(rows[0]["activity_json"]["action_type"], "CREATE_POST")
        self.assertEqual(self.updater.get_stats()["total_activities"], 1)
        self.assertEqual(self.updater.get_stats()["skipped_count"], 1)

    def test_requires_started_updater_and_existing_graph(self):
        with self.assertRaises(RuntimeError):
            self.updater.add_activity_from_dict({"action_type": "LIKE_POST"}, "reddit")
        self.updater.start()
        with self.assertRaises(Exception):
            broken = updater_mod.LocalGraphMemoryUpdater("missing", "sim2", self.store)
            broken.start()
            broken.add_activity_from_dict({"action_type": "LIKE_POST"}, "reddit")

    def test_manager_lifecycle(self):
        manager = updater_mod.LocalGraphMemoryManager
        manager.stop_all()
        item = manager.create_updater(f"sim-{uuid.uuid4()}", self.graph_id)
        self.assertIs(manager.get_updater(item.simulation_id), item)
        self.assertEqual(manager.get_simulation_ids_for_graph(self.graph_id), [item.simulation_id])
        manager.stop_updater(item.simulation_id)
        self.assertIsNone(manager.get_updater(item.simulation_id))


if __name__ == "__main__":
    unittest.main()
