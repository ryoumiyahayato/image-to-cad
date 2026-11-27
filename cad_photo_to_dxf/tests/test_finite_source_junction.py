"""Discriminating source/refusal controls and real two-process saved contacts."""
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path

import pytest

from app.native_objects import attached_stroke_graph as planner
from app.native_objects import finite_source_junction as junction


SPEC = importlib.util.spec_from_file_location(
    "issue63_junction_checkpoint",
    Path(__file__).resolve().parents[2] / "experiments/issue63_bounded_source/run_junction_checkpoint.py")
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)


def _reference():
    terminal = {"host_path_id": "HOST", "host_path_index": 1, "host_source_graph_edge_ids": [7, 8]}
    rows = [{"stroke_id": "GUEST", "endpoint_evidence": [terminal], "source_graph_edge_ids": [3]},
            {"stroke_id": "HOST", "endpoint_evidence": [], "source_graph_edge_ids": [7, 8]},
            {"stroke_id": "OTHER", "endpoint_evidence": [], "source_graph_edge_ids": [9]}]
    return terminal, rows, {row["stroke_id"]: index for index, row in enumerate(rows)}


@pytest.mark.parametrize("missing", [None, "host_path_id", "host_path_index"])
def test_host_reference_accepts_absent_optional_field_and_checks_actual_identity(missing):
    terminal, rows, by_id = _reference()
    if missing is not None:
        terminal.pop(missing)
    assert junction._host_index(terminal, rows, by_id) == 1


@pytest.mark.parametrize("change,reason", [
    ({"host_path_id": "ABSENT"}, "EXPLICIT_HOST_ID_IS_UNKNOWN"),
    ({"host_path_id": None}, "EXPLICIT_HOST_ID_IS_UNKNOWN"),
    ({"host_path_id": ""}, "EXPLICIT_HOST_ID_IS_UNKNOWN"),
    ({"host_path_id": "OTHER"}, "NAME_INDEX_AND_OBJECT_IDENTITY_DISAGREE"),
    ({"host_path_index": None}, "EXPLICIT_HOST_INDEX_IS_INVALID"),
    ({"host_path_index": True}, "EXPLICIT_HOST_INDEX_IS_INVALID"),
    ({"host_path_index": 1.0}, "EXPLICIT_HOST_INDEX_IS_INVALID"),
    ({"host_path_index": "1"}, "EXPLICIT_HOST_INDEX_IS_INVALID"),
    ({"host_path_index": -1}, "EXPLICIT_HOST_INDEX_IS_INVALID"),
    ({"host_path_index": 3}, "EXPLICIT_HOST_INDEX_IS_INVALID"),
    ({"host_path_id": "GUEST", "host_path_index": 0}, "CANNOT_USE_ITSELF"),
    ({"host_source_graph_edge_ids": [9]}, "SOURCE_BINDING_DOES_NOT_MATCH"),
])
def test_explicit_host_reference_corruption_cannot_fall_back(change, reason):
    terminal, rows, by_id = _reference()
    terminal.update(change)
    with pytest.raises(ValueError, match=reason):
        junction._host_index(terminal, rows, by_id)


def test_stale_lookup_and_foreign_terminal_cannot_impersonate_the_actual_objects():
    terminal, rows, by_id = _reference()
    by_id["HOST"] = 2
    with pytest.raises(ValueError, match="ACTUAL_CANDIDATE_IDENTITIES"):
        junction._host_index(terminal, rows, by_id)
    by_id["HOST"] = 1
    with pytest.raises(ValueError, match="ACTUAL_GUEST_IDENTITY"):
        junction._host_index(deepcopy(terminal), rows, by_id)
    with pytest.raises(ValueError, match="DOES_NOT_BELONG"):
        junction._host_index(terminal, rows, by_id, guest_index=2)
    rows[2]["endpoint_evidence"].append(terminal)
    with pytest.raises(ValueError, match="ONE_ACTUAL_GUEST_IDENTITY"):
        junction._host_index(terminal, rows, by_id, guest_index=0)


@pytest.mark.parametrize("kind", ["axial", "oblique"])
def test_raw_source_domains_and_shared_construction_preserve_all_original_values(kind):
    source, graph, rows, _ = checkpoint.authored_scene(kind)
    original_rows, original_graph, original_source = deepcopy(rows), planner._plain(graph.nodes), source.tobytes()
    result, receipt = junction.materialize_shared_vertices_v2(source, graph, rows, {0: {"pass": False}})
    assert receipt["pass"], receipt["failure_reasons"]
    assert not receipt["cached_core_pass_used"]
    assert len(receipt["insertions"]) == 2
    assert rows == original_rows and planner._plain(graph.nodes) == original_graph and source.tobytes() == original_source
    for old, new in zip(rows, result):
        assert checkpoint._subsequence(old["representation"]["points"], new["representation"]["points"])
        assert old["representation"]["points"][0] == new["representation"]["points"][0]
        assert old["representation"]["points"][-1] == new["representation"]["points"][-1]
    for attempt in receipt["attempts"]:
        domain = attempt["source_domain"]
        assert domain["pass"] and domain["locator_padding_px"] == 0
        assert len(domain["all_original_external_ports"]) == 3
        assert all(spoke["pass"] for spoke in domain["all_original_arm_spokes"])
        if kind == "oblique":
            assert domain["inside_skeleton_core_closed_cells"] is False
    # Public receipts must be JSON-native, including source-graph NumPy values.
    json.dumps(receipt, allow_nan=False)
    again, replay = junction.materialize_shared_vertices_v2(source, graph, result)
    assert replay["pass"] and not replay["insertions"]
    assert [row["representation"] for row in again] == [row["representation"] for row in result]


def test_one_ulp_wrong_near_point_is_refused_without_a_fixed_epsilon():
    source, graph, rows, cores = checkpoint.authored_scene()
    guest, end, _ = checkpoint.attachments(rows)[0]
    point = rows[guest]["representation"]["points"][0 if end == 0 else -1]
    before_value = point[1]
    point[1] = math.nextafter(point[1], math.inf)
    assert 0 < point[1] - before_value < 1e-7
    original = deepcopy(rows)
    result, receipt = junction.materialize_shared_vertices_v2(source, graph, rows, cores)
    assert not receipt["pass"] and result == original and rows == original
    assert receipt["attempts"][0]["source_domain"]["pass"]
    assert receipt["failure_reasons"] == ["NO_UNIQUE_CORRECTLY_ROUNDED_ORIGINAL_SOURCE_INTERSECTION"]


@pytest.mark.parametrize("marker", [
    {"body_role": "NECESSARY_PRIOR_FINITE_PORT"},
    {"role": "NECESSARY_PRIOR_FINITE_PORT"},
    {"body_role": "UNKNOWN_BODY_ROLE"},
    {"body_role": "COMPLETE_TARGET_STROKE", "prior_binding": {}},
    {"full_saved_geometry": None},
    {"parent_object_id": "OLD_FORMAL_OBJECT"},
    {"prior_source_binding": {}},
])
def test_prior_finite_port_or_saved_identity_never_enters_new_candidate_reconstruction(marker):
    source, graph, rows, cores = checkpoint.authored_scene()
    _, _, host_index = checkpoint.attachments(rows)[0]
    rows[host_index].update(marker)
    original = deepcopy(rows)
    result, receipt = junction.materialize_shared_vertices_v2(source, graph, rows, cores)
    assert not receipt["pass"] and result == original and rows == original
    assert receipt["failure_reasons"] == ["SHARED_VERTEX_CONSTRUCTOR_ACCEPTS_NEW_CANDIDATES_ONLY"]
    assert not receipt["attempts"] and not receipt["insertions"]


def test_binary64_certificate_handles_derived_half_ulp_and_ties_to_even():
    even, odd = 1.0, math.nextafter(1.0, math.inf)
    midpoint = (Fraction.from_float(even) + Fraction.from_float(odd)) / 2
    assert junction.nearest_binary64_certificate(even, midpoint)["pass"]
    assert not junction.nearest_binary64_certificate(odd, midpoint)["pass"]
    exact_third = Fraction(1, 3)
    rounded = float(exact_third)
    assert junction.nearest_binary64_certificate(rounded, exact_third)["pass"]
    assert not junction.nearest_binary64_certificate(math.nextafter(rounded, math.inf), exact_third)["pass"]


def test_finite_host_global_end_is_not_authorized_by_a_repeated_internal_vertex():
    location = junction._finite_host_location((Fraction(0), Fraction(0)),
                                              [(0, 0), (1, 0), (0, 0), (2, 0)])
    assert not location["pass"]


def test_actual_writer_exit_then_cold_reader_preserves_contacts_and_refuses_corruption(tmp_path):
    directory = tmp_path / "checkpoint"
    manifest = checkpoint.run(directory)
    assert manifest["pass"]
    assert manifest["writer_exited_before_reader_started"]
    assert manifest["writer_pid"] != manifest["reader_pid"]
    writer = json.loads((directory / "WRITER.json").read_text(encoding="utf-8"))
    reader = json.loads((directory / "COLD_READER.json").read_text(encoding="utf-8"))
    assert all(writer["negative_source_controls"].values())
    assert reader["construction_pass_consumed"] is False
    for case in reader["cases"].values():
        assert case["saved"]["pass"] and not case["tampered"]["pass"]
        assert all(case["saved"]["all_original_vertices_retained"])
        assert all(case["saved_source_domain_pass"])
        assert all(contact["exact_finite_incidence"] and contact["explicit_shared_internal_vertex"]
                   for contact in case["saved"]["contacts"])
    # This particular ordinary translation/unit conversion must expose the
    # pre-construction implicit-contact bug, not merely test a trivial exact axis.
    assert not any(contact["exact_finite_incidence"]
                   for contact in reader["cases"]["oblique"]["before_implicit"]["contacts"])
    negative = json.loads((directory / "SOURCE_NEGATIVES.json").read_text(encoding="utf-8"))
    assert "WHITE_HOLE_OR_INTERNAL_END" in " ".join(negative["white_hole"]["constructor_receipt"]["failure_reasons"])
    assert "THREE_ORIGINAL_EXTERNAL_ARMS" in " ".join(negative["fourth_arm"]["constructor_receipt"]["failure_reasons"])
    assert negative["white_gap"]["fresh_original_graph"]
    assert all(Path(phase["external_log"]).parent == directory.parent for phase in manifest["phases"].values())
