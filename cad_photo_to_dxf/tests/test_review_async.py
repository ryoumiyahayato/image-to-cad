"""P19-B focused races. Simulated confirmations remain QA_TEST_ONLY."""

from threading import Event
from time import monotonic, sleep

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from tests import test_manual_text_recovery as recovery_tests
from tests.test_manual_text_recovery import confirm
from app.core.review_project import ReviewProject, ReviewProjectError
from app.gui import review_async
from app.gui.review_project_actions import save_review_project_to, detach_review_project

project = recovery_tests.project


def wait_until(condition, timeout=10):
    end = monotonic() + timeout
    while not condition() and monotonic() < end:
        QApplication.processEvents()
        sleep(0.005)
    assert condition(), "review worker did not reach expected state"


def drain():
    scheduler = review_async.preview_scheduler()
    wait_until(lambda: scheduler.running is None and scheduler.pending is None)


def test_latest_only_queue_drops_cancelled_result_and_duplicate(project, monkeypatch):
    drain()
    entered, release = Event(), Event()
    calls, applied = [], []

    def render(structure, *, text_review, cancellation_token=None):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return np.full((10, 10), len(calls), np.uint8)

    monkeypatch.setattr(review_async, "render_final_structure_preview", render)
    owner = QWidget()
    client = review_async.PreviewClient(owner)
    errors = []
    client.request(
        project,
        lambda image: applied.append(("old", int(image[0, 0]))),
        errors.append,
        key="A",
    )
    wait_until(entered.is_set)
    client.request(
        project,
        lambda image: applied.append(("middle", int(image[0, 0]))),
        errors.append,
        key="B",
    )
    request = client.request(
        project,
        lambda image: applied.append(("latest", int(image[0, 0]))),
        errors.append,
        key="C",
    )
    assert (
        client.request(
            project, lambda _: pytest.fail("duplicate applied"), errors.append, key="C"
        )
        == request
    )
    scheduler = review_async.preview_scheduler()
    assert scheduler.running is not None and scheduler.pending is not None
    release.set()
    drain()
    assert (
        calls == [1, 2] and applied == [("latest", 2)] and not errors and client.ready
    )
    owner.close()


def test_save_snapshot_preserves_new_dirty_and_cache_lifetime(
    project, tmp_path, monkeypatch
):
    from app.gui import MainWindow

    entered, release = Event(), Event()
    real_save = ReviewProject.save

    def delayed_save(snapshot, path):
        entered.set()
        assert release.wait(5)
        real_save(snapshot, path)

    monkeypatch.setattr(ReviewProject, "save", delayed_save)
    window = MainWindow()
    window._review_project = project
    target = tmp_path / "QA_TEST_ONLY-save.icreview"
    save_review_project_to(window, target, asynchronous=True)
    wait_until(entered.is_set)
    confirm(project)
    with pytest.raises(ReviewProjectError, match="正在保存"):
        save_review_project_to(window, target, asynchronous=True)
    detach_review_project(window)
    assert project._cache_path.is_file()
    release.set()
    wait_until(lambda: window._review_save_job is None)
    assert project.dirty
    assert not project._cache_path.exists()
    reopened = ReviewProject.open(target)
    try:
        assert reopened.records == []
    finally:
        reopened.close()
        window.close()


def test_replaced_other_client_can_retry_same_key(project, monkeypatch):
    drain()
    entered, release = Event(), Event()
    calls, applied, errors = [], [], []

    def render(structure, *, text_review, cancellation_token=None):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return np.zeros((10, 10), np.uint8)

    monkeypatch.setattr(review_async, "render_final_structure_preview", render)
    owners = [QWidget() for _ in range(3)]
    a, b, c = [review_async.PreviewClient(owner) for owner in owners]
    a.request(project, lambda _: applied.append("A"), errors.append, key="A")
    wait_until(entered.is_set)
    old = b.request(project, lambda _: applied.append("old B"), errors.append, key="B")
    c.request(project, lambda _: applied.append("C"), errors.append, key="C")
    assert b.key is None and not b.ready
    retry = b.request(
        project, lambda _: applied.append("retry B"), errors.append, key="B"
    )
    assert retry != old
    release.set()
    drain()
    assert calls == [1, 2] and applied == ["A", "retry B"] and b.ready and not errors
    for owner in owners:
        owner.close()


def test_save_failure_keeps_dirty_and_previous_save(project, tmp_path, monkeypatch):
    from app.gui import MainWindow

    target = tmp_path / "QA_TEST_ONLY-previous.icreview"
    project.save(target)
    before = target.read_bytes()
    confirm(project)
    window = MainWindow()
    window._review_project = project
    messages = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args: messages.append(args[-1])
    )

    def fail(*args):
        raise OSError("QA_TEST_ONLY write failure")

    monkeypatch.setattr(ReviewProject, "save", fail)
    save_review_project_to(window, target, asynchronous=True)
    wait_until(lambda: window._review_save_job is None)
    assert messages == ["QA_TEST_ONLY write failure"]
    assert project.dirty and target.read_bytes() == before
    detach_review_project(window)
    window.close()


def test_roi_preempts_inflight_full_page_and_keeps_latest_view(project, monkeypatch):
    drain()
    entered = Event()
    calls = []
    applied = []

    def full(structure, *, text_review, cancellation_token):
        entered.set()
        while not cancellation_token.cancelled:
            sleep(0.005)
        cancellation_token.checkpoint()

    def region(self, structure, **options):
        calls.append(options["roi"])
        return np.zeros((10, 10), np.uint8)

    monkeypatch.setattr(review_async, "render_final_structure_preview", full)
    monkeypatch.setattr(review_async.PreparedDxfPreview, "render", region)
    owner = QWidget()
    main = review_async.PreviewClient(owner)
    detail = review_async.PreviewClient(QWidget(), owner)
    main.request(project, lambda _: applied.append("stale-full"), pytest.fail)
    wait_until(entered.is_set)
    detail.request(
        project, lambda _: applied.append("old-roi"), pytest.fail, roi=(10, 10, 20, 20)
    )
    detail.request(
        project,
        lambda _: applied.append("current-roi"),
        pytest.fail,
        roi=(20, 20, 20, 20),
    )
    drain()
    assert applied == ["current-roi"]
    assert calls == [(20, 20, 20, 20)]
    assert main.key is None and detail.ready
    main.close()
    detail.close()
    owner.close()
    detail.owner.close()


def test_emitted_roi_matches_full_crop_and_explicit_millimetres(project, tmp_path):
    import ezdxf
    from app.core.preview import (
        render_final_structure_preview,
        render_emitted_dxf_preview,
    )
    from app.export.trace_single_export import export_final_structure_dxf
    from app.core.scale_calibrator import ScaleCalibration

    roi = (20, 30, 170, 160)
    full = render_final_structure_preview(
        project.baseline, text_review=project.validated_review()
    )
    cropped = render_final_structure_preview(
        project.baseline, text_review=project.validated_review(), roi=roi
    )
    assert np.array_equal(cropped, full[30:190, 20:190])
    path = tmp_path / "physical.dxf"
    # Explicit physical unit conversion must preserve source placement.
    calibration = ScaleCalibration((0.0, 0.0), (1000.0, 0.0), 100.0)
    result = export_final_structure_dxf(
        project.baseline, path, calibration, text_review=project.validated_review()
    )
    physical = render_emitted_dxf_preview(
        ezdxf.readfile(path),
        path.parent,
        project.baseline.source_size_px,
        roi=roi,
        units_per_source_pixel=result.mm_per_pixel,
    )
    assert physical.shape == cropped.shape
    assert np.mean(np.abs(physical.astype(float) - cropped)) < 2
