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

    def test_active_entrypoint_preserves_guard_and_review_chain(self) -> None:
        main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        state_source = (APP_ROOT / "gui_state_guard.py").read_text(encoding="utf-8")
        review_source = (APP_ROOT / "gui_review.py").read_text(encoding="utf-8")
        guard_source = (APP_ROOT / "gui_guard.py").read_text(encoding="utf-8")
        compatibility_source = (APP_ROOT / "gui.py").read_text(encoding="utf-8")

        self.assertIn("from app.gui_state_guard import MainWindow", main_source)
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

    def test_normal_gui_uses_visual_review_without_circle_coordinate_dialog(self) -> None:
        review_source = (APP_ROOT / "gui_review.py").read_text(encoding="utf-8")
        state_source = (APP_ROOT / "gui_state_guard.py").read_text(encoding="utf-8")

        self.assertIn("LayerReviewDialog", review_source)
        self.assertIn("background=background", review_source)
        self.assertNotIn("CircleReviewDialog", review_source)
        self.assertNotIn("review_circles", review_source)
        self.assertIn("PDF 页面与合并", state_source)
        self.assertIn("document_pages_for_export", state_source)


if __name__ == "__main__":
    unittest.main()
