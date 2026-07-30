from __future__ import annotations

from collections.abc import Callable
from time import perf_counter


PerformanceCallback = Callable[[str, float], None]


def performance_clock() -> float:
    """Return a monotonic high-resolution timestamp for stage measurements."""

    return perf_counter()


def emit_performance(
    callback: PerformanceCallback | None,
    stage: str,
    seconds: float,
) -> None:
    """Publish one non-negative stage duration without affecting processing."""

    if callback is not None:
        callback(stage, max(0.0, float(seconds)))


def record_performance(
    callback: PerformanceCallback | None,
    stage: str,
    started_at: float,
) -> None:
    emit_performance(
        callback,
        stage,
        performance_clock() - started_at,
    )
