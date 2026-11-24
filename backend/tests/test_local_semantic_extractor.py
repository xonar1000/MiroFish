"""Tests for the opt-in LLM-backed local semantic extractor."""
import importlib.util
from pathlib import Path
import sys
import unittest
import uuid

SERVICE_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
sys.path.insert(0, str(SERVICE_DIR))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


memory = load("semantic_memory_store", "memory_store.py")
sys.modules["memory_store"] = memory
adapter_mod = load("semantic_local_adapter", "local_graph_adapter.py")
sys.modules["local_graph_adapter"] = adapter_mod
ingestor_mod = load("semantic_local_ingestor", "local_document_ingestor.py")
sys.modules["local_document_ingestor"] = ingestor_mod
extractor_mod = load("semantic_local_extractor", "local_semantic_extractor.py")


class FakeLLM:
    def chat_json(self, **kwargs):
        return {
            "entities": [
                {"name": "Acme", "type": "Organization", "summary": "A company"},
                {"name": "Ana", "type": "Person", "summary": "A person"},
            ],
            "relationships": [
                {"source": "Ana", "target": "Acme", "type": "WORKS_FOR",
                 "fact": "Ana works for Acme", "attributes": {}},
            ],
        }


class LocalSemanticExtractorTests(unittest.TestCase):
    def setUp(self):
        self.store = memory.SQLiteMemoryStore(":memory:")
        self.adapter = adapter_mod.LocalGraphAdapter(self.store)
        self.ingestor = ingestor_mod.LocalDocumentIngestor(self.adapter)
        self.ontology = {
            "entity_types": [{"name": "Person"}, {"name": "Organization"}],
            "edge_types": [{"name": "WORKS_FOR"}],
        }
        self.graph_id = self.ingestor.ingest_text(
            "Ana works for Acme.", self.ontology, chunk_size=100, chunk_overlap=0,
            graph_id=f"semantic-{uuid.uuid4()}",
        )["graph_id"]
        self.extractor = extractor_mod.LocalSemanticExtractor(
            adapter=self.adapter, llm_client=FakeLLM()
        )

    def test_extracts_ontology_constrained_nodes_and_edges(self):
        result = self.extractor.extract_graph(self.graph_id, self.ontology)
        nodes = self.adapter.list_nodes(self.graph_id)
        edges = self.adapter.list_edges(self.graph_id)
        self.assertEqual(result["status"], "semantic_extraction_completed")
        self.assertEqual(result["node_count"], 2)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["name"], "WORKS_FOR")
        graph = self.adapter.get_graph(self.graph_id)
        self.assertEqual(graph["metadata"]["semantic_extraction"]["status"], "completed")

    def test_rejects_unknown_graph_and_incomplete_ontology(self):
        with self.assertRaises(ValueError):
            self.extractor.extract_graph("missing", self.ontology)
        with self.assertRaises(ValueError):
            self.extractor.extract_graph(self.graph_id, {"entity_types": [], "edge_types": []})


if __name__ == "__main__":
    unittest.main()
