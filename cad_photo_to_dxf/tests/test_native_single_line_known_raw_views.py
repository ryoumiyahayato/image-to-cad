"""Known raw disagreements cannot disappear behind recognition early stopping."""

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.native_objects import independent_recognizer as independent
from app.native_objects import observation_cache as observations
from app.native_objects import single_line_labels as labels
from app.native_objects import text_regions as base
from tests.test_native_single_line_labels import _drawing, _prediction


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _cached_fixture(tmp_path, monkeypatch, *, second_tess=None, second_model=None):
    gray, roi, _, part = _drawing()
    cache = observations.ObservationCache(tmp_path / "raw", create=True)
    monkeypatch.setenv(observations.ENVIRONMENT_VARIABLE, str(cache.root))
    tess_identity = {
        "name": "tesseract", "version": "tesseract controlled-fixture",
        "executable_sha256": "a"*64, "traineddata_sha256": "b"*64,
        "language": "eng", "oem": 1, "CPU_threads": 1,
    }
    model_identity = {
        "name": "PP-OCRv6_rec_small", "distribution": "test-fixture",
        "model_sha256": independent.MODEL_SHA256, "ONNXRuntime": "fixture",
        "providers": ["CPUExecutionProvider"], "character_dictionary_sha256": "c"*64,
        "policy": deepcopy(independent.POLICY),
    }

    def forbidden(*args, **kwargs):
        pytest.fail("a preexisting raw check must not execute either recognizer")

    model = SimpleNamespace(identity=model_identity, recognize=forbidden)
    monkeypatch.setattr(base, "_resolve_tesseract", lambda *args: {"executable": "fixture", "version": tess_identity["version"]})
    monkeypatch.setattr(observations, "tesseract_identity", lambda engine: tess_identity)
    monkeypatch.setattr(base, "_ocr", forbidden)
    records = {}
    for index, text in enumerate(["AB-12,3", second_tess]):
        if text is None:
            continue
        spec = labels.POLICY["Tesseract_views"][index]
        normalized, actual = labels._view(gray, part, spec["scale"], spec["padding"])
        pad = spec["padding"]
        payload = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            f"5\t1\t1\t1\t1\t1\t{pad}\t{pad}\t{normalized.shape[1]}\t{normalized.shape[0]}\t23\t{text}\n"
        ).encode()
        request = observations.tesseract_spec(
            normalized, actual, padding=pad, psm=spec["psm"], dpi=400, engine=tess_identity
        )
        receipt = cache.put(request, payload, observations.producer_identity(
            __file__, engine=tess_identity,
            metadata={"command": ["fixture", "--psm", str(spec["psm"]), "--dpi", "400", "-l", "eng", "--oem", "1"],
                      "engine_version": tess_identity["version"]},
        ))
        records[("Tesseract", index)] = receipt
    for index, text in enumerate(["AB-12,3", second_model]):
        if text is None:
            continue
        spec = labels.POLICY["PP_OCR_views"][index]
        _, actual = labels._view(gray, part, spec["scale"], spec["padding"])
        original, tensor = independent.prepare_model_input(actual)
        prediction = _prediction(text)
        prediction.update(
            input_array_sha256=_sha(original.tobytes()), input_shape_px=list(original.shape),
            model_tensor_sha256=_sha(tensor.tobytes()), model_tensor_shape=list(tensor.shape),
            source_geometry_modified=False, raw_transcription_rewritten=False,
        )
        request = observations.model_spec(original, tensor, model_identity)
        records[("PP-OCR", index)] = cache.put(
            request, observations.canonical_bytes(prediction),
            observations.producer_identity(__file__, engine=model_identity),
        )
    return gray, roi, part, model, cache, records


def test_first_pair_match_cannot_hide_a_cached_later_single_engine_conflict(tmp_path, monkeypatch):
    gray, roi, part, model, _, _ = _cached_fixture(tmp_path, monkeypatch, second_tess="AB-12,8")
    result = labels.recognize_single_line_label(
        gray, roi, {"source_partition": part}, tmp_path/"result",
        recognizer=model, evidence_root=tmp_path,
    )
    assert not result["accepted"]
    assert len(result["evidence"]["tesseract_views"]) == 2
    assert len(result["evidence"]["ppocr_views"]) == 1
    assert "UNRESOLVED_COMPLETE_RAW_CHARACTER_CONFLICT" in result["reasons"]
    assert result["new_Tesseract_calls"] == result["new_model_calls"] == 0


def test_cached_second_model_is_read_even_when_second_tesseract_does_not_exist(tmp_path, monkeypatch):
    gray, roi, part, model, _, _ = _cached_fixture(tmp_path, monkeypatch, second_model="AB-12,8")
    result = labels.recognize_single_line_label(
        gray, roi, {"source_partition": part}, tmp_path/"result",
        recognizer=model, evidence_root=tmp_path,
    )
    assert not result["accepted"]
    assert len(result["evidence"]["tesseract_views"]) == 1
    assert len(result["evidence"]["ppocr_views"]) == 2
    assert "CONFLICTING_CONFIDENT_PP_OCR_VIEW" in result["reasons"]
    assert result["new_Tesseract_calls"] == result["new_model_calls"] == 0


@pytest.mark.parametrize("second_tess", [None, "AB--12,3"])
def test_missing_later_view_does_not_force_new_recognition_and_asymmetric_cold_passes(
    tmp_path, monkeypatch, second_tess
):
    gray, roi, part, model, _, _ = _cached_fixture(tmp_path, monkeypatch, second_tess=second_tess)
    result = labels.recognize_single_line_label(
        gray, roi, {"source_partition": part}, tmp_path/"result",
        recognizer=model, evidence_root=tmp_path,
    )
    assert result["accepted"], result["reasons"]
    assert result["new_Tesseract_calls"] == result["new_model_calls"] == 0
    check = labels.verify_single_line_label_evidence(gray, roi, result["evidence"], tmp_path)
    assert check["pass"], check
    assert check["known_view_count"] == (2 if second_tess is None else 3)
    if second_tess is not None:
        tampered = deepcopy(result["evidence"])
        tampered["tesseract_views"] = tampered["tesseract_views"][:1]
        check = labels.verify_single_line_label_evidence(gray, roi, tampered, tmp_path)
        assert not check["pass"] and "KNOWN_RAW_VIEW_OMITTED" in check["reason"]


def test_corrupt_known_cache_is_an_error_and_never_a_new_recognition_request(tmp_path, monkeypatch):
    gray, roi, part, model, cache, records = _cached_fixture(tmp_path, monkeypatch, second_tess="AB-12,8")
    receipt = records[("Tesseract", 1)]
    (cache.root/"blobs"/receipt["payload_sha256"]).write_bytes(b"damaged original raw")
    with pytest.raises(ValueError, match="RAW_OBSERVATION_PAYLOAD_HASH_MISMATCH"):
        labels.recognize_single_line_label(
            gray, roi, {"source_partition": part}, tmp_path/"result",
            recognizer=model, evidence_root=tmp_path,
        )


def test_changed_inventory_record_is_rejected_by_cold_reader(tmp_path, monkeypatch):
    gray, roi, part, model, _, _ = _cached_fixture(tmp_path, monkeypatch, second_tess="AB--12,3")
    result = labels.recognize_single_line_label(
        gray, roi, {"source_partition": part}, tmp_path/"result",
        recognizer=model, evidence_root=tmp_path,
    )
    evidence = deepcopy(result["evidence"])
    inventory = json.loads((tmp_path/evidence["preexisting_raw_view_inventory"]["path"]).read_text())
    row = next(r for r in inventory["views"] if r["engine"] == "Tesseract" and r["view_index"] == 1)
    (tmp_path/row["raw_payload"]["path"]).write_bytes(b"deleted opposing raw artifact")
    assert not labels.verify_single_line_label_evidence(gray, roi, evidence, tmp_path)["pass"]


@pytest.mark.parametrize("family,field", [
    ("Tesseract", "psm"),
    ("Tesseract", "crop"),
    ("Tesseract", "recognition_input"),
    ("Tesseract", "engine"),
    ("PP-OCR", "model_tensor"),
    ("PP-OCR", "engine"),
])
def test_internally_rehashed_cache_record_still_requires_actual_source_and_config(
    tmp_path, monkeypatch, family, field
):
    gray, roi, part, model, _, _ = _cached_fixture(tmp_path, monkeypatch)
    result = labels.recognize_single_line_label(
        gray, roi, {"source_partition": part}, tmp_path/"result",
        recognizer=model, evidence_root=tmp_path,
    )
    evidence = deepcopy(result["evidence"])
    inventory_ref = evidence["preexisting_raw_view_inventory"]
    inventory_path = tmp_path/inventory_ref["path"]
    inventory = json.loads(inventory_path.read_text())
    row = next(r for r in inventory["views"] if r["engine"] == family and r["view_index"] == 0)
    record_path = tmp_path/row["cache_record"]["path"]
    record = json.loads(record_path.read_text())
    spec = record["specification"]
    if field == "psm":
        spec[field] = 13
    elif field == "engine":
        key = "traineddata_sha256" if family == "Tesseract" else "character_dictionary_sha256"
        spec[field][key] = "d"*64
    else:
        spec[field]["sha256"] = "d"*64
    record["key"] = observations.digest(spec)
    record_path.write_bytes(observations.canonical_bytes(record))
    row["cache_record"]["sha256"] = _sha(record_path.read_bytes())
    receipt = row["raw_observation_cache"]
    receipt["key"] = record["key"]
    receipt["record_sha256"] = row["cache_record"]["sha256"]
    if family == "Tesseract":
        view = evidence["tesseract_views"][0]
        meta_path = tmp_path/view["metadata"]["path"]
        metadata = json.loads(meta_path.read_text())
        metadata["raw_observation_cache"] = deepcopy(receipt)
        meta_path.write_bytes(observations.canonical_bytes(metadata))
        view["metadata"]["sha256"] = _sha(meta_path.read_bytes())
    else:
        evidence["ppocr_views"][0]["observation_receipt"]["raw_observation_cache"] = deepcopy(receipt)
    inventory_path.write_bytes(observations.canonical_bytes(inventory))
    inventory_ref["sha256"] = _sha(inventory_path.read_bytes())
    check = labels.verify_single_line_label_evidence(gray, roi, evidence, tmp_path)
    assert not check["pass"]
    assert "KNOWN_CACHE_SOURCE_CONFIGURATION_CHANGED" in check["reason"]
