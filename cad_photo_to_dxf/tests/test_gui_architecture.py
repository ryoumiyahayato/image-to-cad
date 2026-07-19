from __future__ import annotations

import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"


def imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class GuiArchitectureTests(unittest.TestCase):
    def test_compatibility_gui_contains_no_processing_pipeline(self) -> None:
        source = (APP_ROOT / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined_functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        forbidden_functions = {
            "auto_perspective",
            "preprocess",
            "detect_and_clean",
            "export_file",
            "build_processing_report",
        }
        self.assertTrue(forbidden_functions.isdisjoint(defined_functions))

        imported = imported_modules(tree)
        forbidden_modules = {
            "line_detect",
            "geometry_cleaner",
            "layer_classifier",
            "dxf_exporter",
            "reporting",
            "processing_service",
            "pipeline_service",
        }
        self.assertTrue(forbidden_modules.isdisjoint(imported))

    def test_active_entrypoint_preserves_guard_chain_and_uses_trace_release(self) -> None:
        main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        release_source = (APP_ROOT / "gui_trace_release.py").read_text(encoding="utf-8")
        trace_source = (APP_ROOT / "gui_trace_mode.py").read_text(encoding="utf-8")
        consolidated_source = (APP_ROOT / "gui_consolidated.py").read_text(
            encoding="utf-8"
        )
        state_source = (APP_ROOT / "gui_state_guard.py").read_text(encoding="utf-8")
        review_source = (APP_ROOT / "gui_review.py").read_text(encoding="utf-8")
        guard_source = (APP_ROOT / "gui_guard.py").read_text(encoding="utf-8")
        compatibility_source = (APP_ROOT / "gui.py").read_text(encoding="utf-8")

        self.assertIn("from app.gui_state_guard import MainWindow", main_source)
        self.assertIn("from app.gui_trace_release import MainWindow", main_source)
        self.assertIn("from .gui_trace_mode import MainWindow", release_source)
        self.assertIn("from .gui_consolidated import MainWindow", trace_source)
        self.assertIn("from .gui_state_guard import", consolidated_source)
        self.assertIn("from .gui_review import MainWindow", state_source)
        self.assertIn("from .gui_guard import MainWindow", review_source)
        self.assertIn("from . import gui as _gui", guard_source)
        self.assertIn("from .ui_shell import MainWindow", compatibility_source)

    def test_ui_shell_has_no_cad_algorithm_imports(self) -> None:
        source = (APP_ROOT / "ui_shell.py").read_text(encoding="utf-8")
        forbidden_import_fragments = (
            "detect_lines",
            "clean_geometry",
            "classify_layers",
            "export_dxf",
            "build_processing_report",
            "process_corrected_image",
            "PipelineService",
        )
        for fragment in forbidden_import_fragments:
            self.assertNotIn(fragment, source)

    def test_normal_gui_uses_literal_trace_and_black_white_repair(self) -> None:
        release_source = (APP_ROOT / "gui_trace_release.py").read_text(encoding="utf-8")
        trace_source = (APP_ROOT / "gui_trace_mode.py").read_text(encoding="utf-8")
        engine_source = (APP_ROOT / "raster_trace.py").read_text(encoding="utf-8")
        paint_source = (APP_ROOT / "trace_paint.py").read_text(encoding="utf-8")

        self.assertIn("TRACE_PDF_DPI = 300", release_source)
        self.assertIn("trace_image", release_source)
        self.assertIn("完整拓印全部黑白线条", trace_source)
        self.assertIn("图纸比例 1:", trace_source)
        self.assertIn("TracePaintDialog", trace_source)
        self.assertIn("cv2.RETR_TREE", engine_source)
        self.assertIn("cv2.CHAIN_APPROX_SIMPLE", engine_source)
        self.assertNotIn("detect_lines(", engine_source)
        self.assertNotIn("clean_geometry", engine_source)
        self.assertIn("黑色：补充线条", paint_source)
        self.assertIn("白色：擦除错误", paint_source)


if __name__ == "__main__":
    unittest.main()
