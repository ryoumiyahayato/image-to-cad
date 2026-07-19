from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

from PySide6.QtWidgets import QDialog

from .gui_trace_release import MainWindow as _TraceReleaseMainWindow
from .raster_trace import RasterTraceResult, trace_binary
from .trace_paint import TracePaintDialog
from .trace_storage import save_trace_cache


class MainWindow(_TraceReleaseMainWindow):
    """Final exact-CAD shell with cache reuse and neutral CAD terminology."""

    def __init__(self) -> None:
        self._dirty_trace_keys: set[tuple[str, int | None]] = set()
        super().__init__()

    def _build_controls(self):  # type: ignore[override]
        scroll = super()._build_controls()
        self.tabs.setTabText(self.tabs.indexOf(self.corrected_canvas), "校正图")
        self.tabs.setTabText(self.tabs.indexOf(self.preprocess_tabs), "处理与验证")
        self.tabs.setTabText(self.tabs.indexOf(self.detected_canvas), "CAD 轮廓预览")
        return scroll

    def _set_single_image_state(self, image, *, corrected: bool) -> None:
        super()._set_single_image_state(image, corrected=corrected)
        self._dirty_trace_keys.clear()

    def _apply_trace_result(
        self,
        result: RasterTraceResult,
        *,
        started_at: datetime,
        duration: float,
        save_pdf_state: bool,
    ) -> None:
        self._dirty_trace_keys.add(self._current_trace_key())
        super()._apply_trace_result(
            result,
            started_at=started_at,
            duration=duration,
            save_pdf_state=save_pdf_state,
        )

    def _restore_cached_trace_for_page(self, page_index: int) -> None:
        super()._restore_cached_trace_for_page(page_index)
        self._dirty_trace_keys.discard(self._current_trace_key())

    def _store_current_trace(self) -> Path | None:
        """Reuse an unchanged page cache instead of recompressing it at export."""

        if self.binary_image is None or not self._trace_paths:
            return None
        key = self._current_trace_key()
        state = (
            self._pdf_page_states.get(self._current_pdf_page_index, {})
            if self._native_pdf_mode
            else {}
        )
        existing = self._trace_cache_by_key.get(key)
        if existing is None and state.get("trace_cache_path"):
            existing = Path(str(state["trace_cache_path"]))
        if (
            key not in self._dirty_trace_keys
            and existing is not None
            and existing.exists()
        ):
            self._trace_cache_by_key[key] = existing
            return existing

        target = existing or self._cache_path_for_key(key)
        result = RasterTraceResult(
            binary=self.binary_image,
            stages=dict(self.preprocess_stages),
            paths=tuple(self._trace_paths),
            threshold=int(self._trace_threshold or 128),
            foreground_pixels=int(self._trace_foreground_pixels),
            vertex_count=int(self._trace_vertex_count),
            warnings=tuple(self._last_warnings),
        )
        save_trace_cache(target, result)
        self._trace_cache_by_key[key] = target
        self._dirty_trace_keys.discard(key)
        return target

    def review_layers(self) -> None:
        if self.binary_image is None:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "尚无 CAD 轮廓", "请先生成当前页 CAD 轮廓。")
            return
        dialog = TracePaintDialog(self.binary_image, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.edited_binary()
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        revision = self._state_revision

        def operation(token, progress) -> object:
            paths = trace_binary(
                edited,
                cancellation_token=token,
                progress_callback=progress,
            )
            return RasterTraceResult(
                binary=edited,
                stages={
                    "CAD 轮廓来源（修改后）": edited.copy(),
                },
                paths=paths,
                threshold=self._trace_threshold or 128,
                foreground_pixels=int((edited == 0).sum()),
                vertex_count=sum(len(path.points) for path in paths),
                warnings=(),
            )

        def completed(value: object) -> None:
            if revision != self._state_revision:
                return
            self._apply_trace_result(
                value,  # type: ignore[arg-type]
                started_at=started_at,
                duration=time.perf_counter() - started,
                save_pdf_state=self._native_pdf_mode,
            )
            self.statusBar().showMessage("已按修改内容重新生成当前页 CAD 轮廓")

        self._start_processing(
            operation,
            completed,
            "正在按修改内容重新生成 CAD 轮廓…",
        )
