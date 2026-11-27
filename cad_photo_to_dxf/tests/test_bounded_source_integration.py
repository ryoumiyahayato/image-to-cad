"""Discriminating boundaries of exact candidate and source ownership gates."""
from copy import deepcopy
from fractions import Fraction as F
import importlib.util
from pathlib import Path

import pytest

from app.native_objects import attached_stroke_graph as planner
from app.native_objects import attached_stroke_width_exact as exact
from app.native_objects import bounded_source_component as component

SPEC = importlib.util.spec_from_file_location("junction_small_inputs",
    Path(__file__).resolve().parents[2] / "experiments/issue63_bounded_source/run_junction_checkpoint.py")
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)


def test_new_candidate_uses_once_rounded_exact_source_intersection():
    source, graph, rows, _ = checkpoint.authored_scene("oblique")
    guest, end, host = checkpoint.attachments(rows)[0]
    geometry = deepcopy(rows[host]["representation"])
    geometry["points"][-1][1] = 48.2
    result = planner._attachment_endpoint(source, graph, rows[guest]["endpoint_evidence"][end], geometry)
    # Derive the rational intersection independently from the actual declared
    # host endpoints and the unchanged vertical raw-source chord.
    a, b = (tuple(map(F, p)) for p in geometry["points"][-2:])
    expected = F(40), a[1] + (F(40)-a[0]) * (b[1]-a[1]) / (b[0]-a[0])
    assert tuple(exact.decode_rational(v) for v in result["original_source_intersection_exact"]) == expected
    assert result["native_endpoint_px"] == list(map(float, expected))
    assert all(row["pass"] for row in result["native_rounding_certificate"])


def test_new_candidate_refuses_intersection_infinitesimally_outside_finite_host():
    source, graph, rows, _ = checkpoint.authored_scene("oblique")
    guest, end, _ = checkpoint.attachments(rows)[0]
    epsilon = 2.0 ** -40
    finite = {"points": [[40.0 + epsilon, 38.0 + epsilon / 4], [80.0, 48.0]],
              "closed": False, "bulges": [0., 0.]}
    with pytest.raises(ValueError, match="NO_UNIQUE_SOURCE_SUPPORTED_FINITE_HOST_INTERSECTION"):
        planner._attachment_endpoint(source, graph, rows[guest]["endpoint_evidence"][end], finite)


def test_nearly_parallel_far_intersection_is_rejected_before_raster_enumeration(monkeypatch):
    source, graph, rows, _ = checkpoint.authored_scene("oblique")
    guest, end, _ = checkpoint.attachments(rows)[0]
    host = {"points": [[41.0, 20.0], [41.0 + 2.0 ** -40, 60.0]], "closed": False, "bulges": [0., 0.]}
    def forbidden(*args):
        raise AssertionError("An unbounded rejected intersection must not enumerate raster cells")
    monkeypatch.setattr(exact, "segment_cells", forbidden)
    with pytest.raises(ValueError, match="NO_UNIQUE_SOURCE_SUPPORTED_FINITE_HOST_INTERSECTION"):
        planner._attachment_endpoint(source, graph, rows[guest]["endpoint_evidence"][end], host)


def test_source_branch_cannot_be_swallowed_by_a_large_width_claim():
    source, graph, rows, _ = checkpoint.authored_scene("axial")
    relevant = {tuple(map(int, p)) for edge in graph.edges for p in graph.xy(edge["pixels"])}
    full = component._source_edge_ledger(graph, rows, relevant)
    assert full["pass"]
    changed = deepcopy(rows)
    changed[0]["source_path_px"] = changed[0]["source_path_px"][:-5]
    # This deliberately large unrelated field claim must be ignored by the
    # original-edge gate; it is not admissible evidence of source ownership.
    changed[0]["bounded_width_field"] = {"pass": True, "claimed_radius": 10000}
    truncated = component._source_edge_ledger(graph, changed, relevant)
    assert not truncated["pass"]
    assert truncated["unassigned_original_edge_ids"]
    assert all(not row["width_coverage_consumed_as_ownership"] for row in truncated["relevant_edges"])


def test_all_measured_white_cells_survive_ineligible_section_status():
    import numpy as np
    source = np.full((16, 16), 255, dtype=np.uint8)
    source[8, 8] = 0
    body = {"stroke_id": "S", "width": {"sections": [{"constraint_eligible": False,
        "section_source_cells": [[8, 8], [8, 7], [8, 6]], "original_values": [0, 255, 255],
        "independent_black_cells": [[8, 8]], "first_white_cells": [[8, 7]]}]}}
    result = component._observations(source, [body], [[8, 8]], [])
    assert result["pass"]
    assert (8, 7) in result["white_cells"] and (8, 6) in result["white_cells"]
    assert result["owned_black_constraints"] == []
