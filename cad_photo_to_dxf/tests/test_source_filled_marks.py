from __future__ import annotations

import json

import cv2
import ezdxf
import numpy as np

from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.raster_trace import trace_binary
from app.geometry.source_filled_marks import retain_filled_source_marks


def test_local_fill_in_shared_ink_preserves_hollow_and_text_holes(tmp_path):
    source = np.full((135, 235), 255, dtype=np.uint8)
    cv2.circle(source, (54, 55), 10, 0, 2)
    cv2.line(source, (65, 55), (145, 55), 0, 1)
    cv2.circle(source, (104, 55), 9, 0, -1)
    cv2.putText(source, "O", (158, 65), cv2.FONT_HERSHEY_SIMPLEX, .9, 0, 2)
    source[90, 55] = 0
    source[94, 65:67] = 0
    paths = trace_binary(source)
    assert any(p.depth == 1 for p in paths)

    residual, records = retain_filled_source_marks(
        source, source, source, dpi=100, protected=np.zeros_like(source, dtype=bool),
    )
    mark, = records
    assert np.linalg.norm(np.array(mark["center_px"]) - [104, 55]) < 1
    assert len(mark["contact_sites"]) == 2
    assert np.array_equal(source[:, :80], residual[:, :80])
    assert np.array_equal(source[:, 127:], residual[:, 127:])
    assert mark["fit"]["p95_radial_error_px"] <= mark["fit"]["p95_limit_px"]

    structure = build_final_structure(
        source_size_px=source.shape[::-1], contour_binary=residual,
        contours=trace_binary(residual), preview_binary=source,
        provenance={"stroke_presentation": {"local_filled_marks": records}},
    )
    saved = export_final_structure_dxf(structure, tmp_path / "filled-mark.dxf")
    model = ezdxf.readfile(saved.path).modelspace()
    hatch, = [e for e in model.query("HATCH") if e.has_xdata("SOURCE_FILLED_MARK")]
    assert hatch.dxf.layer == "ENGINEERING_SYMBOL"
    tags = hatch.get_xdata("SOURCE_FILLED_MARK")
    evidence = json.loads("".join(t.value for t in tags[1:]))
    assert evidence["electrical_connectivity"] == "UNRESOLVED"
    raster = np.zeros((source.shape[0]*4, source.shape[1]*4), dtype=np.uint8)
    for path in hatch.paths:
        cells = [(round(4*x), round(4*(source.shape[0]-y))) for x, y, _ in path.vertices]
        cv2.fillPoly(raster, [np.asarray(cells, dtype=np.int32)], 255)
    footprint = raster[2::4, 2::4] > 0
    assert np.array_equal(footprint, (source == 0) & (residual == 255))
    assert int(footprint.sum()) == evidence["source_pixels"] + evidence["lead_source_pixels"]


def test_nearby_disconnected_ink_does_not_qualify_an_isolated_dot():
    source = np.full((100, 130), 255, dtype=np.uint8)
    cv2.circle(source, (43, 50), 9, 0, -1)
    cv2.line(source, (55, 50), (92, 50), 0, 1)
    residual, records = retain_filled_source_marks(
        source, source, source, dpi=100, protected=np.zeros_like(source, dtype=bool),
    )
    assert not records
    assert np.array_equal(residual, source)
