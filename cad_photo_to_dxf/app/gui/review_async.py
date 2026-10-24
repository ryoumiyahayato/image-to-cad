"""Bounded review preview work; only result application touches widgets."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication

from app.core.cancellation import CancellationToken
from app.core.preview import render_final_structure_preview, PreparedDxfPreview
from app.gui.worker import ProcessingWorker

LAYER_POLICY = "honor exported off/frozen"


def timing(event, **values):
    """Optional, bounded local measurements. No source contents or fingerprints."""
    path = os.environ.get("IMAGE_TO_CAD_REVIEW_TIMING_LOG")
    if not path:
        return
    try:
        target = Path(path)
        if target.exists() and target.stat().st_size >= 512_000:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(dict(event=event, at=perf_counter(), **values)) + "\n"
            )
    except OSError:
        pass


def detached_review(project):
    # Baseline arrays/frame are immutable. Journals and lazy guards are private.
    # Rendering never reads _cache_path; saves retain the owning project lease.
    draft = project.draft()
    draft._guard = None
    draft._manifest = deepcopy(project._manifest)
    draft._bindings = deepcopy(project._bindings)
    draft._suggestions = deepcopy(project._suggestions)
    return draft


class ReviewJob(QObject):
    """One Qt worker, retained until QThread.finished (never GUI-thread wait)."""

    def __init__(self, operation, completed, failed, finished=None):
        super().__init__(QApplication.instance())
        self.thread = QThread(self)
        self.token = CancellationToken()
        self.worker = ProcessingWorker(operation, self.token)
        self.worker.moveToThread(self.thread)
        self.completed = completed
        self.failed = failed
        self.finished = finished
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self._success)
        self.worker.failed.connect(self._failure)
        for signal in (
            self.worker.succeeded,
            self.worker.failed,
            self.worker.cancelled,
        ):
            signal.connect(self.thread.quit)
            signal.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished)

    def start(self):
        self.thread.start()

    @Slot(object)
    def _success(self, result):
        self.completed(result)

    @Slot(str)
    def _failure(self, message):
        self.failed(message)

    @Slot()
    def _finished(self):
        if self.finished:
            self.finished()
        self.thread.deleteLater()
        self.deleteLater()


@dataclass
class PreviewRequest:
    client: object
    request_id: int
    revision: int
    project: object
    apply: object
    failed: object
    roi: object = None
    output_scale: float = 1.0
    export_key: object = None
    document_uuid: str = ""
    physical_page: int = 1
    zoom: float | None = None
    layer_policy: str = LAYER_POLICY


class PreviewScheduler(QObject):
    def __init__(self):
        super().__init__(QApplication.instance())
        self.running = None
        self.pending = None
        self.job = None
        self.prepared = PreparedDxfPreview()
        self.released_owners = set()
        self.sequence = 0
        self.last_beat = perf_counter()
        self.max_gap_ms = 0.0
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(20)
        self.heartbeat.timeout.connect(self._beat)
        if os.environ.get("IMAGE_TO_CAD_REVIEW_TIMING_LOG"):
            self.heartbeat.start()

    def _beat(self):
        now = perf_counter()
        gap = (now - self.last_beat) * 1000
        self.last_beat = now
        if gap > self.max_gap_ms:
            self.max_gap_ms = gap
            timing("heartbeat_max", milliseconds=gap)

    def submit(
        self, client, project, apply, failed, *, roi=None, output_scale=1.0, zoom=None
    ):
        self.sequence += 1
        source = project._manifest["source"]
        request = PreviewRequest(
            client,
            self.sequence,
            client.revision,
            detached_review(project),
            apply,
            failed,
            roi,
            output_scale,
            (
                id(client.owner),
                source["document_uuid"],
                source["physical_page"],
                project.snapshot_uuid,
                project.records,
                LAYER_POLICY,
            ),
            source["document_uuid"],
            source["physical_page"],
            zoom,
        )
        timing(
            "preview_request",
            request=request.request_id,
            revision=request.revision,
            snapshot=project.snapshot_uuid,
            journal_records=len(project._records),
            roi=roi,
            output_scale=output_scale,
            zoom=zoom,
            document_uuid=request.document_uuid,
            physical_page=request.physical_page,
            layer_policy=request.layer_policy,
        )
        if self.running is None:
            self._start(request)
        else:
            if roi is not None and self.running.roi is None:
                # A focused review supersedes an in-flight whole-page refresh.
                self.running.client.invalidate()
            if self.pending:
                timing("preview_discard_pending", request=self.pending.request_id)
                discarded = self.pending
                if discarded.revision == discarded.client.revision:
                    # A different client can replace this pending request.
                    # Its same-key retry must remain eligible for rendering.
                    discarded.client.key = None
                    discarded.client.ready = False
                    discarded.client.request_id = None
            self.pending = request
            timing("preview_queue", running=1, pending=1)
        return request.request_id

    def invalidate(self, client):
        if self.pending and self.pending.client is client:
            timing("preview_cancel_pending", request=self.pending.request_id)
            self.pending = None
        if self.running and self.running.client is client:
            timing("preview_cancel_running", request=self.running.request_id)
            self.job.token.cancel()

    def release_client(self, client):
        self.released_owners.add(id(client.owner))
        if self.running is None:
            self._release_prepared()

    def _release_prepared(self):
        if self.prepared.key and self.prepared.key[0] in self.released_owners:
            self.prepared.close()
        if self.running is None:
            self.released_owners.clear()

    def cancel_window(self, window):
        for request in (self.running, self.pending):
            if request and request.client.window is window:
                request.client.invalidate()
                self.release_client(request.client)

    def busy_for(self, window):
        return bool(self.running and self.running.client.window is window)

    def _start(self, request):
        self.running = request

        def operation(token, progress):
            token.checkpoint()
            start = perf_counter()
            if request.roi is None:
                image = render_final_structure_preview(
                    request.project.baseline,
                    text_review=request.project.validated_review(),
                    cancellation_token=token,
                )
            else:
                image = self.prepared.render(
                    request.project.baseline,
                    text_review=request.project.validated_review(),
                    key=request.export_key,
                    roi=request.roi,
                    output_scale=request.output_scale,
                    cancellation_token=token,
                )
            token.checkpoint()
            timing(
                "preview_computed",
                request=request.request_id,
                seconds=perf_counter() - start,
                bytes=image.nbytes,
            )
            if request.roi is not None:
                entities = {}
                doc = self.prepared.doc
                if doc is not None:
                    used_layers = {entity.dxf.layer for entity in doc.modelspace()}
                    visible = [
                        name
                        for name in sorted(used_layers)
                        if not (
                            doc.layers.get(name).is_off()
                            or doc.layers.get(name).is_frozen()
                        )
                    ]
                    timing(
                        "preview_layers",
                        request=request.request_id,
                        document_uuid=request.document_uuid,
                        physical_page=request.physical_page,
                        snapshot=request.project.snapshot_uuid,
                        revision=request.revision,
                        roi=request.roi,
                        zoom=request.zoom,
                        layer_policy=request.layer_policy,
                        visible=visible,
                        hidden=sorted(used_layers - set(visible)),
                    )
                    for entity in doc.modelspace().query("TEXT"):
                        if entity.has_xdata("MANUAL_TEXT_INSERTION"):
                            tags = entity.get_xdata("MANUAL_TEXT_INSERTION")
                            layer = doc.layers.get(entity.dxf.layer)
                            entities[str(tags[3].value)] = dict(
                                content=entity.dxf.text,
                                entity=entity.dxftype(),
                                layer=entity.dxf.layer,
                                source="manual",
                                source_transfer=tags[6].value,
                                visible=not (layer.is_off() or layer.is_frozen()),
                            )
                return dict(image=image, entities=entities)
            return image

        self.job = ReviewJob(operation, self._completed, self._failed, self._finished)
        timing("preview_start", request=request.request_id, revision=request.revision)
        self.job.start()

    def _current(self):
        request = self.running
        return request and request.revision == request.client.revision

    def _completed(self, image):
        request = self.running
        if not self._current():
            timing("preview_discard_result", request=request.request_id)
            return
        start = perf_counter()
        if isinstance(image, dict):
            request.client.entities = image["entities"]
            image = image["image"]
        request.apply(image)
        if self._current():
            request.client.ready = True
        timing(
            "preview_apply",
            request=request.request_id,
            revision=request.revision,
            seconds=perf_counter() - start,
        )

    def _failed(self, message):
        if self._current():
            self.running.client.key = None
            self.running.failed(message)

    def _finished(self):
        timing(
            "preview_finished",
            request=self.running.request_id,
            cancelled=self.job.token.cancelled,
        )
        self.running = None
        self.job = None
        self._release_prepared()
        pending, self.pending = self.pending, None
        if pending and pending.revision == pending.client.revision:
            self._start(pending)


def preview_scheduler():
    app = QApplication.instance()
    if not hasattr(app, "_review_preview_scheduler"):
        app._review_preview_scheduler = PreviewScheduler()
    return app._review_preview_scheduler


class PreviewClient:
    def __init__(self, owner, window=None):
        self.owner = owner
        self.window = window or owner
        self.revision = 0
        self.key = None
        self.ready = False
        self.request_id = None
        self.entities = {}

    def invalidate(self):
        self.revision += 1
        self.key = None
        self.ready = False
        preview_scheduler().invalidate(self)

    def close(self):
        self.invalidate()
        preview_scheduler().release_client(self)

    def request(
        self, project, apply, failed, *, key=None, roi=None, output_scale=1.0, zoom=None
    ):
        key = key if key is not None else (project.snapshot_uuid, project.records)
        source = project._manifest["source"]
        key = (
            source["document_uuid"],
            source["physical_page"],
            project.snapshot_uuid,
            LAYER_POLICY,
            key,
        )
        if roi is not None:
            key = (key, tuple(roi), float(output_scale), zoom)
        if (self.revision, key) == self.key:
            timing(
                "preview_duplicate_skipped",
                request=self.request_id,
                revision=self.revision,
            )
            return self.request_id
        self.invalidate()
        self.key = (self.revision, deepcopy(key))
        self.request_id = preview_scheduler().submit(
            self, project, apply, failed, roi=roi, output_scale=output_scale, zoom=zoom
        )
        return self.request_id


def release_project(window, project):
    job = getattr(window, "_review_save_job", None)
    if job is not None and job.project is project:
        job.release_project = True
    else:
        project.close()


def defer_close_for_review(window):
    scheduler = preview_scheduler()
    scheduler.cancel_window(window)
    if not (scheduler.busy_for(window) or getattr(window, "_review_save_job", None)):
        return False
    if not getattr(window, "_review_close_timer", None):
        timer = QTimer(window)
        window._review_close_timer = timer

        def finish():
            if not scheduler.busy_for(window) and not getattr(
                window, "_review_save_job", None
            ):
                timer.stop()
                window._review_close_timer = None
                timer.deleteLater()
                window.close()

        timer.timeout.connect(finish)
        timer.start(50)
    window.statusBar().showMessage("正在结束预览或保存；完成后关闭，窗口仍可操作。")
    return True
