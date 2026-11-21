"""Raw evidence reuse changes execution, never the recognition/adoption answer."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from app.native_objects import observation_cache as cache_module
from app.native_objects import text_regions
from app.native_objects.execution import file_sha, use_context
from app.native_objects.independent_recognizer import IndependentRecognizer, POLICY

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t1\t1\t5\t4\t98\tA\n"
)


def _configured(tmp_path, monkeypatch, *, historical=False):
    root = tmp_path / "raw-cache"
    cache = cache_module.ObservationCache(
        root, create=True, allow_historical_tesseract=historical
    )
    monkeypatch.setenv(cache_module.ENVIRONMENT_VARIABLE, str(root))
    binary, data = tmp_path / "tesseract", tmp_path / "eng.traineddata"
    binary.write_bytes(b"test-executable-identity")
    data.write_bytes(b"test-language-data-identity")
    engine = {
        "executable": str(binary),
        "version": "tesseract test",
        "list_langs_output": f'List of available languages in "{tmp_path}" (1):\neng\n',
    }
    monkeypatch.setattr(text_regions, "_resolve_tesseract", lambda *args: engine)
    calls = []

    def recognize(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=TSV, stderr="", returncode=0)

    monkeypatch.setattr(text_regions, "run_subprocess", recognize)
    return cache, engine, calls


def test_same_pixels_different_producer_names_call_tesseract_once(
    tmp_path, monkeypatch
):
    cache, _, calls = _configured(tmp_path, monkeypatch)
    image = np.full((20, 30), 255, dtype=np.uint8)
    image[2:6, 3:8] = 0
    first, _ = text_regions._ocr(
        image, [0, 0, 15, 12], 7, tmp_path / "one", "first", None
    )
    second, meta = text_regions._ocr(
        image, [0, 0, 15, 12], 7, tmp_path / "two", "renamed", None
    )
    assert len(calls) == 1
    assert first[0]["text"] == second[0]["text"] == "A"
    assert first[0]["observation_key"] == second[0]["observation_key"]
    assert (
        meta["reused_raw_observation"] and not meta["command_executed_for_this_request"]
    )
    assert meta["raw_observation_cache"]["kind"] == "tesseract-tsv"
    assert cache.snapshot()["entry_count"] == 1


def test_same_pixels_at_distinct_coordinates_keep_geometry_but_one_agreement_vote(
    tmp_path, monkeypatch
):
    from app.native_objects.source_text_completion import BoundObservations

    _, _, calls = _configured(tmp_path, monkeypatch)
    tile = np.full((10, 10), 255, dtype=np.uint8)
    tile[1:5, 1:6] = 0
    image = np.hstack((tile, tile))
    first_box, second_box = [0, 0, 10, 10], [10, 0, 20, 10]
    first, _ = text_regions._ocr(image, first_box, 7, tmp_path / "first", "one", None)
    second, _ = text_regions._ocr(
        image, second_box, 7, tmp_path / "second", "two", None
    )
    assert len(calls) == 1
    assert first[0]["observation_key"] == second[0]["observation_key"]
    assert second[0]["bbox_xyxy_px"][0] - first[0]["bbox_xyxy_px"][0] == 10
    store = BoundObservations(image, tmp_path / "completion", "a" * 64, 200)
    first_context = store.ingest(tmp_path / "first/one.tsv")
    second_context = store.ingest(tmp_path / "second/two.tsv")
    assert first_context != second_context
    one = store.alternative(first_context, first_box)
    two = store.alternative(second_context, second_box)
    assert one["observation_key"] == two["observation_key"]
    assert (
        two["all_words"][0]["bbox_xyxy_px"][0]
        == one["all_words"][0]["bbox_xyxy_px"][0] + 10
    )
    assert two["observation_provenance"]["command_executed_for_this_request"] is False


@pytest.mark.parametrize("changed", ["padding", "psm", "dpi", "pixels", "engine"])
def test_a_changed_recognition_input_does_not_hit_old_observation(
    tmp_path, monkeypatch, changed
):
    _, engine, calls = _configured(tmp_path, monkeypatch)
    image = np.full((15, 15), 255, dtype=np.uint8)
    text_regions._ocr(image, [0, 0, 10, 10], 7, tmp_path / "first", "x", None)
    values = {"padding_px": 0, "dpi": 200}
    if changed == "padding":
        values["padding_px"] = 2
    elif changed == "dpi":
        values["dpi"] = 201
    elif changed == "pixels":
        image[2, 2] = 0
    elif changed == "engine":
        Path(engine["executable"]).write_bytes(b"different-executable")
    text_regions._ocr(
        image,
        [0, 0, 10, 10],
        6 if changed == "psm" else 7,
        tmp_path / "second",
        "x",
        None,
        **values,
    )
    assert len(calls) == 2


def test_corrupt_cache_fails_without_an_extra_ocr_call(tmp_path, monkeypatch):
    cache, _, calls = _configured(tmp_path, monkeypatch)
    image = np.full((10, 10), 255, dtype=np.uint8)
    _, meta = text_regions._ocr(image, [0, 0, 10, 10], 7, tmp_path / "first", "x", None)
    payload = cache.root / "blobs" / meta["raw_observation_cache"]["payload_sha256"]
    payload.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="PAYLOAD_HASH_MISMATCH"):
        text_regions._ocr(image, [0, 0, 10, 10], 7, tmp_path / "second", "x", None)
    assert len(calls) == 1


def test_explicit_historical_namespace_preserves_unknown_engine_bytes_and_binds_source(
    tmp_path, monkeypatch
):
    cache, engine, calls = _configured(tmp_path, monkeypatch, historical=True)
    image = np.full((10, 10), 255, dtype=np.uint8)
    spec = cache_module.tesseract_spec(
        image,
        image,
        padding=0,
        psm=7,
        dpi=200,
        engine=cache_module.tesseract_identity(engine),
    )
    old = cache_module.historical_tesseract_spec(spec, "a" * 64)
    cache.put(
        old,
        TSV.encode(),
        {
            "origin": "imported_verified_raw_observation",
            "engine": old["engine"],
            "metadata": {"command": ["original-recorded-command"]},
        },
    )
    with use_context(
        cancel_file=tmp_path / "cancel",
        event_file=tmp_path / "events.jsonl",
        identity={"source_sha256": "a" * 64},
    ):
        words, meta = text_regions._ocr(
            image, [0, 0, 10, 10], 7, tmp_path / "same", "x", None
        )
    assert len(calls) == 0
    assert meta["raw_observation_cache"]["kind"] == "historical-tesseract-tsv"
    assert meta["engine_identity"]["historical_model_byte_identity_proven"] is False
    assert "executable_sha256" not in meta["engine_identity"]
    provenance = words[0]["observation_provenance"]
    assert provenance["historical_model_byte_identity_proven"] is False
    assert provenance["raw_observation_kind"] == "historical-tesseract-tsv"
    assert provenance["command_executed_for_this_request"] is False
    assert provenance["consumer_installed_engine_identity"]["executable_sha256"]
    with use_context(
        cancel_file=tmp_path / "cancel",
        event_file=tmp_path / "events.jsonl",
        identity={"source_sha256": "b" * 64},
    ):
        text_regions._ocr(image, [0, 0, 10, 10], 7, tmp_path / "different", "x", None)
    assert len(calls) == 1


def test_model_raw_ctc_is_reused_without_inference_or_rewriting(tmp_path, monkeypatch):
    _configured(tmp_path, monkeypatch)
    recognizer = IndependentRecognizer.__new__(IndependentRecognizer)
    recognizer.identity = {
        "name": "fixture",
        "distribution": "fixture",
        "model_sha256": "1" * 64,
        "ONNXRuntime": "fixture",
        "providers": ["CPUExecutionProvider"],
        "character_dictionary_sha256": "2" * 64,
        "policy": copy.deepcopy(POLICY),
    }
    recognizer.characters, recognizer.input_name = ["blank", "A", "B"], "input"
    calls = []

    def infer(*args):
        calls.append(args)
        return [np.array([[[0.1, 0.8, 0.1], [0.1, 0.8, 0.1]]], dtype=np.float32)]

    recognizer.session = SimpleNamespace(run=infer)
    image = np.full((14, 25), 255, dtype=np.uint8)
    first, second = recognizer.recognize(image), recognizer.recognize(image)
    assert first == second
    assert len(calls) == 1
    assert first["raw_transcription_rewritten"] is False
    recognizer.identity["model_sha256"] = "3" * 64
    recognizer.recognize(image)
    assert len(calls) == 2


def _importer():
    path = (
        Path(__file__).resolve().parents[2]
        / "maintenance/import_native_raw_observations.py"
    )
    specification = importlib.util.spec_from_file_location("test_raw_importer", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_later_import_binary_measurement_never_becomes_historical_identity():
    importer = _importer()
    identity, proven = importer._original_engine(
        {},
        {
            "engine_identity": {
                "engine_version": "tesseract 5.5.0",
                "current_executable_sha256": "a" * 64,
                "current_model_sha256": "b" * 64,
                "historical_executable_sha256": None,
                "historical_model_sha256": None,
                "historical_model_byte_identity_proven": False,
            }
        },
    )
    assert proven is False
    assert identity["historical_model_byte_identity_proven"] is False
    assert "executable_sha256" not in identity


def test_importer_rejects_rehashed_png_with_wrong_source_pixels(tmp_path):
    importer = _importer()
    image = np.full((8, 8), 255, dtype=np.uint8)
    altered = image.copy()
    altered[0, 0] = 0
    path = tmp_path / "changed.png"
    Image.fromarray(altered).save(path)
    with pytest.raises(ValueError, match="DIFFERS_FROM_ORIGINAL_SOURCE"):
        importer._check_png(path, image)


def test_importer_rejects_metadata_outside_or_different_from_publication(tmp_path):
    importer = _importer()
    path = tmp_path / "meta.json"
    path.write_text("{}")
    manifest = {"files": {"meta.json": {"sha256": file_sha(path), "bytes": 2}}}
    assert importer._published_file(tmp_path, manifest, "meta.json") == path
    path.write_text(json.dumps({"modified": True}))
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        importer._published_file(tmp_path, manifest, "meta.json")
    with pytest.raises(ValueError, match="OUTSIDE_DECLARED_PUBLICATION"):
        importer._published_file(tmp_path, manifest, "../elsewhere.json")
