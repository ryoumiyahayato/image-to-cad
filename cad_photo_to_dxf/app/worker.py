from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .cancellation import CancellationToken, ProcessingCancelled


class ProcessingWorker(QObject):
    """Run one cancellable processing operation on a Qt worker thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, float)

    def __init__(
        self,
        operation: Callable[
            [CancellationToken, Callable[[str, float], None]],
            object,
        ],
        token: CancellationToken,
    ) -> None:
        super().__init__()
        self._operation = operation
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(self._token, self._emit_progress)
            self._token.checkpoint()
        except ProcessingCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)

    def _emit_progress(self, stage: str, fraction: float) -> None:
        self.progress.emit(stage, max(0.0, min(1.0, float(fraction))))
