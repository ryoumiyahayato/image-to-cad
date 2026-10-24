"""Compare current fixtures to the reviewed, versioned compact baseline.

The original and P10-A baselines remain immutable historical evidence.
The current contract retains every P10-A source obligation. Its only allowed
identity extension on these inputs is an empty closed-scan-curve record list.
"""

import argparse
from collections import Counter
from dataclasses import replace
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
    baseline = json.loads((ROOT / "docs/refactor/preservation-current-20261024.json").read_text())
    assert baseline["format"] == "compact-preservation-20261024-v1"
    assert baseline["algorithm_version"] == ProductionProcessingConfig().algorithm_version, "Unreviewed algorithm version"
    assert baseline["final_structure_schema_version"] == FINAL_STRUCTURE_SCHEMA_VERSION, "Unreviewed structure schema"
    assert baseline["trace_cache_version"] == TRACE_CACHE_VERSION, "Unreviewed cache version"
    previous = load_p10a_baseline()
    assert baseline["transition"] == previous["transition"], "P10-A source obligations changed"
    assert set(baseline["cases"]) == set(previous["cases"]), "P10-A case coverage changed"
    for name, case in baseline["cases"].items():
        assert {k: v for k, v in case.items() if k != "id"} == {
            k: v for k, v in previous["cases"][name].items() if k != "id"
        }, f"{name}: P10-A geometry or output contract changed"
    return baseline


def verify_p10a_identity(name, structure):
    """Permit only the reviewed empty metadata extension, not geometry drift."""
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
            assert not ezdxf.readfile(exported.path).audit().errors
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
    print("EXACT 2026-10-24 baseline match; P10-A identity and historical LINE source obligations preserved")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"passed": True, "inputs": measured}, indent=2) + "\n",
            encoding="utf-8",
        )
