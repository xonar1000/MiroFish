"""Contract tests for LocalEntityReader."""
import importlib.util
from pathlib import Path
import sys
import unittest

SERVICE_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
sys.path.insert(0, str(SERVICE_DIR))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


memory = load("reader_memory_store", "memory_store.py")
adapter_mod = load("reader_local_adapter", "local_graph_adapter.py")
sys.modules["local_graph_adapter"] = adapter_mod
reader_mod = load("reader_local_entity_reader", "local_entity_reader.py")


class LocalEntityReaderTests(unittest.TestCase):
    def setUp(self):
        store = memory.SQLiteMemoryStore(":memory:")
        self.adapter = adapter_mod.LocalGraphAdapter(store)
        self.graph = self.adapter.create_graph("test", graph_id="g1")
        self.adapter.upsert_nodes(self.graph, [
            {"uuid": "p", "name": "Ana", "labels": ["Entity", "Person"]},
            {"uuid": "c", "name": "Acme", "labels": ["Entity", "Company"]},
            {"uuid": "u", "name": "Other", "labels": ["Entity"]},
        ])
        self.adapter.upsert_edges(self.graph, [{
            "uuid": "e", "name": "WORKS_AT", "fact": "Ana works at Acme",
            "source_node_uuid": "p", "target_node_uuid": "c",
        }])
        self.reader = reader_mod.LocalEntityReader(self.adapter)

    def test_filters_and_enriches_incoming_and_outgoing(self):
        result = self.reader.filter_defined_entities(self.graph)
        self.assertEqual((result.total_count, result.filtered_count), (3, 2))
        ana = next(x for x in result.entities if x.uuid == "p")
        acme = next(x for x in result.entities if x.uuid == "c")
        self.assertEqual(ana.related_edges[0]["direction"], "outgoing")
        self.assertEqual(acme.related_edges[0]["direction"], "incoming")
        self.assertEqual(ana.related_nodes[0]["uuid"], "c")

    def test_type_filter_and_no_enrichment(self):
        result = self.reader.filter_defined_entities(self.graph, ["Company"], False)
        self.assertEqual([x.uuid for x in result.entities], ["c"])
        self.assertEqual(result.entities[0].related_edges, [])
        self.assertEqual(self.reader.get_entities_by_type(self.graph, "Person")[0].uuid, "p")

    def test_single_entity_context_and_missing_entity(self):
        self.assertEqual(self.reader.get_entity_with_context(self.graph, "p").name, "Ana")
        self.assertIsNone(self.reader.get_entity_with_context(self.graph, "missing"))

    def test_serialized_contract(self):
        data = self.reader.filter_defined_entities(self.graph).to_dict()
        self.assertEqual(data["entity_types"], ["Company", "Person"])
        self.assertIn("related_nodes", data["entities"][0])
