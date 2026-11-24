"""Tests for local source chunk ingestion."""
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


memory = load("ingest_memory_store", "memory_store.py")
sys.modules["memory_store"] = memory
adapter_mod = load("ingest_local_adapter", "local_graph_adapter.py")
sys.modules["local_graph_adapter"] = adapter_mod
ingestor_mod = load("ingest_local_document", "local_document_ingestor.py")


class LocalDocumentIngestorTests(unittest.TestCase):
    def setUp(self):
        self.store = memory.SQLiteMemoryStore(":memory:")
        self.adapter = adapter_mod.LocalGraphAdapter(self.store)
        self.ingestor = ingestor_mod.LocalDocumentIngestor(self.adapter)

    def test_ingest_persists_chunks_and_ontology_metadata(self):
        ontology = {"entity_types": [{"name": "Person"}], "edge_types": []}
        result = self.ingestor.ingest_text(
            "abcdefghij", ontology, chunk_size=4, chunk_overlap=1,
            graph_id=f"g-{uuid.uuid4()}",
        )
        chunks = self.ingestor.get_source_chunks(result["graph_id"])
        self.assertEqual([x["content"] for x in chunks], ["abcd", "defg", "ghij"])
        graph = self.adapter.get_graph(result["graph_id"])
        self.assertEqual(graph["metadata"]["ontology"], ontology)
        self.assertFalse(result["semantic_extraction_complete"])
        self.assertEqual(result["node_count"], 0)

    def test_empty_text_and_invalid_overlap_rejected(self):
        with self.assertRaises(ValueError):
            self.ingestor.ingest_text("  ", {})
        with self.assertRaises(ValueError):
            self.ingestor.split_text("abc", 3, 3)

    def test_graph_deletion_cascades_source_chunks(self):
        result = self.ingestor.ingest_text("source text", {}, chunk_size=20)
        graph_id = result["graph_id"]
        self.assertTrue(self.adapter.delete_graph(graph_id))
        self.assertEqual(self.store.list_document_chunks(graph_id), [])


if __name__ == "__main__":
    unittest.main()
