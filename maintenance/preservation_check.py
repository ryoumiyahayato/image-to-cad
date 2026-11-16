"""Compare current fixtures to the reviewed, versioned compact baseline.

The original and P10-A baselines remain immutable historical evidence.
The current contract retains every P10-A LINE source obligation. A finite,
source-checked r13 transition restores the sample's original dark image edge
and represents fourteen degenerate raster runs by their actual source cells.
The previous contracts remain immutable; no runtime geometry is changed here.
"""

import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "cad_photo_to_dxf"
sys.path.insert(0, str(PROJECT))
import cv2
import ezdxf
import numpy as np
from app.core.processing import ProductionProcessingConfig, ProductionProcessingService
from app.export.trace_single_export import export_final_structure_dxf
from app.core.cache import save_trace_cache, load_trace_cache
from app.core.cache import TRACE_CACHE_VERSION
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION, metadata_to_jsonable
from app.geometry.line_detect import LineSegment
from app.geometry.scan_cleanup import prepare_scan_page
from app.geometry.source_stroke_reconciliation import _measurement_claim_window


def load_p10a_baseline():
    baseline = json.loads((ROOT / "docs/refactor/preservation-current-p10a.json").read_text())
    assert baseline["format"] == "compact-preservation-p10a-v1"
    return baseline


def load_current_baseline():
    baseline = json.loads((ROOT / "docs/refactor/preservation-current-20261116.json").read_text())
    assert baseline["format"] == "compact-preservation-20261116-v1"
    assert baseline["algorithm_version"] == ProductionProcessingConfig().algorithm_version, "Unreviewed algorithm version"
    assert baseline["final_structure_schema_version"] == FINAL_STRUCTURE_SCHEMA_VERSION, "Unreviewed structure schema"
    assert baseline["trace_cache_version"] == TRACE_CACHE_VERSION, "Unreviewed cache version"
    previous = json.loads((ROOT / "docs/refactor/preservation-current-20261024.json").read_text())
    p10a = load_p10a_baseline()
    assert baseline["transition"] == previous["transition"] == p10a["transition"], "P10-A source obligations changed"
    assert set(baseline["cases"]) == set(previous["cases"]) == set(p10a["cases"]), "P10-A case coverage changed"
    raster = load_raster_transition()
    for name, case in baseline["cases"].items():
        expected = dict(previous["cases"][name])
        if name in raster:
            review = raster[name]
            assert expected["id"] == review["before_id"]
            assert expected["dxf_entities"] == review["dxf_entities_before"]
            expected.update(id=review["after_id"], dxf_entities=review["dxf_entities_after"])
        assert case == expected, f"{name}: unreviewed geometry or output contract changed"
    return baseline


def load_raster_transition():
    value = json.loads((ROOT / "docs/refactor/preservation-raster-transition-20261116.json").read_text())
    assert value["format"] == "compact-r13-raster-transition-20261116-v1"
    assert set(value["cases"]) == {"sample-test"}, "Unreviewed raster transition case"
    assert sha256((PROJECT / "samples/test.jpg").read_bytes()).hexdigest() == value["cases"]["sample-test"]["mask"]["source_file_sha256"], (
        "Reviewed raster source fixture changed"
    )
    return value["cases"]


def project_reviewed_raster_transition(name, structure):
    """Reconstruct only enumerated historical records for the old identity check.

    This is an assertion projection, never a product/cache/export mutation.
    Both actual masks and every changed path must match the finite review.
    All other geometry, source IDs, widths and metadata survive unchanged.
    """
    review = load_raster_transition().get(name)
    if review is None:
        return structure
    mask = review["mask"]
    actual = structure.contour_binary
    assert list(actual.shape) == mask["shape"], f"{name}: raster source shape changed"
    assert sha256(actual.tobytes()).hexdigest() == mask["after_sha256"], (
        f"{name}: unreviewed raster source mask"
    )
    band = np.ones(actual.shape, dtype=bool)
    margin = mask["border_width_px"]
    band[margin:-margin, margin:-margin] = False
    assert int(band.sum()) == mask["restored_black_pixels"]
    assert np.all(actual[band] == 0), f"{name}: restored original edge ink lost"
    historical_mask = actual.copy()
    historical_mask[band] = 255
    assert sha256(historical_mask.tobytes()).hexdigest() == mask["before_sha256"], (
        f"{name}: unreviewed non-edge source change"
    )
    paths = list(structure.contours)
    for item in review["contours"]:
        index, before, after = item["index"], item["before"], item["after"]
        path = paths[index]
        assert [list(point) for point in path.points] == after["points"], (
            f"{name}: unreviewed raster contour geometry at {index}"
        )
        assert all(getattr(path, key) == after[key] == before[key] for key in ("parent", "depth", "root")), (
            f"{name}: raster contour hierarchy changed"
        )
        paths[index] = replace(path, points=tuple(map(tuple, before["points"])))
    return replace(structure, contour_binary=historical_mask, contours=tuple(paths))


def verify_p10a_identity(name, structure):
    """Reject changes outside the finite r13 transition and empty curve metadata."""
    structure = project_reviewed_raster_transition(name, structure)
    provenance = metadata_to_jsonable(structure.provenance)
    presentation = provenance.get("stroke_presentation", {})
    if "closed_scan_curve_records" in presentation:
        assert presentation.pop("closed_scan_curve_records") == [], (
            f"{name}: unreviewed closed-curve records"
        )
    previous = load_p10a_baseline()
    assert replace(structure, provenance=provenance).structure_id == previous["cases"][name]["id"], (
        f"{name}: P10-A observable structure changed beyond reviewed empty metadata"
    )


def verify_transition(name, image, structure, baseline, historical):
    """Account for every old LINE; a count-only or source-losing update fails."""
    raster = load_raster_transition().get(name)
    if raster is not None:
        # An image extent is not an independently verified physical paper edge.
        # These restored pixels must be dark in the actual unprocessed source.
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        mask = raster["mask"]
        assert list(gray.shape) == mask["shape"]
        band = np.ones(gray.shape, dtype=bool)
        margin = mask["border_width_px"]
        band[margin:-margin, margin:-margin] = False
        assert np.all(gray[band] < 128), f"{name}: restored edge lacks original black source"
    old = {tuple(line) for line in historical[name]["lines"]}
    current = {(line.x1, line.y1, line.x2, line.y2): line
               for line in structure.straight_lines}
    approved = baseline["transition"].get(name, [])
    assert not set(current) - old, f"{name}: unreviewed added geometry"
    assert old - set(current) == {tuple(row["removed"]) for row in approved}, (
        f"{name}: unaccounted historical LINE change"
    )
    if not approved:
        return
    prepared = prepare_scan_page(image)
    for row in approved:
        keeper = current[tuple(row["keeper"])]
        assert keeper.width == row["width"]
        assert set(row["source_ids"]).issubset(keeper.source_ids)
        removed = LineSegment(*row["removed"], width=row["width"])
        window, (kept, previous) = _measurement_claim_window(
            (keeper, removed), shape=prepared.binary.shape)
        assert not np.any((previous > 0) & (kept == 0) & (prepared.binary[window] < 128)), (
            f"{name}: removed LINE has unique source ink"
        )


def inputs():
    from tests.test_processing_contract import _page

    yield "processing-contract-page", _page()
    # Existing sample at its native resolution.
    yield "sample-test", cv2.imread(str(PROJECT / "samples/test.jpg"))
    from tests.test_source_stroke_reconciliation_v1 import _page as blank, _draw, _line

    page = blank()
    for line in [
        _line(20, 50, 100, 50, "a"),
        _line(104, 50, 210, 50, "b"),
        _line(100, 20, 100, 180, "c"),
    ]:
        _draw(page, line)
    yield "reconciliation-gap-junction", page


def measure(*, baseline=None, historical=None):
    output = {}
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        for name, image in inputs():
            result = ProductionProcessingService.process_page(
                image, ProductionProcessingConfig(enable_ocr=False)
            )
            structure = result.final_structure
            assert structure is not None
            if baseline is not None:
                verify_transition(name, image, structure, baseline, historical)
                verify_p10a_identity(name, structure)
            exported = export_final_structure_dxf(structure, tmp / f"{name}.dxf")
            document = ezdxf.readfile(exported.path)
            assert not document.audit().errors
            verify_raster_export(name, structure, document)
            saved = load_trace_cache(save_trace_cache(tmp / f"{name}.npz", result))
            assert saved.final_structure.structure_id == structure.structure_id
            item = {
                "id": structure.structure_id,
                "size": list(structure.source_size_px),
                "members": {
                    key: len(getattr(structure, key))
                    for key in (
                        "straight_lines",
                        "contours",
                        "texts",
                        "logos",
                        "signatures",
                        "arcs",
                    )
                },
                "lines": [[x.x1, x.y1, x.x2, x.y2] for x in structure.straight_lines],
                "dxf_entities": dict(
                    Counter(
                        x.dxftype() for x in ezdxf.readfile(exported.path).modelspace()
                    )
                ),
            }
            output[name] = item
            print(name, item["members"], flush=True)
    return output


def verify_raster_export(name, structure, document):
    """Check actual saved HATCH cells and source tags, not only entity counts."""
    from app.diagnostics.trace_verification import verify_trace_paths

    assert verify_trace_paths(structure.contour_binary, structure.contours).exact, (
        f"{name}: contour tree no longer reproduces the exact source mask"
    )
    paths = [path for path in structure.contours if len(path.points) in (1, 2)]
    expected = {}
    height = structure.source_size_px[1]
    for path in paths:
        x0, y0 = path.points[0]
        x1, y1 = path.points[-1]
        assert all(float(v).is_integer() for v in (x0, y0, x1, y1))
        assert x0 == x1 or y0 == y1 or abs(x1-x0) == abs(y1-y0)
        dx, dy = int(np.sign(x1-x0)), int(np.sign(y1-y0))
        count = int(max(abs(x1-x0), abs(y1-y0))) + 1
        key = ("UNRESOLVED", int(x0), int(y0), int(x1), int(y1))
        assert key not in expected
        expected[key] = {(int(y0)+dy*i, int(x0)+dx*i) for i in range(count)}
    seen = set()
    actual_cell_count = 0
    for hatch in document.modelspace().query("HATCH"):
        key = tuple(t.value for t in hatch.get_xdata("RASTER_INK_SOURCE"))
        assert key in expected and key not in seen, f"{name}: unbound or duplicate raster HATCH"
        seen.add(key)
        layer = document.layers.get(hatch.dxf.layer)
        assert hatch.dxf.layer == "UNRESOLVED_RASTER_INK" and hatch.dxf.color == 7
        assert not layer.is_off() and not layer.is_frozen()
        assert (not hatch.dxf.get("invisible", 0)
                and not hatch.dxf.hasattr("true_color")
                and not hatch.dxf.hasattr("transparency")
                and layer.dxf.color == 7 and not layer.dxf.hasattr("true_color")), (
            f"{name}: raster HATCH display changed"
        )
        assert hatch.dxf.solid_fill == 1 and hatch.dxf.associative == 0 and hatch.dxf.hatch_style == 0
        assert tuple(hatch.dxf.elevation) == (0, 0, 0) and tuple(hatch.dxf.extrusion) == (0, 0, 1)
        assert hatch.gradient is None
        cells = set()
        for boundary in hatch.paths:
            assert boundary.is_closed and len(boundary.vertices) == 4
            assert all(v[2] == 0 for v in boundary.vertices)
            vertices = np.array([v[:2] for v in boundary.vertices])
            assert np.equal(vertices, np.rint(vertices)).all()
            left, bottom = vertices.min(axis=0).astype(int)
            right, top = vertices.max(axis=0).astype(int)
            assert {tuple(v) for v in vertices} == {(left,bottom),(right,bottom),(right,top),(left,top)}
            area_twice = sum(
                x0*y1-x1*y0
                for (x0,y0),(x1,y1) in zip(vertices, np.roll(vertices, -1, axis=0))
            )
            assert right > left and top > bottom and abs(area_twice) == 2*(right-left)*(top-bottom), (
                f"{name}: raster HATCH boundary is not a simple rectangle"
            )
            part = {(y,x) for y in range(height-top,height-bottom) for x in range(left,right)}
            assert not cells.intersection(part)
            cells.update(part)
        assert cells == expected[key], f"{name}: raster HATCH differs from actual source cells"
        assert all(structure.contour_binary[y,x] == 0 for y,x in cells)
        actual_cell_count += len(cells)
    assert seen == set(expected), f"{name}: original raster source run missing"
    review = load_raster_transition().get(name)
    if review is not None:
        assert actual_cell_count == review["raster_run_cells"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.baseline:
        parser.error("Historical baseline is immutable; changes require a reviewed new version")
    baseline = load_current_baseline()
    historical = json.loads((ROOT / "docs/refactor/preservation-baseline.json").read_text())
    measured = measure(baseline=baseline, historical=historical)
    assert set(measured) == set(baseline["cases"])
    for name, value in measured.items():
        assert value == baseline["cases"][name], name
    print("EXACT 2026-11-16 reviewed baseline match; finite raster transition, P10-A identity projection and historical LINE source obligations preserved")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"passed": True, "inputs": measured}, indent=2) + "\n",
            encoding="utf-8",
        )
