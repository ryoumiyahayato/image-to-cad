"""P16-A TEST_ONLY paint-context controls. Not a native-fill importer."""

import ezdxf
import numpy as np
import pytest

from app.core.image_loader import load_image
from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.line_detect import LineSegment
from app.geometry.raster_trace import TracePath
from app.geometry.source_presentation import source_fill_records
from tests.test_native_text_review import pdf_source


@pytest.mark.parametrize(
    "kind,stream,center_dark",
    [
        ("fill", "0 g 20 20 30 30 re f ", True),
        ("stroke", "0 G 1 w 20 20 30 30 re S ", False),
        ("both", "0 g 0 G 1 w 20 20 30 30 re B ", True),
        ("transparent", "q /GS gs 0 g 20 20 30 30 re f Q ", False),
        ("white_occlusion", "0 g 20 20 30 30 re f 1 g 30 20 10 30 re f ", False),
        ("clipped", "q 20 20 10 30 re W n 0 g 20 20 30 30 re f Q ", False),
    ],
)
def test_formal_pdf_loader_preserves_paint_context_without_inventing_native_fill(
    tmp_path, kind, stream, center_dark
):
    path = pdf_source(tmp_path, prefix=stream)
    evidence = []
    frame = load_image(path, pdf_dpi=72, grayscale=True, pdf_geometry_sink=evidence)
    assert bool(frame[115, 35] < 128) == center_dark
    if kind in {"fill", "white_occlusion", "clipped"}:
        assert frame[115, 25] < 128
    if kind in {"stroke", "both"}:
        assert frame[115, 20] < 200
    # The existing optional evidence is ARC-only. Empty candidates do not mean
    # that there were no PATH/fill objects, nor do they authorize a HATCH.
    assert not evidence[0].candidates


def test_native_fills_leave_the_source_opening_unpainted(tmp_path):
    path = pdf_source(tmp_path, prefix="0 g 20 20 20 30 re f 60 20 20 30 re f ")
    frame = load_image(path, pdf_dpi=72, grayscale=True)
    assert frame[115, 30] < 128 and frame[115, 70] < 128
    assert np.all(frame[101:129, 41:59] == 255)


def test_hatch_and_independent_helper_survive_formal_export(tmp_path):
    gray = np.full((500, 600), 255, np.uint8)
    gray[30:46, 30:46] = 90
    path = TracePath(((30, 30), (45, 30), (45, 45), (30, 45)), None, 0, 0)
    fills = source_fill_records(gray, (path,))
    assert fills
    # Explicit TEST_ONLY independent helper. Coexistence does not transfer the
    # HATCH's source responsibility or permit removal of any existing member.
    helper = LineSegment(30, 60, 45, 60, layer="ANNOTATION")
    structure = build_final_structure(
        source_size_px=(600, 500),
        contour_binary=gray,
        contours=(path,),
        straight_lines=(helper,),
        provenance={"stroke_presentation": {"fill_records": fills}},
    )
    doc = ezdxf.readfile(
        export_final_structure_dxf(structure, tmp_path / "roles.dxf").path
    )
    assert len(doc.modelspace().query("HATCH")) == 1
    line = doc.modelspace().query("LINE")[0]
    # The current writer uses TRACE_STRAIGHT for lines; it does not preserve a
    # custom input role/layer. This check proves coexistence, not role transfer.
    assert line.dxf.layer == "TRACE_STRAIGHT" and tuple(line.dxf.start)[:2] == (30, 440)
    assert not doc.audit().errors
