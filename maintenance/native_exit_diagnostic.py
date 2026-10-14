"""Temporary PR #34 isolation, not a substitute for the normal CI process."""

from importlib import import_module
from pathlib import Path
import sys
import gc


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
    if group == "probes":
        import cv2
        import numpy as np
        import pypdfium2 as pdfium
        from PySide6.QtGui import QImage, QPainter, QPainterPath, QFont
        from PySide6.QtWidgets import QApplication
        print("cv2", cv2.__version__, flush=True)
        app = QApplication([])
        image = np.full((80, 120), 255, np.uint8)
        cv2.line(image, (10, 40), (100, 40), 0, 2)
        points = np.array([[10, 40], [100, 40]], np.int32)
        lsd = cv2.createLineSegmentDetector()
        def pdf_cycle():
            doc = pdfium.PdfDocument.new()
            page = doc.new_page(80, 80)
            bitmap = page.render(scale=1)
            bitmap.close()
            page.close()
            doc.close()
        def qt_cycle():
            canvas = QImage(120, 80, QImage.Format.Format_RGB32)
            path = QPainterPath()
            path.addText(10, 40, QFont("Sans", 10), "A1")
            painter = QPainter(canvas)
            painter.drawPath(path)
            painter.end()
        calls = {
            "cv2-line": lambda: cv2.line(image, (10,40), (100,40), 0, 2),
            "cv2-polylines": lambda: cv2.polylines(image, [points], False, 0, 1),
            "cv2-contours": lambda: cv2.findContours(image, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE),
            "cv2-components": lambda: cv2.connectedComponentsWithStats(image),
            "cv2-hough": lambda: cv2.HoughLinesP(image, 1, np.pi/180, 15, minLineLength=10),
            "cv2-lsd": lambda: lsd.detect(image),
            "pdf-cycle": pdf_cycle,
            "qt-cycle": qt_cycle,
        }
        for name, call in calls.items():
            for _ in range(8):
                call()
            gc.collect()
            counts = [sys.getrefcount(None)]
            for _batch in range(2):
                for _ in range(128):
                    call()
                gc.collect()
                counts.append(sys.getrefcount(None))
            print(name, counts, flush=True)
    elif group == "imports":
        for name in ("pypdfium2", "cv2", "rapidocr", "onnxruntime",
                     "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
            import_module(name)
            print("imported", name, "None references", sys.getrefcount(None), flush=True)
    else:
        import pytest

        names = [name for group_names in GROUPS.values() for name in group_names] if group == "combined" else GROUPS.get(group, [])
        paths = ([str(PROJECT / "tests")] if group == "full" else
                 [str(PROJECT / "tests" / name) for name in names
                  if (PROJECT / "tests" / name).exists()])
        print("Selected files:", paths, flush=True)
        raise SystemExit(pytest.main(["-q", *paths], plugins=[NoneReferences()]))
