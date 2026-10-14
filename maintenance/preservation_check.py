"""Compare current fixtures to the retained compact baseline.

The baseline's historical generation provenance is unproven. This is a current
regression check, not proof of independent PRE execution; that evidence is
documented separately under docs/refactor.
"""

import argparse
from collections import Counter
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


def measure():
    output = {}
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        for name, image in inputs():
            result = ProductionProcessingService.process_page(
                image, ProductionProcessingConfig(enable_ocr=False)
            )
            structure = result.final_structure
            assert structure is not None
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
    measured = measure()
    path = ROOT / "docs/refactor/preservation-baseline.json"
    if args.baseline:
        path.write_text(json.dumps(measured, indent=2) + "\n")
    else:
        expected = json.loads(path.read_text())
        for name, value in measured.items():
            assert value == {
                k: v for k, v in expected[name].items() if k != "legacy"
            }, name
        print("EXACT current compact baseline match (historical baseline provenance UNPROVEN)")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"passed": True, "inputs": measured}, indent=2) + "\n",
                encoding="utf-8",
            )
