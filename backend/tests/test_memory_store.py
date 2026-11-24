import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "memory_store.py"
SPEC = importlib.util.spec_from_file_location("mirofish_memory_store", MODULE_PATH)
MEMORY_STORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEMORY_STORE)
MemoryStoreError = MEMORY_STORE.MemoryStoreError
SQLiteMemoryStore = MEMORY_STORE.SQLiteMemoryStore


class SQLiteMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteMemoryStore(Path(self.temp_dir.name) / "memory.sqlite3")
        self.graph_id = self.store.create_graph("Research graph", {"source": "test"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_shared_in_memory_database(self):
        store = SQLiteMemoryStore(":memory:")
        graph_id = store.create_graph("In-memory graph")
        self.assertEqual(store.get_graph(graph_id)["name"], "In-memory graph")

    def test_graph_round_trip_and_delete(self):
        graph = self.store.get_graph(self.graph_id)
        self.assertEqual(graph["name"], "Research graph")
        self.assertEqual(graph["metadata"], {"source": "test"})
        self.assertTrue(self.store.delete_graph(self.graph_id))
        self.assertIsNone(self.store.get_graph(self.graph_id))
        self.assertFalse(self.store.delete_graph(self.graph_id))

    def test_node_and_edge_upsert_round_trip(self):
        self.assertEqual(self.store.upsert_nodes(self.graph_id, [{
            "uuid": "n1", "name": "Ada", "labels": ["Person"],
            "summary": "Researcher", "attributes": {"field": "math"},
        }]), 1)
        self.store.upsert_nodes(self.graph_id, [{
            "uuid": "n1", "name": "Ada Lovelace", "labels": ["Person"],
            "summary": "Updated", "attributes": {"field": "computing"},
        }])
        nodes = self.store.list_nodes(self.graph_id)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], "Ada Lovelace")
        self.assertEqual(nodes[0]["attributes"]["field"], "computing")

        self.assertEqual(self.store.upsert_edges(self.graph_id, [{
            "uuid": "e1", "source_id": "n1", "target_id": "n2",
            "name": "RELATED_TO", "attributes": {"weight": 2},
        }]), 1)
        edges = self.store.list_edges(self.graph_id)
        self.assertEqual(edges[0]["source_id"], "n1")
        self.assertEqual(edges[0]["attributes"]["weight"], 2)

    def test_missing_graph_rejects_nodes(self):
        with self.assertRaises(MemoryStoreError):
            self.store.upsert_nodes("missing", [{"uuid": "n1"}])

    def test_activity_log_is_ordered_and_scoped(self):
        self.store.append_activity("sim-a", self.graph_id, 1, "2026-01-01T00:00:00", {
            "action": "CREATE_POST", "text": "hello",
        })
        self.store.append_activity("sim-a", self.graph_id, 2, "2026-01-01T00:01:00", {
            "action": "LIKE_POST",
        })
        self.store.append_activity("sim-b", self.graph_id, 1, "2026-01-01T00:00:00", {
            "action": "FOLLOW",
        })
        activities = self.store.list_activities("sim-a")
        self.assertEqual([item["round_num"] for item in activities], [1, 2])
        self.assertEqual(activities[0]["activity"]["text"], "hello")
        self.assertEqual(len(self.store.list_activities("sim-b")), 1)

    def test_invalid_edge_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.upsert_edges(self.graph_id, [{"uuid": "e1", "source_id": "n1"}])


if __name__ == "__main__":
    unittest.main()
