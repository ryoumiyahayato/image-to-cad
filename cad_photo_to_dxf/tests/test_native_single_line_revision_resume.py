"""Published revision chains: real source/raw replay, synthetic engine records.

No OCR binary or model inference is run. The production source partition,
serialization, raw replay, legacy command checks and revision gates are real.
"""

from copy import deepcopy
import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import pytest

from app.native_objects import independent_recognizer as independent
from app.native_objects import pipeline, revision_resume as resume
from app.native_objects import single_line_labels as labels
from app.native_objects import text_regions as base
from app.native_objects.contracts import save_json
from app.native_objects.execution import file_sha, read_json


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _producers(new=True):
    names = [*resume._PRODUCERS, *resume._DERIVED_PRODUCERS]
    if new:
        names += list(resume._SINGLE_LINE_PRODUCERS)
        names += list(resume._TEXT_CONTACT_PRODUCERS)
        names += list(resume._SOURCE_GAP_PRODUCERS)
    return {
        "app.native_objects." + name: file_sha(
            Path(resume.__file__).with_name(name + ".py")
        )
        for name in names
    }


def _ownership(evidence, upstream, stage, producers):
    dictionary = {"objects": [], "uncertainties": [], "short_source_components": []}
    directory = evidence / "text_geometry_ownership"
    save_json(directory / "source_fitted_dictionary.json", dictionary)
    audit = {
        "producer_sha256": producers["app.native_objects.source_text_ownership"],
        "upstream_text_sha256": resume._canonical_digest(upstream),
        "saved_geometry_proposals_sha256": resume._canonical_digest(dictionary),
        "source_array_sha256": stage["source_array_sha256"],
        "source_pixels_removed": 0,
        "OCR_calls": 0,
        "source_fits": 0,
    }
    save_json(directory / "source_text_ownership_audit.json", audit)
    final = deepcopy(upstream)
    final["source_text_ownership"] = audit
    save_json(directory / "completed_text.json", final)
    row = {
        "producer_module": "app.native_objects.source_text_ownership",
        "producer_sha256": producers["app.native_objects.source_text_ownership"],
        "path": "text_geometry_ownership/completed_text.json",
        "sha256": file_sha(directory / "completed_text.json"),
        "source_fitted_dictionary_path": "text_geometry_ownership/source_fitted_dictionary.json",
        "source_fitted_dictionary_sha256": file_sha(
            directory / "source_fitted_dictionary.json"
        ),
        "dependency_producers": {
            name: digest
            for name, digest in producers.items()
            if name != "app.native_objects.source_text_ownership"
        },
    }
    return final, row


def _published(evidence):
    hashes = {path: file_sha(path) for path in evidence.rglob("*") if path.is_file()}

    def check(path):
        assert path in hashes, "not published: " + str(path)
        resume._verify_file(path, hashes[path], "published " + path.name)

    return check


def _input(evidence):
    gray = np.full((220, 500), 255, np.uint8)
    regions, groups = [], []
    for index, (text, point, complete) in enumerate(
        [
            ("AB-12,3", (35, 70), False),
            ("CD-45,6", (35, 150), False),
            ("STORE", (330, 70), True),
        ]
    ):
        local = np.full_like(gray, 255)
        cv2.putText(
            local, text, point, cv2.FONT_HERSHEY_SIMPLEX, 0.85, 0, 1, cv2.LINE_8
        )
        gray = np.minimum(gray, local)
        yy, xx = np.nonzero(local < 192)
        box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
        rid, gid = f"R{index}", f"G{index}"
        regions.append(
            {
                "id": rid,
                "bbox_xyxy_px": box,
                "discovery_bbox_xyxy_px": box,
                "text": "STORE" if complete else "UNKNOWN",
                "complete": complete,
                "words": [],
                "enclosure": None,
            }
        )
        groups.append(
            {
                "id": gid,
                "region_ids": [rid],
                "geometry_type": "TEXT",
                "bbox_xyxy_px": box,
                "text": regions[-1]["text"],
                "complete": complete,
            }
        )
    text = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [500, 220],
        "roi_xyxy_px": [0, 0, 500, 220],
        "source_array_sha256": base.source_array_sha256(gray),
        "regions": regions,
        "groups": groups,
    }
    path = evidence / "source_text_completion/completed_text.json"
    save_json(path, text)
    return gray, text


def _controlled_records(monkeypatch, evidence):
    observations = [("AB-12,3", 96.0), ("CD-45,6", 70.0), ("CD-45,6", 70.0)]
    calls = {"tsv": 0, "model": 0}
    engine = {
        "executable": str(evidence / "controlled-tesseract"),
        "engine_version": "tesseract controlled-fixture",
    }

    def ocr(image, box, psm, directory, name, progress, padding_px=0, *, dpi=200):
        text, confidence = observations[calls["tsv"]]
        calls["tsv"] += 1
        crop = np.ascontiguousarray(image[box[1] : box[3], box[0] : box[2]])
        padded = np.pad(crop, padding_px, constant_values=255)
        png, tsv, meta = [
            directory / (name + suffix) for suffix in (".png", ".tsv", ".json")
        ]
        Image.fromarray(padded).save(png)
        raw = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        raw += f"5\t1\t1\t1\t1\t1\t{padding_px}\t{padding_px}\t{crop.shape[1]}\t{crop.shape[0]}\t{confidence}\t{text}\n"
        tsv.write_text(raw, encoding="utf-8")
        metadata = {
            "status": "COMPLETED",
            "return_code": 0,
            "tsv_sha256": file_sha(tsv),
            "image_sha256": file_sha(png),
            "command_executed_for_this_request": True,
            "engine_version": engine["engine_version"],
            "command": [
                engine["executable"],
                str(png),
                "stdout",
                "-l",
                "eng",
                "--oem",
                "1",
                "--psm",
                str(psm),
                "--dpi",
                str(dpi),
                "tsv",
            ],
            "specification": {
                "crop_xyxy_px": box,
                "crop_array_sha256": base.source_array_sha256(crop),
                "psm": psm,
                "external_white_padding_px": padding_px,
                "language": "eng",
                "source_pixels_modified": False,
                "recognition_dpi": dpi,
                "pixel_scale": [1, 1],
                "padding_replaces_source_pixels": False,
            },
        }
        save_json(meta, metadata)
        words = base._parse_tsv(
            raw,
            [
                -padding_px,
                -padding_px,
                padded.shape[1] - padding_px,
                padded.shape[0] - padding_px,
            ],
            name,
            psm,
        )
        return words, metadata

    class Model:
        identity = {
            "model_sha256": independent.MODEL_SHA256,
            "policy": deepcopy(independent.POLICY),
        }

        def recognize(self, image):
            text = observations[calls["model"]][0]
            calls["model"] += 1
            original, tensor = independent.prepare_model_input(image)
            self.last_observation = {"model_inference_executed_for_this_request": True}
            return {
                "raw_text": text,
                "raw_CTC_tokens": [
                    {
                        "time_step": index + 1,
                        "token_index": index + 50,
                        "character": char,
                        "score": 0.999,
                    }
                    for index, char in enumerate(text)
                ],
                "model_mean_confidence": 0.999,
                "minimum_emitted_character_confidence": 0.999,
                "input_array_sha256": _hash(original.tobytes()),
                "input_shape_px": list(original.shape),
                "model_tensor_sha256": _hash(tensor.tobytes()),
                "model_tensor_shape": list(tensor.shape),
                "source_geometry_modified": False,
                "raw_transcription_rewritten": False,
            }

    monkeypatch.setattr(base, "_ocr", ocr)
    monkeypatch.setattr(base, "_resolve_tesseract", lambda *args: engine)
    monkeypatch.setattr(labels, "_RECOGNIZER", Model())
    return calls, engine


def _fixture(tmp_path, monkeypatch, prior_ownership=False):
    evidence = tmp_path / "evidence"
    gray, completion = _input(evidence)
    producers = _producers()
    stage = {
        "source_sha256": "a" * 64,
        "source_array_sha256": completion["source_array_sha256"],
        "source_size_px": completion["source_size_px"],
        "roi_xyxy_px": completion["roi_xyxy_px"],
    }
    before = deepcopy(completion)
    old = {
        "producer_module": "app.native_objects.source_text_completion",
        "producer_sha256": producers["app.native_objects.source_text_completion"],
        "path": "source_text_completion/completed_text.json",
        "sha256": file_sha(evidence / "source_text_completion/completed_text.json"),
        "dependency_producers": {},
    }
    if prior_ownership:
        before, old = _ownership(evidence, completion, stage, _producers(False))
    save_json(evidence / "completed_stages.json", {**stage, "text": old})
    calls, engine = _controlled_records(monkeypatch, evidence)
    monkeypatch.setattr(pipeline, "checkpoint_artifact", lambda *args: None)
    single = pipeline._complete_single_line_stage(
        gray,
        before,
        evidence,
        stage["source_sha256"],
        stage["roi_xyxy_px"],
        200,
        lambda *_: None,
    )
    assert single["single_line_label_recovery"]["accepted_labels"] == 1
    assert single["single_line_label_recovery"]["pending_labels"] == 1
    final, row = _ownership(evidence, single, stage, producers)
    stage["text"] = row
    save_json(evidence / "completed_stages.json", stage)

    def forbidden(*args, **kwargs):
        pytest.fail("revision recovery must not execute OCR or model inference")

    monkeypatch.setattr(base, "_ocr", forbidden)
    monkeypatch.setattr(independent, "IndependentRecognizer", forbidden)
    return evidence, gray, completion, single, final, stage, producers, calls, engine


@pytest.mark.parametrize("prior_ownership", [False, True])
def test_new_revision_replays_raw_stage_and_binds_new_ownership_upstream(
    tmp_path, monkeypatch, prior_ownership
):
    evidence, gray, completion, single, final, stage, producers, calls, engine = (
        _fixture(tmp_path, monkeypatch, prior_ownership)
    )
    published = _published(evidence)
    restored, chain, tsv, models = resume._verify_single_line_stage(
        evidence, final, stage, completion, producers, gray, published
    )
    assert restored == single and len(tsv) == len(models) == 3
    assert [row["accepted"] for row in chain["source_replays"]] == [True, False]
    assert all(
        row["new_OCR_calls"] == row["new_model_calls"] == 0
        for row in chain["source_replays"]
    )
    assert calls == {"tsv": 3, "model": 3}
    assert resume._verify_ownership_chain(
        evidence, stage["text"], restored, producers, stage, published
    )["not_formal_adoption"]
    for relative, binding in tsv.items():
        checked = resume._verify_single_line_ocr(
            evidence / relative, gray, 200, engine, binding
        )
        assert (
            checked["source_transform_replayed"]
            and checked["status"] == "VERIFIED_COMPLETED_OBSERVATION"
        )
    resume._producer_checks(producers)
    assert set(resume._SINGLE_LINE_PRODUCERS) <= set(
        resume._revision_producer_names(stage["text"])
    )
    assert "single_line_labels" in resume._ROOTS


def test_old_revision_retains_source_completion_ownership_chain(tmp_path):
    evidence = tmp_path / "evidence"
    _, completion = _input(evidence)
    producers = _producers(False)
    stage = {"source_array_sha256": completion["source_array_sha256"]}
    _, row = _ownership(evidence, completion, stage, producers)
    assert not resume._has_single_line_producer(row)
    assert not set(resume._SINGLE_LINE_PRODUCERS) & set(
        resume._revision_producer_names(row)
    )
    resume._producer_checks(producers)
    assert resume._verify_ownership_chain(
        evidence, row, completion, producers, stage, _published(evidence)
    )["not_formal_adoption"]


@pytest.mark.parametrize(
    "damage",
    [
        "source",
        "raw-tsv",
        "derived-png",
        "upstream",
        "missing-proof",
        "pending-decision",
        "raw-inventory",
        "new-text",
    ],
)
def test_new_revision_rejects_source_evidence_and_candidate_tampering(
    tmp_path, monkeypatch, damage
):
    evidence, gray, completion, _, final, stage, producers, _, _ = _fixture(
        tmp_path, monkeypatch
    )
    published = _published(evidence)
    summary = final["single_line_label_recovery"]
    result_path = evidence / (
        "single_line_labels/labels/"
        + summary["attempts"][0]["id"]
        + "/label_result.json"
    )
    proof = read_json(result_path)["evidence"]
    if damage == "source":
        gray[0, 0] = 0
    elif damage in {"raw-tsv", "derived-png"}:
        key = "raw_tsv" if damage == "raw-tsv" else "recognition_image"
        (evidence / proof["tesseract_views"][0][key]["path"]).write_bytes(
            b"tampered actual artifact"
        )
    elif damage == "upstream":
        (evidence / "single_line_labels/upstream_completed_text.json").write_text("{}")
    elif damage == "missing-proof":
        next(
            region for region in final["regions"] if "single_line_recovery" in region
        ).pop("single_line_recovery")
    elif damage == "pending-decision":
        pending = evidence / (
            "single_line_labels/labels/"
            + summary["attempts"][1]["id"]
            + "/label_result.json"
        )
        observation = read_json(pending)
        observation["evidence"]["decision"]["reasons"] = []
        with pytest.raises(ValueError, match="SAVED_DECISION_CHANGED"):
            resume._replay_single_line_result(
                observation, gray, stage["roi_xyxy_px"], evidence
            )
        return
    elif damage == "raw-inventory":
        save_json(evidence / "single_line_labels/unregistered.json", {})
    elif damage == "new-text":
        next(group for group in final["groups"] if "single_line_recovery" in group)[
            "text"
        ] = "AB-12,8"
    with pytest.raises(ValueError):
        resume._verify_single_line_stage(
            evidence, final, stage, completion, producers, gray, published
        )


@pytest.mark.parametrize(
    "damage", ["old-upstream", "dictionary", "source-count", "producer"]
)
def test_new_ownership_chain_cannot_reuse_old_upstream_or_changed_geometry(
    tmp_path, monkeypatch, damage
):
    evidence, _, completion, single, _, stage, producers, _, _ = _fixture(
        tmp_path, monkeypatch
    )
    path = evidence / "text_geometry_ownership/source_text_ownership_audit.json"
    audit = read_json(path)
    if damage == "old-upstream":
        audit["upstream_text_sha256"] = resume._canonical_digest(completion)
    elif damage == "dictionary":
        audit["saved_geometry_proposals_sha256"] = "0" * 64
    elif damage == "source-count":
        audit["source_pixels_removed"] = 1
    else:
        audit["producer_sha256"] = "0" * 64
    save_json(path, audit)
    with pytest.raises(ValueError, match="OWNERSHIP_CHAIN_CHANGED"):
        resume._verify_ownership_chain(
            evidence, stage["text"], single, producers, stage, _published(evidence)
        )


@pytest.mark.parametrize("damage", ["engine", "command", "dpi"])
def test_derived_view_keeps_original_ocr_engine_and_command_checks(
    tmp_path, monkeypatch, damage
):
    evidence, gray, completion, _, final, stage, producers, _, engine = _fixture(
        tmp_path, monkeypatch
    )
    _, _, tsv, _ = resume._verify_single_line_stage(
        evidence, final, stage, completion, producers, gray, _published(evidence)
    )
    relative, binding = next(iter(tsv.items()))
    path = evidence / relative
    metadata = read_json(path)
    if damage == "engine":
        engine["engine_version"] = "tesseract different"
    elif damage == "command":
        metadata["command"].append("--unexpected")
    else:
        metadata["specification"]["recognition_dpi"] = 200
    save_json(path, metadata)
    with pytest.raises(ValueError):
        resume._verify_single_line_ocr(path, gray, 200, engine, binding)


def test_new_producer_pair_cannot_be_missing_or_changed():
    producers = _producers()
    producers.pop("app.native_objects.circle_character_recognition")
    with pytest.raises(ValueError, match="SINGLE_LINE_PRODUCER_SET_INCOMPLETE"):
        resume._producer_checks(producers)
    producers = _producers()
    producers["app.native_objects.single_line_labels"] = "0" * 64
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        resume._producer_checks(producers)


def test_pending_prefix_replays_bound_wider_source_observation_without_ocr(
    tmp_path, monkeypatch
):
    from tests.test_native_single_line_labels import (
        _RawModel, _contract, _drawing, _engines,
    )

    gray, roi, seed, _ = _drawing()
    # A separately observed suffix lies beyond this narrow derived row.  Its
    # literal is kept in an original upstream record, never passed to either
    # controlled recognition engine as a hint or used to complete the text.
    cv2.putText(gray, "4", (310, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.85, 0, 1, cv2.LINE_8)
    partition, reason = labels._partition(gray, roi, seed)
    assert partition is not None and reason is None
    assert partition["bbox_xyxy_px"][2] < 300
    snapshot = _contract(gray, roi, [seed[0], seed[1], 330, seed[3]])
    snapshot["regions"][0]["text"] = "AB-12,34"
    upstream = tmp_path / "single_line_labels/upstream_completed_text.json"
    save_json(upstream, snapshot)
    plan = {
        "id": "synthetic-pending-prefix", "region_ids": ["R1"],
        "source_partition": partition,
        "upstream_observations": {
            "snapshot": labels._file_record(upstream, tmp_path),
            "region_ids": ["R1"],
        },
    }
    calls = _engines(monkeypatch, [("AB-12,3", 96), ("AB-12,3", 96)])
    model = _RawModel([("AB-12,3", 0.999), ("AB-12,3", 0.999)])
    observation = labels.recognize_single_line_label(
        gray, roi, plan, tmp_path / "single_line_labels/labels/pending",
        recognizer=model, evidence_root=tmp_path,
    )
    assert not observation["accepted"] and observation["geometry"] is None
    assert observation["reasons"] == ["NARROW_PREFIX_OMITS_OBSERVED_ALPHANUMERIC_SUFFIX"]
    proof = observation["evidence"]
    # This was the integration defect: replaying only the already cropped raw
    # views would approve the prefix and disagree with the saved pending row.
    assert labels._decision(
        proof["tesseract_views"], proof["ppocr_views"], proof["source_partition"]
    )["accepted"]
    before_calls = (len(calls), len(model.calls))

    def forbidden(*_args, **_kwargs):
        pytest.fail("pending revision replay must not execute recognition")

    monkeypatch.setattr(base, "_ocr", forbidden)
    monkeypatch.setattr(independent, "IndependentRecognizer", forbidden)
    monkeypatch.setattr(model, "recognize", forbidden)
    replay = resume._replay_single_line_result(observation, gray, roi, tmp_path)
    assert replay["raw_source_and_decision_replayed"]
    assert replay["pending_observation_not_adopted"]
    assert replay["accepted"] is False
    assert replay["new_OCR_calls"] == replay["new_model_calls"] == 0
    assert before_calls == (len(calls), len(model.calls)) == (2, 2)
    # Changing the saved observation file cannot remove the suffix veto.
    changed = deepcopy(snapshot)
    changed["regions"][0]["text"] = "AB-12,3"
    save_json(upstream, changed)
    with pytest.raises(ValueError):
        resume._replay_single_line_result(observation, gray, roi, tmp_path)
