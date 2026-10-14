from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.line_detect import LineSegment
from app.ocr.auxiliary_recognition import TextCandidate


def test_final_structure_export_links_scan_with_one_line_and_text(tmp_path: Path) -> None:
    scan = np.full((120, 240, 3), 255, dtype=np.uint8)
    cv2.line(scan, (10, 20), (220, 20), (0, 0, 0), 1)
    structure = build_final_structure(
        source_size_px=(240, 120),
        contour_binary=cv2.cvtColor(scan, cv2.COLOR_BGR2GRAY),
        contours=(),
        straight_lines=(LineSegment(10.0, 20.0, 220.0, 20.0),),
        texts=(TextCandidate("施工说明", (20, 30, 80, 18), 0.92, "text_candidate"),),
    )

    result = export_final_structure_dxf(
        structure, tmp_path / "drawing.dxf", raster_image=scan
    )

    assert result.path.is_file()
    assert result.line_count == 1
    assert result.text_count == 1
    assert result.underlay_path is not None
    assert result.underlay_path.is_file()
    assert np.array_equal(cv2.imread(str(result.underlay_path)), scan)
    document = ezdxf.readfile(result.path)
    audit = document.audit()
    assert not audit.errors
    assert not audit.fixes
    modelspace = document.modelspace()
    lines = list(modelspace.query("LINE"))
    texts = list(modelspace.query("TEXT"))
    images = list(modelspace.query("IMAGE"))
    assert len(lines) == len(texts) == len(images) == 1
    assert tuple(lines[0].dxf.start) == (10.0, 100.0, 0.0)
    assert tuple(lines[0].dxf.end) == (220.0, 100.0, 0.0)
    assert texts[0].dxf.text == "施工说明"
    assert images[0].dxf.layer == "SCAN_UNDERLAY"
    image_def = document.entitydb[images[0].dxf.image_def_handle]
    assert result.path.parent / image_def.dxf.filename == result.underlay_path
