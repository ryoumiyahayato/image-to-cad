from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.document_export import DocumentPage, export_scan_document
from app.line_detect import LineSegment


def test_multi_page_scan_document_keeps_pages_and_layouts(tmp_path: Path) -> None:
    first = np.full((80, 120, 3), 255, np.uint8)
    cv2.line(first, (5, 5), (110, 70), (0, 0, 0), 2)
    second = np.full((100, 70, 3), 245, np.uint8)
    cv2.rectangle(second, (10, 10), (60, 90), (0, 0, 0), 1)
    pages = [
        DocumentPage(
            page_number=1,
            source_path=tmp_path / "unused-1.png",
            image=first,
            lines=(LineSegment(5, 5, 110, 70, layer="DETAIL"),),
            page_size_mm=(120.0, 80.0),
            label="First sheet",
        ),
        DocumentPage(
            page_number=2,
            source_path=tmp_path / "unused-2.png",
            image=second,
            page_size_mm=(70.0, 100.0),
            label="Second sheet",
        ),
    ]

    output = tmp_path / "set.dxf"
    result = export_scan_document(pages, output)

    assert result.page_count == 2
    assert result.line_count == 1
    assert len(result.underlay_paths) == 2
    for underlay in result.underlay_paths:
        assert underlay.exists()
    assert np.array_equal(
        cv2.imdecode(np.fromfile(str(result.underlay_paths[0]), np.uint8), cv2.IMREAD_COLOR),
        first,
    )

    document = ezdxf.readfile(output)
    assert not document.audit().errors
    assert len(document.modelspace().query("IMAGE")) == 2
    assert len(document.modelspace().query("LINE")) == 1
    layout_names = {layout.name for layout in document.layouts}
    assert "PAGE_001_First_sheet" in layout_names
    assert "PAGE_002_Second_sheet" in layout_names
