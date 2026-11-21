"""Cold-read and actual glyph-render checks using synthetic source rows only."""

import ezdxf
import pytest
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.recorder import Recorder

from app.native_objects.cad_io import export_objects


def source_objects(angle=0):
    # Repeated content/width makes rendered glyph bounds directly comparable:
    # paragraph indentation must affect geometry, without adding text spaces.
    rows = [
        {"bbox_xyxy_px": [12, 20, 72, 32], "width_px": 60},
        {"bbox_xyxy_px": [10, 38, 70, 50], "width_px": 60},
        {"bbox_xyxy_px": [17, 56, 77, 68], "width_px": 60},
    ]
    return [
        {
            "id": "synthetic-note",
            "kind": "MTEXT",
            "layer": "ANNOTATION",
            "geometry": {
                "text": "SAMPLE\nSAMPLE\nSAMPLE",
                "lines": ["SAMPLE"] * 3,
                "x": 10,
                "y": 20,
                "height_px": 12,
                "width_px": 67,
                "line_pitch_px": 18,
                "rotation_deg_image": angle,
                "source_line_geometries": rows,
            },
        },
        {
            "id": "synthetic-neighbor",
            "kind": "LINE",
            "layer": "GEOMETRY",
            "geometry": {"start": [4, 5], "end": [85, 5]},
        },
    ]


@pytest.mark.parametrize("angle", [0, 27])
def test_source_row_offsets_reach_saved_mtext_glyph_geometry(tmp_path, angle):
    path = tmp_path / "synthetic.dxf"
    objects = source_objects(angle)
    meta = export_objects(
        objects, path, [0, 0, 100, 100], 25.4, "synthetic",
        diagnostic_source_mtext_layout=True,
    )
    doc = ezdxf.readfile(path)
    assert not doc.audit().has_errors
    notes = list(doc.modelspace().query("MTEXT"))
    assert len(notes) == 1
    note = notes[0]
    assert note.plain_text() == "SAMPLE\nSAMPLE\nSAMPLE"
    assert note.dxf.char_height == 12
    assert note.dxf.line_spacing_style == 2
    assert note.dxf.line_spacing_factor == pytest.approx(0.9)
    assert note.dxf.rotation == -angle
    assert note.dxf.flow_direction == 1
    assert all(row["source_left_offset_applied"] for row in meta["written"][0]["mtext_line_layout"])

    # This is the real ezdxf drawing frontend, which turns the saved MTEXT into
    # glyph paths. Undo rotation only in the diagnostic coordinates, then check
    # the actual path bounds. Merely writing an unused paragraph tag fails here.
    recorder = Recorder()
    Frontend(RenderContext(doc), recorder).draw_entities([note])
    matrix = note.ucs().matrix.copy()
    matrix.inverse()
    boxes = []
    for record in recorder.records:
        record.transform_inplace(matrix)
        boxes.append(record.bbox())
    boxes.sort(key=lambda box: box.extmax.y, reverse=True)
    assert len(boxes) == 3
    assert [b.extmin.x - boxes[1].extmin.x for b in boxes] == pytest.approx([2, 0, 7], abs=1e-7)
    # ezdxf's layout engine uses 1.667 rather than the DXF 5/3 line-height
    # ratio; its two-interval difference here is 0.0072 source pixels.
    assert [boxes[0].extmin.y - b.extmin.y for b in boxes] == pytest.approx([0, 18, 36], abs=0.01)
    assert len({round(b.size.x, 7) for b in boxes}) == 1

    neighbors = list(doc.modelspace().query("LINE"))
    assert len(neighbors) == 1
    assert tuple(neighbors[0].dxf.start) == (4, 95, 0)
    assert tuple(neighbors[0].dxf.end) == (85, 95, 0)


def test_missing_rows_still_cannot_be_exported_as_a_complete_mtext(tmp_path):
    objects = source_objects()
    objects[0]["geometry"]["source_line_geometries"].pop()
    with pytest.raises(ValueError, match="MTEXT_REQUIRES_ORDERED_SOURCE_LINE_GEOMETRIES"):
        export_objects(objects, tmp_path / "incomplete.dxf", [0, 0, 100, 100], 25.4, "synthetic")


def test_failed_consumer_paragraph_layout_is_not_the_production_default(tmp_path):
    path = tmp_path / "baseline.dxf"
    meta = export_objects(source_objects(27), path, [0, 0, 100, 100], 25.4, "synthetic")
    note = ezdxf.readfile(path).modelspace().query("MTEXT").first
    assert "\\pxi" not in note.text
    assert note.plain_text() == "SAMPLE\nSAMPLE\nSAMPLE"
    assert note.dxf.rotation == 0
    rows = meta["written"][0]["mtext_line_layout"]
    assert all(row["source_left_offset_applied"] is False for row in rows)
    assert all(row["layout_profile"] == "EXISTING_MAIN_MTEXT_EXPRESSION" for row in rows)
