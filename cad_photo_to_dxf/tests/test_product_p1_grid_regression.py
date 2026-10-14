"""Real Warehouse PDF regressions in the original UAT raster coordinates."""
from functools import lru_cache
import json
from pathlib import Path

import ezdxf
import numpy as np
import pytest

from app.core.image_loader import load_image
from app.core.scale_calibrator import ScaleCalibration
from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.line_detect import LineSegment
from app.geometry.scan_cleanup import prepare_scan_page
from app.geometry.source_stroke_reconciliation import ReconciliationLedger
from app.geometry.straight_line_reconstruction import normalize_source_supported_grid_strokes

HERE = Path(__file__).parent


@lru_cache(maxsize=2)
def source(page):
    image = load_image(HERE / "real_regression/assets/sources/warehouse-electrical-vector.pdf",
                       page_index=page - 1, pdf_dpi=240 if page == 1 else 110, grayscale=True)
    return prepare_scan_page(image)


def observations(uid):
    data = json.loads((HERE / "fixtures/product-p1-source-lines.json").read_text())
    return [LineSegment(**{**item, "source_ids": tuple(item["source_ids"]),
                           "history": tuple(item["history"]),
                           "classification_reasons": tuple(item["classification_reasons"])})
            for item in data[uid]]


def test_w01_real_triplicate_and_two_junctions_survive_finalstructure_dxf_reopen(tmp_path):
    prepared = source(1)
    lines = observations("W01")
    ledger = ReconciliationLedger(source_gray=prepared.gray, source_binary=prepared.binary,
                                  protected_mask=np.zeros_like(prepared.binary), scale=1.0)
    repaired = normalize_source_supported_grid_strokes(
        lines, binary=prepared.binary, maximum_extension=0.4 * 240 / 25.4,
        reconciliation_ledger=ledger)
    assert len(repaired) == 3
    horizontal = next(line for line in repaired if "HOUGH-000029" in line.source_ids)
    assert set(horizontal.source_ids) == {"HOUGH-000029", "LSD-001063", "LSD-001069"}
    assert (horizontal.x1, horizontal.y1, horizontal.x2, horizontal.y2) == (471, 1024, 660, 1024)
    for sid, point in [("HOUGH-000244", horizontal.p1), ("HOUGH-000106", horizontal.p2)]:
        vertical = next(line for line in repaired if sid in line.source_ids)
        assert np.array_equal(vertical.p2, point)
    # The entire retained span is original ink, including both repaired nodes.
    assert np.all(prepared.binary[1024, 471:661] == 0)
    result = ledger.reconcile(main_candidates=repaired, accepted_main=repaired,
                              restoration_candidates=(), ownership_masks={
                                  "line": np.where(prepared.binary == 0, 255, 0).astype(np.uint8),
                                  **{key: np.zeros_like(prepared.binary) for key in
                                     ("text", "logo", "signature", "graphic", "residual")},
                              })
    result.assert_complete(result.lines)
    h, w = prepared.binary.shape
    structure = build_final_structure(source_size_px=(w, h), contour_binary=np.full((h, w), 255, np.uint8),
                                     contours=(), straight_lines=result.lines)
    path = tmp_path / "W01.dxf"
    export_final_structure_dxf(structure, path, ScaleCalibration((0, 0), (w - 1, 0), 230.0111111111111))
    doc = ezdxf.readfile(path)
    assert not doc.audit().errors
    entities = list(doc.modelspace().query("LINE"))
    assert len(entities) == 3
    endpoints = [tuple(e.dxf.start) for e in entities] + [tuple(e.dxf.end) for e in entities]
    assert sorted(endpoints.count(p) for p in set(endpoints)) == [1, 1, 2, 2]
    entity = entities[0]
    handle = entity.dxf.handle
    edited = (entity.dxf.start.x + 0.125, entity.dxf.start.y, 0)
    entity.dxf.start = edited
    doc.saveas(tmp_path / "edited.dxf")
    reopened = ezdxf.readfile(tmp_path / "edited.dxf")
    assert tuple(reopened.entitydb[handle].dxf.start) == edited
    assert not reopened.audit().errors


def test_w03_real_parallel_walls_door_opening_and_xy_pattern_remain_separate():
    prepared = source(3)
    lines = observations("W03")
    repaired = normalize_source_supported_grid_strokes(
        lines, binary=prepared.binary, maximum_extension=0.4 * 110 / 25.4)
    # Includes distinct rails y=373/381/384, the door at x=2233..2245,
    # and the actual XY interrupted wiring beside that door.
    assert repaired == lines
    assert any(line.y1 == 373 for line in repaired)
    assert any(line.y1 == 381 for line in repaired)
    assert any(line.y1 == 384 for line in repaired)
    assert not any(2230 < line.x1 < 2250 and 2230 < line.x2 < 2250
                   and min(line.y1, line.y2) < 1100 and max(line.y1, line.y2) > 1200
                   for line in repaired)


def test_w01_real_wordmark_enclosure_is_outside_table_repair():
    lines = observations("W01_ENCLOSURE")
    assert len(lines) == 2
    assert normalize_source_supported_grid_strokes(
        lines, binary=source(1).binary, maximum_extension=0.4 * 240 / 25.4) == lines


@pytest.mark.parametrize("veto", ["protected", "source_gap"])
def test_w01_rule_identity_never_overrides_protection_or_missing_source(veto):
    prepared = source(1)
    binary = prepared.binary.copy()
    protected = np.zeros_like(binary)
    if veto == "protected":
        protected[1024, 550] = 255
    else:
        binary[1020:1030, 550] = 255
    original = observations("W01")
    result = normalize_source_supported_grid_strokes(
        original, binary=binary, maximum_extension=0.4 * 240 / 25.4, protected_mask=protected)
    ids = {"HOUGH-000029", "LSD-001063", "LSD-001069"}
    assert [line for line in result if ids.intersection(line.source_ids)] == [
        line for line in original if ids.intersection(line.source_ids)]
