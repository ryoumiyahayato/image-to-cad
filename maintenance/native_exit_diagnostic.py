"""Temporary PR #34 isolation, not a substitute for the normal CI process."""

from importlib import import_module
from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[1] / "cad_photo_to_dxf"
sys.path.insert(0, str(PROJECT))

GROUPS = {
    "pdf": [
        "test_native_arc_pipeline.py", "test_native_arc_replacement.py",
        "test_pdf_arc_admission.py", "test_pdf_arc_round_cap.py", "test_pdf_input.py",
    ],
    "ocr": [
        "test_ocr_recognition.py", "test_ocr_digit_orientation.py",
        "test_rotated_text_orientation.py", "test_optimized_ocr.py",
    ],
    "qt": [
        "test_exact_gui_cache.py", "test_exact_ui_reduction.py", "test_gui_architecture.py",
        "test_font_aware_ocr_export.py", "test_native_text_geometry.py",
        "test_librecad_lff_export.py", "test_review_save_preservation.py",
        "test_trace_scale_semantics.py", "test_visual_acceptance.py",
    ],
    "processing": [
        "test_processing_contract.py", "test_scan_line_regularization.py",
        "test_source_stroke_reconciliation_v1.py", "test_product_p4_same_track_aliases.py",
    ],
}


class NoneReferences:
    def __init__(self):
        self.last = sys.getrefcount(None)
        self.changes = []

    def pytest_runtest_logfinish(self, nodeid, location):
        current = sys.getrefcount(None)
        self.changes.append((current - self.last, nodeid))
        self.last = current

    def pytest_sessionfinish(self):
        print("None references at session finish:", sys.getrefcount(None), flush=True)
        print("Largest per-test decreases (diagnostic, not assertions):", flush=True)
        for change in sorted(self.changes)[:12]:
            print(change, flush=True)


if __name__ == "__main__":
    group = sys.argv[1]
    print(sys.version, "group", group, "None references", sys.getrefcount(None), flush=True)
    if group == "imports":
        for name in ("pypdfium2", "cv2", "rapidocr", "onnxruntime",
                     "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
            import_module(name)
            print("imported", name, "None references", sys.getrefcount(None), flush=True)
    else:
        import pytest

        paths = [str(PROJECT / "tests" / name) for name in GROUPS[group]
                 if (PROJECT / "tests" / name).exists()]
        print("Selected files:", paths, flush=True)
        raise SystemExit(pytest.main(["-q", *paths], plugins=[NoneReferences()]))
