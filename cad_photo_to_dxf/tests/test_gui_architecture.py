from __future__ import annotations

import ast
import unittest
from pathlib import Path


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


def imported_names(source: str, module: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != module:
            continue
        names.update(alias.name for alias in node.names)
    return names


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

    def test_active_entrypoint_preserves_guard_chain_and_uses_public_release(
        self,
    ) -> None:
        main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        public_source = (APP_ROOT / "gui_public_release.py").read_text(encoding="utf-8")
        final_source = (APP_ROOT / "gui_final_release.py").read_text(encoding="utf-8")
        librecad_source = (APP_ROOT / "gui_librecad_release.py").read_text(
            encoding="utf-8"
        )
        exact_source = (APP_ROOT / "gui_exact_release.py").read_text(encoding="utf-8")
        release_source = (APP_ROOT / "gui_trace_release.py").read_text(encoding="utf-8")
        trace_source = (APP_ROOT / "gui_trace_mode.py").read_text(encoding="utf-8")
        consolidated_source = (APP_ROOT / "gui_consolidated.py").read_text(
            encoding="utf-8"
        )
        state_source = (APP_ROOT / "gui_state_guard.py").read_text(encoding="utf-8")
        review_source = (APP_ROOT / "gui_review.py").read_text(encoding="utf-8")
        guard_source = (APP_ROOT / "gui_guard.py").read_text(encoding="utf-8")
        compatibility_source = (APP_ROOT / "gui.py").read_text(encoding="utf-8")

        self.assertIn("from app.gui_public_release import MainWindow", main_source)
        self.assertIn("from app.gui_state_guard import MainWindow", main_source)
        self.assertIn("MainWindow", imported_names(public_source, "gui_final_release"))
        self.assertIn("from . import gui_librecad_release as _release", final_source)
        self.assertIn("class MainWindow(_release.MainWindow)", final_source)
        self.assertIn("MainWindow", imported_names(librecad_source, "gui_exact_release"))
        self.assertIn("MainWindow", imported_names(exact_source, "gui_trace_release"))
        self.assertIn("MainWindow", imported_names(release_source, "gui_trace_mode"))
        self.assertIn("MainWindow", imported_names(trace_source, "gui_consolidated"))
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

    def test_normal_gui_uses_portable_editable_character_workflow(self) -> None:
        final_source = (APP_ROOT / "gui_final_release.py").read_text(encoding="utf-8")
        librecad_source = (APP_ROOT / "gui_librecad_release.py").read_text(
            encoding="utf-8"
        )
        public_source = (APP_ROOT / "gui_public_release.py").read_text(encoding="utf-8")
        exact_source = (APP_ROOT / "gui_exact_release.py").read_text(encoding="utf-8")
        release_source = (APP_ROOT / "gui_trace_release.py").read_text(encoding="utf-8")
        engine_source = (APP_ROOT / "raster_trace.py").read_text(encoding="utf-8")
        paint_source = (APP_ROOT / "trace_paint.py").read_text(encoding="utf-8")
        export_source = (APP_ROOT / "trace_gui_export.py").read_text(encoding="utf-8")
        entity_source = (APP_ROOT / "trace_dxf_entities.py").read_text(
            encoding="utf-8"
        )
        outline_source = (APP_ROOT / "ocr_outline_export.py").read_text(
            encoding="utf-8"
        )
        layout_source = (APP_ROOT / "ocr_layout.py").read_text(encoding="utf-8")
        ocr_review_source = (APP_ROOT / "ocr_review.py").read_text(encoding="utf-8")
        font_review_source = (APP_ROOT / "font_ocr_review.py").read_text(
            encoding="utf-8"
        )
        font_source = (APP_ROOT / "font_library.py").read_text(encoding="utf-8")
        spec_source = (PROJECT_ROOT / "cad_photo_to_dxf.spec").read_text(
            encoding="utf-8"
        )

        self.assertIn("TRACE_PDF_DPI = 300", release_source)
        self.assertIn("PROCESS_PDF_DPI = 240", final_source)
        self.assertIn("SIDEBAR_WIDTH = 540", final_source)
        self.assertIn("_release.TRACE_PDF_DPI = PROCESS_PDF_DPI", final_source)
        self.assertIn("CAD 轮廓生成", exact_source)
        self.assertIn("生成当前页 CAD 轮廓", exact_source)
        self.assertIn("生成当前 PDF 全部页 CAD 轮廓", exact_source)
        self.assertIn("检查与验证", exact_source)
        self.assertIn("验证当前页", exact_source)
        self.assertIn("self.tabs.removeTab(preprocess_index)", exact_source)
        self.assertIn('group.title() == "视图"', exact_source)
        self.assertIn('group.title().startswith("纸张与坐标")', exact_source)
        self.assertNotIn("生成当前 PDF 全部页 CAD 轮廓（可取消）", exact_source)
        self.assertIn("CAD 轮廓预览", exact_source)
        self.assertIn("正在按修改内容重新生成 CAD 轮廓", exact_source)
        self.assertIn("导出 CAD（每页独立文件）", librecad_source)
        self.assertIn("trace_image_optimized", librecad_source)
        self.assertNotIn("内置字体匹配", librecad_source)
        self.assertIn("正在应用修改并重新生成 CAD", public_source)
        self.assertNotIn("正在按修改内容重新生成 CAD 轮廓", public_source)
        self.assertIn("one_dxf_per_pdf_page", export_source)
        self.assertIn("ocr_per_character_text_entities", export_source)
        self.assertIn('"ocr_line_as_single_vector_block": False', export_source)
        self.assertIn("one_text_entity_per_non_space_character", export_source)
        self.assertIn("add_ocr_outline_blocks", outline_source)
        self.assertIn("one native editable TEXT per character", outline_source)
        self.assertIn("character_boxes", layout_source)
        self.assertIn("replacement_safe", layout_source)
        self.assertIn("install_bundled_fonts_for_cad", outline_source)
        self.assertIn("检查、预览并确认 OCR 文字", ocr_review_source)
        self.assertIn("self.text_edit.textChanged.connect", ocr_review_source)
        self.assertIn("approved=bool(text.strip())", ocr_review_source)
        self.assertIn("最终 CAD 字体预览", font_review_source)
        self.assertIn("_cad_preview_text_items", font_review_source)
        self.assertIn("set_extended_font_data", font_source)
        self.assertIn("install_bundled_fonts_for_cad", font_source)
        self.assertIn("prepare_font_bundle", spec_source)
        self.assertIn("resources/fonts", spec_source)
        self.assertIn("cv2.RETR_TREE", engine_source)
        self.assertIn("cv2.CHAIN_APPROX_SIMPLE", engine_source)
        self.assertNotIn("detect_lines(", engine_source)
        self.assertNotIn("clean_geometry", engine_source)
        self.assertIn("黑色：补充缺失内容", paint_source)
        self.assertIn("白色：删除错误内容", paint_source)
        self.assertIn("后台导出", export_source)
        self.assertIn("TRACE_STRAIGHT", entity_source)
        self.assertIn("TRACE_CURVE", entity_source)
        self.assertIn("TRACE_TEXT_SYMBOL", entity_source)
        self.assertIn("OCR_TEXT", entity_source)
        self.assertNotIn('"TRACE_TEXT_OUTLINE"', entity_source)


if __name__ == "__main__":
    unittest.main()
