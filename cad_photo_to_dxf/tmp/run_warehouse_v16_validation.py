from __future__ import annotations

import json
from pathlib import Path
import sys
from time import perf_counter

import ezdxf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.dxf_validator import validate_dxf  # noqa: E402
from app.image_loader import load_image, pdf_page_size_mm  # noqa: E402
from app.ocr_outline_export import accepted_ocr_texts  # noqa: E402
from app.optimized_trace import trace_image_optimized  # noqa: E402
from app.scale_calibrator import ScaleCalibration  # noqa: E402
from app.trace_dxf_entities import TracePalette  # noqa: E402
from app.trace_single_export import export_exact_trace_dxf  # noqa: E402


SOURCE = Path(r"C:\Users\agcrf\Desktop\图纸-综合仓库-电专业+815.pdf")
OUTPUT_DIRECTORY = Path(
    r"C:\Users\agcrf\Desktop\image-to-cad\cad_photo_to_dxf"
    r"\validation\scan-artifact-visual-fix-2026-07-28"
)
OUTPUT_DXF = OUTPUT_DIRECTORY / "warehouse-page-001-ownership-v16.dxf"
OUTPUT_REPORT = OUTPUT_DIRECTORY / "warehouse-page-001-ownership-v16.report.json"
PAGE_INDEX = 0
PDF_DPI = 290


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    page_mm = pdf_page_size_mm(SOURCE, PAGE_INDEX)
    image = load_image(
        SOURCE,
        page_index=PAGE_INDEX,
        pdf_dpi=PDF_DPI,
        grayscale=True,
    )
    started = perf_counter()
    trace = trace_image_optimized(image, enable_ocr=True)
    height, width = image.shape
    calibration = ScaleCalibration((0.0, 0.0), (float(width), 0.0), page_mm[0])
    exported = export_exact_trace_dxf(
        trace.paths,
        OUTPUT_DXF,
        height,
        calibration,
        image_width=width,
        palette=TracePalette(straight=5, curve=6, text_symbol=6),
        straight_lines=trace.straight_lines,
        texts=trace.texts,
        signatures=trace.signatures,
    )
    audit = validate_dxf(OUTPUT_DXF)
    document = ezdxf.readfile(OUTPUT_DXF)
    entity_count = len(list(document.modelspace()))
    editable_texts = accepted_ocr_texts(trace.texts)
    payload = {
        "source": str(SOURCE),
        "page": PAGE_INDEX + 1,
        "page_mm": list(page_mm),
        "dpi": PDF_DPI,
        "image_shape": [height, width],
        "seconds": round(perf_counter() - started, 3),
        "texts_total": len(trace.texts),
        "texts_editable": len(editable_texts),
        "signatures": len(trace.signatures),
        "straight_lines": len(trace.straight_lines),
        "trace_paths": len(trace.paths),
        "dxf_entities": entity_count,
        "exported_trace_paths": exported.trace_path_count,
        "exported_texts": exported.text_count,
        "audit_passed": audit.passed,
        "audit_errors": list(audit.audit_errors),
        "audit_fixes": list(audit.audit_fixes),
        "warnings": list(trace.warnings),
    }
    OUTPUT_REPORT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
