"""All core encodings, failed read branches and acyclic source dependencies."""
from copy import deepcopy

import numpy as np

from app.native_objects.finite_component_source_audit import (
    _all_core_port_directions, _core_evidence_v2, _direction_table_v2,
)
from app.native_objects import structure_contact_geometry as structure
from app.native_objects.text_contact_geometry import build_text_contact_source_graph


class _Graph:
    def __init__(self, *, short=False, incoming_short=False):
        def pixel(p):
            return int(p[1] * 100 + p[0])
        core = [(40, 40), (41, 40), (41, 41), (40, 41)]
        arms = [[(40, y) for y in range(40, 19 if not incoming_short else 35, -1)],
                [(41, y) for y in range(41, 62)],
                [(x, 41) for x in range(40, 19, -1)],
                [(x, 40) for x in range(41, 44 if short else 62)]]
        self.edges, self.nodes, self.links = [], {}, {}
        self.nodes[0] = {"pixels": [pixel(p) for p in core], "edges": [], "pairing": {},
                         "internal_source_endpoint_count": 0, "terminal": None, "center": [40.5, 40.5]}
        for eid, arm in enumerate(arms):
            ids = [pixel(p) for p in arm]
            self.edges.append({"pixels": ids, "nodes": [0, eid + 1]})
            self.nodes[0]["edges"].append((eid, 0))
            self.nodes[eid + 1] = {"pixels": [ids[-1]], "edges": [(eid, 1)], "pairing": {},
                "internal_source_endpoint_count": 1, "terminal": {"kind": "OBSERVED_FREE_SOURCE_ENDPOINT"},
                "center": list(arm[-1])}
            for a, b in zip(ids, ids[1:]):
                self.links.setdefault(a, set()).add(b)
                self.links.setdefault(b, set()).add(a)
        ids = self.nodes[0]["pixels"]
        for a, b in zip(ids, ids[1:] + ids[:1]):
            self.links.setdefault(a, set()).add(b)
            self.links.setdefault(b, set()).add(a)
        self.source = np.full((100, 100), 255, np.uint8)
        for p in self.links:
            self.source[p // 100, p % 100] = 0

    def oriented(self, port):
        raw = self.edges[port[0]]["pixels"]
        return raw if port[1] == 0 else list(reversed(raw))

    def xy(self, pixels):
        return np.asarray([(p % 100, p // 100) for p in pixels], float)

    def neighbors(self, pixel):
        return self.links.get(pixel, set())


def test_solid_original_microcycle_preserves_all_edges_and_unique_external_pairs():
    graph = _Graph()
    before = deepcopy(graph.links)
    table = _direction_table_v2(graph, 0)
    result = _core_evidence_v2(graph.source, graph, 0, table)
    assert result["pass"], result["reasons"]
    assert result["minimal_raw_box_all_black"]
    assert result["complete_external_unique_pairing"]
    assert len(result["all_original_adjacencies"]) == 4
    assert result["original_adjacencies_removed"] == [] and before == graph.links
    broken = graph.source.copy()
    broken[40, 40] = 255
    assert not _core_evidence_v2(broken, graph, 0, table)["pass"]
    graph.nodes[0]["internal_source_endpoint_count"] = 1
    assert not _core_evidence_v2(graph.source, graph, 0, table)["pass"]


def test_short_failed_competing_arm_is_retained_and_prevents_complete_pairing():
    graph = _Graph(short=True)
    table = _direction_table_v2(graph, 0)
    assert not table["all_directions_complete"]
    assert not any(pair["pass"] for pair in table["pairs"])
    assert [43, 40] in table["evidence_read_pixels_px"]
    assert any(r["reason"] == "DIRECTION_CHORD_TOO_SHORT" for r in table["failed_short_and_truncated_branches"])


def test_direction_traversal_keeps_every_original_core_path_encoding():
    graph = _Graph(incoming_short=True)
    reads = {"edges": set(), "nodes": set(), "pixels": set(), "failed": [], "core_walks": {}}
    looks, complete, _ = _all_core_port_directions(graph, (0, 1), {}, reads)
    assert complete and looks
    assert reads["core_walks"]
    assert all(len(row["all_walks_px"]) == 2 for row in reads["core_walks"].values())
    assert len(looks) == 6
    assert set(graph.nodes[0]["pixels"]) <= reads["pixels"]


def test_dependency_positive_rebuilt_from_source_uses_only_earlier_proof_rounds():
    from tests.test_native_structure_contact_geometry import _close_contact_source
    source, roi, prior = _close_contact_source()
    context = build_text_contact_source_graph(source, roi)
    old_plan = structure.plan_structure_contact_geometry(source, roi, prior, source_graph=context)
    nodes = {proof["node_id"] for path in old_plan["paths"] for proof in path["contact_continuations"]
             if proof.get("direction_dependency_proofs")}
    assert nodes
    before = {nid: dict(node["pairing"]) for nid, node in context.graph.nodes.items()}
    tables = [_direction_table_v2(context.graph, nid) for nid in nodes]
    assert all(any(p["pass"] for p in t["pairs"]) for t in tables)
    proofs = [p for t in tables for p in t["direction_dependency_proofs"]]
    assert proofs
    for table in tables:
        rounds = {p["proof_id"]: p["round"] for p in table["direction_dependency_proofs"]}
        for proof in table["direction_dependency_proofs"]:
            assert all(rounds[d] < proof["round"] for d in proof["earlier_proof_ids"])
        assert table["minimum_pair_margin_deg"] == 18 and table["maximum_pair_deviation_deg"] == 20
    assert before == {nid: dict(node["pairing"]) for nid, node in context.graph.nodes.items()}
