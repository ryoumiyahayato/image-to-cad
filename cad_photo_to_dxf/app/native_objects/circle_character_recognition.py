"""Source-bound single-character observations inside an independently proved ring.

The circle detector supplies the complete interior ink, never a transcription.
Both recognizers see the original tight glyph crop plus external white padding.
No ring pixels are erased, no character whitelist is sent to either engine, and
the saved verifier checks the raw files without running recognition again.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath

import numpy as np

from . import independent_recognizer as independent
from . import text_regions as base
from .contracts import save_json
from .evidence_paths import relative_evidence_path
from .execution import check_cancel


POLICY = {
    "version": "native-circle-character-two-engine-finite-views-v2",
    "Tesseract_psm": 10,
    "external_white_padding_px": 4,
    "fallback_Tesseract_nearest_neighbor_scale": 2,
    "fallback_Tesseract_external_padding_px": 16,
    "fallback_model_external_padding_px": 0,
    "maximum_views_per_engine": 2,
    "Tesseract_glyph_bbox_tolerance_source_px": 1.0,
    "fallback_only_after_initial_pair_not_accepted": True,
    "any_high_confidence_raw_conflict_blocks_adoption": True,
    "minimum_word_confidence": 85.0,
    "minimum_numeric_word_confidence": 95.0,
    "model_mean_confidence_minimum": 0.98,
    "model_emitted_character_confidence_minimum": 0.95,
    "minimum_glyph_height_px": 8,
    "maximum_glyph_height_px": 70,
    "maximum_raw_characters": 1,
    "required_engine_families": ["Tesseract", "PP-OCR"],
    "source_pixels_modified": False,
    "external_padding_replaces_source_pixels": False,
    "case_or_expected_answer_input": False,
    "same_raw_input_recognized_once_via_observation_cache": True,
    "ambiguous_unresolved_classes": ["I", "l", "1", "O", "0"],
}

_RECOGNIZER = None


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_record(path, root):
    path = Path(path)
    return {
        "path": relative_evidence_path(path, root),
        "sha256": _sha(path.read_bytes()),
    }


def _read_record(root, record):
    name = record.get("path")
    if not isinstance(name, str) or "\\" in name:
        raise ValueError("CHARACTER_RAW_EVIDENCE_PATH_INVALID")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("CHARACTER_RAW_EVIDENCE_OUTSIDE_JOB")
    root = Path(root).resolve()
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
        raise ValueError("CHARACTER_RAW_EVIDENCE_MISSING_OR_OUTSIDE_JOB")
    data = path.read_bytes()
    if _sha(data) != record.get("sha256"):
        raise ValueError("CHARACTER_RAW_EVIDENCE_HASH_CHANGED")
    return data


def _glyph_source(gray, roi, evidence):
    box = evidence.get("glyph_bbox_xyxy_px")
    if (
        not isinstance(box, (list, tuple))
        or len(box) != 4
        or any(isinstance(v, bool) or not isinstance(v, int) for v in box)
    ):
        raise ValueError("CIRCLE_INTERIOR_GLYPH_BBOX_MISSING")
    x0, y0, x1, y1 = box
    if not (
        roi[0] <= x0 < x1 <= roi[2]
        and roi[1] <= y0 < y1 <= roi[3]
        and 0 <= x0 < x1 <= gray.shape[1]
        and 0 <= y0 < y1 <= gray.shape[0]
    ):
        raise ValueError("CIRCLE_INTERIOR_GLYPH_OUTSIDE_SOURCE")
    if not evidence.get("interior_is_complete_separate_components"):
        raise ValueError("CIRCLE_INTERIOR_NOT_COMPLETE_SEPARATE_SOURCE")
    crop = np.ascontiguousarray(gray[y0:y1, x0:x1], dtype=np.uint8)
    support = np.zeros(crop.shape, dtype=bool)
    runs = evidence.get("interior_support_runs_y_x0_x1", [])
    if not runs:
        raise ValueError("CIRCLE_INTERIOR_NO_GLYPH_SOURCE")
    for run in runs:
        if len(run) != 3 or any(isinstance(v, bool) or not isinstance(v, int) for v in run):
            raise ValueError("CIRCLE_INTERIOR_SOURCE_RUN_INVALID")
        y, a, b = run
        if not (y0 <= y < y1 and x0 <= a < b <= x1):
            raise ValueError("CIRCLE_INTERIOR_SOURCE_RUN_OUTSIDE_GLYPH")
        if support[y - y0, a - x0:b - x0].any():
            raise ValueError("CIRCLE_INTERIOR_SOURCE_RUN_DUPLICATED")
        support[y - y0, a - x0:b - x0] = True
    threshold = int(evidence.get("policy", {}).get("source_threshold", 128))
    if not np.array_equal(support, crop < threshold):
        raise ValueError("CIRCLE_INTERIOR_BBOX_CONTAINS_UNBOUND_INK")
    ys, xs = np.nonzero(support)
    if (
        not len(xs)
        or [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        != [0, 0, crop.shape[1], crop.shape[0]]
    ):
        raise ValueError("CIRCLE_INTERIOR_GLYPH_BBOX_NOT_COMPLETE_TIGHT_SOURCE")
    if not POLICY["minimum_glyph_height_px"] <= crop.shape[0] <= POLICY["maximum_glyph_height_px"]:
        raise ValueError("CIRCLE_INTERIOR_GLYPH_SIZE_UNRESOLVED")
    return crop, list(box)


def _finite_score(value, maximum):
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and 0 <= value <= maximum
    )


def _raw_tsv_integrity(raw):
    """A malformed word cannot vanish in the shared permissive TSV parser.

    Inspect every nonempty word before that parser drops invalid geometry or
    strips text. Reject the raw view without rewriting any recorded fields.
    """
    try:
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
        )
        fields = reader.fieldnames or []
        required = {"level", "left", "top", "width", "height", "conf", "text"}
        if not required.issubset(fields) or len(fields) != len(set(fields)):
            return False
        for row in reader:
            if None in row or row.get("level") not in {"1", "2", "3", "4", "5"}:
                return False
            text = row.get("text") or ""
            if row["level"] == "5" and text.strip():
                x, y, width, height = [
                    int(row[key]) for key in ("left", "top", "width", "height")
                ]
                if (
                    x < 0 or y < 0 or width <= 0 or height <= 0
                    or not all(math.isfinite(float(v)) for v in (x, y, width, height))
                    or text != text.strip()
                ):
                    return False
                if not _finite_score(float(row["conf"]), 100):
                    return False
                for key in ("page_num", "block_num", "par_num", "line_num", "word_num"):
                    if key in row and int(row[key]) < 0:
                        return False
        return True
    except (ValueError, TypeError, OverflowError, UnicodeError, csv.Error):
        return False


def _tesseract_confident(words):
    return bool(words) and all(
        _finite_score(word.get("confidence"), 100)
        and word["confidence"] >= (
            POLICY["minimum_numeric_word_confidence"]
            if word.get("text", "").isdigit() else POLICY["minimum_word_confidence"]
        )
        for word in words
    )


def _model_integrity(model):
    tokens = model.get("raw_CTC_tokens", [])
    scores = [token.get("score") for token in tokens]
    mean, minimum = model.get("model_mean_confidence"), model.get("minimum_emitted_character_confidence")
    if not tokens:
        return model.get("raw_text") == "" and mean is None and minimum is None
    if (
        not scores or not all(_finite_score(score, 1) for score in scores)
        or not _finite_score(mean, 1) or not _finite_score(minimum, 1)
        or abs(mean - sum(scores) / len(scores)) > 1e-7
        or abs(minimum - min(scores)) > 1e-7
        or model.get("raw_text") != "".join(t.get("character", "") for t in tokens)
    ):
        return False
    return True


def _model_confident(model):
    return (
        _model_integrity(model) and bool(model.get("raw_CTC_tokens"))
        and model["model_mean_confidence"] >= POLICY["model_mean_confidence_minimum"]
        and model["minimum_emitted_character_confidence"] >= POLICY["model_emitted_character_confidence_minimum"]
    )


def _single_character(text):
    return isinstance(text, str) and len(text) == 1 and text.isascii() and text.isalnum()


def _full_glyph_word(words, box):
    if len(words) != 1 or not _single_character(words[0].get("text")) or not _tesseract_confident(words):
        return False
    measured = words[0].get("bbox_xyxy_px", [])
    return (
        len(measured) == 4
        and all(math.isfinite(float(v)) for v in measured)
        and max(abs(float(a) - float(b)) for a, b in zip(measured, box))
        <= POLICY["Tesseract_glyph_bbox_tolerance_source_px"]
    )


def _decision(tesseract_views, model_views, box):
    full_tesseract = {
        view["words"][0]["text"] for view in tesseract_views
        if _full_glyph_word(view["words"], box)
    }
    full_model = {
        view["prediction"]["raw_text"] for view in model_views
        if _model_confident(view["prediction"])
        and _single_character(view["prediction"].get("raw_text"))
        and len(view["prediction"]["raw_CTC_tokens"]) == 1
    }
    strong = {
        " ".join(w.get("text", "") for w in view["words"])
        for view in tesseract_views if _tesseract_confident(view["words"])
    } | {
        view["prediction"].get("raw_text", "")
        for view in model_views if _model_confident(view["prediction"])
    }
    common = full_tesseract & full_model
    reasons = []
    if any(view.get("raw_tsv_integrity") is False for view in tesseract_views):
        reasons.append("TESSERACT_RAW_TSV_INVALID_WORD_SCORE_OR_STRUCTURE")
    if any(not _model_integrity(view["prediction"]) for view in model_views):
        reasons.append("MODEL_RAW_CHARACTER_SCORE_OR_TOKEN_INCONSISTENCY")
    if any(not _finite_score(word.get("confidence"), 100)
           for view in tesseract_views for word in view["words"]):
        reasons.append("TESSERACT_RAW_SCORE_NONFINITE_OR_OUT_OF_RANGE")
    if not full_tesseract:
        reasons.append("TESSERACT_NO_CONFIDENT_COMPLETE_SOURCE_CHARACTER")
    if not full_model:
        reasons.append("PP_OCR_NO_CONFIDENT_COMPLETE_SINGLE_CHARACTER")
    if len(common) != 1:
        reasons.append("INDEPENDENT_ENGINES_NO_UNIQUE_COMPLETE_CHARACTER_CONSENSUS")
    if len(strong) > 1:
        reasons.append("HIGH_CONFIDENCE_RAW_OBSERVATIONS_CONFLICT")
    text = next(iter(common)) if len(common) == 1 else None
    if text in POLICY["ambiguous_unresolved_classes"]:
        reasons.append("CHARACTER_CLASS_NEEDS_ADDITIONAL_SOURCE_DISCRIMINATION")
    return {
        "accepted": not reasons, "text": text if not reasons else None,
        "reasons": reasons,
        "Tesseract_raw_texts": [" ".join(w.get("text", "") for w in v["words"]) for v in tesseract_views],
        "PP_OCR_raw_texts": [v["prediction"].get("raw_text", "") for v in model_views],
        "Tesseract_complete_confident_characters": sorted(full_tesseract),
        "PP_OCR_complete_confident_characters": sorted(full_model),
        "high_confidence_raw_strings": sorted(strong),
    }


def _view_input(crop, scale, padding):
    image = np.repeat(np.repeat(crop, scale, axis=0), scale, axis=1)
    return image, np.pad(image, padding, mode="constant", constant_values=255)


def _map_tesseract_words(words, box, scale):
    if scale == 1:
        return words
    mapped = []
    for word in words:
        item = dict(word)
        a, b, c, d = word["bbox_xyxy_px"]
        item["bbox_xyxy_px"] = [box[0] + a / scale, box[1] + b / scale,
                                 box[0] + c / scale, box[1] + d / scale]
        mapped.append(item)
    return mapped


def _producer_identity():
    return {
        "module": __name__, "sha256": _sha(Path(__file__).read_bytes()),
        "Tesseract_producer_sha256": _sha(Path(base.__file__).read_bytes()),
        "model_producer_sha256": _sha(Path(independent.__file__).read_bytes()),
    }


def recognize_circle_character(
    gray, roi, row, output_dir, *, dpi=200, recognizer=None, evidence_root=None
):
    """Use one initial pair, then at most one justified normalized view per engine."""
    global _RECOGNIZER
    check_cancel("CIRCULAR_MARKER_CHARACTER")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(evidence_root) if evidence_root is not None else output
    source = row["source_evidence"]
    try:
        crop, box = _glyph_source(gray, roi, source)
    except ValueError as exc:
        result = {
            "accepted": False, "text_geometry": None, "evidence": None,
            "reasons": [str(exc)], "new_Tesseract_calls": 0, "new_model_calls": 0,
        }
        save_json(output / "character_result.json", result)
        return result
    engine = base._resolve_tesseract(os.environ.get("I2CAD_TESSERACT", ""), os.environ.get("TESSDATA_PREFIX"))
    save_json(output / "policy_frozen_before_recognition.json", {"policy": POLICY, "engine": engine})
    if recognizer is None:
        if _RECOGNIZER is None:
            _RECOGNIZER = independent.IndependentRecognizer()
        recognizer = _RECOGNIZER
    model_identity_path = output / "model_identity.json"
    save_json(model_identity_path, recognizer.identity)
    tesseract_views, model_views = [], []

    def tesseract_view(name, scale, padding):
        normalized, actual_input = _view_input(crop, scale, padding)
        input_gray = gray if scale == 1 else normalized
        input_box = box if scale == 1 else [0, 0, normalized.shape[1], normalized.shape[0]]
        words, metadata = base._ocr(
            input_gray, input_box, POLICY["Tesseract_psm"], output, name, None,
            padding_px=padding, dpi=int(dpi) * scale,
        )
        words = _map_tesseract_words(words, box, scale)
        raw_valid = _raw_tsv_integrity((output / (name + ".tsv")).read_bytes())
        view = {
            "view": name, "normalization": {
                "source_bbox_xyxy_px": box, "pixel_scale": [scale, scale],
                "resampling": "NONE" if scale == 1 else "NEAREST_NEIGHBOR_REPEATED_SOURCE_SAMPLES",
                "external_white_padding_px": padding,
                "recognition_dpi": int(dpi) * scale,
                "recognition_input_array_sha256": _sha(actual_input.tobytes()),
                "original_source_modified": False,
            },
            "raw_tsv": _file_record(output / (name + ".tsv"), root),
            "metadata": _file_record(output / (name + ".json"), root),
            "recognition_image": _file_record(output / (name + ".png"), root),
            "words": words,
            "raw_tsv_integrity": raw_valid,
            "command_executed_for_this_request": bool(metadata.get("command_executed_for_this_request")),
        }
        tesseract_views.append(view)

    def model_view(name, padding):
        _, actual_input = _view_input(crop, 1, padding)
        prediction = recognizer.recognize(actual_input)
        path = output / (name + ".json")
        save_json(path, prediction)
        receipt = getattr(recognizer, "last_observation", {})
        model_views.append({
            "view": name, "normalization": {
                "source_bbox_xyxy_px": box, "external_white_padding_px": padding,
                "recognition_input_array_sha256": _sha(actual_input.tobytes()),
                "original_source_modified": False,
            },
            "prediction_file": _file_record(path, root), "prediction": prediction,
            "observation_receipt": receipt,
            "model_inference_executed_for_this_request": bool(receipt.get("model_inference_executed_for_this_request", True)),
        })

    tesseract_view("glyph-p10", 1, POLICY["external_white_padding_px"])
    model_view("model-padded", POLICY["external_white_padding_px"])
    initial = _decision(tesseract_views, model_views, box)
    if not initial["accepted"] and initial["reasons"] != ["CHARACTER_CLASS_NEEDS_ADDITIONAL_SOURCE_DISCRIMINATION"]:
        tesseract_view("glyph-x2-p10", POLICY["fallback_Tesseract_nearest_neighbor_scale"], POLICY["fallback_Tesseract_external_padding_px"])
        model_view("model-tight", POLICY["fallback_model_external_padding_px"])
    decision = _decision(tesseract_views, model_views, box)
    geometry = {
        "text": decision["text"], "x": box[0], "y": box[3],
        "height_px": box[3] - box[1], "width_px": box[2] - box[0],
        "rotation_deg_image": 0.0,
    } if decision["accepted"] else None
    evidence = {
        "schema": "native-circle-character-evidence-v2", "policy": POLICY,
        "source_bbox_xyxy_px": box,
        "source_crop_array_sha256": _sha(crop.tobytes()),
        "interior_support_sha256": _sha(json.dumps(source["interior_support_runs_y_x0_x1"], separators=(",", ":")).encode()),
        "source_pixels_modified": False, "recognition_dpi": int(dpi),
        "tesseract_views": tesseract_views, "ppocr_views": model_views,
        "model_identity": _file_record(model_identity_path, root),
        "initial_decision": initial, "decision": decision, "text_geometry": geometry,
        "producer": _producer_identity(),
        "new_Tesseract_calls": sum(v["command_executed_for_this_request"] for v in tesseract_views),
        "new_model_calls": sum(v["model_inference_executed_for_this_request"] for v in model_views),
        "expected_answers_provided": False, "raw_transcription_rewritten": False,
    }
    result = {
        "accepted": decision["accepted"], "text_geometry": geometry,
        "evidence": evidence, "reasons": decision["reasons"],
        "new_Tesseract_calls": evidence["new_Tesseract_calls"], "new_model_calls": evidence["new_model_calls"],
    }
    save_json(output / "character_result.json", result)
    return result


def replay_circle_character_observations(gray, roi, obj, evidence_root=None):
    """Recompute complete source and every raw observation, including rejections.

    A successful replay authenticates observations; it does not adopt a letter.
    The unchanged two-engine decision remains available to the separate source
    reference route and cannot be overwritten by that route.
    """
    result = {"pass": False, "new_OCR_calls": 0, "new_model_calls": 0}
    try:
        from .circular_markers import verify_circle_source_evidence
        ring = verify_circle_source_evidence(gray, roi, obj, evidence_root)
        if not ring.get("pass"):
            raise ValueError("CHARACTER_RING_AND_INTERIOR_SOURCE_NOT_VERIFIED")
        source = obj["source_evidence"]
        evidence = source["character_evidence"]
        if evidence_root is None or evidence.get("schema") != "native-circle-character-evidence-v2":
            raise ValueError("CHARACTER_RAW_EVIDENCE_ROOT_OR_SCHEMA_MISSING")
        if evidence.get("policy") != POLICY or evidence.get("producer") != _producer_identity():
            raise ValueError("CHARACTER_POLICY_OR_PRODUCER_IDENTITY_CHANGED")
        crop, box = _glyph_source(gray, roi, source)
        if (
            evidence.get("source_bbox_xyxy_px") != box
            or evidence.get("source_crop_array_sha256") != _sha(crop.tobytes())
            or evidence.get("interior_support_sha256") != _sha(json.dumps(source["interior_support_runs_y_x0_x1"], separators=(",", ":")).encode())
            or evidence.get("source_pixels_modified") is not False
            or evidence.get("expected_answers_provided") is not False
            or evidence.get("raw_transcription_rewritten") is not False
        ):
            raise ValueError("CHARACTER_ORIGINAL_SOURCE_BINDING_CHANGED")
        saved_t = evidence["tesseract_views"]
        saved_p = evidence["ppocr_views"]
        if not 1 <= len(saved_t) <= 2 or len(saved_t) != len(saved_p):
            raise ValueError("CHARACTER_FINITE_VIEW_COUNT_CHANGED")
        from PIL import Image
        from io import BytesIO

        t_views, p_views = [], []
        t_specs = [("glyph-p10", 1, POLICY["external_white_padding_px"]), ("glyph-x2-p10", 2, POLICY["fallback_Tesseract_external_padding_px"])]
        p_specs = [("model-padded", POLICY["external_white_padding_px"]), ("model-tight", POLICY["fallback_model_external_padding_px"])]
        for view, (name, scale, pad) in zip(saved_t, t_specs):
            normalized, actual_input = _view_input(crop, scale, pad)
            expected_box = box if scale == 1 else [0, 0, normalized.shape[1], normalized.shape[0]]
            raw = _read_record(evidence_root, view["raw_tsv"])
            raw_valid = _raw_tsv_integrity(raw)
            if not raw_valid or view.get("raw_tsv_integrity") is not True:
                raise ValueError("CHARACTER_TESSERACT_RAW_TSV_INVALID_WORD_SCORE_OR_STRUCTURE")
            meta = json.loads(_read_record(evidence_root, view["metadata"]))
            png = _read_record(evidence_root, view["recognition_image"])
            spec = meta["specification"]
            norm = view["normalization"]
            if (
                view.get("view") != name or norm.get("source_bbox_xyxy_px") != box
                or norm.get("pixel_scale") != [scale, scale]
                or norm.get("external_white_padding_px") != pad
                or norm.get("original_source_modified") is not False
                or norm.get("recognition_dpi") != evidence["recognition_dpi"] * scale
                or norm.get("recognition_input_array_sha256") != _sha(actual_input.tobytes())
                or meta.get("status") != "COMPLETED" or meta.get("return_code") != 0
                or meta.get("tsv_sha256") != _sha(raw) or meta.get("image_sha256") != _sha(png)
                or spec.get("crop_xyxy_px") != expected_box
                or spec.get("crop_array_sha256") != base.source_array_sha256(normalized)
                or spec.get("psm") != POLICY["Tesseract_psm"]
                or spec.get("external_white_padding_px") != pad or spec.get("language") != "eng"
                or spec.get("source_pixels_modified") is not False
                or spec.get("recognition_dpi") != evidence["recognition_dpi"] * scale
                or not np.array_equal(actual_input, np.asarray(Image.open(BytesIO(png)).convert("L")))
            ):
                raise ValueError("CHARACTER_TESSERACT_SOURCE_OR_NORMALIZATION_BINDING_CHANGED")
            origin = [expected_box[0] - pad, expected_box[1] - pad, expected_box[2] + pad, expected_box[3] + pad]
            words = base._parse_tsv(raw.decode("utf-8"), origin, name, POLICY["Tesseract_psm"])
            t_views.append({"words": _map_tesseract_words(words, box, scale),
                            "raw_tsv_integrity": raw_valid})
        identity = json.loads(_read_record(evidence_root, evidence["model_identity"]))
        if identity.get("model_sha256") != independent.MODEL_SHA256 or identity.get("policy") != independent.POLICY:
            raise ValueError("CHARACTER_INDEPENDENT_MODEL_IDENTITY_CHANGED")
        for view, (name, pad) in zip(saved_p, p_specs):
            _, actual_input = _view_input(crop, 1, pad)
            prediction = json.loads(_read_record(evidence_root, view["prediction_file"]))
            original, tensor = independent.prepare_model_input(actual_input)
            norm = view["normalization"]
            if (
                view.get("view") != name or norm.get("source_bbox_xyxy_px") != box
                or norm.get("external_white_padding_px") != pad or norm.get("original_source_modified") is not False
                or norm.get("recognition_input_array_sha256") != _sha(actual_input.tobytes())
                or prediction.get("input_array_sha256") != _sha(original.tobytes())
                or prediction.get("model_tensor_sha256") != _sha(tensor.tobytes())
                or prediction.get("raw_transcription_rewritten") is not False
                or prediction.get("source_geometry_modified") is not False
            ):
                raise ValueError("CHARACTER_INDEPENDENT_MODEL_SOURCE_BINDING_CHANGED")
            p_views.append({"prediction": prediction})
        initial = _decision(t_views[:1], p_views[:1], box)
        decision = _decision(t_views, p_views, box)
        if (
            decision != evidence.get("decision")
            or initial != evidence.get("initial_decision")
            or (initial["accepted"] and len(t_views) != 1)
        ):
            raise ValueError("CHARACTER_RAW_ENGINES_DO_NOT_CONFIRM_SAVED_TEXT")
        geometry = {
            "text": decision["text"], "x": box[0], "y": box[3],
            "height_px": box[3] - box[1], "width_px": box[2] - box[0], "rotation_deg_image": 0.0,
        } if decision["accepted"] else None
        if geometry != evidence.get("text_geometry"):
            raise ValueError("CHARACTER_ORIGINAL_DECISION_GEOMETRY_CHANGED")
        result.update({
            "pass": True, "source_bbox_xyxy_px": box, "text": decision["text"],
            "decision": decision, "text_geometry": geometry,
            "complete_source_raw_characters": sorted({
                view["words"][0]["text"] for view in t_views
                if len(view["words"]) == 1
                and _single_character(view["words"][0].get("text"))
                and len(view["words"][0].get("bbox_xyxy_px", [])) == 4
                and max(abs(float(a) - float(b)) for a, b in zip(
                    view["words"][0]["bbox_xyxy_px"], box
                )) <= POLICY["Tesseract_glyph_bbox_tolerance_source_px"]
            } | {
                view["prediction"]["raw_text"] for view in p_views
                if _single_character(view["prediction"].get("raw_text"))
                and len(view["prediction"].get("raw_CTC_tokens", [])) == 1
            }),
            "independent_engine_families": ["Tesseract", "PP-OCR"],
            "all_raw_artifacts_read_and_hashed": True,
            "Tesseract_views_replayed": len(t_views), "PP_OCR_views_replayed": len(p_views),
            "original_glyph_pixels_and_model_tensors_rechecked": True,
        })
    except (KeyError, TypeError, ValueError, OSError) as exc:
        result["reason"] = str(exc)
    return result


def verify_circle_character_evidence(gray, roi, obj, evidence_root=None):
    """Cold verify the actual TEXT through its unchanged, source-bound route."""
    result = replay_circle_character_observations(gray, roi, obj, evidence_root)
    if not result.get("pass"):
        return result
    evidence = obj["source_evidence"]["character_evidence"]
    decision = result["decision"]
    if decision["accepted"]:
        if evidence.get("source_reference_resolution") is not None:
            return {**result, "pass": False, "reason": "STRICT_CHARACTER_CANNOT_REPLACE_ITS_ORIGINAL_ADOPTION_ROUTE"}
        geometry = result["text_geometry"]
        result["adoption_basis"] = "STRICT_TWO_ENGINE_COMPLETE_SOURCE_CHARACTER"
    else:
        from .circle_glyph_resolution import verify_source_reference_resolution

        resolved = verify_source_reference_resolution(gray, roi, obj, evidence_root, result)
        if not resolved.get("pass"):
            return {**result, "pass": False, "reason": resolved.get("reason", "CHARACTER_RAW_ENGINES_DO_NOT_CONFIRM_SAVED_TEXT")}
        geometry = resolved["text_geometry"]
        result.update(
            text=geometry["text"],
            text_geometry=geometry,
            adoption_basis="SAME_SOURCE_FROZEN_GLYPH_REFERENCES",
            source_reference_resolution_recomputed=True,
            source_reference_verification=resolved,
        )
    if geometry != obj["geometry"].get("text_geometry"):
        return {**result, "pass": False, "reason": "CHARACTER_SAVED_GEOMETRY_OR_CONTENT_CHANGED"}
    return result
