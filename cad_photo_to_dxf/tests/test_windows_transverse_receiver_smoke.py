"""Generated-fixture and external saved-output gates; no EXE claims here."""

import json
import math
from pathlib import Path

import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects.carrier_reconciliation import plan_existing_carrier_reconciliation
from app.native_objects.geometry import extract_lines
from scripts.windows_native_smoke import (
    _transverse_fixture_strokes,
    create_transverse_receiver_fixture,
    inspect_transverse_complete_line,
    inspect_transverse_fixture_protection_pixels,
    inspect_transverse_receiver_members,
)


def fixture(tmp_path):
    font = Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"
    path = tmp_path / "source.png"
    create_transverse_receiver_fixture(path, font)
    return path


@pytest.mark.parametrize("filled", [(472, 80), (100, 405)])
def test_transverse_source_controls_detect_a_bridged_original_white_gap(tmp_path, filled):
    source = fixture(tmp_path)
    assert inspect_transverse_fixture_protection_pixels(source)["pass"]
    with Image.open(source) as image:
        damaged = image.copy()
    damaged.putpixel(filled, 0)
    damaged.save(source)
    with pytest.raises(AssertionError, match="white"):
        inspect_transverse_fixture_protection_pixels(source)


@pytest.mark.parametrize("damage", ["truncated", "extended", "fragmented"])
def test_transverse_whole_line_gate_rejects_partial_or_overlong_objects(damage):
    document = ezdxf.new("R2013")
    mm = 25.4 / 200

    def point(p):
        return p[0] * mm, (480 - p[1]) * mm

    expected = _transverse_fixture_strokes()[0]
    entity = document.modelspace().add_line(point(expected[0]), point(expected[1]))
    assert inspect_transverse_complete_line(entity, expected)["single_complete_LINE"]
    end = list(expected[1])
    if damage == "truncated":
        end[1] -= 10
        entity.dxf.end = point(end)
    elif damage == "extended":
        end[1] += 10
        entity.dxf.end = point(end)
    else:
        entity = document.modelspace().add_lwpolyline([point(p) for p in expected])
    with pytest.raises(AssertionError):
        inspect_transverse_complete_line(entity, expected)


def test_controlled_scan_naturally_creates_old_receivers_and_one_whole_replacement(tmp_path):
    source = fixture(tmp_path)
    with Image.open(source) as image:
        gray = np.asarray(image.convert("L"))
    text = {"coordinate_system": "source_pixels_top_left", "source_size_px": [640, 480],
            "roi_xyxy_px": [0, 0, 640, 480], "regions": []}
    originals = extract_lines(gray, (0, 0, 640, 480), text, tmp_path)["objects"]
    receiving = [row for row in originals
                 if abs(row["geometry"]["end"][0]-row["geometry"]["start"][0]) > 500
                 and 325 < (row["geometry"]["end"][1]+row["geometry"]["start"][1])/2 < 338]
    assert len(receiving) == 2
    result = plan_existing_carrier_reconciliation(
        gray, (0, 0, 640, 480), originals, receiving_object_ids=[row["id"] for row in receiving],
    )
    assert len(result["objects"]) == 1
    assert set(result["retired_ids"]) == {row["id"] for row in receiving}
    replacement = result["objects"][0]["geometry"]
    assert math.dist(replacement["start"], (20, 330)) < 2.5
    assert math.dist(replacement["end"], (605, 332)) < 2.5
    assert inspect_transverse_fixture_protection_pixels(source)["pass"]


def test_external_gate_cannot_pass_unproved_lines_using_a_success_counter(tmp_path):
    source = fixture(tmp_path)
    document = ezdxf.new("R2013")
    document.appids.new("I2CAD_NATIVE_V2")
    row = document.modelspace().add_line((0, 0), (5, 5))
    row.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": "unproved", "kind": "LINE"}))])
    with pytest.raises(AssertionError, match="actually adopt"):
        inspect_transverse_receiver_members(document, {"objects": [{"id": "unproved"}]},
                                           {"source_gate_pass": True}, source, tmp_path)
