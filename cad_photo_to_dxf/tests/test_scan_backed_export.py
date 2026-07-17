from __future__ import annotations

import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.dxf_exporter import export_dxf
from app.line_detect import LineSegment


def test_export_includes_linked_scan_and_high_confidence_text(tmp_path) -> None:
    output = tmp_path / "drawing.dxf"
    scan = np.full((120, 240, 3), 255, dtype=np.uint8)
    result = export_dxf(
        [LineSegment(10.0, 20.0, 220.0, 20.0)],
        output,
        image_height=120,
        texts=[TextCandidate("施工说明", (20, 30, 80, 18), 0.92, "text_candidate")],
        raster_image=scan,
    )

    assert output.is_file()
    assert result.underlay_path is not None
    assert result.underlay_path.is_file()
    assert result.line_count == 1
    assert result.text_count == 1

    document = ezdxf.readfile(output)
    entity_types = [entity.dxftype() for entity in document.modelspace()]
    assert entity_types.count("LINE") == 1
    assert entity_types.count("TEXT") == 1
    assert entity_types.count("IMAGE") == 1
