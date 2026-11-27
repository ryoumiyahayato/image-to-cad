"""Frozen local controls for the finite attached-end raw-ink contract.

The five 96x96 capsule scenes follow the independently written contract appendix.
Every image gets a fresh original source graph. These tests bind actual graph
ports for the pure local gate; they do not manufacture an adopted owner or claim
that a two-arm L is an ordinary three-arm attached-stroke discovery positive.
"""
from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest

from app.native_objects import attached_stroke_ink as ink
from app.native_objects.text_contact_geometry import build_text_contact_source_graph


SHAPE = (96, 96)
ROI = [0, 0, 96, 96]
JUNCTION = [40.0, 48.0]


def _capsule_mask(a, b, radius=2.0):
    """Author an input image from pixel-center sampling of a finite capsule.

    This fixture rasterizer is separate from the production closed-cell proof.
    The explicit radius/segments were frozen before any new gate was run.
    """
    yy, xx = np.indices(SHAPE)
    points = np.stack((xx, yy), axis=-1).astype(float)
    start, end = np.asarray(a, float), np.asarray(b, float)
    delta = end - start
    fractions = np.clip((points - start) @ delta / float(delta @ delta), 0, 1)
    nearest = start + fractions[..., None] * delta
    return np.sum((points - nearest) ** 2, axis=-1) <= radius * radius


def _representation(a, b):
    return {"points": [list(a), list(b)], "bulges": [0.0, 0.0], "closed": False}


def _fresh_scene(variant="normal"):
    source_guest_end = (40, 56) if variant == "clear_extension" else (40, 48)
    source_host_end = (40, 48) if variant in ("finite_host_cap", "shortened_host_cap") else (76, 48)
    mask = _capsule_mask((40, 12), source_guest_end) | _capsule_mask((12, 48), source_host_end)
    if variant == "disconnected":
        mask |= _capsule_mask((40, 58), (40, 64))
    if variant == "white_hole":
        # A completely surrounded original white cell off both native axes.
        mask[47, 41] = False
    if variant == "strict_upper_cell":
        # Its closed cell is exactly 3.5 px from both finite terminal axes.
        mask[52, 40] = True
    gray = np.where(mask, 0, 255).astype(np.uint8)
    context = build_text_contact_source_graph(gray, ROI)
    guest = _representation((40, 12), (40, 48))
    candidate_host_end = ((35, 48) if variant == "wrong_finite_host" else
                          (36, 48) if variant == "shortened_host_cap" else source_host_end)
    host = _representation((12, 48), candidate_host_end)
    return gray, context, guest, host


def _bind_actual_t(context, guest_geometry, host_geometry):
    graph = context.graph
    junctions = [nid for nid, node in graph.nodes.items() if len(node["edges"]) >= 3]
    assert junctions, "The fixed input has no actual junction node to test."
    nid = min(junctions, key=lambda key: float(np.min(np.linalg.norm(
        graph.xy(graph.nodes[key]["pixels"]) - JUNCTION, axis=1))))
    assert np.min(np.linalg.norm(graph.xy(graph.nodes[nid]["pixels"]) - JUNCTION, axis=1)) < 6

    def displacement(port):
        samples = graph.xy(graph.oriented(port))
        return samples[-1] - samples[0]

    guest_ports = [port for port in graph.nodes[nid]["edges"]
                   if displacement(port)[1] < -abs(displacement(port)[0])]
    host_ports = [port for port in graph.nodes[nid]["edges"]
                  if abs(displacement(port)[0]) > abs(displacement(port)[1])]
    assert len(guest_ports) == 1 and len(host_ports) == 2

    def row(identity, geometry, ports):
        edge_ids = sorted({port[0] for port in ports})
        return {"stroke_id": identity, "representation": geometry,
                "source_graph_edge_ids": edge_ids,
                "source_node_ids": sorted({node for eid in edge_ids for node in graph.edges[eid]["nodes"]})}

    guest = row("authored-capsule-guest", guest_geometry, guest_ports)
    host = row("authored-capsule-host", host_geometry, host_ports)
    terminal = {"node_id": nid, "port": list(guest_ports[0]), "native_endpoint_px": list(JUNCTION)}
    return terminal, guest, host


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _record(tmp_path, source, context, report):
    np.save(tmp_path / "original_source.npy", source)
    (tmp_path / "receipt.json").write_text(
        json.dumps(_plain(report), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (tmp_path / "source_identity.json").write_text(json.dumps({
        "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "fresh_graph_source_crop_sha256": context.source_crop_hash,
        "fresh_graph_skeleton_sha256": hashlib.sha256(context.graph.skel.tobytes()).hexdigest(),
        "source_graph_rebuilt_for_this_image": True,
        "producer_sha256": ink.producer_sha256(),
        "scope": "LOCAL_DEVELOPMENT_CONTROL_NOT_ORDINARY_ADOPTION",
    }, indent=2) + "\n", encoding="utf-8")


def _prove(tmp_path, variant="normal"):
    source, context, guest_geometry, host_geometry = _fresh_scene(variant)
    terminal, guest, host = _bind_actual_t(context, guest_geometry, host_geometry)
    original_bytes = source.tobytes()
    original = deepcopy((terminal, guest, host))
    report = ink.prove_attached_endpoint_raw_responsibility(
        source, context.graph, terminal, guest, host, [guest, host])
    _record(tmp_path, source, context, report)
    assert source.tobytes() == original_bytes
    assert (terminal, guest, host) == original
    assert context.source_crop_hash == hashlib.sha256(source.tobytes()).hexdigest()
    return source, context, report


def test_constant_width_round_t_is_a_positive_terminal_control(tmp_path):
    _, _, report = _prove(tmp_path)
    assert report["pass"], report["failure_reasons"]
    assert report["status"] == "PROVED_TERMINAL"
    assert report["finite_host_contact"]["pass"]
    assert report["guest_object_to_source"]["pass"] and report["host_object_to_source"]["pass"]
    for width in report["independent_width_evidence"].values():
        assert width["pass"] and width["independent_section_count"] >= 2
        assert width["half_width_interval_px"] == [1.5, 3.5]
        assert width["upper_bound_is_strict"]
    assert report["coherent_terminal_models"]["pass"]
    assert report["complete_pixel_accounting"]
    assert report["unexplained_original_cells"] == []
    assert report["junction_normalization"]["canonical_native_endpoint_proved"]
    assert report["junction_normalization"]["physical_subpixel_termination_identifiable"] is False


def test_observable_eight_pixel_continuation_refuses_old_terminal_without_drawing(tmp_path):
    _, _, report = _prove(tmp_path, "clear_extension")
    assert not report["pass"]
    assert "PENDING_UNEXPLAINED_INK" in report["failure_reasons"]
    assert any(cell[1] > 50 for cell in report["unexplained_original_cells"])
    assert report["short_continuation_competition"]["distinct_observable_boundary_exists"]
    assert all(event["adopted"] is False for event in report["short_continuation_competition"]["events"])
    assert report["new_geometry_generated"] is False
    assert report["actual_native_endpoint_px"] == JUNCTION


def test_disconnected_neighbor_does_not_extend_the_ordinary_cap(tmp_path):
    source, context, report = _prove(tmp_path, "disconnected")
    assert report["pass"], report["failure_reasons"]
    assert report["actual_native_endpoint_px"] == JUNCTION
    assert not report["short_continuation_competition"]["distinct_observable_boundary_exists"]
    assert np.all(source[51:56, 37:44] == 255)
    # The normal proof need not expand past its closed envelope. Independently
    # examine a wider original patch to verify the authored neighbor's identity.
    patch, black, own, _, _, _ = ink._patch(source, context.graph, np.asarray(JUNCTION), 20)
    assert patch["connected_component_count"] == 2
    assert np.any(black[:, 1] >= 56)
    assert not np.any(own[black[:, 1] >= 56])


def test_wrong_finite_host_is_not_licensed_by_its_infinite_axis(tmp_path):
    _, _, report = _prove(tmp_path, "wrong_finite_host")
    assert not report["pass"]
    assert "REJECTED_SOURCE_OR_FINITE_CONTACT_CONTRADICTION" in report["failure_reasons"]
    assert report["host_object_to_source"]["pass"]
    assert report["finite_host_contact"] == {
        "pass": False, "segment_index": 0, "fraction": 1.0, "distance_px": 5.0}
    assert report["new_geometry_generated"] is False


def _finite_cap_geometry_control(tmp_path, variant):
    source, context, guest_geometry, host_geometry = _fresh_scene(variant)
    guest, host = np.asarray(guest_geometry["points"]), np.asarray(host_geometry["points"])
    guest_width = ink._section(source, np.array([40.0, 28.0]), np.array([0.0, 1.0]), [host], set())
    host_width = ink._section(source, np.array([24.0, 48.0]), np.array([1.0, 0.0]), [guest], set())
    assert guest_width["pass"] and host_width["pass"]
    yy, xx = np.indices(SHAPE)
    local = (xx >= 30) & (xx <= 50) & (yy >= 38) & (yy <= 58)
    black = np.column_stack(np.nonzero(local & (source < 128))[::-1])
    white = np.column_stack(np.nonzero(local & (source >= 128))[::-1])
    models = ink._coherent_models(black, white, guest, host,
                                 [guest_width["half_width_interval_px"], host_width["half_width_interval_px"]])
    distance, segment, fraction, _ = ink._point_distances([JUNCTION], host)
    report = {"scope": "FINITE_CAP_GEOMETRY_CONTROL_NOT_A_THREE_ARM_DISCOVERY",
              "guest_width": guest_width, "host_width": host_width, "coherent_models": models,
              "finite_host_distance_px": float(distance[0]), "finite_host_segment": int(segment[0]),
              "finite_host_fraction": float(fraction[0]),
              "guest_object_to_source": ink._source_centerline_check(source, guest),
              "host_object_to_source": ink._source_centerline_check(source, host)}
    _record(tmp_path, source, context, report)
    return source, guest, host, report


def test_real_finite_host_cap_has_original_round_cap_support(tmp_path):
    source, _, host, report = _finite_cap_geometry_control(tmp_path, "finite_host_cap")
    assert report["coherent_models"]["pass"]
    assert report["finite_host_distance_px"] == 0 and report["finite_host_fraction"] == 1
    assert report["guest_object_to_source"]["pass"] and report["host_object_to_source"]["pass"]
    assert source[48, 42] == 0
    assert ink._pixel_role(np.array([42.0, 48.0]), host, "FINITE_HOST") == "FINITE_HOST_NORMAL_CAP"
    assert ink._cell_min_distances([[42.0, 48.0]], host).tolist() == [1.5]


def test_shortened_real_host_does_not_retain_the_same_finite_contact(tmp_path):
    _, _, _, report = _finite_cap_geometry_control(tmp_path, "shortened_host_cap")
    assert report["host_object_to_source"]["pass"]
    assert report["finite_host_distance_px"] == 4.0
    assert report["finite_host_fraction"] == 1.0
    # Capsule union compatibility alone cannot grant the missing finite contact.
    # This L fixture is intentionally not claimed as a three-arm adoption run.


def test_off_axis_original_white_hole_is_preserved_and_refuses_capsule_fill(tmp_path):
    source, _, report = _prove(tmp_path, "white_hole")
    assert source[47, 41] == 255
    assert report["guest_object_to_source"]["pass"] and report["host_object_to_source"]["pass"]
    assert not report["pass"]
    assert any(component["enclosed_original_white_hole"] and [41, 47] in component["source_cells"]
               for component in report["original_patch"]["original_white_components"])
    models = report["coherent_terminal_models"]
    assert models is not None and not models["pass"]
    assert any([41, 47] in model.get("unresolved_white_cells", []) for model in models["rejected_models"])


def test_independent_half_width_upper_bound_is_strict_without_epsilon_credit(tmp_path):
    source, context, guest_geometry, host_geometry = _fresh_scene("strict_upper_cell")
    guest, host = np.asarray(guest_geometry["points"]), np.asarray(host_geometry["points"])
    section = ink._section(source, np.array([40.0, 28.0]), np.array([0.0, 1.0]), [host], set())
    assert section["pass"] and section["half_width_interval_px"] == [1.5, 3.5]
    assert section["upper_bound_is_strict"]
    black = np.array([[40.0, 52.0]])
    assert source[52, 40] == 0
    assert ink._cell_min_distances(black, guest).tolist() == [3.5]
    assert ink._cell_min_distances(black, host).tolist() == [3.5]
    strict = ink._coherent_models(black, [], guest, host, [[1.5, 3.5], [1.5, 3.5]])
    just_above = ink._coherent_models(black, [], guest, host,
                                    [[1.5, float(np.nextafter(3.5, np.inf))], [1.5, 3.5]])
    _record(tmp_path, source, context, {"scope": "SINGLE_CELL_WIDTH_BOUND_KERNEL_NOT_FULL_ADOPTION",
                                      "section": section, "strict": strict, "just_above": just_above})
    assert not strict["pass"]
    assert just_above["pass"]
    assert just_above["feasible_models"][0]["guest_half_width_px"] == 3.5


@pytest.mark.parametrize(("radius", "expected_pass"), [(0.5, False), (0.49, True)])
def test_white_exterior_requires_a_common_witness_outside_both_capsules(tmp_path, radius, expected_pass):
    guest = np.array([[47.5, 45.0], [47.5, 51.0]])
    host = np.array([[48.5, 45.0], [48.5, 51.0]])
    mask = _capsule_mask(*guest, radius=0.5) | _capsule_mask(*host, radius=0.5)
    mask[48, 48] = False
    source = np.where(mask, 0, 255).astype(np.uint8)
    context = build_text_contact_source_graph(source, ROI)
    white = np.array([[48.0, 48.0]])
    witnesses = white[:, None, :] + np.array([(x, y) for y in (-0.5, 0, 0.5) for x in (-0.5, 0, 0.5)])
    guest_distance = ink._point_distances(witnesses.reshape(-1, 2), guest)[0]
    host_distance = ink._point_distances(witnesses.reshape(-1, 2), host)[0]
    assert np.any(guest_distance > radius) and np.any(host_distance > radius)
    report = ink._coherent_models([], white, guest, host, [[radius, 0.75], [radius, 0.75]])
    _record(tmp_path, source, context, {"scope": "WHITE_UNION_KERNEL_NOT_FULL_ADOPTION", "models": report})
    assert report["pass"] is expected_pass
    if not expected_pass:
        assert not np.any((guest_distance > radius) & (host_distance > radius))
        assert report["rejected_models"][0]["reason"] == "WHITE_CELL_HAS_NO_PROVED_EXTERIOR_POINT"
