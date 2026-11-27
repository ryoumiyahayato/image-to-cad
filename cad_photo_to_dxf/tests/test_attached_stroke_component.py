"""Authored source controls for complete finite component responsibility.

Every raster control rebuilds its original source graph. The local model seam
does not claim ordinary planner adoption or saved-file verification; those gates
are exercised separately. Raster authoring uses pixel-center sampling, not the
production closed-cell or white-witness predicates.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json

import numpy as np
from PIL import Image
import pytest

from app.native_objects import attached_stroke_component as component
from app.native_objects import attached_stroke_graph as planner
from app.native_objects import attached_stroke_width_exact as exact
from app.native_objects.text_contact_geometry import build_text_contact_source_graph


def _raster(segments, shape=(80, 96), radius=2):
    yy, xx = np.indices(shape)
    points = np.stack((xx, yy), axis=-1).astype(float)
    ink = np.zeros(shape, bool)
    for start, end in segments:
        start, end = np.asarray(start, float), np.asarray(end, float)
        delta = end - start
        fraction = np.clip((points - start) @ delta / float(delta @ delta), 0, 1)
        nearest = start + fraction[..., None] * delta
        ink |= np.sum((points - nearest) ** 2, axis=-1) <= radius * radius
    return np.where(ink, 0, 255).astype(np.uint8)


def _three_body_scene():
    source = _raster([((16, 40), (80, 40)), ((40, 16), (40, 40)), ((64, 40), (64, 64))], radius=1.5)
    context = build_text_contact_source_graph(source, [0, 0, source.shape[1], source.shape[0]])
    graph = context.graph
    junctions = [nid for nid, node in graph.nodes.items() if len(node["edges"]) == 3]
    assert len(junctions) == 2
    pairs, attachments, cores = {}, set(), {}
    for nid in junctions:
        directions = planner._node_directions(graph, nid)
        passed = [pair for pair in directions["all_pair_candidates"] if pair["pass"]]
        assert len(passed) == 1
        a, b = map(tuple, passed[0]["pair"])
        pairs[(nid, a)], pairs[(nid, b)] = b, a
        attachments.update((nid, port) for port in graph.nodes[nid]["edges"] if port not in (a, b))
        cores[nid] = planner._core_proof(source, graph, nid)
        assert cores[nid]["pass"]
    routes = planner._walk_decomposition(graph, {"edges": list(range(len(graph.edges))),
                                                 "nodes": sorted(graph.nodes)}, pairs, attachments)
    # The native fitter requires owner bookkeeping even when this local model
    # has no prior object. No prior body is sent to the component audit.
    rows = planner._geometry_routes(source, graph, routes,
                                    {"id": "AUTHORED_LOCAL_SCENE_NO_PRIOR_BODY", "binding": {}}, cores)
    for row in rows:
        for endpoint in row["endpoint_evidence"]:
            if "host_path_index" in endpoint:
                endpoint["host_path_id"] = rows[endpoint["host_path_index"]]["stroke_id"]
    assert len(rows) == 3
    return source, graph, rows, cores


def _body(identity, points, lower=Fraction(1, 4), upper=Fraction(9, 4)):
    return {"stroke_id": identity, "representation": {"points": points, "closed": False},
            "width": {"half_width_squared_interval": exact.encode_interval(lower, upper)}}


def _cells(source):
    by, bx = np.nonzero(source < 128)
    wy, wx = np.nonzero(source >= 128)
    return np.column_stack((bx, by)).tolist(), np.column_stack((wx, wy)).tolist()


def _record(tmp_path, source, report, rows=None):
    Image.fromarray(source).save(tmp_path / "original_source.png")
    (tmp_path / "report.json").write_text(json.dumps(planner._plain(report), indent=2, allow_nan=False) + "\n",
                                          encoding="utf-8")
    (tmp_path / "source_identity.json").write_text(json.dumps({
        "original_source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "shape": list(source.shape), "fresh_original_source_graph": True,
        "scope": "AUTHORED_LOCAL_MODEL_CONTROL_NOT_ORDINARY_ADOPTION_OR_SAVED_DXF",
        "component_producer_sha256": component.producer_sha256(),
    }, indent=2) + "\n", encoding="utf-8")
    if rows is not None:
        (tmp_path / "native_rows.json").write_text(json.dumps(planner._plain(rows), indent=2, allow_nan=False) + "\n",
                                                   encoding="utf-8")


def _sole_graph_row(source, native):
    context = build_text_contact_source_graph(source, [0, 0, source.shape[1], source.shape[0]])
    graph = context.graph
    assert len(graph.edges) == 1
    row = {"stroke_id": "AUTHORED_COMPLETE_SINGLE_SOURCE_CHAIN",
           "representation": {"points": native, "closed": False},
           "source_graph_edge_ids": [0], "source_node_ids": sorted(graph.nodes),
           "source_path_px": graph.xy(graph.edges[0]["pixels"]).tolist(), "endpoint_evidence": []}
    return graph, row


def test_three_complete_bodies_are_a_real_positive_source_component(tmp_path):
    source, graph, rows, cores = _three_body_scene()
    before = source.tobytes(), deepcopy(rows)
    report = component.audit_finite_bodies(source, graph, rows, cores=cores)
    _record(tmp_path, source, report, rows)
    assert report["pass"], report["failure_reasons"]
    assert report["status"] == "COMPLETE_SOURCE_MODEL_PASS"
    assert report["coherent_component_model"]["pass"]
    assert report["complete_pixel_accounting"]
    assert report["observation_closed"]
    assert all(body["independently_supported"] for body in report["bodies"])
    assert all(body["width"]["every_complete_chain_port_enumerated"] for body in report["bodies"])
    assert all(body["width"]["independent_section_count"] >= 2 for body in report["bodies"])
    assert any(len(item.get("joint_model_body_ids", [])) > 1 for item in report["pixel_ledger"])
    assert all(item["assignment_is_joint_model_proved"] for item in report["pixel_ledger"]
               if item["relevant_connected_ink"])
    assert source.tobytes() == before[0] and rows == before[1]


def test_missing_connected_neighbor_remains_unknown_ink_and_an_unproved_exit(tmp_path):
    source, graph, rows, cores = _three_body_scene()
    neighbor = max(rows, key=lambda row: max(p[1] for p in row["representation"]["points"]))
    targets = [row for row in rows if row is not neighbor]
    report = component.audit_finite_bodies(source, graph, targets, cores=cores)
    _record(tmp_path, source, report, targets)
    assert not report["pass"]
    assert any(item["classification"] == "UNKNOWN_CONNECTED_INK" for item in report["pixel_ledger"])
    assert any(item["classification"] == "UNKNOWN_CONNECTED_EXIT" for item in report["window_exits"])
    assert "PENDING_UNKNOWN_EXIT_OR_CLIPPED_TARGET_SCOPE" in report["failure_reasons"]


def test_neighbor_without_its_own_complete_source_chain_cannot_explain_pixels(tmp_path):
    source, graph, rows, cores = _three_body_scene()
    neighbor = max(rows, key=lambda row: max(p[1] for p in row["representation"]["points"]))
    neighbor["body_role"] = "NECESSARY_PRIOR_FINITE_NEIGHBOR"
    neighbor["source_path_px"] = neighbor["source_path_px"][:3]
    report = component.audit_finite_bodies(source, graph, rows, cores=cores)
    _record(tmp_path, source, report, rows)
    assert not report["pass"]
    observed = next(body for body in report["bodies"] if body["stroke_id"] == neighbor["stroke_id"])
    assert not observed["chain_binding"]["pass"]
    assert not observed["independently_supported"]
    assert neighbor["stroke_id"] in report["coherent_component_model"]["unsupported_body_ids"]
    assert all(neighbor["stroke_id"] not in item["compatible_body_ids"] for item in report["pixel_ledger"])


def test_complete_raw_source_chain_cannot_hide_an_external_edge_from_width_sampling():
    source, graph, rows, _ = _three_body_scene()
    host = next(row for row in rows if len(row["source_graph_edge_ids"]) > 1)
    assert component._chain_binding(source, graph, host)["pass"]
    omitted = host["source_graph_edge_ids"].pop(1)
    binding = component._chain_binding(source, graph, host)
    assert not binding["pass"], f"Undeclared source edge {omitted} was silently excluded from width ports."
    assert binding["reasons"]


def test_complete_target_cannot_skip_both_endpoint_evidence_records():
    source, graph, rows, cores = _three_body_scene()
    guest = next(row for row in rows if any("host_path_index" in terminal for terminal in row["endpoint_evidence"]))
    guest["endpoint_evidence"] = []
    report = component.audit_finite_bodies(source, graph, rows, cores=cores)
    assert not report["pass"]
    assert any("ENDPOINT" in reason for reason in report["failure_reasons"])


def test_exact_geometry_record_cannot_override_different_actual_native_points():
    row = {"representation": {"points": [[0, 0], [2, 0]], "closed": False},
           "representation_exact_points": [[exact.encode_rational(v) for v in point]
                                            for point in ((0, 0), (3, 0))]}
    with pytest.raises(ValueError):
        component._points(row)


@pytest.mark.parametrize("sideways, expected_squared", [(0.0, Fraction(1, 4)), (0.375, Fraction(25, 64))])
def test_short_native_terminal_segment_keeps_long_source_direction_and_actual_bend(sideways, expected_squared, tmp_path):
    source, graph, rows, cores = _three_body_scene()
    guest = next(row for row in rows if any("host_path_id" in terminal for terminal in row["endpoint_evidence"]))
    attached_index = next(i for i, terminal in enumerate(guest["endpoint_evidence"]) if "host_path_id" in terminal)
    points = guest["representation"]["points"]
    end, adjacent = (0, 1) if attached_index == 0 else (-1, -2)
    a, b = np.asarray(points[end]), np.asarray(points[adjacent])
    intermediate = (a + (b - a) * (0.5 / np.linalg.norm(b - a))).tolist()
    intermediate[0] += sideways
    if attached_index == 0:
        points.insert(1, intermediate)
    else:
        points.insert(len(points) - 1, intermediate)
    guest["representation"]["bulges"] = [0.0] * len(points)
    original = deepcopy(guest["representation"])
    report = component.audit_finite_bodies(source, graph, rows, cores=cores)
    _record(tmp_path, source, report, rows)
    assert report["pass"], report["failure_reasons"]
    endpoint = next(item for item in report["endpoints"]
                    if item["guest_id"] == guest["stroke_id"] and item["end"] == attached_index)
    assert exact.decode_rational(endpoint["actual_native_terminal_segment_squared_length"]) == expected_squared
    assert endpoint["source_direction_pass"]
    assert all(observation["source_chord_squared_px"] >= 16
               for observation in endpoint["source_direction_observations"])
    assert guest["representation"] == original


def test_all_remote_sections_are_retained_when_constant_width_intersection_is_empty(tmp_path):
    source = np.full((80, 96), 255, dtype=np.uint8)
    source[37:44, 16:48] = 0
    source[39:42, 48:81] = 0
    graph, row = _sole_graph_row(source, [(16, 40), (80, 40)])
    width = component.measure_whole_chain_width(source, graph, row, [row])
    _record(tmp_path, source, width, [row])
    assert width["source_ports_enumerated"] == [[0, 0], [0, 1]]
    assert len(width["sections"]) == 6
    assert width["reason"] == "CONSTANT_WIDTH_MODEL_INAPPLICABLE"
    assert exact.decode_interval(width["half_width_squared_interval"]) == (Fraction(25, 4),) * 2
    assert width["lower_bound_section_indices"] and width["upper_bound_section_indices"]


def test_same_body_bend_is_excluded_from_independent_normal_evidence(tmp_path):
    source = _raster([((16, 24), (24, 24)), ((24, 24), (24, 64))])
    graph, row = _sole_graph_row(source, [(16, 24), (24, 24), (24, 64)])
    width = component.measure_whole_chain_width(source, graph, row, [row])
    _record(tmp_path, source, width, [row])
    excluded = [section for section in width["sections"]
                if section.get("same_body_noncollinear_finite_axes_excluded")
                and section["reason"] == "SECTION_NOT_INDEPENDENT_OF_JUNCTION_OR_OTHER_STROKE"]
    assert excluded
    assert all(not section["constraint_eligible"] for section in excluded)
    assert len(width["sections"]) == 6


def test_finite_union_positive_needs_every_participating_body():
    segments = [((4, 12), (20, 12)), ((12, 4), (12, 12)), ((16, 12), (16, 20))]
    source = _raster(segments, shape=(25, 25), radius=1)
    black, white = _cells(source)
    bodies = [_body(str(index), list(segment)) for index, segment in enumerate(segments)]
    complete = component.solve_finite_union(black, white, bodies)
    missing = component.solve_finite_union(black, white, bodies[:2])
    assert complete["pass"] and complete["existence_certificate_complete"]
    assert len(complete["black_witnesses"]) == len(black)
    assert len(complete["white_witnesses"]) == len(white)
    assert not missing["pass"] and missing["status"] == "NO_MODEL_BLACK_OUTSIDE_ALL_STRICT_ENVELOPES"
    assert any(cell[1] >= 18 for cell in missing["unexplained_black_cells"])


def test_strict_cap_upper_boundary_cannot_explain_a_real_tail_cell():
    body = _body("finite", [(4, 8), (12, 8)], lower=1, upper=Fraction(25, 4))
    result = component.solve_finite_union([[15, 8]], [], [body])
    assert not result["pass"]
    assert result["status"] == "NO_MODEL_BLACK_OUTSIDE_ALL_STRICT_ENVELOPES"
    assert result["unexplained_black_cells"] == [[15, 8]]


def test_observable_outward_source_extension_finds_a_finite_refusal_witness():
    source = _raster([((4, 12), (20, 12)), ((12, 4), (12, 18))], shape=(25, 25), radius=1)
    black, white = _cells(source)
    bodies = [_body("guest", [(12, 4), (12, 12)]), _body("host", [(4, 12), (20, 12)])]
    original = source.tobytes(), deepcopy(bodies)
    assert not component.solve_finite_union(black, white, bodies)["pass"]
    ledger = [{"source_cell": cell, "relevant_connected_ink": True,
               "compatible_body_ids": [body["stroke_id"] for body in bodies
                   if exact.cell_polyline_distance_squared(cell, body["representation"]["points"]) < Fraction(9, 4)]}
              for cell in black]
    endpoints = [{"guest_id": "guest", "end": 1, "host_id": "host", "source_direction_pass": True}]
    competition = component._continuation_events(source, bodies, bodies, endpoints, black, white, ledger, True)
    assert competition["distinct_observable_boundary_exists"]
    assert competition["status"] == "OBSERVABLE_FINITE_CONTINUATION_COMPETITOR_FOUND"
    assert any(event["coherent_with_original_black_and_white"] for event in competition["events"])
    assert all(event["adopted"] is False for event in competition["events"])
    assert competition["new_geometry_generated"] is False
    assert source.tobytes() == original[0] and bodies == original[1]


def test_enclosed_white_hole_and_preserved_white_gap_use_the_same_frozen_rule():
    hole = component.solve_finite_union([[8, 7]], [[8, 8]], [
        _body("body", [(4, 8), (12, 8)], lower=Fraction(9, 4), upper=4)])
    assert not hole["pass"] and hole["status"] == "NO_COHERENT_FINITE_UNION"
    parts = [[(4, 8), (8, 8)], [(10, 8), (14, 8)]]
    positive = component.solve_finite_union([[7, 8], [11, 8]], [[9, 8]],
                                           [_body(str(i), path) for i, path in enumerate(parts)])
    filled = component.solve_finite_union([[7, 8], [11, 8]], [[9, 8]],
        [_body(str(i), path, lower=Fraction(5, 4), upper=4) for i, path in enumerate(parts)])
    assert positive["pass"]
    assert not filled["pass"] and filled["states_rejected_by_common_white_witness"] == 1


def test_model_state_resource_stop_is_pending_not_an_infeasibility_claim():
    body = _body("finite", [(4, 8), (12, 8)], lower=0, upper=4)
    result = component.solve_finite_union([[8, 9]], [], [body], max_states=1)
    assert not result["pass"] and result["resource_truncated"]
    assert not result["search_complete"]
    assert result["status"] == "PENDING_EXACT_MODEL_SEARCH_RESOURCE_BOUND"
    assert result["visited_state_count"] == 1


def test_window_resource_stop_is_reported_without_adopting_or_erasing_source(monkeypatch):
    source, graph, rows, cores = _three_body_scene()
    original = source.tobytes()
    monkeypatch.setitem(component.POLICY, "maximum_window_cells", 1)
    report = component.audit_finite_bodies(source, graph, rows, cores=cores)
    assert not report["pass"]
    assert report["status"] == "PENDING_INVALID_OR_RESOURCE_LIMITED_COMPONENT_INPUT"
    assert "FINITE_COMPONENT_WINDOW_RESOURCE_BOUND" in report["failure_reasons"]
    assert source.tobytes() == original


def _tiny_gap_scene(displacement=1e-9):
    source, graph, rows, cores = _three_body_scene()
    guest_index = next(i for i, row in enumerate(rows)
                       if any("host_path_index" in terminal for terminal in row["endpoint_evidence"]))
    guest = rows[guest_index]
    end_index = next(i for i, terminal in enumerate(guest["endpoint_evidence"]) if "host_path_index" in terminal)
    terminal = guest["endpoint_evidence"][end_index]
    guest["representation"]["points"][0 if end_index == 0 else -1][1] += displacement
    return source, graph, rows, cores, guest_index, end_index, terminal["host_path_index"], terminal["node_id"]


def test_shared_vertex_construction_is_explicit_and_rechecks_actual_new_finite_geometry(tmp_path):
    source, graph, rows, cores, guest_index, end_index, host_index, _ = _tiny_gap_scene()
    before = deepcopy(rows)
    guest_point = rows[guest_index]["representation"]["points"][0 if end_index == 0 else -1]
    assert exact.point_polyline_distance_squared(guest_point, rows[host_index]["representation"]["points"]) > 0
    constructed, receipt = component.materialize_shared_vertices(source, graph, rows, cores)
    assert receipt["pass"], receipt["failure_reasons"]
    assert receipt["changed_candidate_count"] == 1
    assert receipt["guest_endpoints_modified"] is False and receipt["prior_objects_modified"] is False
    assert exact.point_polyline_distance_squared(guest_point, constructed[host_index]["representation"]["points"]) == 0
    assert constructed[guest_index]["representation"] == before[guest_index]["representation"]
    assert all(point in constructed[host_index]["representation"]["points"]
               for point in before[host_index]["representation"]["points"])
    for row in constructed:
        for terminal in row["endpoint_evidence"]:
            if "host_path_index" in terminal:
                assert terminal["host_path_id"] == constructed[terminal["host_path_index"]]["stroke_id"]
    report = component.audit_finite_bodies(source, graph, constructed, cores=cores)
    _record(tmp_path, source, {"construction": receipt, "component": report}, constructed)
    assert report["pass"], report["failure_reasons"]
    assert rows == before


def test_tiny_gap_without_an_independent_shared_source_core_is_not_closed():
    source, graph, rows, cores, _, _, _, nid = _tiny_gap_scene()
    cores[nid]["pass"] = False
    before = deepcopy(rows)
    returned, receipt = component.materialize_shared_vertices(source, graph, rows, cores)
    assert not receipt["pass"]
    assert receipt["failure_reasons"] == ["SHARED_VERTEX_HAS_NO_INDEPENDENT_SAME_SOURCE_CORE"]
    assert returned == before and rows == before


def test_shared_vertex_cannot_extend_the_actual_finite_host():
    source, graph, rows, cores, guest_index, end_index, host_index, _ = _tiny_gap_scene()
    guest_point = rows[guest_index]["representation"]["points"][0 if end_index == 0 else -1]
    host = rows[host_index]["representation"]
    host["points"] = [host["points"][0], [guest_point[0], 40.0]]
    host["bulges"] = [0.0, 0.0]
    _, receipt = component.materialize_shared_vertices(source, graph, rows, cores)
    assert not receipt["pass"]
    assert receipt["failure_reasons"] == ["SHARED_VERTEX_WOULD_EXTEND_FINITE_HOST"]


def test_shared_vertex_does_not_enlarge_the_frozen_construction_limit():
    source, graph, rows, cores, *_ = _tiny_gap_scene(displacement=2e-7)
    _, receipt = component.materialize_shared_vertices(source, graph, rows, cores)
    assert not receipt["pass"]
    assert receipt["failure_reasons"] == ["SHARED_VERTEX_EXCEEDS_EXISTING_CONSTRUCTION_PRECISION"]


def test_distinct_shared_points_with_exact_equal_host_projection_stay_competing():
    source, graph, rows, cores, guest_index, end_index, _, _ = _tiny_gap_scene()
    competing = deepcopy(rows[guest_index])
    competing["stroke_id"] = "AUTHORED_COMPETING_SOURCE_INTERPRETATION"
    competing["representation"]["points"][0 if end_index == 0 else -1][1] = 40.0 - 1e-9
    rows.append(competing)
    _, receipt = component.materialize_shared_vertices(source, graph, rows, cores)
    assert not receipt["pass"]
    assert receipt["failure_reasons"] == ["SHARED_VERTICES_HAVE_COMPETING_EQUAL_PROJECTIONS"]


def test_shared_vertex_never_modifies_a_necessary_prior_body():
    source, graph, rows, cores, _, _, host_index, _ = _tiny_gap_scene()
    rows[host_index]["body_role"] = "NECESSARY_PRIOR_FINITE_NEIGHBOR"
    before = deepcopy(rows)
    returned, receipt = component.materialize_shared_vertices(source, graph, rows, cores)
    assert not receipt["pass"]
    assert any("PRIOR" in reason for reason in receipt["failure_reasons"])
    assert returned == before and rows == before


def test_subpixel_shared_vertex_that_crosses_a_white_cell_is_rejected_exactly(tmp_path):
    source = np.full((96, 96), 255, dtype=np.uint8)
    for i in range(16, 81):
        source[i, i] = 0
        source[i + 1, i] = 0
    source[16:41, 40] = 0
    graph = build_text_contact_source_graph(source, [0, 0, 96, 96]).graph
    nid = next(nid for nid, node in graph.nodes.items() if len(node["edges"]) == 3)
    cores = {nid: planner._core_proof(source, graph, nid)}
    assert cores[nid]["pass"]
    host = {"stroke_id": "AUTHORED_ABOVE_GRID_CORNER_HOST", "source_node_ids": [nid],
            "representation": {"points": [[16.0, 16.0 + 1e-9], [80.0, 80.0 + 1e-9]], "closed": False},
            "source_path_px": [[i, i] for i in range(16, 81)], "endpoint_evidence": []}
    guest = {"stroke_id": "AUTHORED_BELOW_GRID_CORNER_GUEST", "source_node_ids": [nid],
             "representation": {"points": [[40.0, 40.0 - 1e-9], [40.0, 16.0]], "closed": False},
             "source_path_px": [[40, y] for y in range(40, 15, -1)],
             "endpoint_evidence": [{"node_id": nid, "host_path_index": 0}]}
    assert component.exact_centerline_source_support(source, component._points(host))["pass"]
    assert component.exact_centerline_source_support(source, component._points(guest))["pass"]
    original = deepcopy([host, guest])
    returned, receipt = component.materialize_shared_vertices(source, graph, [host, guest], cores)
    _record(tmp_path, source, receipt, original)
    assert not receipt["pass"]
    assert receipt["failure_reasons"] == ["SHARED_VERTEX_GEOMETRY_TOUCHES_ORIGINAL_WHITE_OR_UNOBSERVED_CELL"]
    assert [41, 40] in receipt["construction_white_cells"]
    assert returned == original
