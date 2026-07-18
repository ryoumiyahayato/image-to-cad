from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.auxiliary_recognition import CircleCandidate, TextCandidate
from app.document_exporter import DocumentPage, export_document_dxf
from app.line_detect import LineSegment


def _write_scan(path: Path, width: int, height: int, label: str) -> np.ndarray:
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (6, 6), (width - 7, height - 7), (0, 0, 0), 2)
    cv2.putText(
        image,
        label,
        (15, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    assert cv2.imwrite(str(path), image)
    return image


def test_export_document_places_pages_in_one_editable_dxf(tmp_path: Path) -> None:
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first_image = _write_scan(first_path, 240, 160, "PAGE 1")
    second_image = _write_scan(second_path, 180, 220, "PAGE 2")
    pages = [
        DocumentPage(
            lines=(LineSegment(10, 50, 220, 50, layer="GRID_OR_AXIS"),),
            image_width=240,
            image_height=160,
            circles=(CircleCandidate((80, 90), 14, 1.0),),
            texts=(TextCandidate("P1", (100, 80, 28, 16), 1.0, "manual_text"),),
            raster_path=first_path,
            label="First page",
            source_page=1,
        ),
        DocumentPage(
            lines=(LineSegment(10, 70, 160, 70, layer="WALL_OR_FRAME"),),
            image_width=180,
            image_height=220,
            raster_path=second_path,
            label="Second page",
            source_page=2,
        ),
    ]

    result = export_document_dxf(pages, tmp_path / "combined.dxf")

    assert result.page_count == 2
    assert result.line_count == 2
    assert result.circle_count == 1
    assert result.text_count == 1
    assert len(result.underlay_paths) == 2
    assert np.array_equal(first_image, cv2.imread(str(result.underlay_paths[0])))
    assert np.array_equal(second_image, cv2.imread(str(result.underlay_paths[1])))

    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    assert len(modelspace.query("IMAGE")) == 2
    assert len(modelspace.query("CIRCLE")) == 1
    assert len(modelspace.query("LINE")) == 10  # two vectors plus two page frames
    assert len(modelspace.query("TEXT")) == 3  # one editable text plus page labels
    group_names = {name for name, _group in document.groups}
    assert {"PAGE_001", "PAGE_002"} <= group_names
