"""Apply an explicit, separately accounted source review to saved OCR data.

This is a data adapter, not recognition.  It never changes an automatic text,
word, confidence, completeness flag, unresolved reason, or group membership.
New values live only under ``source_review``.  Manual/assistant transcription
is recorded as such and cannot be credited as an automatic OCR improvement.

Manifest schema ``native_source_review_v1``:
  source_sha256, upstream_text:{path,sha256,producer_module,producer_sha256},
  reviewer:{id,kind:'human'|'assistant'}, method, reviews:[...].
Each review supplies region_id, action, and evidence:[{path,sha256,
bbox_xyxy_px,kind:'native_source_crop'}].  Evidence must exactly match the
declared original-resolution crop.  Optional base_dir resolves relative paths.

Actions:
* approve_unchanged_candidate: text equals the existing region string exactly.
* select_cached_alternative: ocr_references name saved JSON observations by
  path + sha256 + id + source_sha256; chosen text is their unchanged tokens.
* reviewed_transcription: text is explicitly entered from source review.
An optional bbox_xyxy_px is always counted as an explicit geometry input.
"""

from __future__ import annotations

import copy
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import time


SCHEMA = "native_source_review_v1"
COORDINATES = "source_pixels_top_left"
ACTIONS = {
    "approve_unchanged_candidate",
    "select_cached_alternative",
    "reviewed_transcription",
}
PRODUCERS = {
    "app.native_objects.text_regions": "text_regions.py",
    "app.native_objects.text_line_domains": "text_line_domains.py",
    "app.native_objects.source_review": "source_review.py",
}


class SourceReviewError(ValueError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _resolve(value, directory):
    if not isinstance(value, str) or not value:
        raise SourceReviewError("EXPLICIT_ARTIFACT_PATH_REQUIRED")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (directory / path).resolve()


def _verify_hash(path, expected, label):
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in expected)
    ):
        raise SourceReviewError("FULL_SHA256_REQUIRED:" + label)
    actual = _sha(path)
    if actual != expected.lower():
        raise SourceReviewError("ARTIFACT_HASH_MISMATCH:" + label)
    return actual


def _box(value, size, label, integer=False):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SourceReviewError("BBOX_XYXY_REQUIRED:" + label)
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in value
    ):
        raise SourceReviewError("BBOX_VALUES_INVALID:" + label)
    if integer and any(int(v) != v for v in value):
        raise SourceReviewError("NATIVE_CROP_REQUIRES_INTEGER_PIXELS:" + label)
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise SourceReviewError("BBOX_OUTSIDE_SOURCE:" + label)
    return [int(v) for v in value] if integer else list(value)


def _inside(a, b):
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def _area(a):
    return max(0, a[2] - a[0]) * max(0, a[3] - a[1])


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _overlap(a, b):
    return _intersection(a, b) / max(1.0, min(_area(a), _area(b)))


def _union(boxes):
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _median(values):
    values = sorted(values)
    n = len(values)
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def _text_value(value, label):
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise SourceReviewError("EXPLICIT_NONEMPTY_SINGLE_LINE_TEXT_REQUIRED:" + label)
    return value


def _reviewer(entry, manifest):
    reviewer = entry.get("reviewer", manifest.get("reviewer"))
    if (
        not isinstance(reviewer, dict)
        or not isinstance(reviewer.get("id"), str)
        or not reviewer["id"].strip()
        or reviewer.get("kind") not in ("human", "assistant")
    ):
        raise SourceReviewError("EXPLICIT_HUMAN_OR_ASSISTANT_REVIEWER_REQUIRED")
    method = entry.get("method", manifest.get("method"))
    if not isinstance(method, str) or not method.strip():
        raise SourceReviewError("SOURCE_REVIEW_METHOD_REQUIRED")
    return copy.deepcopy(reviewer), method


def _change_record(old, new):
    changes = []
    inserted = deleted = substituted = 0
    for tag, a, b, c, d in SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        old_piece, new_piece = old[a:b], new[c:d]
        changes.append(
            {
                "operation": tag,
                "old_range": [a, b],
                "new_range": [c, d],
                "old_characters": old_piece,
                "new_characters": new_piece,
            }
        )
        if tag == "replace":
            substituted += min(len(old_piece), len(new_piece))
            inserted += max(0, len(new_piece) - len(old_piece))
            deleted += max(0, len(old_piece) - len(new_piece))
        elif tag == "insert":
            inserted += len(new_piece)
        elif tag == "delete":
            deleted += len(old_piece)
    return {
        "old_text": old,
        "reviewed_text": new,
        "text_changed": old != new,
        "character_diff": changes,
        "inserted_codepoints": inserted,
        "deleted_codepoints": deleted,
        "substituted_codepoints": substituted,
        "count_scope": "deterministic string differences, not measured typing or clicks",
    }


def _geometry(box, rotation=0.0):
    return {
        "bbox_xyxy_px": list(box),
        "x": box[0],
        "y": box[3],
        "height_px": box[3] - box[1],
        "width_px": box[2] - box[0],
        "rotation_deg_image": rotation,
        "coordinate_system": COORDINATES,
        "frame_or_wall_geometry_not_approved_by_this_text_review": True,
    }


def _load_observation(reference, directory, source_sha, size):
    if not isinstance(reference, dict):
        raise SourceReviewError("OCR_REFERENCE_OBJECT_REQUIRED")
    path = _resolve(reference.get("path"), directory)
    digest = _verify_hash(path, reference.get("sha256"), "OCR_OBSERVATIONS")
    if reference.get("source_sha256") != source_sha:
        raise SourceReviewError("OCR_REFERENCE_SOURCE_SHA_MISMATCH")
    observation_id = reference.get("id")
    if not isinstance(observation_id, str) or not observation_id:
        raise SourceReviewError("SAVED_OCR_OBSERVATION_ID_REQUIRED")
    document = json.loads(path.read_text())
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict) and isinstance(document.get("observations"), list):
        rows = document["observations"]
        declared = document.get(
            "source_sha256", document.get("encoded_original_source_sha256")
        )
        if declared is not None and declared != source_sha:
            raise SourceReviewError("OBSERVATION_DOCUMENT_SOURCE_MISMATCH")
    else:
        raise SourceReviewError("SAVED_OCR_OBSERVATION_LIST_REQUIRED")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("id") == observation_id
    ]
    if len(matches) != 1:
        raise SourceReviewError("OCR_OBSERVATION_ID_NOT_UNIQUE_OR_MISSING")
    row = matches[0]
    text = _text_value(row.get("text"), observation_id)
    box = _box(row.get("bbox_xyxy_px"), size, observation_id)
    confidence = row.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
    ):
        raise SourceReviewError("SAVED_OCR_OBSERVATION_CONFIDENCE_MISSING")
    return {
        "path": str(path),
        "sha256": digest,
        "id": observation_id,
        "source_sha256": source_sha,
        "text": text,
        "bbox_xyxy_px": box,
        "confidence": confidence,
        "context_id": row.get("context_id", row.get("tile_id")),
        "psm": row.get("psm"),
        "saved_observation_unchanged": copy.deepcopy(row),
    }


def _resolve_action(region, entry, directory, source_sha, size):
    action = entry.get("action")
    if action not in ACTIONS:
        raise SourceReviewError("UNKNOWN_SOURCE_REVIEW_ACTION")
    selected = []
    original_box = _box(region["bbox_xyxy_px"], size, region["id"])
    if action == "approve_unchanged_candidate":
        text = _text_value(entry.get("text"), region["id"])
        if text != region["text"]:
            raise SourceReviewError("UNCHANGED_APPROVAL_CANNOT_REWRITE_TEXT")
        automatic_box = original_box
    elif action == "select_cached_alternative":
        references = entry.get("ocr_references")
        if not isinstance(references, list) or not references:
            raise SourceReviewError(
                "CACHED_SELECTION_REQUIRES_SAVED_OBSERVATION_REFERENCES"
            )
        selected = [
            _load_observation(ref, directory, source_sha, size) for ref in references
        ]
        unique = {(word["path"], word["id"]) for word in selected}
        if len(unique) != len(selected):
            raise SourceReviewError("DUPLICATE_CACHED_OBSERVATION_SELECTION")
        for word in selected:
            if _overlap(word["bbox_xyxy_px"], original_box) < 0.60:
                raise SourceReviewError(
                    "CACHED_OBSERVATION_DOES_NOT_LOCATE_TO_TARGET_REGION"
                )
        selected.sort(
            key=lambda word: (
                word["bbox_xyxy_px"][0],
                word["bbox_xyxy_px"][1],
                word["id"],
            )
        )
        automatic_box = _union([word["bbox_xyxy_px"] for word in selected])
        iou = _intersection(automatic_box, original_box) / max(
            1.0,
            _area(automatic_box)
            + _area(original_box)
            - _intersection(automatic_box, original_box),
        )
        if iou < 0.60:
            raise SourceReviewError(
                "CACHED_SELECTION_COVERS_ONLY_A_DIFFERENT_OR_PARTIAL_REGION"
            )
        heights = [w["bbox_xyxy_px"][3] - w["bbox_xyxy_px"][1] for w in selected]
        baselines = [w["bbox_xyxy_px"][3] for w in selected]
        if max(baselines) - min(baselines) > 0.5 * max(heights):
            raise SourceReviewError("CACHED_WORDS_ARE_NOT_ONE_SOURCE_LINE")
        text = " ".join(word["text"] for word in selected)
        if "text" in entry and entry["text"] != text:
            raise SourceReviewError("CACHED_SELECTION_TEXT_DIFFERS_FROM_SAVED_TOKENS")
    else:
        text = _text_value(entry.get("text"), region["id"])
        automatic_box = original_box
    explicit_box = "bbox_xyxy_px" in entry
    box = (
        _box(entry["bbox_xyxy_px"], size, region["id"] + "/review_box")
        if explicit_box
        else list(automatic_box)
    )
    scope_boxes = [original_box]
    for key in ("discovery_bbox_xyxy_px", "inspection_bbox_xyxy_px"):
        if region.get(key):
            scope_boxes.append(_box(region[key], size, region["id"] + "/" + key))
    if max(_overlap(box, scope) for scope in scope_boxes) < 0.60:
        raise SourceReviewError("REVIEW_BOX_DOES_NOT_LOCATE_TO_EXISTING_REGION")
    rotation = entry.get("rotation_deg_image", 0.0)
    if (
        isinstance(rotation, bool)
        or not isinstance(rotation, (int, float))
        or not math.isfinite(rotation)
    ):
        raise SourceReviewError("REVIEW_ROTATION_INVALID")
    accounting = {
        "review_decision_records": 1,
        "transcription_value_inputs": int(action == "reviewed_transcription"),
        "transcription_codepoints_supplied": len(text)
        if action == "reviewed_transcription"
        else 0,
        "cached_observation_selections": len(selected),
        "explicit_bbox_value_inputs": int(explicit_box),
        "explicit_bbox_coordinate_values_supplied": 4 if explicit_box else 0,
        "explicit_rotation_value_inputs": int("rotation_deg_image" in entry),
        "new_automatic_OCR_calls": 0,
        "automatic_recognition_credit": 0,
        "human_clicks": "NOT_MEASURED",
        "human_time": "NOT_MEASURED",
        "count_scope": "explicit review manifest input records, not GUI click or typing measurements",
    }
    return text, _geometry(box, float(rotation)), selected, accounting


def _verify_evidence(
    entry, directory, source_gray, source_sha, original_box, review_box
):
    from PIL import Image

    evidence = entry.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise SourceReviewError("PER_REVIEW_SOURCE_IMAGE_EVIDENCE_REQUIRED")
    verified = []
    for item in evidence:
        if (
            not isinstance(item, dict)
            or item.get("kind", "native_source_crop") != "native_source_crop"
        ):
            raise SourceReviewError("ORIGINAL_RESOLUTION_SOURCE_CROP_REQUIRED")
        path = _resolve(item.get("path"), directory)
        digest = _verify_hash(path, item.get("sha256"), "SOURCE_REVIEW_IMAGE")
        if item.get("source_sha256", source_sha) != source_sha:
            raise SourceReviewError("REVIEW_IMAGE_DECLARED_SOURCE_MISMATCH")
        box = _box(item.get("bbox_xyxy_px"), source_gray.size, "evidence", integer=True)
        if item.get("pixel_scale", [1, 1]) != [1, 1]:
            raise SourceReviewError("REVIEW_REQUIRES_NATIVE_CROP_NOT_RESCALED_PREVIEW")
        with Image.open(path) as im:
            actual = im.convert("L")
            expected = source_gray.crop(tuple(box))
            if actual.size != expected.size or actual.tobytes() != expected.tobytes():
                raise SourceReviewError(
                    "REVIEW_IMAGE_PIXELS_DO_NOT_MATCH_DECLARED_SOURCE_CROP"
                )
        verified.append(
            {
                "path": str(path),
                "sha256": digest,
                "bbox_xyxy_px": box,
                "source_sha256": source_sha,
                "pixel_scale": [1, 1],
                "original_source_pixels_match": True,
            }
        )
    if not any(_inside(review_box, item["bbox_xyxy_px"]) for item in verified):
        raise SourceReviewError("EVIDENCE_DOES_NOT_SHOW_COMPLETE_REVIEWED_TEXT_BOX")
    if not any(
        _intersection(original_box, item["bbox_xyxy_px"]) > 0 for item in verified
    ):
        raise SourceReviewError("EVIDENCE_DOES_NOT_LOCATE_TO_ORIGINAL_REGION")
    return verified


def _automatic_view(data):
    view = {
        "regions": copy.deepcopy(data["regions"]),
        "groups": copy.deepcopy(data["groups"]),
    }
    for row in view["regions"] + view["groups"]:
        row.pop("source_review", None)
    return view


def _review_groups(result):
    regions = {row["id"]: row for row in result["regions"]}
    reviewed_groups = []
    for group in result["groups"]:
        rows = [regions[rid] for rid in group["region_ids"]]
        if not any("source_review" in row for row in rows):
            continue
        if "source_review" in group:
            raise SourceReviewError("EXISTING_GROUP_REVIEW_REQUIRES_EXPLICIT_REVISION")
        effective = []
        for row in rows:
            review = row.get("source_review")
            effective.append(
                {
                    "region_id": row["id"],
                    "text": review["text"] if review else row["text"],
                    "geometry": copy.deepcopy(review["geometry"])
                    if review
                    else _geometry(row["bbox_xyxy_px"]),
                    "accepted": review["accepted"]
                    if review
                    else bool(row.get("complete")),
                    "origin": review["action"]
                    if review
                    else "unchanged_automatic_region",
                    "automatic_complete_unchanged": row.get("complete"),
                    "explicit_review_present": review is not None,
                }
            )
        box = _union([line["geometry"]["bbox_xyxy_px"] for line in effective])
        heights = [line["geometry"]["height_px"] for line in effective]
        geometry = _geometry(box)
        if len(effective) > 1:
            tops = [line["geometry"]["bbox_xyxy_px"][1] for line in effective]
            geometry.update(
                x=box[0],
                y=box[1],
                height_px=_median(heights),
                line_pitch_px=_median([b - a for a, b in zip(tops, tops[1:])]),
                lines=[line["text"] for line in effective],
                geometry_type="MTEXT",
            )
        else:
            geometry["geometry_type"] = "TEXT"
            geometry["rotation_deg_image"] = effective[0]["geometry"][
                "rotation_deg_image"
            ]
        text = "\n".join(line["text"] for line in effective)
        review = {
            "accepted": all(line["accepted"] for line in effective),
            "text": text,
            "geometry": geometry,
            "lines": effective,
            "region_ids": list(group["region_ids"]),
            "original_automatic_text": group["text"],
            "original_automatic_complete": group.get("complete"),
            "original_automatic_unresolved_reasons": copy.deepcopy(
                group.get("unresolved_reasons", [])
            ),
            "automatic_fields_or_membership_changed": False,
            "recognition_credit": "SOURCE_REVIEW_BRANCH_ONLY_NOT_NEW_AUTOMATIC_RECOGNITION",
            "contains_entered_transcription": any(
                line["origin"] == "reviewed_transcription" for line in effective
            ),
            "all_lines_resolved_for_review_branch": all(
                line["accepted"] for line in effective
            ),
        }
        group["source_review"] = review
        reviewed_groups.append({"group_id": group["id"], **review})
    return reviewed_groups


def _producer_dependency(upstream, data):
    module = upstream.get("producer_module")
    expected = upstream.get("producer_sha256")
    if module not in PRODUCERS:
        raise SourceReviewError("UPSTREAM_TEXT_PRODUCER_NOT_ALLOWED")
    path = Path(__file__).with_name(PRODUCERS[module])
    _verify_hash(path, expected, "UPSTREAM_PRODUCER")
    rows = [{"module": module, "sha256": expected}]
    dependencies = upstream.get(
        "dependency_producers", data.get("producer", {}).get("dependencies", [])
    )
    if isinstance(dependencies, dict):
        dependencies = [
            {"module": name, "sha256": digest} for name, digest in dependencies.items()
        ]
    for dependency in dependencies:
        name = dependency["module"]
        if name not in PRODUCERS:
            raise SourceReviewError("UPSTREAM_DEPENDENCY_NOT_ALLOWED")
        _verify_hash(
            Path(__file__).with_name(PRODUCERS[name]),
            dependency["sha256"],
            "UPSTREAM_DEPENDENCY",
        )
        if not any(row["module"] == name for row in rows):
            rows.append({"module": name, "sha256": dependency["sha256"]})
    return rows


def apply_source_review(text_data, manifest, source_path, out):
    """Validate and append explicit source-review fields; never run OCR/CAD.

    ``manifest`` may be a JSON path or a dictionary.  Relative paths resolve
    against manifest.base_dir, then its file directory (or cwd for a dict).
    The function writes a new completed_text + producer manifest, suitable for
    a separately labelled review-assisted downstream branch.
    """
    from PIL import Image

    started = time.perf_counter()
    if isinstance(manifest, (str, Path)):
        manifest_path = Path(manifest).resolve()
        manifest_data = json.loads(manifest_path.read_text())
        default_directory = manifest_path.parent
        manifest_file_sha = _sha(manifest_path)
    elif isinstance(manifest, dict):
        manifest_data = copy.deepcopy(manifest)
        manifest_path, manifest_file_sha = None, None
        default_directory = Path.cwd()
    else:
        raise SourceReviewError("REVIEW_MANIFEST_MUST_BE_DATA_OR_JSON_PATH")
    if manifest_data.get("schema") != SCHEMA:
        raise SourceReviewError("SOURCE_REVIEW_MANIFEST_SCHEMA_MISMATCH")
    directory = (
        _resolve(manifest_data["base_dir"], default_directory)
        if manifest_data.get("base_dir")
        else default_directory
    )
    source_path = Path(source_path).resolve()
    source_sha = _verify_hash(
        source_path, manifest_data.get("source_sha256"), "ORIGINAL_SOURCE"
    )
    upstream = manifest_data.get("upstream_text")
    if not isinstance(upstream, dict):
        raise SourceReviewError("UPSTREAM_TEXT_FILE_AND_HASH_REQUIRED")
    upstream_path = _resolve(upstream.get("path"), directory)
    upstream_sha = _verify_hash(upstream_path, upstream.get("sha256"), "UPSTREAM_TEXT")
    saved = json.loads(upstream_path.read_text())
    if _digest(saved) != _digest(text_data):
        raise SourceReviewError("PASSED_TEXT_DIFFERS_FROM_HASHED_SAVED_RESULT")
    dependencies = _producer_dependency(upstream, text_data)
    if text_data.get("coordinate_system") != COORDINATES:
        raise SourceReviewError("SOURCE_TEXT_COORDINATE_SYSTEM_MISMATCH")
    with Image.open(source_path) as im:
        if getattr(im, "n_frames", 1) != 1:
            raise SourceReviewError("SINGLE_SOURCE_FRAME_REQUIRED")
        source_gray = im.convert("L")
    if list(source_gray.size) != list(text_data.get("source_size_px", [])):
        raise SourceReviewError("SOURCE_SIZE_DOES_NOT_MATCH_TEXT_DATA")
    source_array_sha = hashlib.sha256(source_gray.tobytes()).hexdigest()
    if source_array_sha != text_data.get("source_array_sha256"):
        raise SourceReviewError("SOURCE_GRAY_SAMPLES_DO_NOT_MATCH_TEXT_DATA")
    roi = _box(text_data.get("roi_xyxy_px"), source_gray.size, "ROI", integer=True)
    if (
        manifest_data.get("roi_xyxy_px", roi) != roi
        or manifest_data.get("coordinate_system", COORDINATES) != COORDINATES
    ):
        raise SourceReviewError("REVIEW_MANIFEST_SOURCE_COORDINATES_MISMATCH")
    entries = manifest_data.get("reviews")
    if not isinstance(entries, list) or not entries:
        raise SourceReviewError("EXPLICIT_NONEMPTY_REVIEW_LIST_REQUIRED")
    result = copy.deepcopy(text_data)
    by_id = {row["id"]: row for row in result["regions"]}
    if len(by_id) != len(result["regions"]):
        raise SourceReviewError("DUPLICATE_AUTOMATIC_REGION_ID")
    before_digest = _digest(_automatic_view(text_data))
    seen, decisions = set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            raise SourceReviewError("REVIEW_ENTRY_MUST_BE_OBJECT")
        rid = entry.get("region_id")
        if rid not in by_id or rid in seen:
            raise SourceReviewError("UNKNOWN_OR_DUPLICATE_REVIEW_REGION")
        seen.add(rid)
        region = by_id[rid]
        if "source_review" in region:
            raise SourceReviewError("EXISTING_REGION_REVIEW_REQUIRES_EXPLICIT_REVISION")
        reviewer, method = _reviewer(entry, manifest_data)
        text, geometry, alternatives, accounting = _resolve_action(
            region, entry, directory, source_sha, source_gray.size
        )
        evidence = _verify_evidence(
            entry,
            directory,
            source_gray,
            source_sha,
            region["bbox_xyxy_px"],
            geometry["bbox_xyxy_px"],
        )
        accepted = entry.get("accepted", True)
        if not isinstance(accepted, bool):
            raise SourceReviewError("REVIEW_ACCEPTED_MUST_BE_EXPLICIT_BOOLEAN")
        if accepted and not _inside(geometry["bbox_xyxy_px"], roi):
            raise SourceReviewError("ACCEPTED_REVIEW_TEXT_CROSSES_REQUESTED_ROI")
        review = {
            "accepted": accepted,
            "action": entry["action"],
            "text": text,
            "geometry": geometry,
            "reviewer": reviewer,
            "method": method,
            "evidence": evidence,
            "source_sha256": source_sha,
            "upstream_text_sha256": upstream_sha,
            "selected_saved_OCR_observations": alternatives,
            "change_record": _change_record(region["text"], text),
            "input_accounting": accounting,
            "automatic_result_before_review": {
                "text": region["text"],
                "complete": region.get("complete"),
                "unresolved_reasons": copy.deepcopy(
                    region.get("unresolved_reasons", [])
                ),
                "word_confidences": [
                    {
                        "id": w.get("id"),
                        "text": w.get("text"),
                        "confidence": w.get("confidence"),
                    }
                    for w in region.get("words", [])
                ],
            },
            "automatic_fields_changed": False,
            "recognition_credit": "SOURCE_REVIEW_ONLY_NOT_NEW_AUTOMATIC_RECOGNITION",
            "transcription_origin": (
                reviewer["kind"] + "_source_review_entry"
                if entry["action"] == "reviewed_transcription"
                else "unchanged_saved_OCR_value_selected_or_approved_by_source_review"
            ),
            "CAD_geometry_and_GUI_acceptance_not_proven": True,
        }
        if entry.get("notes") is not None:
            review["notes"] = str(entry["notes"])
        region["source_review"] = review
        decisions.append({"region_id": rid, **copy.deepcopy(review)})
    groups = _review_groups(result)
    if _digest(_automatic_view(result)) != before_digest:
        raise RuntimeError("AUTOMATIC_DATA_WAS_MODIFIED_BY_REVIEW_ADAPTER")
    if _sha(source_path) != source_sha or _sha(upstream_path) != upstream_sha:
        raise RuntimeError("SOURCE_OR_UPSTREAM_FILE_CHANGED_DURING_REVIEW")
    counts = {
        key: sum(row["input_accounting"][key] for row in decisions)
        for key in (
            "review_decision_records",
            "transcription_value_inputs",
            "transcription_codepoints_supplied",
            "cached_observation_selections",
            "explicit_bbox_value_inputs",
            "explicit_bbox_coordinate_values_supplied",
            "explicit_rotation_value_inputs",
        )
    }
    counts.update(
        new_automatic_OCR_calls=0,
        automatic_recognition_credit=0,
        human_clicks="NOT_MEASURED",
        human_time="NOT_MEASURED",
    )
    provenance = {
        "module": __name__,
        "sha256": _sha(__file__),
        "dependencies": dependencies,
        "source_sha256": source_sha,
        "source_array_sha256": source_array_sha,
        "upstream_text_path": str(upstream_path),
        "upstream_text_sha256": upstream_sha,
        "review_manifest_path": str(manifest_path) if manifest_path else None,
        "review_manifest_file_sha256": manifest_file_sha,
        "review_manifest_canonical_sha256": _digest(manifest_data),
        "automatic_candidate_generation_not_called": True,
        "source_cases_expected_answers_not_opened_by_adapter": True,
    }
    audit = {
        "schema": "applied_source_review_audit_v1",
        "producer": provenance,
        "source_sha256": source_sha,
        "upstream_text_sha256": upstream_sha,
        "decisions": decisions,
        "reviewed_groups": groups,
        "input_accounting": counts,
        "automatic_regions_and_groups_digest_before": before_digest,
        "automatic_regions_and_groups_digest_after_stripping_review": _digest(
            _automatic_view(result)
        ),
        "all_automatic_fields_unchanged": True,
        "automatic_complete_regions_unchanged": sum(
            bool(row.get("complete")) for row in result["regions"]
        ),
        "explicitly_review_accepted_regions": sum(row["accepted"] for row in decisions),
        "review_branch_accepted_groups": sum(row["accepted"] for row in groups),
        "no_CAD_or_OCR_executed": True,
        "production_GO": False,
        "resources": {"wall_seconds": time.perf_counter() - started},
    }
    result["source_review_audit"] = audit
    result["upstream_producer_before_source_review"] = copy.deepcopy(
        text_data.get("producer")
    )
    result["producer"] = provenance
    result["status"] = "EXPLICIT_SOURCE_REVIEW_BRANCH_AUTOMATIC_RESULTS_UNCHANGED"
    output = Path(out)
    planned = [
        "completed_text.json",
        "text_regions.json",
        "source_review_audit.json",
        "completed_stages.json",
        "applied_review_manifest.json",
    ]
    if any((output / name).exists() for name in planned):
        raise FileExistsError("REVIEW_OUTPUT_FILES_ALREADY_EXIST")
    output.mkdir(parents=True, exist_ok=True)
    _dump(output / "applied_review_manifest.json", manifest_data)
    _dump(output / "source_review_audit.json", audit)
    _dump(output / "completed_text.json", result)
    _dump(output / "text_regions.json", result)
    _dump(
        output / "completed_stages.json",
        {
            "source_sha256": source_sha,
            "source_array_sha256": source_array_sha,
            "source_size_px": list(source_gray.size),
            "coordinate_system": COORDINATES,
            "roi_xyxy_px": roi,
            "text": {
                "path": "completed_text.json",
                "sha256": _sha(output / "completed_text.json"),
                "producer_module": __name__,
                "producer_sha256": provenance["sha256"],
                "dependency_producers": dependencies,
                "upstream_text_sha256": upstream_sha,
                "branch": "EXPLICIT_SOURCE_REVIEW_NOT_AUTOMATIC",
                "automatic_fields_unchanged": True,
            },
        },
    )
    return result
