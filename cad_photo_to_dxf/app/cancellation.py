from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Callable


class ProcessingCancelled(RuntimeError):
    """Raised when a cooperative processing task has been cancelled."""


ProgressCallback = Callable[[str, float], None]


@dataclass
class CancellationToken:
    """Thread-safe cooperative cancellation checked between expensive operations.

    OpenCV and OCR calls implemented in native code cannot be interrupted while the
    individual call is running. Callers should checkpoint immediately before and
    after each such call, and periodically inside Python loops.
    """

    _event: Event = field(default_factory=Event, init=False, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def checkpoint(self) -> None:
        if self.cancelled:
            raise ProcessingCancelled("Processing was cancelled")


def checkpoint(token: CancellationToken | None) -> None:
    if token is not None:
        token.checkpoint()


def report_progress(
    callback: ProgressCallback | None,
    stage: str,
    fraction: float,
) -> None:
    if callback is not None:
        callback(stage, max(0.0, min(1.0, float(fraction))))
