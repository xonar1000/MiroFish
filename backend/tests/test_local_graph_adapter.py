"""Contract tests for the isolated SQLite graph adapter."""
import importlib.util
import sys
from pathlib import Path
import unittest

SERVICE_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
sys.path.insert(0, str(SERVICE_DIR))


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


memory_store = load_module("mirofish_test_memory_store", "memory_store.py")
adapter_module = load_module("mirofish_test_local_graph_adapter", "local_graph_adapter.py")
LocalGraphAdapter = adapter_module.LocalGraphAdapter
MemoryStoreError = memory_store.MemoryStoreError
SQLiteMemoryStore = memory_store.SQLiteMemoryStore


class LocalGraphAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = LocalGraphAdapter(SQLiteMemoryStore(":memory:"))
        self.graph_id = self.adapter.create_graph("Contract graph", graph_id="g-test")

    def test_graph_lifecycle_and_info(self):
        self.assertEqual(self.adapter.get_graph(self.graph_id)["name"], "Contract graph")
        info = self.adapter.graph_info(self.graph_id)
        self.assertEqual(info["node_count"], 0)
        self.assertEqual(info["edge_count"], 0)
        self.assertTrue(self.adapter.delete_graph(self.graph_id))
        self.assertIsNone(self.adapter.get_graph(self.graph_id))

    def test_node_and_edge_round_trip_preserves_zep_shaped_fields(self):
        self.adapter.upsert_nodes(self.graph_id, [
            {"uuid": "n1", "name": "Alice", "labels": ["Entity", "Person"],
             "summary": "A person", "attributes": {"city": "Cali"}},
            {"uuid": "n2", "name": "Acme", "labels": ["Entity", "Company"]},
        ])
        self.adapter.upsert_edges(self.graph_id, [{
            "uuid": "e1", "name": "WORKS_AT", "fact": "Alice works at Acme",
            "source_node_uuid": "n1", "target_node_uuid": "n2",
            "attributes": {"since": "2024"},
        }])
        nodes = self.adapter.list_nodes(self.graph_id)
        edges = self.adapter.list_edges(self.graph_id)
        self.assertEqual(nodes[0]["uuid"], "n1")
        self.assertEqual(nodes[0]["attributes"], {"city": "Cali"})
        self.assertEqual(edges[0]["fact"], "Alice works at Acme")
        self.assertEqual(edges[0]["attributes"], {"since": "2024"})
        self.assertEqual(self.adapter.graph_info(self.graph_id)["entity_types"],
                         ["Company", "Person"])
        graph = self.adapter.graph_data(self.graph_id)
        self.assertEqual(graph["edges"][0]["source_node_name"], "Alice")
        self.assertEqual(graph["edges"][0]["target_node_name"], "Acme")

    def test_rejects_edges_with_missing_endpoints(self):
        with self.assertRaises(ValueError):
            self.adapter.upsert_edges(self.graph_id, [{
                "uuid": "bad", "source_node_uuid": "missing",
                "target_node_uuid": "missing-too",
            }])

    def test_missing_graph_is_not_reported_as_empty_graph(self):
        with self.assertRaises(MemoryStoreError):
            self.adapter.graph_info("does-not-exist")


if __name__ == "__main__":
    unittest.main()
