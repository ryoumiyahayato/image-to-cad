"""Prove privacy initialization order with fake ORT, without real model loading."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


GUARD = Path(__file__).parents[1] / "app/native_objects/offline_runtime.py"


def isolated_guard(monkeypatch, *, preloaded=False):
    for name in list(sys.modules):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            monkeypatch.delitem(sys.modules, name)
    if preloaded:
        monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace())
    spec = importlib.util.spec_from_file_location("isolated_ort_privacy_guard", GUARD)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def test_environment_is_disabled_before_import_and_api_before_every_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    guard = isolated_guard(monkeypatch)
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
    events = []

    def disable():
        events.append("disable")

    class Options:
        pass

    class Session:
        def __init__(self, *args, **kwargs):
            assert events[-1] == "disable"
            assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
            assert kwargs["providers"] == ["CPUExecutionProvider"]
            events.append("session")

        def get_modelmeta(self):
            return SimpleNamespace(custom_metadata_map={"character": "A\nB"})

        def get_inputs(self):
            return [SimpleNamespace(name="input")]

        def get_providers(self):
            return ["CPUExecutionProvider"]

    fake = SimpleNamespace(
        disable_telemetry_events=disable,
        SessionOptions=Options,
        InferenceSession=Session,
        __version__="fake-no-native-library",
    )

    def import_fake(name):
        assert name == "onnxruntime"
        assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
        events.append("import")
        monkeypatch.setitem(sys.modules, name, fake)
        return fake

    from app.native_objects import independent_recognizer as recognizer

    monkeypatch.setattr(guard.importlib, "import_module", import_fake)
    model = tmp_path / "synthetic.onnx"
    model.write_bytes(b"not-an-onnx-model; fake session only")
    monkeypatch.setattr(
        recognizer, "MODEL_SHA256", hashlib.sha256(model.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(recognizer, "private_onnxruntime", guard.private_onnxruntime)
    monkeypatch.setattr(
        recognizer, "runtime_privacy_status", guard.runtime_privacy_status
    )
    first = recognizer.IndependentRecognizer(model)
    second = recognizer.IndependentRecognizer(model)
    assert events == ["import", "disable", "session"] * 2
    assert (
        first.identity["runtime_privacy"]["official_disable_telemetry_events_calls"]
        == 1
    )
    assert (
        second.identity["runtime_privacy"]["official_disable_telemetry_events_calls"]
        == 2
    )
    assert not second.identity["runtime_privacy"]["system_network_activity_measured"]
    assert not second.identity["runtime_privacy"]["system_zero_network_claimed"]


def test_unknown_preloaded_runtime_fails_closed_even_if_env_now_says_disabled(
    monkeypatch,
):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    with pytest.raises(RuntimeError, match="PRELOADED_WITHOUT_PRIVACY_BOOTSTRAP"):
        isolated_guard(monkeypatch, preloaded=True)


def test_changed_environment_after_import_and_missing_api_fail_closed(monkeypatch):
    guard = isolated_guard(monkeypatch)
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace())
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    with pytest.raises(RuntimeError, match="ENV_CHANGED_AFTER_INITIALIZATION"):
        guard.private_onnxruntime()
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    monkeypatch.setattr(
        guard.importlib, "import_module", lambda name: SimpleNamespace()
    )
    with pytest.raises(RuntimeError, match="DISABLE_API_UNAVAILABLE"):
        guard.private_onnxruntime()


def test_manager_passes_opt_out_to_child_and_records_configuration(
    tmp_path, monkeypatch
):
    from PIL import Image
    from app.core import native_job_manager as managers

    guard = isolated_guard(monkeypatch)
    monkeypatch.setattr(managers, "prepare_onnx_privacy", guard.prepare_onnx_privacy)
    monkeypatch.setattr(
        managers, "runtime_privacy_status", guard.runtime_privacy_status
    )
    identity = {"sha256": "a" * 64, "git": {"available": False}}
    monkeypatch.setattr(managers, "algorithm_fingerprint", lambda: identity)
    source = tmp_path / "controlled.png"
    Image.new("L", (32, 32), 255).save(source)
    manager = managers.NativeJobManager(tmp_path / "jobs")
    task = manager.create(input_path=source, roi=[0, 0, 32, 32], dpi=200)
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    observed = []

    def no_child(command, **kwargs):
        observed.append(kwargs["env"])
        raise OSError("synthetic worker intentionally not launched")

    monkeypatch.setattr(managers.subprocess, "Popen", no_child)
    with pytest.raises(OSError, match="intentionally not launched"):
        manager.start(task["job_id"])
    assert len(observed) == 1
    assert observed[0]["ORT_DISABLE_TELEMETRY"] == "1"
    request = json.loads(
        (tmp_path / "jobs" / task["job_id"] / "attempts/0001/request.json").read_text()
    )
    assert request["runtime_privacy"]["environment_value"] == "1"
    assert request["runtime_privacy"]["prepared_before_managed_ORT_import"]
    assert request["runtime_privacy"]["official_disable_telemetry_events_calls"] == 0
    assert not request["runtime_privacy"]["system_network_activity_measured"]
