"""Cold saved-file proof, using only small public synthetic source images."""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects.cad_io import cold_audit, export_objects, mark
from app.native_objects.connections import extract_connections


ROI = (0, 0, 220, 160)
DPI = 200


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(path, value):
    Path(path).write_text(json.dumps(value, indent=2))


@pytest.fixture(scope="module")
def source_template(tmp_path_factory, native_geometry_export_context):
    """Actual path discovery/export; font loading and rendering are not exercised."""
    folder = tmp_path_factory.mktemp("retrace-source")
    ink = np.zeros((160, 220), np.uint8)
    for center in ((25, 90), (195, 90)):
        cv2.circle(ink, center, 12, 1, 1)
    for points in (
        [(37, 90), (65, 69), (90, 63), (109, 60)],
        [(111, 60), (130, 63), (155, 69), (183, 90)],
    ):
        cv2.polylines(ink, [np.asarray(points, np.int32)], False, 1, 1)
    cv2.rectangle(ink, (109, 59), (111, 61), 1, 1)
    gray = np.where(ink, 0, 255).astype(np.uint8)
    discovered = extract_connections(
        gray, ROI, [], folder / "evidence/connections/discovery"
    )
    assert len(discovered["objects"]) == 1
    assert discovered["objects"][0]["kind"] == "CONNECTION_PATH"
    # The formal path geometry and cold audit are real. REVIEW labels are not
    # rendered or measured, so this fixture makes no font/resource claim.
    with native_geometry_export_context(discovered["objects"]):
        export_objects(
            discovered["objects"],
            folder / "result.dxf",
            ROI,
            DPI,
            hashlib.sha256(gray.tobytes()).hexdigest(),
        )
    return folder, gray


@pytest.fixture
def saved_case(source_template, tmp_path):
    folder, gray = source_template
    shutil.copytree(folder, tmp_path, dirs_exist_ok=True)
    return tmp_path, gray.copy()


def _meta(folder):
    return json.loads((folder / "result.objects.json").read_text())


def _cert(meta):
    return meta["objects"][0]["source_evidence"]["crossing_evidence"][0][
        "local_cycle_cover_evidence"
    ]


def _audit(case):
    folder, gray = case
    return cold_audit(
        folder / "result.dxf", gray, ROI, DPI, folder / "evidence/cold_audit.json"
    )


def _edit_dxf(folder, mutate, *, update_geometry=False):
    """Rebind only test files so deeper certificate guards are exercised."""
    path = folder / "result.dxf"
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace() if e.dxf.layer == "CONNECTIONS")
    mutate(doc, entity)
    doc.saveas(path)
    meta = _meta(folder)
    meta["dxf_sha256"] = _sha(path)
    if update_geometry:
        vertices = list(entity.get_points("xyb"))
        obj = meta["objects"][0]
        obj["geometry"] = {
            "points": [
                [x / (25.4 / DPI), ROI[3] - y / (25.4 / DPI)] for x, y, _ in vertices
            ],
            "bulges": [b for _, _, b in vertices],
            "closed": entity.closed,
        }
        obj["source_evidence"]["control_vertex_count"] = len(vertices)
    _save(folder / "result.objects.json", meta)


def _assert_retrace_rejected(report, reason=None):
    assert not report["certified_same_owner_retraces"]
    assert report["exact_duplicate_segments"]
    assert report["all_repeated_segments"] == report["exact_duplicate_segments"]
    if reason:
        failures = str(report["same_owner_retrace_cold_proof"]["object_checks"])
        assert reason in failures
        assert not report["source_gate_pass"]


def test_saved_continuous_source_cover_is_proven_by_handle_and_exact_segment_indices(
    saved_case,
):
    folder, gray = saved_case
    before = (_sha(folder / "result.dxf"), gray.copy())
    report = _audit(saved_case)
    assert report["source_gate_pass"]
    assert not report["ezdxf_errors"] and not report["ezdxf_in_memory_fixes"]
    assert not report["exact_duplicate_segments"]
    assert len(report["all_repeated_segments"]) == 4
    assert len(report["certified_same_owner_retraces"]) == 4
    proof = report["same_owner_retrace_cold_proof"]
    assert proof["evidence_status"] == "COMPLETE_COLD_PROOF"
    assert (
        proof["object_checks"][0]["cells"][0]["actual_white_minimum_clearance_px"] == 1
    )
    handle = _meta(folder)["written"][0]["handle"]
    for row in proof["allowances"]:
        assert row["handle"] == handle
        assert len(set(row["segment_indices"])) == 2
        assert row["source_owner_count"] == 1
        assert row["actual_traversal_count"] == 2
    assert before[0] == _sha(folder / "result.dxf")
    assert np.array_equal(before[1], gray)
    assert proof["TIFF_container_hash_verified_by_this_function"] is False


def test_noncertified_reverse_repetition_keeps_the_original_blocking_duplicate_gate(
    saved_case,
):
    folder, _ = saved_case
    meta = _meta(folder)
    meta["objects"][0]["source_evidence"]["crossing_evidence"] = []
    _save(folder / "result.objects.json", meta)
    _assert_retrace_rejected(_audit(saved_case))


def test_same_object_id_on_two_actual_handles_is_not_an_exemption(saved_case):
    folder, _ = saved_case
    _edit_dxf(folder, lambda doc, entity: doc.modelspace().add_entity(entity.copy()))
    report = _audit(saved_case)
    _assert_retrace_rejected(report, "EXACTLY_ONE_MODELSPACE_HANDLE")
    assert any(
        len(set(row["actual_handles"])) == 2
        for row in report["exact_duplicate_segments"]
    )


def test_another_formal_owner_cannot_claim_the_same_source_graph_edges(saved_case):
    folder, _ = saved_case
    other_id = "CONTROLLED-OTHER-OWNER"

    def duplicate(doc, entity):
        copied = entity.copy()
        doc.modelspace().add_entity(copied)
        mark(copied, {"id": other_id, "kind": "CONNECTION_PATH"})

    _edit_dxf(folder, duplicate)
    meta = _meta(folder)
    other = deepcopy(meta["objects"][0])
    other["id"] = other_id
    meta["objects"].append(other)
    doc = ezdxf.readfile(folder / "result.dxf")
    copied = [e for e in doc.modelspace() if e.dxf.layer == "CONNECTIONS"][-1]
    meta["written"].append(
        {**meta["written"][0], "id": other_id, "handle": copied.dxf.handle}
    )
    _save(folder / "result.objects.json", meta)
    _assert_retrace_rejected(
        _audit(saved_case), "SOURCE_GRAPH_ADJACENCY_HAS_ANOTHER_FORMAL_PATH_OWNER"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("thickness", 1e-8),
        ("elevation", 1),
        ("extrusion", (0, 1, 0)),
        ("const_width", 1e-8),
        ("linetype", "BYBLOCK"),
    ],
)
def test_extruded_wide_or_unresolved_strokes_cannot_use_a_centerline_certificate(
    saved_case, field, value
):
    folder, _ = saved_case
    _edit_dxf(folder, lambda _doc, e: e.dxf.set(field, value))
    _assert_retrace_rejected(_audit(saved_case))


@pytest.mark.parametrize("via_layer", [False, True])
def test_a_patterned_linetype_is_rejected_even_with_identical_vertices(
    saved_case, via_layer
):
    folder, _ = saved_case

    def patterned(doc, entity):
        doc.linetypes.new("CONTROLLED_DASH", dxfattribs={"pattern": [2.0, 1.0, -1.0]})
        if via_layer:
            doc.layers.get(entity.dxf.layer).dxf.linetype = "CONTROLLED_DASH"
        else:
            entity.dxf.linetype = "CONTROLLED_DASH"

    _edit_dxf(folder, patterned)
    _assert_retrace_rejected(_audit(saved_case), "EFFECTIVE_LINETYPE_IS_NOT_CONTINUOUS")


@pytest.mark.parametrize("column", [2, 3, 4])
def test_per_vertex_width_or_bulge_cannot_receive_a_retrace_allowance(
    saved_case, column
):
    folder, _ = saved_case

    def changed(_doc, entity):
        vertices = list(entity.get_points("xyseb"))
        row = list(vertices[0])
        row[column] = 0.01
        vertices[0] = row
        entity.set_points(vertices, format="xyseb")

    _edit_dxf(folder, changed)
    _assert_retrace_rejected(_audit(saved_case), "RETRACE_HAS_WIDTH_OR_BULGE")


def test_closed_polyline_cannot_receive_a_retrace_allowance(saved_case):
    folder, _ = saved_case
    _edit_dxf(folder, lambda _doc, entity: setattr(entity, "closed", True))
    _assert_retrace_rejected(_audit(saved_case), "ONE_OPEN_TOP_LEVEL_LWPOLYLINE")


@pytest.mark.parametrize(
    "case",
    ["missing_graph", "wrong_graph_hash", "wrong_source_crop", "missing_sidecar"],
)
def test_missing_or_unbound_evidence_never_waives_repetitions(saved_case, case):
    folder, gray = saved_case
    graph = folder / "evidence/connections/discovery/source_graph.json"
    if case == "missing_graph":
        graph.unlink()
    elif case == "wrong_graph_hash":
        graph.write_text(graph.read_text() + " ")
    elif case == "wrong_source_crop":
        gray[1, 1] = 0
    else:
        (folder / "result.objects.json").unlink()
    _assert_retrace_rejected(_audit(saved_case))


@pytest.mark.parametrize(
    "case", ["object_id", "written_id", "written_handle", "dxf_hash", "roi", "dpi"]
)
def test_sidecar_identity_and_coordinate_bindings_are_not_silently_overwritten(
    saved_case, case
):
    folder, _ = saved_case
    meta = _meta(folder)
    if case == "object_id":
        meta["objects"].append(deepcopy(meta["objects"][0]))
    elif case == "written_id":
        meta["written"].append(deepcopy(meta["written"][0]))
    elif case == "written_handle":
        meta["written"].append({**meta["written"][0], "id": "OTHER"})
    elif case == "dxf_hash":
        meta["dxf_sha256"] = "0" * 64
    elif case == "roi":
        meta["roi_xyxy_px"][0] += 1
    else:
        meta["dpi"] += 1
    _save(folder / "result.objects.json", meta)
    _assert_retrace_rejected(_audit(saved_case))


@pytest.mark.parametrize(
    "case",
    [
        "white_missing",
        "white_shifted",
        "white_eight_contacts",
        "neighborhood_hash",
        "walk",
        "counter",
        "overlap",
    ],
)
def test_stale_or_incomplete_cell_proofs_fail_closed(saved_case, case):
    folder, _ = saved_case
    meta = _meta(folder)
    cert = _cert(meta)
    hole = cert["original_source_hole_evidence"]
    if case == "white_missing":
        del cert["original_source_hole_evidence"]
    elif case == "white_shifted":
        hole["enclosed_white_hole_points"][0][0] += 1
    elif case == "white_eight_contacts":
        hole["white_eight_neighborhood_boundary_contacts"].append([107, 58])
    elif case == "neighborhood_hash":
        hole["thresholded_source_neighborhood_sha256"] = "0" * 64
    elif case == "walk":
        cert["finite_cover_walks"][0]["source_walk_points"].pop(2)
    elif case == "counter":
        cert["finite_cover_walks"][0]["source_edge_traversals"][0][
            "traversal_count"
        ] += 1
    else:
        crossings = meta["objects"][0]["source_evidence"]["crossing_evidence"]
        crossings.append(deepcopy(crossings[0]))
    _save(folder / "result.objects.json", meta)
    _assert_retrace_rejected(_audit(saved_case))


def test_a_raw_port_cannot_be_hidden_from_the_source_cell_declaration(saved_case):
    folder, _ = saved_case
    root = folder / "evidence/connections/discovery"
    graph = json.loads((root / "source_graph.json").read_text())
    cell_id = _cert(_meta(folder))["cell_node_ids"][0]
    next(n for n in graph["nodes"] if n["id"] == cell_id)["all_ports"].pop()
    _save(root / "source_graph.json", graph)
    discovery = json.loads((root / "connections.json").read_text())
    discovery["source_graph"]["sha256"] = _sha(root / "source_graph.json")
    _save(root / "connections.json", discovery)
    _assert_retrace_rejected(
        _audit(saved_case), "RAW_CELL_PORTS_DO_NOT_INCLUDE_ALL_ACTUAL_GRAPH_EDGE_ENDS"
    )


def test_changed_vertices_fail_even_if_the_test_sidecar_geometry_is_rebound(saved_case):
    folder, _ = saved_case

    def changed(_doc, entity):
        vertices = list(entity.get_points("xyseb"))
        row = list(vertices[9])
        row[0] += (25.4 / DPI) * 0.25
        vertices[9] = row
        entity.set_points(vertices, format="xyseb")

    _edit_dxf(folder, changed, update_geometry=True)
    _assert_retrace_rejected(
        _audit(saved_case), "PROTECTED_WALK_NOT_ONE_CONTIGUOUS_ACTUAL_VERTEX_RUN"
    )


def test_extra_retraversal_outside_the_protected_run_is_not_covered_by_a_good_cell(
    saved_case,
):
    folder, _ = saved_case

    def extra(_doc, entity):
        vertices = list(entity.get_points("xyseb"))
        # Preserve the complete good cell and both real endpoints, but add an
        # unproved reverse traversal of the last approach segment.
        entity.set_points(vertices + vertices[-2:], format="xyseb")

    _edit_dxf(folder, extra, update_geometry=True)
    _assert_retrace_rejected(
        _audit(saved_case),
        "ACTUAL_NATIVE_RETRACE_POSITIONS_OR_MULTIPLICITIES_NOT_EXACT",
    )


def test_removing_the_repeated_arc_does_not_turn_a_changed_object_into_a_pass(
    saved_case,
):
    folder, _ = saved_case

    def remove(_doc, entity):
        vertices = list(entity.get_points("xyseb"))
        entity.set_points(vertices[:8] + vertices[16:], format="xyseb")

    _edit_dxf(folder, remove, update_geometry=True)
    report = _audit(saved_case)
    assert not report["source_gate_pass"]
    assert not report["local_retrace_certificate_gate_pass"]
    assert not report["certified_same_owner_retraces"]
    assert "PROTECTED_WALK" in str(
        report["same_owner_retrace_cold_proof"]["object_checks"]
    )


def test_an_unordered_edge_counter_cannot_substitute_for_the_actual_protected_walk(
    saved_case,
):
    folder, _ = saved_case

    def reorder(_doc, entity):
        vertices = list(entity.get_points("xyseb"))
        original = vertices[3:18]
        changed = original[:6] + original[4:0:-1] + original[8:4:-1] + original[-1:]

        def edges(points):
            return Counter(
                tuple(sorted((tuple(a[:2]), tuple(b[:2]))))
                for a, b in zip(points, points[1:])
            )

        assert len(original) == len(changed)
        assert edges(original) == edges(changed)
        assert original != changed
        entity.set_points(vertices[:3] + changed + vertices[18:], format="xyseb")

    _edit_dxf(folder, reorder, update_geometry=True)
    _assert_retrace_rejected(
        _audit(saved_case), "PROTECTED_WALK_NOT_ONE_CONTIGUOUS_ACTUAL_VERTEX_RUN"
    )


def test_the_continuous_name_cannot_conceal_an_actual_dot_pattern(saved_case):
    folder, _ = saved_case

    def dotted(doc, _entity):
        doc.linetypes.get("CONTINUOUS").setup_pattern([0, 0])

    _edit_dxf(folder, dotted)
    _assert_retrace_rejected(_audit(saved_case), "CONTINUOUS_LINETYPE_HAS_A_PATTERN")


@pytest.mark.parametrize("case", ["crossing_type", "source_evidence_type", "cell_type"])
def test_malformed_proof_records_become_failures_and_do_not_crash_the_cold_reader(
    saved_case, case
):
    folder, _ = saved_case
    meta = _meta(folder)
    if case == "source_evidence_type":
        meta["objects"][0]["source_evidence"] = None
    elif case == "crossing_type":
        meta["objects"][0]["source_evidence"]["crossing_evidence"] = [None]
    else:
        meta["objects"][0]["source_evidence"]["crossing_evidence"][0][
            "local_cycle_cover_evidence"
        ] = ["invalid"]
    _save(folder / "result.objects.json", meta)
    _assert_retrace_rejected(_audit(saved_case))
