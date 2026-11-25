"""External saved-output checker tests; these do not claim OCR or EXE execution."""

import json
from pathlib import Path

import ezdxf
from PIL import Image
import pytest

from scripts.windows_native_smoke import (
    _structure_contact_curve_points,
    create_structure_contact_fixture,
    inspect_structure_contact_members,
    inspect_structure_fixture_source_gap,
    inspect_structure_path_edit_isolation,
    inspect_structure_path_shape,
)


def _checker_document():
    document = ezdxf.new("R2013")
    document.units = 4
    document.appids.new("I2CAD_NATIVE_V2")
    mm = 25.4 / 200

    def point(value):
        return value[0] * mm, (480 - value[1]) * mm

    def identify(entity, oid, kind):
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": oid, "kind": kind}))])
        return entity

    path = identify(document.modelspace().add_lwpolyline([point(p) for p in _structure_contact_curve_points()]),
                    "checker-path", "CONNECTION_PATH")
    identify(document.modelspace().add_line(point((300, 330)), point((580, 330))), "checker-carrier", "LINE")
    identify(document.modelspace().add_circle(point((110, 150)), 22 * mm), "checker-circle", "CIRCLE")
    identify(document.modelspace().add_line(point((390, 80)), point((471, 80))), "checker-gap-lead", "LINE")
    identify(document.modelspace().add_circle(point((500, 80)), 26 * mm), "checker-gap-circle", "CIRCLE")
    return document, path


def _fixture(tmp_path):
    font = Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"
    source = tmp_path / "controlled-source.png"
    create_structure_contact_fixture(source, font)
    return source


def test_structure_fixture_retains_real_white_columns_and_detects_filled_source(tmp_path):
    source = _fixture(tmp_path)
    check = inspect_structure_fixture_source_gap(source)
    assert check["source_gap_width_px"] == 2
    with Image.open(source) as original:
        changed = original.copy()
    changed.putpixel((472, 80), 0)
    changed.save(source)
    with pytest.raises(AssertionError, match="white source columns"):
        inspect_structure_fixture_source_gap(source)


@pytest.mark.parametrize("damage", ["truncated-end", "glyph-loop", "retrace", "closed"])
def test_structure_whole_shape_checker_rejects_partial_or_character_owned_geometry(damage):
    document, path = _checker_document()
    assert inspect_structure_path_shape(path)["single_native_path"]
    points = _structure_contact_curve_points()
    if damage == "truncated-end":
        points[-1] = (380, 310)
    elif damage == "glyph-loop":
        points[-1:] = [(380, 290), (395, 307), (380, 324), (380, 330)]
    elif damage == "retrace":
        points[-1:] = [(380, 290), (380, 320), (380, 300), (380, 330)]
    else:
        path.closed = True
    if damage != "closed":
        path.set_points([(x * 25.4 / 200, (480 - y) * 25.4 / 200) for x, y in points])
    with pytest.raises(AssertionError):
        inspect_structure_path_shape(path)


def test_structure_saved_checker_cannot_pass_an_unproved_ordinary_curve(tmp_path):
    source = _fixture(tmp_path)
    document, _ = _checker_document()
    rows = [{"id": "checker-" + name} for name in ("path", "carrier", "circle", "gap-lead", "gap-circle")]
    with pytest.raises(AssertionError, match="complete new round-to-carrier path"):
        inspect_structure_contact_members(document, {"objects": rows}, {}, source)


def test_structure_path_move_delete_survives_save_with_circle_carrier_and_gap_kept(tmp_path):
    document, _ = _checker_document()
    source = tmp_path / "checker-transport-only.dxf"
    document.saveas(source)
    original = source.read_bytes()
    result = inspect_structure_path_edit_isolation(source, tmp_path / "edits", "checker-path")
    assert result["pass"] and result["GUI_operations_claimed"] is False
    assert [row["action"] for row in result["checks"]] == ["move-path", "delete-path"]
    assert all(row["unchanged_other_formal_objects"] == 4 for row in result["checks"])
    assert source.read_bytes() == original
