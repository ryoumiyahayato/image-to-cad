"""Focused desktop contracts; these are UI checks, not CAD accuracy evidence.

Run ``python -m app.gui.native_task_contract_checks`` for coordinate/data
contracts. Add ``--qt`` for a small offscreen control-state smoke check. The
Qt check uses an explicit fake manager and never invokes OCR or conversion.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from app.gui.native_task_viewmodel import (
    source_roi_to_preview,
    preview_rect_to_source,
    issue_local_box,
    load_quality,
    request_from_controls,
    issue_label,
    issue_user_details,
    saved_review_notice,
)


class DataContracts(unittest.TestCase):
    def test_half_open_corner_rotation(self):
        # An asymmetric source and ROI catch axis swaps, W-1 mistakes, and
        # clockwise/counterclockwise ambiguity independently of rendering.
        roi, size = [10, 20, 70, 60], [100, 80]
        expected = {
            0: [10, 20, 70, 60],
            90: [20, 10, 60, 70],
            180: [30, 20, 90, 60],
            270: [20, 30, 60, 90],
        }
        for angle, box in expected.items():
            preview = [80, 100] if angle in (90, 270) else size
            with self.subTest(angle=angle):
                self.assertEqual(source_roi_to_preview(roi, size, preview, angle), box)
                self.assertEqual(preview_rect_to_source(box, size, preview, angle), roi)

    def test_thumbnail_round_trip_preserves_integer_edges(self):
        # The full raster is not passed to recognition through this preview.
        for size in ([3881, 5299], [2339, 1654], [10800, 7600]):
            roi = [101, 257, size[0] - 77, size[1] - 29]
            for angle in (0, 90, 180, 270):
                working = size[::-1] if angle in (90, 270) else size
                factor = 1600 / max(working)
                preview = [round(value * factor) for value in working]
                with self.subTest(size=size, angle=angle):
                    rect = source_roi_to_preview(roi, size, preview, angle)
                    self.assertEqual(
                        preview_rect_to_source(rect, size, preview, angle), roi
                    )

    def test_fractional_drag_encloses_source_pixel_cells(self):
        self.assertEqual(
            preview_rect_to_source([1.1, 2.2, 8.1, 9.1], [100, 100], [10, 10], 0),
            [11, 22, 81, 91],
        )

    def test_issue_origin_and_explicit_unknown(self):
        self.assertEqual(
            issue_local_box(
                {"bbox_xyxy_px": [110, 220, 130, 240]}, [100, 200, 500, 600]
            ),
            [10, 20, 30, 40],
        )
        self.assertIsNone(issue_local_box({"bbox_xyxy_px": None}, [100, 200, 500, 600]))

    def test_issue_list_is_not_filtered_and_malformed_ids_are_rejected(self):
        data = {
            "coordinate_system": "job_working_pixels_top_left",
            "roi_xyxy_px": [100, 200, 500, 600],
            "issues": [
                {"id": "located", "bbox_xyxy_px": [110, 220, 130, 240]},
                {"id": "unknown", "bbox_xyxy_px": None},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "quality_review.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(len(load_quality(path)["issues"]), 2)
            data["issues"][1]["id"] = "located"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_quality(path)

    def test_request_cannot_claim_undeployed_language_or_empty_selection(self):
        with self.assertRaises(ValueError):
            request_from_controls(
                "source.png", [0, 0, 100, 100], 200, None, 1, 0, "chi_sim"
            )
        with self.assertRaises(ValueError):
            request_from_controls("source.png", [2, 0, 2, 100], 200, None, 1, 0)
        request = request_from_controls(
            "source.png", [2, 3, 100, 101], 200, None, 1, 90
        )
        self.assertEqual(request["roi"], [2, 3, 100, 101])
        self.assertIsNone(request["page_number"])
        self.assertEqual(request["orientation"], 90)

    def test_issue_user_text_keeps_location_without_exposing_raw_codes(self):
        issue = {
            "id": "ISSUE-internal-id",
            "status": "PENDING_SOURCE_REPAIR",
            "reason": "UNEXPLAINED_OR_PARTLY_RECONSTRUCTED_SOURCE_GROUP",
            "bbox_xyxy_px": [110, 220, 130, 240],
            "source_group_ids": ["SRC-identity"],
            "source_support": {
                "source_pixel_count": 35,
                "neither_rendered_nor_near_verified_geometry": 12,
            },
        }
        label = issue_label(issue)
        details = issue_user_details(issue)
        self.assertIn("尚未完整重建", label)
        self.assertIn("(110, 220)", label)
        self.assertNotIn(issue["id"], label)
        self.assertNotIn(issue["reason"], details)
        self.assertIn("35 个像素", details)
        self.assertIn("12 个像素", details)
        self.assertEqual(issue["source_support"]["source_pixel_count"], 35)

    def test_stale_review_is_not_presented_as_current(self):
        stale = {"valid": False, "mismatches": [{"field": "review_code_sha256"}]}
        self.assertIn("旧版本", saved_review_notice(stale))
        self.assertIn("不可导出", saved_review_notice(stale))
        current = {"valid": True, "mismatches": []}
        self.assertIn("当前输入及版本匹配", saved_review_notice(current))
        self.assertIn("待修项仍需核对", saved_review_notice(current))


def qt_controls_smoke():
    """Check only frontend state contracts with no subprocess work."""
    from PySide6.QtWidgets import QApplication
    from app.gui.native_task_panel import NativeTaskPanel

    class Manager:
        def __init__(self):
            self.cancelled = []

        def list_jobs(self):
            return []

        def cancel(self, job_id, reason="user"):
            self.cancelled.append((job_id, reason))
            return {
                "job_id": job_id,
                "status": "CANCEL_REQUESTED",
                "stage": "CANCEL_REQUESTED",
                "progress": 0.42,
                "attempt": 1,
            }

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        manager = Manager()
        panel = NativeTaskPanel(jobs_root=temporary, manager=manager)
        panel.poll_timer.stop()
        panel.job_id = "control-contract"
        signals = []
        panel.running_changed.connect(signals.append)
        panel._update_state(
            {
                "job_id": panel.job_id,
                "status": "RUNNING",
                "stage": "OCR_LOCAL",
                "progress": 0.42,
                "attempt": 1,
            }
        )
        assert panel.cancel_button.isEnabled()
        assert not panel.start_button.isEnabled()
        assert panel.progress.value() == 420
        panel.cancel()
        assert manager.cancelled == [("control-contract", "user")]
        assert not panel.cancel_button.isEnabled()
        assert not panel.request_close()
        panel._update_state(
            {
                "job_id": panel.job_id,
                "status": "CANCELLED",
                "stage": "CANCELLED",
                "progress": 0.42,
                "attempt": 1,
            }
        )
        assert panel.resume_button.isEnabled()
        assert signals == [True, False]
        assert panel.request_close()
        # Changing ROI detaches the prior published result. It may still be
        # opened through history but may not be exported as the new settings.
        panel._closing = False
        panel.state = {"job_id": "prior", "status": "COMPLETED_WITH_ISSUES"}
        panel.job_id = "prior"
        panel._result_domain = True
        panel.roi_spins[2].setValue(100)
        assert panel.state is None and panel.job_id is None
        assert not panel.export_button.isEnabled()
        assert not panel.cad_button.isEnabled()
        panel.close()
        app.processEvents()
    return {
        "scope": "offscreen controls with fake manager; no CAD conversion",
        "status": "PASS",
    }


def qt_recovery_regressions():
    """Only the queued-start / stopped-timer recovery regressions, no OCR."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QListWidgetItem
    from app.gui.native_task_panel import NativeTaskPanel
    from app.native_objects.source_import import file_sha

    class Manager:
        def __init__(self):
            self.calls = []

        def list_jobs(self):
            return []

        def create(self, request):
            self.calls.append(("create", request["roi"]))
            return {"job_id": "new-job", "status": "QUEUED", "attempt": 0}

        def start(self, job_id):
            self.calls.append(("start", job_id))
            return {
                "job_id": job_id,
                "status": "STARTING",
                "stage": "STARTING_WORKER",
                "progress": 0,
                "attempt": 1,
            }

        def resume(self, job_id):
            self.calls.append(("resume", job_id))
            return {
                "job_id": job_id,
                "status": "STARTING",
                "stage": "STARTING_WORKER",
                "progress": 0,
                "attempt": 2,
            }

        def poll(self, job_id):
            return {
                "job_id": job_id,
                "status": "CANCELLED",
                "stage": "CANCELLED",
                "progress": 0.4,
                "attempt": 1,
                "original_input_path": "history.png",
                "parameters": {"roi": [1, 2, 30, 40], "dpi": 200, "frame_number": 1},
            }

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        manager = Manager()
        panel = NativeTaskPanel(jobs_root=temporary, manager=manager)
        errors = []
        panel._error = lambda title, error: errors.append((title, str(error)))
        panel.poll_timer.stop()
        panel.job_id = "queued-job"
        panel.state = {"job_id": panel.job_id, "status": "QUEUED", "attempt": 0}
        panel.resume()
        assert manager.calls == [("start", "queued-job")]
        assert panel.poll_timer.isActive()

        panel.poll_timer.stop()
        panel.state = {"job_id": panel.job_id, "status": "CANCELLED", "attempt": 1}
        panel.resume()
        assert manager.calls[-1] == ("resume", "queued-job")
        assert panel.poll_timer.isActive()

        panel.poll_timer.stop()
        panel.state = {"job_id": panel.job_id, "status": "RESOURCE_STOP", "attempt": 1}
        panel._enable_controls()
        assert not panel.resume_button.isEnabled()
        previous = list(manager.calls)
        panel.resume()
        assert manager.calls == previous and errors
        assert not panel.poll_timer.isActive()

        item = QListWidgetItem("historical task")
        item.setData(Qt.ItemDataRole.UserRole, "historical")
        panel.open_history(item)
        assert panel.job_id == "historical" and panel.poll_timer.isActive()

        # A small fixture supplies only bytes for the preview SHA contract;
        # no image decoder, model, reconstruction or CAD writer is invoked.
        source = Path(temporary) / "input-bytes-for-GUI-contract.png"
        source.write_bytes(b"isolated frontend source identity fixture")
        panel.poll_timer.stop()
        panel.input_path = str(source)
        panel.preview_info = {
            "selection": panel._selection(),
            "source_sha256": file_sha(source),
        }
        panel.start()
        assert manager.calls[-2:] == [("create", [1, 2, 30, 40]), ("start", "new-job")]
        assert panel.poll_timer.isActive()
        assert panel.state["status"] == "STARTING"
        panel.poll_timer.stop()
        panel.state = {"job_id": "new-job", "status": "CANCELLED", "attempt": 1}
        panel.close()
        app.processEvents()
    return {
        "scope": "offscreen frontend recovery regression; fake manager, no CAD conversion",
        "checks": [
            "QUEUED attempt 0 starts",
            "cancelled resumes",
            "resource stop cannot restart",
            "history re-enables polling",
            "new start re-enables polling",
        ],
        "status": "PASS",
    }


if __name__ == "__main__":
    if "--qt-recovery-only" in sys.argv:
        print(json.dumps(qt_recovery_regressions(), ensure_ascii=False))
        raise SystemExit(0)
    qt_requested = "--qt" in sys.argv
    args = [arg for arg in sys.argv if arg != "--qt"]
    result = unittest.main(argv=args, exit=False)
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    if qt_requested:
        print(json.dumps(qt_controls_smoke(), ensure_ascii=False))
