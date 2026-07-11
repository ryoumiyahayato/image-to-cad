from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import ezdxf
import numpy as np

from app import __version__
from app.dxf_validator import validate_dxf
from app.line_detect import LineSegment, _refine_to_centerline
import main
from scripts.validate_dxf import validate_with_freecad
from scripts.versioning import parse_version, write_windows_version_info


class AuditRegressionTests(unittest.TestCase):
    def test_thick_stroke_edge_is_refined_to_its_centerline(self) -> None:
        binary = np.full((240, 420), 255, np.uint8)
        cv2.line(binary, (40, 120), (380, 120), 0, 12)
        foreground = 255 - binary
        distance_map = cv2.distanceTransform(foreground, cv2.DIST_L2, 3)

        edge_candidate = LineSegment(
            40,
            114,
            380,
            114,
            source_ids=("EDGE",),
            history=("test-input",),
        )
        refined = _refine_to_centerline(distance_map, edge_candidate)

        self.assertAlmostEqual(refined.y1, 120.0, delta=1.0)
        self.assertAlmostEqual(refined.y2, 120.0, delta=1.0)
        self.assertIn("refine_centerline", refined.history)

    def test_windows_version_metadata_uses_application_version(self) -> None:
        self.assertEqual(parse_version(__version__), (1, 1, 0, 0))
        with tempfile.TemporaryDirectory() as directory:
            output = write_windows_version_info(
                Path(directory) / "version_info.txt",
                __version__,
            )
            content = output.read_text(encoding="utf-8")
        self.assertIn(f"FileVersion', u'{__version__}'", content)
        self.assertIn(f"ProductVersion', u'{__version__}'", content)

    def test_dxf_validator_detects_duplicates_and_zero_length_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid_geometry.dxf"
            document = ezdxf.new("R2010")
            modelspace = document.modelspace()
            modelspace.add_line((0, 0), (100, 0))
            modelspace.add_line((100, 0), (0, 0))
            modelspace.add_line((25, 25), (25, 25))
            document.saveas(path)

            result = validate_dxf(path)

        self.assertFalse(result.passed)
        self.assertEqual(result.duplicate_line_count, 1)
        self.assertEqual(result.zero_length_count, 1)
        self.assertEqual(result.invalid_coordinate_count, 0)

    def test_dxf_audit_fixes_are_not_accepted_as_clean_validation(self) -> None:
        fake_modelspace = SimpleNamespace(query=lambda _kind: [])
        fake_document = SimpleNamespace(
            audit=lambda: SimpleNamespace(errors=[], fixes=["automatic repair"]),
            modelspace=lambda: fake_modelspace,
        )
        with patch("app.dxf_validator.ezdxf.readfile", return_value=fake_document):
            result = validate_dxf("repaired-by-auditor.dxf")

        self.assertFalse(result.passed)
        self.assertEqual(result.audit_error_count, 0)
        self.assertEqual(result.audit_fix_count, 1)

    def test_branching_cycle_network_is_not_reported_as_one_closed_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "branching_cycles.dxf"
            document = ezdxf.new("R2010")
            modelspace = document.modelspace()
            center = (0, 0)
            left_top = (-10, 10)
            left_bottom = (-10, -10)
            right_top = (10, 10)
            right_bottom = (10, -10)
            for start, end in (
                (center, left_top),
                (left_top, left_bottom),
                (left_bottom, center),
                (center, right_top),
                (right_top, right_bottom),
                (right_bottom, center),
            ):
                modelspace.add_line(start, end)
            document.saveas(path)

            result = validate_dxf(path)

        self.assertTrue(result.passed)
        self.assertEqual(result.connected_component_count, 1)
        self.assertEqual(result.open_component_count, 1)
        self.assertEqual(result.closed_component_count, 0)

    def test_gui_entrypoint_uses_the_audited_main_window(self) -> None:
        calls: dict[str, object] = {}

        class FakeApplication:
            def __init__(self, argv: list[str]) -> None:
                calls["argv"] = argv

            def setApplicationName(self, name: str) -> None:
                calls["application_name"] = name

            def exec(self) -> int:
                calls["executed"] = True
                return 0

        class FakeWindow:
            def __init__(self) -> None:
                calls["window_created"] = True

            def show(self) -> None:
                calls["window_shown"] = True

        pyside_module = ModuleType("PySide6")
        widgets_module = ModuleType("PySide6.QtWidgets")
        widgets_module.QApplication = FakeApplication
        pyside_module.QtWidgets = widgets_module
        main_window_module = ModuleType("app.main_window")
        main_window_module.MainWindow = FakeWindow

        with patch.dict(
            sys.modules,
            {
                "PySide6": pyside_module,
                "PySide6.QtWidgets": widgets_module,
                "app.main_window": main_window_module,
            },
        ):
            result = main.run_gui()

        self.assertEqual(result, 0)
        self.assertTrue(calls.get("window_created"))
        self.assertTrue(calls.get("window_shown"))
        self.assertTrue(calls.get("executed"))

    def test_freecad_nonzero_exit_cannot_be_overridden_by_success_json(self) -> None:
        completed = SimpleNamespace(
            returncode=1,
            stdout=(
                "FreeCAD startup noise\n"
                'DXF_VALIDATION_JSON={"passed": true, "object_count": 3, '
                '"freecad_version": ["0", "21", "2"]}\n'
            ),
            stderr="import failed after reporting",
        )
        with patch("scripts.validate_dxf.subprocess.run", return_value=completed):
            result = validate_with_freecad(Path("drawing.dxf"), "FreeCADCmd")

        self.assertFalse(result["passed"])
        self.assertEqual(result["return_code"], 1)
        self.assertEqual(result["object_count"], 3)

    def test_freecad_zero_object_import_is_rejected(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout=(
                'DXF_VALIDATION_JSON={"passed": false, "object_count": 0, '
                '"freecad_version": ["0", "21", "2"]}\n'
            ),
            stderr="",
        )
        with patch("scripts.validate_dxf.subprocess.run", return_value=completed):
            result = validate_with_freecad(Path("empty.dxf"), "FreeCADCmd")

        self.assertFalse(result["passed"])
        self.assertEqual(result["object_count"], 0)

    def test_freecad_nonempty_import_with_embedded_json_is_accepted(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout=(
                "FreeCAD startup noise\n"
                "\t(16.0 %)DXF_VALIDATION_JSON="
                '{"passed": true, "object_count": 7, '
                '"freecad_version": ["0", "21", "2"]}'
                " trailing progress (17.0 %)\n"
            ),
            stderr="",
        )
        with patch("scripts.validate_dxf.subprocess.run", return_value=completed):
            result = validate_with_freecad(Path("drawing.dxf"), "FreeCADCmd")

        self.assertTrue(result["passed"])
        self.assertEqual(result["object_count"], 7)
        self.assertEqual(result["freecad_version"], ["0", "21", "2"])

    def test_topology_diagnostics_do_not_reject_open_drawing_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topology.dxf"
            document = ezdxf.new("R2010")
            modelspace = document.modelspace()
            modelspace.add_line((0, 0), (10, 0))
            modelspace.add_line((10.2, 0), (20, 0))
            modelspace.add_line((5, -5), (5, 5))
            document.saveas(path)

            result = validate_dxf(path, gap_tolerance=0.5)

        self.assertTrue(result.passed)
        self.assertEqual(result.near_gap_count, 1)
        self.assertEqual(result.unsplit_intersection_count, 1)
        self.assertEqual(result.open_component_count, 3)
        self.assertEqual(result.closed_component_count, 0)
        self.assertEqual(result.dangling_endpoint_count, 6)


if __name__ == "__main__":
    unittest.main()
