"""Configure local inference before importing an ONNX-backed OCR engine."""

from __future__ import annotations

import importlib
import os


def prepare_onnx_privacy() -> None:
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("OMP_NUM_THREADS", "2")


def private_onnxruntime():
    prepare_onnx_privacy()
    runtime = importlib.import_module("onnxruntime")
    runtime.disable_telemetry_events()
    return runtime


prepare_onnx_privacy()
