"""Independent source-topology regressions using synthetic, public-safe pixels.

These examples exercise ownership and absence of invented ink, not any private
drawing coordinates, expected OCR answer, or page-specific adoption whitelist.
"""

from __future__ import annotations

import json
import time

import cv2
import numpy as np

from app.native_objects.connections import (
    _SourceGraph,
    _dense_geometry,
    extract_connections,
)


ROI = (0, 0, 160, 160)


def _graph(ink):
    return _SourceGraph(ink.astype(bool), (0, 0), [], ROI, time.process_time())


def _extract(ink, out, *, text_regions=None):
    gray = np.where(ink, 0, 255).astype(np.uint8)
    untouched = gray.copy()
    result = extract_connections(gray, ROI, [], out, text_regions=text_regions)
    assert np.array_equal(gray, untouched), (
        "Reconstruction must not alter source evidence"
    )
    assert result["source_array_unchanged"]
    return result


def _curved_cross():
    ink = np.zeros((160, 160), np.uint8)
    horizontal = np.array(
        [(20, 70), (50, 77), (80, 80), (110, 77), (140, 70)], np.int32
    )
    vertical = horizontal[:, ::-1].copy()
    cv2.polylines(ink, [horizontal, vertical], False, 1, 1)
    return ink


def test_one_source_group_yields_two_independent_paths_without_connectivity_claim(
    tmp_path,
):
    result = _extract(_curved_cross(), tmp_path)
    objects = result["objects"]
    assert len(objects) == 2
    evidence = [obj["source_evidence"] for obj in objects]
    assert len({ev["source_connected_group_id"] for ev in evidence}) == 1
    edges = [set(ev["source_graph_edge_ids"]) for ev in evidence]
    assert not edges[0] & edges[1], (
        "Deleting one owner must not consume the other path's edges"
    )
    assert {tuple(obj["geometry"]["points"][0]) for obj in objects} == {
        (20.0, 70.0),
        (70.0, 20.0),
    }
    assert {tuple(obj["geometry"]["points"][-1]) for obj in objects} == {
        (140.0, 70.0),
        (70.0, 140.0),
    }
    for ev in evidence:
        assert ev["semantic_connection_type"] == "UNKNOWN_NOT_INFERRED"
        assert (
            ev["crossing_evidence"][0]["semantic_connection"] == "UNKNOWN_NOT_INFERRED"
        )
        assert ev["source_short_branches_deleted"] is False
    graph = json.loads((tmp_path / "source_graph.json").read_text())
    core = next(node for node in graph["nodes"] if len(node["all_ports"]) == 4)
    assert len(core["finite_path_decompositions"]) == 3
    for hypothesis in core["finite_path_decompositions"]:
        assert sorted(port for pair in hypothesis["pairs"] for port in pair) == [
            0,
            1,
            2,
            3,
        ]


def test_real_short_t_branch_is_preserved_and_prevents_an_invented_complete_path(
    tmp_path,
):
    ink = np.zeros((160, 160), np.uint8)
    ink[80, 20:141] = 1
    ink[77:81, 80] = 1
    result = _extract(ink, tmp_path)
    assert not result["objects"]
    assert any(
        "NONUNIQUE_SOURCE_BRANCH" in row["reason"] for row in result["uncertainties"]
    )
    graph = json.loads((tmp_path / "source_graph.json").read_text())
    core = next(node for node in graph["nodes"] if len(node["all_ports"]) == 3)
    assert not core["pairings"]
    assert all(
        hypothesis["unmatched_ports"]
        for hypothesis in core["finite_path_decompositions"]
    )
    retained = {
        tuple(point) for edge in graph["edges"] for point in edge["source_points"]
    }
    retained.update(
        tuple(point) for node in graph["nodes"] for point in node["source_core_points"]
    )
    assert (80.0, 77.0) in retained
    assert all((float(x), float(y)) in retained for y, x in zip(*np.nonzero(ink)))


def test_short_fourth_port_keeps_all_three_hypotheses_and_remains_pending(tmp_path):
    ink = np.zeros((160, 160), np.uint8)
    ink[80, 20:141] = 1
    ink[20:84, 80] = 1
    result = _extract(ink, tmp_path)
    assert not result["objects"]
    graph = json.loads((tmp_path / "source_graph.json").read_text())
    core = next(node for node in graph["nodes"] if len(node["all_ports"]) == 4)
    assert core["reason"] == "PORT_TOO_SHORT_TO_DISTINGUISH_CROSSING"
    assert not core["pairings"]
    assert len(core["finite_path_decompositions"]) == 3
    assert any([80.0, 83.0] in edge["source_points"] for edge in graph["edges"])
    for hypothesis in core["finite_path_decompositions"]:
        assert sorted(port for pair in hypothesis["pairs"] for port in pair) == [
            0,
            1,
            2,
            3,
        ]


def test_two_external_ports_cannot_hide_an_internal_source_hole(tmp_path):
    ink = np.zeros((160, 160), np.uint8)
    cv2.polylines(
        ink, [np.array([(20, 80), (55, 76), (79, 80)], np.int32)], False, 1, 1
    )
    ink[80, 81:141] = 1
    cv2.rectangle(ink, (79, 79), (81, 81), 1, 1)
    ink[80, 80] = 0
    graph = _graph(ink)
    core = next(node for node in graph.nodes.values() if len(node["edges"]) == 2)
    assert core["core_topology"]["cycle_rank"] == 1
    assert not core["pairing"], (
        "A shortest route through this core omits half the observed loop"
    )
    result = _extract(ink, tmp_path)
    assert not result["objects"]
    assert any("CYCLE" in row["reason"] for row in result["uncertainties"])
    assert ink[80, 80] == 0


def test_small_terminal_loop_retains_its_entire_boundary_and_white_hole(tmp_path):
    ink = np.zeros((160, 160), np.uint8)
    ink[80, 20:130] = 1
    cv2.rectangle(ink, (129, 79), (132, 81), 1, 1)
    result = _extract(ink, tmp_path)
    assert len(result["objects"]) == 1
    obj = result["objects"][0]
    ev = obj["source_evidence"]
    assert ev["whole_path_class"] == "COMPLETE_STROKE_WITH_TERMINAL_LOOP"
    source_points = {tuple(point) for point in ev["source_path_points"]}
    assert all((float(x), float(y)) in source_points for y, x in zip(*np.nonzero(ink)))
    raster = np.zeros_like(ink)
    dense = np.rint(_dense_geometry(obj["geometry"], 0.1)).astype(np.int32)
    cv2.polylines(raster, [dense], False, 1, 1)
    assert np.all(raster[ink != 0] != 0), (
        "The same editable path must retain both sides of the lobe"
    )
    assert not raster[80, 130] and not raster[80, 131], (
        "A white hole is evidence, not noise to fill"
    )
    assert obj["geometry"]["closed"] is False


def test_white_gap_yields_separate_source_owners_without_a_bridge(tmp_path):
    ink = np.zeros((160, 160), np.uint8)
    cv2.polylines(
        ink,
        [np.array([(20, 70), (50, 77), (80, 80), (110, 77), (140, 70)], np.int32)],
        False,
        1,
        1,
    )
    ink[:, 78:83] = 0
    result = _extract(ink, tmp_path)
    assert len(result["objects"]) == 2
    assert (
        len(
            {
                obj["source_evidence"]["source_connected_group_id"]
                for obj in result["objects"]
            }
        )
        == 2
    )
    for obj in result["objects"]:
        xs = _dense_geometry(obj["geometry"])[:, 0]
        assert xs.max() <= 77 or xs.min() >= 83
        assert obj["source_evidence"]["source_morphological_gap_closing"] is False


def test_current_glyph_ownership_blocks_only_the_contacting_path(tmp_path):
    ink = _curved_cross()
    runs = [[int(y), int(x), int(x + 1)] for y, x in zip(*np.nonzero(ink)) if x < 55]
    regions = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [160, 160],
        "roi_xyxy_px": list(ROI),
        "regions": [
            {
                "id": "SYNTHETIC_GLYPH",
                "bbox_xyxy_px": [15, 15, 145, 145],
                "compact_source_ink_mask": {"runs_y_x0_x1": runs},
            }
        ],
    }
    result = _extract(ink, tmp_path, text_regions=regions)
    assert len(result["objects"]) == 1
    assert result["objects"][0]["geometry"]["points"][0] == [70.0, 20.0]
    pending = [
        row
        for row in result["uncertainties"]
        if row["reason"] == "CURRENT_SOURCE_GLYPH_OWNERSHIP_CONTACT"
    ]
    assert len(pending) == 1
    assert pending[0]["text_region_ids"] == ["SYNTHETIC_GLYPH"]


def test_touching_round_symbols_do_not_turn_the_middle_boundary_into_connections(
    tmp_path,
):
    ink = np.zeros((160, 160), np.uint8)
    for x in (42, 80, 118):
        cv2.circle(ink, (x, 80), 20, 1, 1)
    result = _extract(ink, tmp_path)
    assert len(result["round_boundary_observations"]) == 3
    assert not result["objects"], (
        "This input has three observed symbol boundaries and zero connecting strokes"
    )
    assert result["uncertainties"], (
        "Boundary responsibility must remain visible in the review record"
    )


def test_a_separate_curved_stroke_between_round_boundaries_is_still_recovered(tmp_path):
    ink = np.zeros((160, 160), np.uint8)
    for x in (30, 130):
        cv2.circle(ink, (x, 80), 12, 1, 1)
    cv2.polylines(
        ink,
        [np.array([(42, 80), (60, 70), (80, 65), (100, 70), (118, 80)], np.int32)],
        False,
        1,
        1,
    )
    result = _extract(ink, tmp_path)
    assert len(result["objects"]) == 1
    obj = result["objects"][0]
    assert (
        obj["source_evidence"]["whole_path_class"] == "ROUND_BOUNDARY_TO_ROUND_BOUNDARY"
    )
    xs = _dense_geometry(obj["geometry"])[:, 0]
    assert xs.min() >= 41 and xs.max() <= 119
    assert obj["source_evidence"]["symbol_boundary_geometry_not_consumed"] is True


def test_terminal_lobe_cannot_bypass_an_additional_cycle_inside_its_core(tmp_path):
    ink = np.zeros((160, 160), np.uint8)
    ink[80, 20:130] = 1
    ink[20:141, 80] = 1
    cv2.rectangle(ink, (129, 79), (132, 81), 1, 1)
    cv2.rectangle(ink, (124, 79), (126, 81), 1, 1)
    ink[80, 125] = 0
    result = _extract(ink, tmp_path)
    for obj in result["objects"]:
        points = np.asarray(obj["source_evidence"]["source_path_points"])
        if points[:, 0].max() > 120:
            owned = {tuple(point) for point in points}
            assert all((float(x), 81.0) in owned for x in (124, 125, 126)), (
                "A terminal lobe does not license dropping a second internal loop after a crossing"
            )
    assert result["uncertainties"] or result["objects"], (
        "The unresolved group must remain accountable"
    )
