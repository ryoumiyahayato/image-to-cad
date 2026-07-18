from __future__ import annotations

import ezdxf
import numpy as np

from app.document_export import DocumentPage, export_scan_document
from app.line_detect import LineSegment


def test_export_scan_document_creates_layout_per_page_and_model_stack(tmp_path) -> None:
    page1 = np.full((100, 200, 3), 255, dtype=np.uint8)
    page2 = np.full((120, 180, 3), 255, dtype=np.uint8)
    result = export_scan_document(
        [
            DocumentPage(1, page1, (420.0, 297.0), (LineSegment(10, 10, 190, 10),)),
            DocumentPage(2, page2, (420.0, 297.0), ()),
        ],
        tmp_path / "document.dxf",
    )

    assert result.path.is_file()
    assert result.page_count == 2
    assert result.line_count == 1
    assert len(result.underlay_paths) == 2
    assert all(path.is_file() for path in result.underlay_paths)
    assert result.layout_names == ("PAGE-001", "PAGE-002")

    document = ezdxf.readfile(result.path)
    assert "PAGE-001" in document.layouts
    assert "PAGE-002" in document.layouts
    assert sum(entity.dxftype() == "IMAGE" for entity in document.modelspace()) == 2
    assert sum(entity.dxftype() == "LINE" for entity in document.modelspace()) == 1
    assert sum(entity.dxftype() == "IMAGE" for entity in document.layouts.get("PAGE-001")) == 1
    assert sum(entity.dxftype() == "LINE" for entity in document.layouts.get("PAGE-001")) == 1
