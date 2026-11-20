"""Portable, explicitly scoped process statistics; unavailable is never zero."""

from __future__ import annotations

import sys
import time

try:
    import resource as _resource
except ImportError:
    _resource = None


def sample() -> dict:
    row = {
        "wall_monotonic_seconds": time.perf_counter(),
        "self_process_cpu_seconds": time.process_time(),
        "children_cpu_seconds": None,
        "self_peak_RSS_bytes": None,
        "children_peak_RSS_bytes": None,
        "backend": "time.process_time",
        "peak_RSS_scope": "unavailable",
        "platform": sys.platform,
    }
    if _resource is not None:
        own = _resource.getrusage(_resource.RUSAGE_SELF)
        children = _resource.getrusage(_resource.RUSAGE_CHILDREN)
        multiplier = 1 if sys.platform == "darwin" else 1024
        row.update(
            self_process_cpu_seconds=own.ru_utime + own.ru_stime,
            children_cpu_seconds=children.ru_utime + children.ru_stime,
            self_peak_RSS_bytes=int(own.ru_maxrss * multiplier),
            children_peak_RSS_bytes=int(children.ru_maxrss * multiplier),
            backend="stdlib.resource.getrusage",
            peak_RSS_scope="per-process lifetime high-water marks; not simultaneous tree RSS",
        )
    return row


def elapsed(before: dict, after: dict | None = None) -> dict:
    after = sample() if after is None else after
    children = (
        after["children_cpu_seconds"] - before["children_cpu_seconds"]
        if after["children_cpu_seconds"] is not None
        and before["children_cpu_seconds"] is not None
        else None
    )
    return {
        "wall_seconds": after["wall_monotonic_seconds"]
        - before["wall_monotonic_seconds"],
        "process_cpu_seconds": after["self_process_cpu_seconds"]
        - before["self_process_cpu_seconds"],
        "completed_children_cpu_seconds": children,
        "self_peak_RSS_bytes": after["self_peak_RSS_bytes"],
        "children_peak_RSS_bytes": after["children_peak_RSS_bytes"],
        "backend": after["backend"],
        "platform": after["platform"],
        "peak_RSS_scope": after["peak_RSS_scope"],
        "unknown_values_encoded_as": None,
        "resource_limits_enforced_by_this_adapter": False,
    }
