"""Whole-wall feasibility and reversible source responsibility."""

import numpy as np
from PIL import Image, ImageDraw

from app.native_objects.wall_candidate_ownership import replacement_support
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
