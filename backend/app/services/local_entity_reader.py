"""SQLite entity reader with the same result shape as ZepEntityReader."""
from dataclasses import dataclass, field
from typing import Any

try:
    from .local_graph_adapter import LocalGraphAdapter
except ImportError:
    from local_graph_adapter import LocalGraphAdapter


@dataclass
class EntityNode:
    uuid: str
    name: str
    labels: list[str]
    summary: str
    attributes: dict[str, Any]
    related_edges: list[dict[str, Any]] = field(default_factory=list)
    related_nodes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self):
        return {"uuid": self.uuid, "name": self.name, "labels": self.labels,
                "summary": self.summary, "attributes": self.attributes,
                "related_edges": self.related_edges, "related_nodes": self.related_nodes}

    def get_entity_type(self):
        return next((x for x in self.labels if x not in ("Entity", "Node")), None)


@dataclass
class FilteredEntities:
    entities: list[EntityNode]
    entity_types: set[str]
    total_count: int
    filtered_count: int

    def to_dict(self):
        return {"entities": [x.to_dict() for x in self.entities],
                "entity_types": sorted(self.entity_types),
                "total_count": self.total_count, "filtered_count": self.filtered_count}


class LocalEntityReader:
    def __init__(self, adapter: LocalGraphAdapter | None = None):
        self.adapter = adapter or LocalGraphAdapter()

    def get_all_nodes(self, graph_id):
        return self.adapter.list_nodes(graph_id)

    def get_all_edges(self, graph_id):
        return self.adapter.list_edges(graph_id)

    @staticmethod
    def _context(node_uuid, edges, node_map):
        related_edges, related_ids = [], set()
        for edge in edges:
            if edge["source_node_uuid"] == node_uuid:
                related_edges.append({"direction": "outgoing", "edge_name": edge["name"],
                    "fact": edge["fact"], "target_node_uuid": edge["target_node_uuid"]})
                related_ids.add(edge["target_node_uuid"])
            elif edge["target_node_uuid"] == node_uuid:
                related_edges.append({"direction": "incoming", "edge_name": edge["name"],
                    "fact": edge["fact"], "source_node_uuid": edge["source_node_uuid"]})
                related_ids.add(edge["source_node_uuid"])
        related_nodes = []
        for uid in sorted(related_ids):
            node = node_map.get(uid)
            if node:
                related_nodes.append({"uuid": node["uuid"], "name": node["name"],
                    "labels": node["labels"], "summary": node.get("summary", "")})
        return related_edges, related_nodes

    def filter_defined_entities(self, graph_id, defined_entity_types=None,
                                enrich_with_edges=True):
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        node_map = {n["uuid"]: n for n in nodes}
        allowed = set(defined_entity_types or [])
        entities, types = [], set()
        for node in nodes:
            labels = [x for x in node.get("labels", []) if x not in ("Entity", "Node")]
            matches = [x for x in labels if not allowed or x in allowed]
            if not matches:
                continue
            types.add(matches[0])
            related_edges, related_nodes = self._context(node["uuid"], edges, node_map) if enrich_with_edges else ([], [])
            entities.append(EntityNode(node["uuid"], node["name"], node["labels"],
                node["summary"], node["attributes"], related_edges, related_nodes))
        return FilteredEntities(entities, types, len(nodes), len(entities))

    def get_entity_with_context(self, graph_id, entity_uuid):
        nodes = self.get_all_nodes(graph_id)
        node_map = {n["uuid"]: n for n in nodes}
        node = node_map.get(entity_uuid)
        if node is None:
            return None
        edges, related = self._context(entity_uuid, self.get_all_edges(graph_id), node_map)
        return EntityNode(node["uuid"], node["name"], node["labels"],
            node["summary"], node["attributes"], edges, related)

    def get_entities_by_type(self, graph_id, entity_type, enrich_with_edges=True):
        return self.filter_defined_entities(graph_id, [entity_type], enrich_with_edges).entities
