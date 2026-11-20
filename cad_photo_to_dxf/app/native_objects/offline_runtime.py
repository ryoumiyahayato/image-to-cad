"""Apply ONNX Runtime's own telemetry opt-out before its native initialization.

This module uses only the standard library. It does not change network or
approval controls. The environment setting prevents ORT's non-Windows 1DS
uploader, events and persistent identifier; the official API additionally
disables non-essential events before each project-owned session is created.
Neither setting is a measurement of all system network activity.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading


_LOCK = threading.RLock()
_PREPARED_PID = None
_API_DISABLE_CALLS = 0
TELEMETRY_ENVIRONMENT_VARIABLE = "ORT_DISABLE_TELEMETRY"


def _runtime_loaded():
    return any(
        name == "onnxruntime" or name.startswith("onnxruntime.") for name in sys.modules
    )


def prepare_onnx_privacy():
    """Fail closed for unknown preloaded ORT; otherwise opt out before import."""
    global _PREPARED_PID
    with _LOCK:
        loaded = _runtime_loaded()
        if loaded and _PREPARED_PID != os.getpid():
            raise RuntimeError(
                "ONNX_RUNTIME_PRELOADED_WITHOUT_PRIVACY_BOOTSTRAP: start a fresh "
                "process through the application entry before loading ONNX Runtime"
            )
        if loaded and os.environ.get(TELEMETRY_ENVIRONMENT_VARIABLE) != "1":
            raise RuntimeError(
                "ONNX_RUNTIME_PRIVACY_ENV_CHANGED_AFTER_INITIALIZATION: "
                "this process cannot establish a clean initialization history"
            )
        os.environ[TELEMETRY_ENVIRONMENT_VARIABLE] = "1"
        _PREPARED_PID = os.getpid()


def private_onnxruntime():
    """Import under the pre-initialization opt-out, then apply the official API."""
    global _API_DISABLE_CALLS
    with _LOCK:
        prepare_onnx_privacy()
        runtime = importlib.import_module("onnxruntime")
        disable = getattr(runtime, "disable_telemetry_events", None)
        if not callable(disable):
            raise RuntimeError("ONNX_RUNTIME_TELEMETRY_DISABLE_API_UNAVAILABLE")
        disable()
        _API_DISABLE_CALLS += 1
        return runtime


def runtime_privacy_status():
    """Configuration evidence only; an external network trace is separate."""
    return {
        "schema": "onnx-runtime-privacy-configuration-v1",
        "environment_variable": TELEMETRY_ENVIRONMENT_VARIABLE,
        "environment_value": os.environ.get(TELEMETRY_ENVIRONMENT_VARIABLE),
        "prepared_before_managed_ORT_import": _PREPARED_PID == os.getpid(),
        "onnxruntime_loaded": _runtime_loaded(),
        "official_disable_telemetry_events_calls": _API_DISABLE_CALLS,
        "unknown_preloaded_runtime_rejected": True,
        "system_network_activity_measured": False,
        "system_zero_network_claimed": False,
        "remote_service_call_counter_is_not_dependency_network_measurement": True,
    }


# Merely importing this guard prepares the process, before a later application
# import can load a third-party OCR wrapper. No ORT import or session occurs.
prepare_onnx_privacy()
