"""Source-complete local-cycle walks, with public synthetic positive/negative inputs."""

from __future__ import annotations

from collections import Counter
import json

import cv2
import numpy as np

from app.native_objects.connection_core_routes import (
    enumerate_bounded_cycle_cells,
    finite_two_port_cycle_cover,
)
from app.native_objects.connections import (
    _bounded_source_polyline,
    _dense_geometry,
    _local_cycle_white_space_checks,
    extract_connections,
)


def _small_cycle():
    ring = {
        (8, 9),
        (9, 9),
        (10, 9),
        (8, 10),
        (10, 10),
        (8, 11),
        (9, 11),
        (10, 11),
    }
    return ring | {(7, 10), (11, 10)}


def _adjacency(points):
    result = {p: set() for p in points}
    for x, y in points:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = (x + dx, y + dy)
                if not (dx or dy) or q not in points:
                    continue
                if dx and dy and ((x + dx, y) in points or (x, y + dy) in points):
                    continue
                result[(x, y)].add(q)
    return result


def _cover(points=None, *, source=None, ports=None, **kwargs):
    points = points or _small_cycle()
    source = source if source is not None else points
    ports = ports or [(7, 10), (11, 10)]
    return finite_two_port_cycle_cover(
        points,
        _adjacency(points),
        ports,
        [(i, 0) for i in range(len(ports))],
        lambda x, y: (x, y) in source,
        **kwargs,
    )


def test_two_finite_cover_walks_keep_every_core_edge_and_the_original_white_hole():
    result = _cover()
    assert result["eligible"]
    assert result["core_topology"] == {
        "pixels": 10,
        "edges": 10,
        "components": 1,
        "cycle_rank": 1,
    }
    assert sum(row["degree"] % 2 for row in result["source_vertex_degrees"]) == 4
    assert len(result["finite_cover_walks"]) == 2
    edge_unions = []
    repeated_unions = []
    for candidate in result["finite_cover_walks"]:
        walk = [tuple(p) for p in candidate["source_walk_points"]]
        assert walk[0] == (7, 10) and walk[-1] == (11, 10)
        assert set(walk) == _small_cycle()
        assert (9, 10) not in walk
        assert candidate["white_hole_minimum_route_clearance_px"] == 1
        counts = Counter(tuple(sorted((a, b))) for a, b in zip(walk, walk[1:]))
        reported = {
            tuple(map(tuple, row["source_edge"])): row["traversal_count"]
            for row in candidate["source_edge_traversals"]
        }
        assert counts == reported
        assert all(
            row["owner_count"] == 1 for row in candidate["source_edge_traversals"]
        )
        assert sorted(counts.values()) == [1] * 6 + [2] * 4
        edge_unions.append(set(counts))
        repeated_unions.append({edge for edge, count in counts.items() if count == 2})
    assert edge_unions[0] == edge_unions[1]
    assert not repeated_unions[0] & repeated_unions[1]
    assert result["original_source_hole_evidence"]["enclosed_white_hole_points"] == [
        [9, 10]
    ]
    assert result["selection_is_encoding_only_not_semantic_inference"]
    assert result["semantic_connection"] == "UNKNOWN_NOT_INFERRED"


def test_original_hole_cannot_be_invented_from_a_skeleton_cycle():
    source = _small_cycle() | {(9, 10)}
    result = _cover(source=source)
    assert not result["eligible"]
    assert result["reason"] == "LOCAL_CYCLE_REQUIRES_ONE_ORIGINAL_ENCLOSED_WHITE_HOLE"


def test_original_diagonal_white_contact_is_retained_without_claiming_eight_neighbor_closure():
    points = {
        (7, 10),
        (8, 10),
        (9, 10),
        (10, 10),
        (11, 10),
        (8, 9),
        (10, 9),
        (9, 8),
    }
    result = _cover(points)
    assert result["eligible"]
    white = result["original_source_hole_evidence"]
    assert white["white_hole_connectivity"] == 4
    assert white["enclosed_white_hole_points"] == [[9, 9]]
    assert white["white_eight_connected_to_neighborhood_boundary"]
    assert white["white_diagonal_contacts_outside_four_neighbor_hole"]
    assert white["white_diagonal_contacts_removed"] is False
    assert white["eight_neighbor_enclosed_hole_claimed"] is False
    for candidate in result["finite_cover_walks"]:
        assert candidate["white_hole_minimum_route_clearance_px"] >= 0.5
        assert [9, 9] not in candidate["source_walk_points"]
    broken = _cover(points - {(9, 8)})
    assert not broken["eligible"], (
        "A real white cut cannot be bridged to close the cycle"
    )


def _partitioned_cell(kind):
    points = _small_cycle()
    left, right = (7, 10), (11, 10)
    if kind == "core":
        parts = {1: points}
        internals = []
        right_node = 1
    elif kind == "self_loop":
        parts = {1: points - {(9, 9)}}
        internals = [([1, 1], [(8, 9), (9, 9), (10, 9)])]
        right_node = 1
    else:
        parts = {
            1: {(7, 10), (8, 10), (8, 9), (8, 11)},
            2: {(11, 10), (10, 10), (10, 9), (10, 11)},
        }
        internals = [
            ([1, 2], [(8, 9), (9, 9), (10, 9)]),
            ([1, 2], [(8, 11), (9, 11), (10, 11)]),
        ]
        right_node = 2
    nodes = {
        nid: {"pixels": list(p), "edges": [], "terminal": None}
        for nid, p in parts.items()
    }
    for nid in (100, 101):
        nodes[nid] = {
            "pixels": [],
            "edges": [],
            "terminal": {"kind": "OBSERVED_ROUND_BOUNDARY_CONTACT"},
        }
    specs = [
        ([100, 1], [(6, 10), left]),
        ([right_node, 101], [right, (12, 10)]),
    ] + internals
    edges = []
    for eid, (nids, chain) in enumerate(specs):
        edges.append(
            {"id": eid, "nodes": nids, "pixels": chain, "length": float(len(chain) - 1)}
        )
        for end, nid in enumerate(nids):
            nodes[nid]["edges"].append((eid, end))
    return points, nodes, edges


def test_core_self_loop_and_two_core_partition_yield_the_same_complete_pixel_owner():
    edge_unions = []
    for kind in ("core", "self_loop", "two_cores"):
        points, nodes, edges = _partitioned_cell(kind)
        adj = _adjacency(points)
        result = enumerate_bounded_cycle_cells(
            nodes,
            edges,
            lambda p: adj[p],
            lambda p: p,
            lambda x, y: (x, y) in points,
        )
        eligible = [row for row in result["cells"] if row["eligible"]]
        assert len(eligible) == 1
        row = eligible[0]
        assert row["external_ports"] == [[0, 1], [1, 0]]
        assert row["internal_source_graph_edge_ids"] == list(range(2, len(edges)))
        assert row["all_internal_source_graph_edges_included"]
        assert set(map(tuple, row["source_core_points"])) == points
        edge_unions.append(row["source_core_edges"])
    assert edge_unions[0] == edge_unions[1] == edge_unions[2]


def test_cell_enumeration_budget_exhaustion_cannot_select_a_partial_owner():
    points, nodes, edges = _partitioned_cell("two_cores")
    adj = _adjacency(points)
    result = enumerate_bounded_cycle_cells(
        nodes,
        edges,
        lambda p: adj[p],
        lambda p: p,
        lambda x, y: (x, y) in points,
        maximum_states_per_seed=0,
    )
    assert result["eligible_cells"] == 0
    assert result["enumeration_budget_pending_node_ids"] == [1, 2]


def test_unprotected_span_encoding_does_not_skip_source_reversals_or_degenerate_samples():
    backwards = np.asarray([[0, 0], [1, 0], [0.5, 0], [2, 0]], float)
    geometry, evidence = _bounded_source_polyline(backwards)
    assert np.array_equal(geometry, backwards), (
        "Coincidence with a straight line does not explain an out-and-back source walk"
    )
    assert evidence["source_projection_order_monotone"]
    degenerate = np.asarray([[0, 0], [0, 0]], float)
    geometry, evidence = _bounded_source_polyline(degenerate)
    assert np.array_equal(geometry, degenerate)
    assert evidence["method"] == "DEGENERATE_SOURCE_SAMPLES_RETAINED"


def test_unprotected_span_search_has_a_fixed_window_and_preserves_finite_segment_order():
    source = np.column_stack((np.arange(350), np.sin(np.arange(350) / 20) * 0.5))
    geometry, evidence = _bounded_source_polyline(source)
    indices = evidence["selected_source_point_indices"]
    assert indices[0] == 0 and indices[-1] == len(source) - 1
    assert all(0 < b - a < 128 for a, b in zip(indices, indices[1:]))
    assert evidence["maximum_window_source_points"] == 128
    assert evidence["candidate_segments_examined"] <= len(source) * 127
    for a, b in zip(indices, indices[1:]):
        delta = source[b] - source[a]
        fractions = (source[a : b + 1] - source[a]) @ delta / (delta @ delta)
        assert np.all(np.diff(fractions) >= 0)
        assert fractions.min() >= 0 and fractions.max() <= 1
        distances = np.linalg.norm(
            source[a : b + 1] - (source[a] + fractions[:, None] * delta), axis=1
        )
        assert distances.max() <= 0.85
    assert np.array_equal(geometry, source[indices])


def test_a_native_segment_cannot_cross_an_original_local_white_pixel():
    cover = _cover()
    crossing = {"local_cycle_cover_evidence": cover}
    bad_geometry = {"points": [[7, 10], [11, 10]], "bulges": [0, 0], "closed": False}
    checked = _local_cycle_white_space_checks(bad_geometry, [crossing])
    assert not checked["pass"]
    assert (
        checked["original_white_pixels"][0]["minimum_native_segment_distance_px"] == 0
    )


def test_real_third_port_and_extra_internal_branch_are_not_silently_owned():
    points = _small_cycle() | {(9, 8), (9, 7)}
    three_ports = _cover(points, ports=[(7, 10), (11, 10), (9, 7)])
    assert not three_ports["eligible"]
    assert three_ports["reason"] == "LOCAL_CYCLE_REQUIRES_TWO_DISTINCT_EXTERNAL_EDGES"
    concealed_branch = _cover(points)
    assert not concealed_branch["eligible"]
    assert (
        concealed_branch["reason"] == "LOCAL_CYCLE_HAS_EXTRA_BRANCH_OR_COMPOSITE_PORT"
    )


def test_multiple_cycles_and_bounded_work_remain_pending():
    points = _small_cycle() | {(8, 7), (9, 7), (10, 7), (8, 8), (10, 8)}
    result = _cover(points)
    assert not result["eligible"]
    assert result["reason"] == "LOCAL_CYCLE_REQUIRES_EXACTLY_ONE_INTERNAL_CYCLE"
    for kwargs in (
        {"maximum_core_pixels": 9},
        {"maximum_core_extent_px": 3},
        {"maximum_walk_steps": 10},
    ):
        bounded = _cover(**kwargs)
        assert not bounded["eligible"]
        assert "BUDGET" in bounded["reason"]


def _round_path(*, left_round=True, right_round=True, white_gap=False):
    ink = np.zeros((160, 220), np.uint8)
    if left_round:
        cv2.circle(ink, (25, 90), 12, 1, 1)
    if right_round:
        cv2.circle(ink, (195, 90), 12, 1, 1)
    for points in (
        [(37, 90), (65, 69), (90, 63), (109, 60)],
        [(111, 60), (130, 63), (155, 69), (183, 90)],
    ):
        cv2.polylines(ink, [np.asarray(points, np.int32)], False, 1, 1)
    cv2.rectangle(ink, (109, 59), (111, 61), 1, 1)
    if white_gap:
        ink[:, 80:84] = 0
    return ink


def _extract(ink, out):
    gray = np.where(ink, 0, 255).astype(np.uint8)
    before = gray.copy()
    result = extract_connections(gray, (0, 0, 220, 160), [], out)
    assert np.array_equal(gray, before)
    return result


def test_complete_round_path_preserves_the_whole_core_walk_in_one_native_geometry(
    tmp_path,
):
    ink = _round_path()
    result = _extract(ink, tmp_path)
    assert len(result["objects"]) == 1
    obj = result["objects"][0]
    ev = obj["source_evidence"]
    assert ev["whole_path_class"] == "ROUND_BOUNDARY_TO_ROUND_BOUNDARY"
    assert (
        ev["endpoint_evidence"][0]["round_id"] != ev["endpoint_evidence"][1]["round_id"]
    )
    covers = [c for c in ev["crossing_evidence"] if c.get("local_cycle_cover_evidence")]
    assert len(covers) == 1
    cover = covers[0]
    lo, hi = cover["protected_source_path_interval"]
    protected = ev["source_path_points"][lo:hi]
    geometry = obj["geometry"]
    assert any(
        geometry["points"][i : i + len(protected)] == protected
        for i in range(len(geometry["points"]))
    )
    assert geometry["closed"] is False
    assert all(bulge == 0 for bulge in geometry["bulges"])
    assert ev["native_representation"]["internal_cycle_control_points_retained"] == len(
        protected
    )
    assert ev["local_cycle_white_space_checks"]["pass"]
    raster = np.zeros_like(ink)
    dense = np.rint(_dense_geometry(geometry, 0.1)).astype(np.int32)
    cv2.polylines(raster, [dense], False, 1, 1)
    assert not raster[60, 110]
    for x, y in cover["local_cycle_cover_evidence"]["source_core_points"]:
        assert raster[y, x]
    assert len(ev["source_graph_edge_ids"]) == len(set(ev["source_graph_edge_ids"]))
    graph = json.loads((tmp_path / "source_graph.json").read_text())
    core = next(
        n
        for n in graph["nodes"]
        if (n.get("local_cycle_cover_evidence") or {}).get("eligible")
    )
    assert core["pairings"] == [], (
        "A finite cover encoding is not a unique source continuation"
    )
    assert core["reason"] == "INTERNAL_SOURCE_CYCLE_REQUIRES_EXPLICIT_DECOMPOSITION"
    assert (
        result["graph_summary"]["source_round_to_round_paths_with_local_cycle_cover"]
        == 1
    )


def test_mixed_free_endpoints_and_white_gaps_cannot_use_the_round_path_exception(
    tmp_path,
):
    for name, params in (
        ("mixed", {"right_round": False}),
        ("free", {"left_round": False, "right_round": False}),
        ("gap", {"white_gap": True}),
    ):
        result = _extract(_round_path(**params), tmp_path / name)
        assert not any(
            c.get("local_cycle_cover_evidence")
            for obj in result["objects"]
            for c in obj["source_evidence"]["crossing_evidence"]
        )
        assert any("CYCLE" in row["reason"] for row in result["uncertainties"])
