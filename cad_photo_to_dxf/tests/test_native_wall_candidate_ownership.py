"""Whole-wall feasibility and reversible source responsibility."""

import json
import numpy as np
from PIL import Image, ImageDraw

from app.native_objects.wall_candidate_ownership import (
    near_overlap,
    replacement_support,
)
from app.native_objects.wall_segments import assemble_walls, _partition_wall_lines
from app.native_objects.wall_partition_gate import enforce_partition_source_gate


def line(identifier, start, end, layer="GEOMETRY"):
    return {
        "id": identifier,
        "kind": "LINE",
        "layer": layer,
        "geometry": {"start": list(start), "end": list(end)},
        "source_evidence": {"source_width_px": 1.0},
    }


def fixture():
    im = Image.new("L", (320, 150), 255)
    draw = ImageDraw.Draw(im)
    draw.line((30, 50, 280, 50), fill=0)
    draw.line((30, 70, 280, 69), fill=0)
    draw.line((280, 50, 280, 69), fill=0)
    draw.line((30, 50, 30, 70), fill=0)
    draw.line((100, 110, 120, 110), fill=0)
    original = [
        line("bad-top", (30, 50.5), (280, 51.625)),
        line("bottom", (30, 70), (280, 69)),
        line("real-short", (100, 110), (120, 110), "SHORT_STROKE"),
    ]
    candidate = line("source-top", (30, 50), (280, 50))
    return np.asarray(im).copy(), original, candidate


def test_feasible_complete_wall_can_choose_a_locally_discarded_fit(tmp_path):
    gray, original, candidate = fixture()
    before = gray.copy()
    result = assemble_walls(
        gray, [0, 0, 320, 150], original, tmp_path, candidate_lines=[candidate]
    )
    result = enforce_partition_source_gate(gray, original, result, tmp_path)
    assert result["partition_source_gate"]["pass"]
    assert len(result["objects"]) == 1
    assert "source-top" in result["objects"][0]["source_evidence"]["source_line_ids"]
    assert (
        next(o for o in result["remaining_lines"] if o["id"] == "real-short")
        == original[-1]
    )
    assert all(o["id"] != "source-top" for o in result["remaining_lines"])
    # A nearby old fit outside this wall's proven responsibility is kept;
    # selecting an alternate must not blanket-delete its neighboring source.
    assert result["source_interval_partition"]
    assert np.array_equal(gray, before)


def test_two_real_parallel_strokes_with_a_white_gap_are_not_duplicates():
    gray = np.full((80, 250), 255, np.uint8)
    gray[30, 20:221] = 0
    gray[32, 20:221] = 0
    first = line("a", (20, 30), (220, 30))["geometry"]
    second = line("b", (20, 32), (220, 32))["geometry"]
    proof = replacement_support(gray, first, second)
    assert proof["actual_white_separator_sample_count"] > 0
    assert not proof["eligible"]


def test_proven_same_stroke_is_retired_after_a_complete_wall_takes_ownership():
    gray = np.full((120, 250), 255, np.uint8)
    gray[50, 20:221] = 0
    gray[70, 20:221] = 0
    gray[50:71, 20] = 0
    gray[50:71, 220] = 0
    old = line("near-fit", (20, 50.7), (220, 50.7))
    wall = {
        "id": "wall",
        "source_evidence": {"source_line_ids": ["chosen-top", "bottom"]},
        "geometry": {
            "members": [
                {
                    "role": "wall_edge",
                    "geometry": line("a", (20, 50), (220, 50))["geometry"],
                },
                {
                    "role": "wall_edge",
                    "geometry": line("b", (20, 70), (220, 70))["geometry"],
                },
                {
                    "role": "observed_end_cap",
                    "geometry": line("c", (220, 50), (220, 70))["geometry"],
                },
            ]
        },
    }
    kept, _, withdrawals, *_ = _partition_wall_lines(gray, [old], [wall])
    assert not kept
    assert withdrawals[0]["fully_replaced"]
    assert withdrawals[0]["wall_claims"][0]["actual_white_separator_sample_count"] == 0


def test_different_nearest_pixels_on_same_stroke_do_not_leave_wall_residue():
    gray = np.full((100, 700), 255, np.uint8)
    # The old fit is nearest to row 50 and the wall fit to row 51 near its
    # right end. Both remain within the original 2 px source tolerance.
    gray[50:52, 20:621] = 0
    first = line("old-fit", (20, 50), (620, 50))
    second = line("wall-edge", (100, 50.6), (600, 52.6))["geometry"]
    before = gray.copy()
    assert near_overlap(first["geometry"], second) is None
    proof = replacement_support(gray, first["geometry"], second)
    assert proof["whole_overlap_replaced"]
    assert proof["covered_intervals_px"] == [[80.0, 580.0]]
    assert proof["common_source_witness_count"] == proof["sample_count"]
    assert proof["first_fit_to_common_source_max_px"] <= 2
    assert proof["replacement_to_common_source_max_px"] <= 2
    assert proof["missing_common_source_witness_sample_count"] == 0
    assert proof["maximum_missing_common_source_witness_gap_px"] == 0
    assert proof["actual_white_separator_sample_count"] == 0
    wall = {
        "id": "wall",
        "source_evidence": {"source_line_ids": ["wall-edge"]},
        "geometry": {"members": [{"role": "wall_edge", "geometry": second}]},
    }
    kept, partitions, withdrawals, *_ = _partition_wall_lines(gray, [first], [wall])
    assert len(kept) == 2
    assert partitions[0]["claimed_union_intervals_px"] == [(80.0, 580.0)]
    assert partitions[0]["remaining_intervals_px"] == [(0.0, 80.0), (580.0, 600.0)]
    assert partitions[0]["length_conservation_error_px"] == 0
    assert not withdrawals[0]["fully_replaced"]
    assert np.array_equal(gray, before)


def test_wider_candidate_screen_does_not_remove_a_separate_parallel_stroke():
    gray = np.full((90, 250), 255, np.uint8)
    gray[40, 20:221] = 0
    gray[43, 20:221] = 0
    first = line("independent", (20, 40), (220, 40))["geometry"]
    second = line("wall", (20, 43), (220, 43))["geometry"]
    assert near_overlap(first, second) is None
    proof = replacement_support(gray, first, second)
    assert not proof["eligible"]
    assert proof["actual_white_separator_sample_count"] == proof["sample_count"]
    assert proof["source_pixels_modified"] is False


def test_geometric_candidate_without_common_original_ink_is_not_replaced():
    gray = np.full((90, 250), 255, np.uint8)
    gray[40, 20:221] = 0
    first = line("real-source", (20, 40), (220, 40))["geometry"]
    second = line("unsupported-fit", (20, 43), (220, 43))["geometry"]
    proof = replacement_support(gray, first, second)
    assert not proof["eligible"]
    assert proof["common_source_witness_count"] == 0
    assert proof["missing_common_source_witness_sample_count"] == proof["sample_count"]
    assert proof["source_thresholds_changed"] is False


def test_partial_wider_fit_stays_pending_without_fragmenting_other_source():
    gray = np.full((100, 700), 255, np.uint8)
    gray[50:52, 20:621] = 0
    # A short section lacks the upper pixel: the wider fit has about 97%
    # shared support, so the unchanged 98% whole-overlap gate must not pass.
    gray[51, 588:601] = 255
    original = line("old-fit", (20, 50), (620, 50))
    member = line("wall-edge", (100, 50.6), (600, 52.6))["geometry"]
    proof = replacement_support(gray, original["geometry"], member)
    assert 0.95 < proof["same_stroke_covered_fraction"] < 0.98
    assert not proof["eligible"]
    assert not proof["covered_intervals_px"]
    assert proof["pending_supported_intervals_px"]
    assert (
        proof["pending_reason"]
        == "WIDER_FIT_REQUIRES_COMPLETE_OVERLAP_SOURCE_RESPONSIBILITY"
    )
    wall = {
        "id": "wall",
        "source_evidence": {"source_line_ids": ["wall-edge"]},
        "geometry": {"members": [{"role": "wall_edge", "geometry": member}]},
    }
    kept, partitions, withdrawals, *_ = _partition_wall_lines(gray, [original], [wall])
    assert kept == [original]
    assert not partitions
    assert not withdrawals


def test_incomplete_wider_ownership_does_not_revoke_an_otherwise_valid_wall(tmp_path):
    gray = np.full((110, 700), 255, np.uint8)
    gray[50, 20:500] = 0
    gray[51, 500:616] = 0
    gray[53, 616:621] = 0
    gray[75, 500:621] = 0
    gray[51:76, 500] = 0
    gray[53:76, 620] = 0
    long_fit = line("long-neighbor", (20, 50), (620, 50))
    source_lines = [
        long_fit,
        line("lower", (500, 53), (620, 53)),
        line("upper", (500, 75), (620, 75)),
    ]
    result = assemble_walls(gray, [0, 0, 700, 110], source_lines, tmp_path)
    result = enforce_partition_source_gate(gray, source_lines, result, tmp_path)
    assert result["partition_source_gate"]["pass"]
    assert len(result["objects"]) == 1
    assert set(result["objects"][0]["source_evidence"]["source_line_ids"]) == {
        "lower",
        "upper",
    }
    assert (
        next(o for o in result["remaining_lines"] if o["id"] == "long-neighbor")
        == long_fit
    )
    saved = json.loads((tmp_path / "wall_segments.json").read_text())
    deferred = [
        p
        for p in saved["deferred_edge_replacements"]
        if p["source_line_id"] == "long-neighbor"
    ]
    assert deferred
    assert deferred[0]["source_responsibility"]["pending_supported_intervals_px"]
    assert not deferred[0]["source_responsibility"]["covered_intervals_px"]


def test_candidate_cannot_restore_a_line_already_consumed_by_another_object(tmp_path):
    gray, original, candidate = fixture()
    # The top line's ownership has left the wall stage (e.g. to a door/frame).
    result = assemble_walls(
        gray, [0, 0, 320, 150], original[1:], tmp_path, candidate_lines=[candidate]
    )
    assert not result["objects"]
    assert not result["candidate_source_lines"]
    assert [o["id"] for o in result["remaining_lines"]] == ["bottom", "real-short"]


def test_revoked_alternate_wall_restores_original_bank_not_extra_candidates(tmp_path):
    gray, original, candidate = fixture()
    result = assemble_walls(
        gray, [0, 0, 320, 150], original, tmp_path, candidate_lines=[candidate]
    )
    assert result["objects"]
    changed = gray.copy()
    changed[45:55, 140:160] = 255
    revoked = enforce_partition_source_gate(changed, original, result, tmp_path)
    assert not revoked["objects"]
    assert {o["id"] for o in revoked["remaining_lines"]} == {o["id"] for o in original}
    assert "source-top" not in {o["id"] for o in revoked["remaining_lines"]}
