"""Public original fixtures for the newly synchronized native-area adapter.

These exercise storage and export, not real-drawing acceptance or GUI editing.
"""

import ezdxf
import numpy as np
import pytest

from app.core.arc_types import PdfPathReference
from app.core.cache import load_trace_cache, save_trace_cache
from app.core.native_fill import NativeFill
from app.core.structure_build import final_structure_from_trace_result
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.raster_trace import RasterTraceResult


def area_result():
    fill = NativeFill(
        source=PdfPathReference("QA_TEST_ONLY.pdf", 1, 0),
        points=((10, 10), (30, 10), (30, 20), (20, 20), (20, 35), (10, 35)),
        rgb=(123, 123, 123),
        page_to_pixel=(1, 0, 0, 1, 0, 0),
        source_dpi=72,
        version=2,
        visibility="full-only-without-opaque-simple-polygon-v2",
    )
    return RasterTraceResult(
        binary=np.full((64, 64), 255, dtype=np.uint8),
        stages={}, paths=(), threshold=128, foreground_pixels=0, vertex_count=0,
        native_fills=(fill,),
    )


def test_native_area_survives_adapter_cache_and_independent_dxf_read(tmp_path):
    result = area_result()
    structure = final_structure_from_trace_result(result)
    assert structure.native_fills == result.native_fills
    stored = load_trace_cache(save_trace_cache(tmp_path / "area.npz", result))
    assert stored.final_structure.native_fills == result.native_fills
    assert stored.final_structure.structure_id == structure.structure_id
    path = export_final_structure_dxf(stored.final_structure, tmp_path / "area.dxf").path
    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())
    assert [entity.dxftype() for entity in entities] == ["HATCH"]
    hatch = entities[0]
    assert hatch.rgb == (123, 123, 123)
    assert [(x, y) for x, y, _ in hatch.paths[0].vertices] == [
        (x, 64 - y) for x, y in result.native_fills[0].points
    ]
    assert hatch.paths[0].is_closed
    assert hatch.get_xdata("P18_NATIVE_FILL")[0].value == result.native_fills[0].object_id
    audit = doc.audit()
    assert not audit.errors and not audit.fixes


@pytest.mark.parametrize("mutation", ["missing", "empty", "changed-color"])
def test_cache_cannot_silently_drop_or_change_a_native_area(tmp_path, mutation):
    path = save_trace_cache(tmp_path / "area.npz", area_result())
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key].copy() for key in archive.files}
    if mutation == "missing":
        del data["native_fills_json"]
    elif mutation == "empty":
        data["native_fills_json"] = np.asarray(["[]"])
    else:
        data["native_fills_json"] = np.char.replace(
            data["native_fills_json"], "123", "124"
        )
    np.savez_compressed(path, **data)
    with pytest.raises(ValueError, match="fingerprint does not match"):
        load_trace_cache(path)
