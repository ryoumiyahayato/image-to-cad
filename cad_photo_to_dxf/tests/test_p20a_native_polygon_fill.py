"""P20-A simple native area contracts; generated streams are QA_TEST_ONLY."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace
import pytest
import ezdxf
from app.core.image_loader import load_image
from app.core.native_fill import NativeFill
from app.core.arc_types import PdfPathReference
from app.export.native_fill_entities import add_native_fill_entities
from tests.test_native_text_review import pdf_source


def extract(tmp_path, stream):
    p = pdf_source(tmp_path, prefix=stream)
    e = []
    frame = load_image(p, pdf_dpi=72, grayscale=True, pdf_geometry_sink=e)
    return frame, e[0]


def test_complete_concave_linear_area_and_dark_independent_stroke(tmp_path):
    frame, e = extract(
        tmp_path,
        "0.48 g 20 20 m 80 20 l 80 40 l 50 40 l 50 70 l 20 70 l h f 0 G 1 w 25 10 m 25 80 l S ",
    )
    assert len(e.native_fills) == 1
    f = e.native_fills[0]
    assert f.version == 2 and len(f.points) == 6
    assert frame[105, 70] > 240 and frame[125, 70] < 150
    assert e.fill_analysis["restored_and_reread"]


def test_actual_closure_required_and_holes_rejected(tmp_path):
    for stream in (
        "0 g 20 20 m 80 20 l 80 60 l 20 60 l f ",
        "0 g 20 20 60 60 re 35 35 20 20 re f* ",
        "0 g 20 20 m 80 60 l 20 60 l 80 20 l h f ",
        "q 20 20 20 30 re W n 0 g 20 20 60 60 re f Q ",
        "0.48 g 20 20 60 60 re f 1 g 35 35 20 20 re f ",
    ):
        _, e = extract(tmp_path, stream)
        assert not e.native_fills and e.fill_analysis["restored_and_reread"]


def test_explicit_repeated_end_and_idempotent_saved_export(tmp_path):
    _, e = extract(
        tmp_path, "0.48 g 20 20 m 50 20 l 80 20 l 80 60 l 20 60 l 20 20 l f "
    )
    assert len(e.native_fills) == 1
    d = ezdxf.new()
    d.layers.add("NATIVE")
    names = {"NATIVE_PDF_FILL": "NATIVE"}
    for _ in range(2):
        add_native_fill_entities(
            d, d.modelspace(), e.native_fills, lambda x, y: (x, y), names
        )
    assert len(d.modelspace().query("HATCH")) == 1
    p = tmp_path / "saved.dxf"
    d.saveas(p)
    d = ezdxf.readfile(p)
    add_native_fill_entities(
        d, d.modelspace(), e.native_fills, lambda x, y: (x, y), names
    )
    assert len(d.modelspace().query("HATCH")) == 1
    assert not d.audit().errors and not d.audit().fixes


def test_v1_reading_and_v2_invalid_ring():
    f = NativeFill(
        PdfPathReference("QA_TEST_ONLY.pdf", 1, 0),
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        (123, 123, 123),
        (1, 0, 0, 1, 0, 0),
        72,
    )
    assert NativeFill.from_payload(f.payload()) == f
    assert (
        replace(
            f, version=2, visibility="full-only-without-opaque-simple-polygon-v2"
        ).version
        == 2
    )
    for points in (
        ((0, 0), (10, 10), (0, 10), (10, 0)),
        ((0, 0), (10, 0), (10, 0), (0, 10)),
    ):
        with pytest.raises(ValueError):
            replace(
                f,
                points=points,
                version=2,
                visibility="full-only-without-opaque-simple-polygon-v2",
            )


def test_equivalent_collinear_samples_do_not_duplicate_or_change_source():
    from app.export.native_fill_entities import equivalent_visible_hatch

    source = NativeFill(
        PdfPathReference("QA_TEST_ONLY.pdf", 1, 0),
        ((0, 0), (5, 0), (10, 0), (10, 10), (0, 10)),
        (123, 123, 123),
        (1, 0, 0, 1, 0, 0),
        72,
        version=2,
        visibility="full-only-without-opaque-simple-polygon-v2",
    )
    d = ezdxf.new()
    d.layers.add("NATIVE")
    h = d.modelspace().add_hatch()
    h.rgb = source.rgb
    h.paths.add_polyline_path(((0, 0), (10, 0), (10, 10), (0, 10)), is_closed=True)
    assert equivalent_visible_hatch(d, h, source.points, source.rgb)
    for _ in range(2):
        add_native_fill_entities(
            d,
            d.modelspace(),
            (source,),
            lambda x, y: (x, y),
            {"NATIVE_PDF_FILL": "NATIVE"},
        )
    assert len(d.modelspace().query("HATCH")) == 1 and len(source.points) == 5
    # Cyclic/reversed sampling on either ring is the same boundary.
    h.paths[0].vertices = [(10, 10, 0), (10, 5, 0), (10, 0, 0), (0, 0, 0), (0, 10, 0)]
    assert equivalent_visible_hatch(d, h, source.points, source.rgb)
    # A bend or a backward excursion is not an equivalent area.
    assert not equivalent_visible_hatch(
        d, h, ((0, 0), (5, 0.01), (10, 0), (10, 10), (0, 10)), source.rgb
    )
    assert not equivalent_visible_hatch(
        d, h, ((0, 0), (7, 0), (3, 0), (10, 0), (10, 10), (0, 10)), source.rgb
    )
