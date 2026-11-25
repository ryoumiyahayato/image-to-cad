"""Production service target for source-supported native objects.

This module never reads test-case crops or expected strings. A complete source
image and explicit ROI are required; no failed stage falls back to old HATCH.
"""

from .performance import profiled
from pathlib import Path, PurePosixPath
from .evidence_paths import relative_evidence_path
import copy
import hashlib
import json
import math
import time
import traceback
import shutil
import numpy as np
import cv2
from PIL import Image
from scipy.ndimage import distance_transform_edt, map_coordinates
from .contracts import save_json, TOLERANCES, validate_text_regions
from .text_regions import extract_text_regions
from .geometry import extract_lines
from .annotations import assemble_annotations
from .wall_segments import assemble_walls
from .cad_io import export_objects, cold_audit, render_saved
from .execution import (
    check_cancel,
    NativeCancelled,
    restore_partial_ocr,
    checkpoint_artifact,
)


def _completed_assembly_checkpoint(cache_dir, identity):
    """Continue a cancelled pre-export job without re-running completed fits."""
    manifest = Path(cache_dir) / "completed_stages.json" if cache_dir else None
    if manifest is None or not manifest.is_file():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    row = data.get("assembly")
    if row is None:
        return None
    if any(data.get(k) != v for k, v in identity.items()):
        raise ValueError("ASSEMBLY_CHECKPOINT_SOURCE_IDENTITY_MISMATCH")
    from app.core.native_job_manager import algorithm_fingerprint

    if row["algorithm_fingerprint"] != algorithm_fingerprint():
        raise ValueError("ASSEMBLY_CHECKPOINT_ALGORITHM_CHANGED")
    path = (manifest.parent / row["path"]).resolve()
    if (
        manifest.parent.resolve() not in path.parents
        or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
    ):
        raise ValueError("ASSEMBLY_CHECKPOINT_PATH_OR_HASH_MISMATCH")
    return json.loads(path.read_text(encoding="utf-8"))


def _discovery_for_resume(cache_dir, out, texts):
    """The discovered OCR observations belong to this same source/attempt.

    They are an execution checkpoint, never an externally supplied approval.
    A raw text checkpoint can exist before its domain-recovery pass completes.
    """
    local = Path(out) / "text/discovery_observations.json"
    if local.is_file():
        return local
    if cache_dir is None:
        raise ValueError("TEXT_DISCOVERY_CHECKPOINT_MISSING")
    manifest = json.loads((Path(cache_dir) / "completed_stages.json").read_text(encoding="utf-8"))
    row = manifest.get("discovery")
    if row is None:
        raise ValueError("TEXT_DISCOVERY_CHECKPOINT_WITHOUT_HASH")
    path = (Path(cache_dir) / row["path"]).resolve()
    if (
        Path(cache_dir).resolve() not in path.parents
        or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
    ):
        raise ValueError("TEXT_DISCOVERY_CHECKPOINT_HASH_MISMATCH")
    save_json(local, json.loads(path.read_text(encoding="utf-8")))
    return local


def _saved_dxf_accepted(audit):
    """An auditor's in-memory repair is not a successful saved-file gate."""
    return (
        not audit["ezdxf_errors"]
        and not audit["ezdxf_in_memory_fixes"]
        and not audit["exact_duplicate_segments"]
        and audit["source_gate_pass"]
    )


def _restore_circular_marker_evidence(cache_dir, out, completion):
    """Restore bound raw artifacts; a prior saved-file verdict is never reused."""
    source_root, destination = Path(cache_dir).resolve(), Path(out).resolve()
    files = completion.get("raw_evidence_files")
    if not isinstance(files, list) or not files:
        raise ValueError("CIRCULAR_ASSEMBLY_RAW_EVIDENCE_MANIFEST_MISSING")
    seen = set()
    for record in files:
        name = record["path"]
        relative = PurePosixPath(name)
        if (not isinstance(name, str) or "\\" in name or relative.is_absolute()
                or ".." in relative.parts or not relative.parts
                or relative.parts[0] != "circular_markers" or name in seen):
            raise ValueError("CIRCULAR_ASSEMBLY_RAW_EVIDENCE_PATH_INVALID")
        seen.add(name)
        source, target = source_root / name, destination / name
        if (source.is_symlink() or source_root not in source.resolve().parents
                or not source.is_file() or target.is_symlink()
                or destination not in target.resolve().parents):
            raise ValueError("CIRCULAR_ASSEMBLY_RAW_EVIDENCE_OUTSIDE_OR_MISSING")
        contents = source.read_bytes()
        if hashlib.sha256(contents).hexdigest() != record["sha256"]:
            raise ValueError("CIRCULAR_ASSEMBLY_RAW_EVIDENCE_HASH_CHANGED")
        if target.exists() and target.read_bytes() != contents:
            raise ValueError("CIRCULAR_ASSEMBLY_DESTINATION_ALREADY_DIFFERS")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(contents)
    save_json(destination / "circular_markers/circular_markers.json", completion)


def _restore_single_line_label_evidence(cache_dir, out, texts):
    """Keep new TEXT raw evidence available after completed-assembly resume."""
    completion = texts.get("single_line_label_recovery")
    if completion is None:
        return
    source_root, destination = Path(cache_dir).resolve(), Path(out).resolve()
    records = completion.get("raw_evidence_files")
    if not isinstance(records, list):
        raise ValueError("SINGLE_LINE_ASSEMBLY_RAW_MANIFEST_MISSING")
    seen = set()
    for record in records:
        name = record.get("path")
        if not isinstance(name, str) or "\\" in name:
            raise ValueError("SINGLE_LINE_ASSEMBLY_RAW_PATH_INVALID")
        relative = PurePosixPath(name)
        if (
            relative.is_absolute() or ".." in relative.parts
            or not relative.parts or relative.parts[0] != "single_line_labels"
            or name in seen
        ):
            raise ValueError("SINGLE_LINE_ASSEMBLY_RAW_PATH_INVALID")
        seen.add(name)
        source, target = source_root / name, destination / name
        if (
            not source.is_file() or source.is_symlink()
            or source_root not in source.resolve().parents
            or target.is_symlink() or destination not in target.resolve().parents
        ):
            raise ValueError("SINGLE_LINE_ASSEMBLY_RAW_SOURCE_MISSING_OR_OUTSIDE")
        contents = source.read_bytes()
        if hashlib.sha256(contents).hexdigest() != record.get("sha256"):
            raise ValueError("SINGLE_LINE_ASSEMBLY_RAW_SOURCE_CHANGED")
        if target.exists() and target.read_bytes() != contents:
            raise ValueError("SINGLE_LINE_ASSEMBLY_DESTINATION_ALREADY_DIFFERS")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(contents)
    save_json(destination / "single_line_labels/summary.json", completion)


def _text_progress_adapter(progress):
    """Text owns a structured event contract; service owns stage/fraction."""
    last_fraction = 0.05

    def receive(event):
        nonlocal last_fraction
        if not isinstance(event, dict) or not isinstance(event.get("stage"), str):
            raise TypeError("TEXT_PROGRESS_EVENT_DICT_WITH_STAGE_REQUIRED")
        done = float(event.get("completed", 0))
        total = max(1, float(event.get("total", 1)))
        last_fraction = max(last_fraction, 0.05 + 0.25 * min(1.0, done / total))
        progress("TEXT:" + event["stage"], last_fraction)

    return receive


def _completed_text_checkpoint(
    cache_dir, source_sha, roi, shape, source_array_sha=None
):
    """Explicit, hash checked restart of a completed text stage only."""
    manifest = Path(cache_dir) / "completed_stages.json" if cache_dir else None
    if not manifest or not manifest.is_file():
        return None, None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("source_sha256") != source_sha or data.get("roi_xyxy_px") != list(roi):
        raise ValueError("COMPLETED_STAGE_SOURCE_OR_ROI_MISMATCH")
    row = data.get("text")
    if not row:
        return None, None
    path = (manifest.parent / row["path"]).resolve()

    allowed = {
        "app.native_objects.text_regions": "text_regions.py",
        "app.native_objects.text_line_domains": "text_line_domains.py",
        "app.native_objects.text_block_rescue": "text_block_rescue.py",
        "app.native_objects.cross_engine_text": "cross_engine_text.py",
        "app.native_objects.source_text_completion": "source_text_completion.py",
        "app.native_objects.single_line_labels": "single_line_labels.py",
        "app.native_objects.source_text_ownership": "source_text_ownership.py",
        "app.native_objects.source_review": "source_review.py",
    }
    producer_module = row.get("producer_module", "app.native_objects.text_regions")
    if producer_module not in allowed:
        raise ValueError("UNRECOGNIZED_TEXT_CHECKPOINT_PRODUCER")
    producer = Path(__file__).with_name(allowed[producer_module])
    if row["producer_sha256"] != hashlib.sha256(producer.read_bytes()).hexdigest():
        raise ValueError("COMPLETED_TEXT_PRODUCER_CHANGED")
    dependencies = row.get("dependency_producers", {})
    dependency_items = (
        dependencies.items()
        if isinstance(dependencies, dict)
        else [(d["module"], d["sha256"]) for d in dependencies]
    )
    dependency_allowed = {
        **allowed,
        "app.native_objects.independent_recognizer": "independent_recognizer.py",
        "app.native_objects.text_confirmation": "text_confirmation.py",
        "app.native_objects.text_context_ownership": "text_context_ownership.py",
        "app.native_objects.circle_character_recognition": "circle_character_recognition.py",
        "app.native_objects.circle_glyph_resolution": "circle_glyph_resolution.py",
        "app.native_objects.text_contact_geometry": "text_contact_geometry.py",
        "app.native_objects.text_contact_partition": "text_contact_partition.py",
        "app.native_objects.text_contact_audit": "text_contact_audit.py",
        "app.native_objects.single_line_neighbor_clearance": "single_line_neighbor_clearance.py",
        "app.native_objects.single_line_text_audit": "single_line_text_audit.py",
        "app.native_objects.single_line_source_layout": "single_line_source_layout.py",
        "app.native_objects.source_row_font_registry": "source_row_font_registry.py",
        "app.native_objects.source_glyph_equivalence": "source_glyph_equivalence.py",
        "app.native_objects.circular_markers": "circular_markers.py",
        "app.native_objects.connections": "connections.py",
        "app.native_objects.text_graph_support": "text_graph_support.py",
        "app.native_objects.connection_core_routes": "connection_core_routes.py",
    }
    for module_name, expected in dependency_items:
        if (
            module_name not in dependency_allowed
            or hashlib.sha256(
                Path(__file__).with_name(dependency_allowed[module_name]).read_bytes()
            ).hexdigest()
            != expected
        ):
            raise ValueError("COMPLETED_TEXT_DEPENDENCY_CHANGED:" + module_name)
    if row["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError("COMPLETED_TEXT_HASH_MISMATCH")
    for name, expected in row.get("additional_producers", {}).items():
        if name not in (
            "text_line_domains",
            "text_block_rescue",
            "cross_engine_text",
            "source_text_completion",
            "single_line_labels",
            "source_text_ownership",
            "source_review",
        ):
            raise ValueError("UNRECOGNIZED_TEXT_CHECKPOINT_DERIVATION")
        producer = Path(__file__).with_name(name + ".py")
        if hashlib.sha256(producer.read_bytes()).hexdigest() != expected:
            raise ValueError("COMPLETED_TEXT_DERIVATION_CHANGED:" + name)
    texts = json.loads(path.read_text(encoding="utf-8"))
    validate_text_regions(texts, shape, roi)
    if (
        source_array_sha is not None
        and texts.get("source_array_sha256") != source_array_sha
    ):
        raise ValueError("COMPLETED_TEXT_WORKING_GRAY_SAMPLES_MISMATCH")
    return texts, {
        "manifest": str(manifest),
        "text_path": str(path),
        "sha256": row["sha256"],
        "new_OCR_calls": 0,
        "producer_row": row,
    }


def _restore_text_contact_evidence(out, completion):
    """Restore the receipt embedded in an authenticated completed assembly."""
    if not completion:
        return
    from .text_contact_adoption import SCHEMA

    if completion.get("schema") != SCHEMA:
        raise ValueError("TEXT_CONTACT_ASSEMBLY_RECEIPT_SCHEMA_CHANGED")
    destination = Path(out) / "text_contact/adoption.json"
    if destination.exists() and json.loads(destination.read_text(encoding="utf-8")) != completion:
        raise ValueError("TEXT_CONTACT_ASSEMBLY_RECEIPT_ALREADY_DIFFERS")
    save_json(destination, completion)


def _finalize_circle_relations(gray, roi, objects, completion, out):
    """Check the assembled external paths, including later text-contact paths.

    Both source checks are idempotent and retain their original geometry
    certificates.  Their order matters: a proved white gap must not be offered
    to the contact restorer.  No character recognition is performed here.
    """
    from .circle_endpoint_contacts import restore_circle_endpoint_contacts
    from .circle_white_gap_protection import protect_circle_white_gaps

    result = copy.deepcopy(completion)
    gaps = protect_circle_white_gaps(gray, roi, objects)
    updates = {obj["id"]: obj for obj in gaps["replacements"]}
    active = [updates.get(obj["id"], obj) for obj in objects]
    contacts = restore_circle_endpoint_contacts(gray, roi, active)
    updates = {obj["id"]: obj for obj in contacts["replacements"]}
    active = [updates.get(obj["id"], obj) for obj in active]
    pending = [row for row in contacts["decisions"] if not row["accepted"]]
    pending += gaps["pending_relations"]
    pending_ids = {row["circle_id"] for row in pending}
    markers = {obj["id"]: obj for obj in result["objects"]}
    for marker in markers.values():
        marker["source_evidence"]["external_endpoint_contact_review"] = {
            "status": "NEARBY_EXTERNAL_ENDPOINT_RELATION_PENDING" if marker["id"] in pending_ids else "NO_UNRESOLVED_OBSERVED_EXTERNAL_ENDPOINT",
            "pending_contacts": [row for row in pending if row["circle_id"] == marker["id"]],
            "complete_network_connectivity_claimed": False,
            "pending_is_not_a_claim_that_source_pixels_should_be_connected": True,
            "protected_source_white_gaps": [end for obj in gaps["replacements"]
                for end in obj["source_evidence"]["circle_white_gap_protection"]["ends"]
                if end["circle_id"] == marker["id"]],
        }
        if marker["kind"] == "CIRCULAR_MARKER":
            marker["status"] = ("COMPLETE_CIRCULAR_COMPONENTS_EXTERNAL_CONTACT_PENDING"
                                if marker["id"] in pending_ids else
                                "COMPLETE_CIRCULAR_MARKER_PENDING_SAVED_AUDIT")
    active = [markers.get(obj["id"], obj) for obj in active]
    result["uncertainties"] = [row for row in result["uncertainties"]
                                if row.get("reason") != "CIRCULAR_EXTERNAL_ENDPOINT_CONTACT_PENDING"]
    result["uncertainties"].extend({
        "id": row["circle_id"], "reason": "CIRCULAR_EXTERNAL_ENDPOINT_CONTACT_PENDING",
        "external_object_id": row["object_id"], "endpoint_number": row["endpoint_number"],
        "original_geometry_retained": True, "details": row,
        "bbox_xyxy_px": markers[row["circle_id"]]["bbox_xyxy_px"],
    } for row in pending if row["circle_id"] in markers)
    for decision in result["decisions"]:
        if decision.get("accepted"):
            decision["external_endpoint_contact_status"] = "PENDING" if decision["id"] in pending_ids else "VERIFIED_OR_NO_OBSERVED_PENDING_END"
            if decision["id"] in markers:
                decision["status"] = markers[decision["id"]]["status"]
    complete = sum(obj["kind"] == "CIRCULAR_MARKER" for obj in markers.values())
    partial = sum(obj["kind"] == "CIRCLE" for obj in markers.values())
    unresolved = sum(obj["kind"] == "CIRCULAR_MARKER" and obj["id"] in pending_ids
                     for obj in markers.values())
    result.update(external_endpoint_contacts=contacts, source_white_gap_protection=gaps,
                  external_relations_checked_after_text_contact_assembly=True)
    result["summary"].update(
        new_complete_markers=complete - unresolved,
        circle_text_compositions_with_external_contacts_pending=unresolved,
        partial_compositions=partial + unresolved,
        pending_positions=len({row["id"] for row in result["uncertainties"]}),
        external_endpoint_contacts=contacts["summary"], source_white_gap_protection=gaps["summary"],
        component_complete_markers_with_external_contact_pending=unresolved,
        component_complete_markers_without_observed_external_contact_pending=complete - unresolved,
        pending_external_contact_circle_ids=sorted(pending_ids),
    )
    save_json(Path(out) / "circular_markers.json", result)
    return active, result


def _completed_geometry_checkpoint(cache_dir, source_sha, roi, texts, gray, out):
    """Reuse fitted source lines, then reapply the current text responsibility.

    Only the saved accepted geometric dictionary is eligible; old uncertain
    fits are not silently promoted. No LSD/source fit or OCR is repeated.
    """
    manifest = Path(cache_dir) / "completed_stages.json" if cache_dir else None
    if not manifest or not manifest.is_file():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    row = data.get("geometry")
    if not row:
        return None
    if data.get("source_sha256") != source_sha or data.get("roi_xyxy_px") != list(roi):
        raise ValueError("GEOMETRY_CHECKPOINT_SOURCE_OR_ROI_MISMATCH")
    from . import geometry as module

    current_producer = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    if row["producer_sha256"] != current_producer:
        original_producer = row.get("producer_source_path")
        if (
            not original_producer
            or hashlib.sha256(
                (manifest.parent / original_producer).read_bytes()
            ).hexdigest()
            != row["producer_sha256"]
        ):
            raise ValueError("GEOMETRY_CHECKPOINT_ORIGINAL_PRODUCER_NOT_PRESERVED")
    path = (manifest.parent / row["path"]).resolve()
    if row["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError("GEOMETRY_CHECKPOINT_HASH_MISMATCH")
    result = json.loads(path.read_text(encoding="utf-8"))
    result = _reclassify_source_fitted_lines(
        result, texts, gray.shape, roi, original_dictionary_sha256=row["sha256"]
    )
    result["resume"] = {
        "path": str(path),
        "sha256": row["sha256"],
        "new_source_fits": 0,
        "new_OCR_calls": 0,
        "original_producer_sha256": row["producer_sha256"],
        "reclassification_producer_sha256": current_producer,
        "text_responsibility_rechecked": True,
        "original_accepted_and_text_deferred_candidates": len(
            result["text_interface"]["contacts"]
        ),
    }
    save_json(Path(out) / "lines.json", result)
    return result


def _reclassify_source_fitted_lines(
    source_fits, texts, shape, roi, *, original_dictionary_sha256
):
    """Recheck saved LINE and isolated-component proposals without refitting.

    The short-component extractor records its text rejection as ``decision``;
    the long-line extractor uses ``reason``. Both must be retained and checked.
    Any later non-text rejection remains authoritative. Every newly retained
    proposal still passes the unchanged dense source gate and DXF cold audit.
    """
    from . import geometry as module

    result = copy.deepcopy(source_fits)
    boxes = validate_text_regions(texts, shape, roi)
    kept = []
    events = []
    candidates = copy.deepcopy(result["objects"])
    old_ids = {o["id"] for o in candidates}
    text_only = {"DEFER_TEXT_OWNERSHIP", "RESUMED_LINE_NEW_TEXT_RESPONSIBILITY"}
    short_records = {c["id"]: c for c in result.get("short_source_components", [])}
    blocked = {
        u.get("id")
        for u in result["uncertainties"]
        if u.get("id") and u.get("reason", u.get("decision")) not in text_only
    }
    for u in result["uncertainties"]:
        # These were already source-fitted and failed only text responsibility.
        # Curve/branch continuation or other geometry failures stay unresolved.
        rejection = u.get("reason", u.get("decision"))
        if (
            rejection in text_only
            and u.get("id") not in old_ids
            and u.get("id") not in blocked
            and u.get("geometry")
        ):
            component = short_records.get(u["id"])
            if component is not None and component["geometry"] != u["geometry"]:
                raise ValueError(
                    "SOURCE_COMPONENT_CHECKPOINT_GEOMETRY_ID_MISMATCH:" + u["id"]
                )
            short = component is not None or "source_component_area" in u
            area = (
                component["source_component_area"]
                if component is not None
                else u.get("source_component_area")
            )
            provenance = copy.deepcopy(u.get("source_evidence", {}))
            provenance.setdefault(
                "method",
                "saved_source_fitted_line_reclassified_with_positive_glyph_support",
            )
            provenance.update(
                original_dictionary_sha256=original_dictionary_sha256,
                original_defer_reason=rejection,
                original_isolated_component_area=area,
            )
            candidates.append(
                {
                    "id": u["id"],
                    "kind": "LINE",
                    "layer": u.get(
                        "candidate_layer", "SHORT_STROKE" if short else "GEOMETRY"
                    ),
                    "geometry": copy.deepcopy(u["geometry"]),
                    "source_evidence": provenance,
                }
            )
            old_ids.add(u["id"])
    result["uncertainties"] = [
        u
        for u in result["uncertainties"]
        if not (
            u.get("id") in old_ids and u.get("reason", u.get("decision")) in text_only
        )
    ]
    for o in candidates:
        a, b = np.asarray(o["geometry"]["start"]), np.asarray(o["geometry"]["end"])
        status, contacts = module.text_relation(a, b, boxes)
        events.append(
            {
                "id": o["id"],
                "geometry": o["geometry"],
                "decision": status,
                "contacts": contacts,
                "actual_word_boxes_read": len(boxes),
            }
        )
        if status.startswith("DEFER"):
            deferred = {
                "id": o["id"],
                "geometry": copy.deepcopy(o["geometry"]),
                "reason": "RESUMED_LINE_NEW_TEXT_RESPONSIBILITY",
                "contacts": contacts,
                "candidate_layer": o["layer"],
                "source_evidence": copy.deepcopy(o.get("source_evidence", {})),
            }
            if o["id"] in short_records:
                deferred["source_component_area"] = short_records[o["id"]][
                    "source_component_area"
                ]
            result["uncertainties"].append(deferred)
        else:
            o["source_evidence"]["text_relation"] = status
            o["source_evidence"]["text_contacts"] = contacts
            kept.append(o)
    result["objects"] = kept
    if "pre_dedup_line_candidates" in result:
        retained_candidates = []
        candidate_checks = []
        for candidate in result["pre_dedup_line_candidates"]:
            g = candidate["geometry"]
            status, contacts = module.text_relation(
                np.asarray(g["start"]), np.asarray(g["end"]), boxes
            )
            candidate_checks.append(
                {"id": candidate["id"], "decision": status, "contacts": contacts}
            )
            if not status.startswith("DEFER"):
                candidate["source_evidence"]["text_relation"] = status
                candidate["source_evidence"]["text_contacts"] = contacts
                retained_candidates.append(candidate)
        result["pre_dedup_line_candidates"] = retained_candidates
        result["candidate_text_responsibility_recheck"] = candidate_checks
    result["text_interface"] = {
        "coordinate_system": "source_pixels_top_left",
        "regions_received": len(texts["regions"]),
        "word_boxes_consumed": len(boxes),
        "missing_field_policy": "RAISE_CONTRACT_ERROR",
        "contacts": events,
    }
    result["responsibility_reclassification"] = {
        "original_dictionary_sha256": original_dictionary_sha256,
        "candidate_count": len(candidates),
        "new_source_fits": 0,
        "coordinates_changed": False,
        "long_reason_and_short_decision_records_both_consumed": True,
        "non_text_failure_ids_preserved": sorted(x for x in blocked if x),
    }
    return result


def _restore_completed_text_assets(cache_dir, out, producer_row):
    """Keep stage-relative raw OCR references valid across a formal resume.

    A domain checkpoint has '../text' references. Moving only its JSON to the
    evidence root changes their meaning. Copy the completed hierarchy without
    rewriting historical bytes; partial later stages are restored separately.
    """
    source, destination = Path(cache_dir), Path(out)
    stages = [
        "app.native_objects.text_regions",
        "app.native_objects.text_line_domains",
        "app.native_objects.text_block_rescue",
        "app.native_objects.cross_engine_text",
        "app.native_objects.source_text_completion",
        "app.native_objects.single_line_labels",
        "app.native_objects.source_text_ownership",
    ]
    module = producer_row.get("producer_module", stages[0])
    if module not in stages:
        raise ValueError("AUTOMATIC_TEXT_RESUME_PRODUCER_NOT_SUPPORTED:" + module)
    directories = [
        "text",
        "text_domain_recovery",
        "text_block_rescue",
        "cross_engine_text",
        "source_text_completion",
        "single_line_labels",
        "text_geometry_ownership",
    ]
    records = []
    for name in ["completed_text.json", *directories[: stages.index(module) + 1]]:
        previous = source / name
        if not previous.exists():
            continue
        files = (
            [previous]
            if previous.is_file()
            else sorted(p for p in previous.rglob("*") if p.is_file())
        )
        for original in files:
            relative = original.relative_to(source)
            target = destination / relative
            if target.exists():
                raise FileExistsError(
                    "RESUMED_TEXT_ASSET_WOULD_OVERWRITE:" + str(relative)
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            records.append(
                {
                    "path": str(relative),
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
    relative = Path(producer_row["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("RESUMED_TEXT_PATH_OUTSIDE_EVIDENCE")
    save_json(
        destination / "text_asset_resume.json",
        {
            "copied": records,
            "authoritative_text_path": str(relative),
            "relative_evidence_layout_preserved": True,
            "new_OCR_calls": 0,
            "old_decisions_are_not_final_DXF_review": True,
        },
    )
    return destination / relative


@profiled("pipeline._dense_line_gate")
def _dense_line_gate(gray, roi, result, out):
    """Pre-export gate at the same .25px density as the independent cold read."""
    x0, y0, x1, y1 = roi
    ox, oy = max(0, x0 - 8), max(0, y0 - 8)
    rx, by = min(gray.shape[1], x1 + 8), min(gray.shape[0], y1 + 8)
    dist = distance_transform_edt(gray[oy:by, ox:rx] >= 128)
    kept = []
    checks = []
    original_ids = {o["id"] for o in result["objects"]}
    candidates = {o["id"]: o for o in result.get("pre_dedup_line_candidates", [])}
    candidates.update({o["id"]: o for o in result["objects"]})
    passed_candidates = []
    for o in candidates.values():
        a, b = np.asarray(o["geometry"]["start"]), np.asarray(o["geometry"]["end"])
        length = float(np.linalg.norm(b - a))
        p = np.linspace(a, b, max(2, int(math.ceil(length / 0.25)) + 1))
        ds = map_coordinates(
            dist, [p[:, 1] - oy, p[:, 0] - ox], order=1, mode="constant", cval=999
        )
        changes = np.diff(np.r_[False, ds > 2, False].astype(int))
        s = np.flatnonzero(changes == 1)
        t = np.flatnonzero(changes == -1)
        gap = float(max(t - s, default=0) * length / max(1, len(p) - 1))
        fraction = float(np.mean(ds <= 2))
        okay = fraction >= 0.98 and gap <= 5
        row = {
            "id": o["id"],
            "source_fraction": fraction,
            "maximum_gap_px": gap,
            "samples": len(p),
            "pass": okay,
        }
        checks.append(row)
        if okay:
            if "source_width_px" not in o.get("source_evidence", {}):
                u = (b - a) / length
                n = np.array([-u[1], u[0]])
                centres = np.linspace(a, b, min(41, max(5, int(length / 3))))[1:-1]
                offset = np.arange(-4, 4.01, 0.5)
                q = centres[:, None, :] + offset[None, :, None] * n
                ink = (
                    map_coordinates(
                        gray,
                        [q[:, :, 1], q[:, :, 0]],
                        order=0,
                        mode="constant",
                        cval=255,
                    )
                    < 128
                )
                widths = []
                for profile in ink:
                    change = np.diff(np.r_[False, profile, False].astype(int))
                    starts = np.flatnonzero(change == 1)
                    ends = np.flatnonzero(change == -1)
                    runs = [
                        (lo, hi)
                        for lo, hi in zip(starts, ends)
                        if lo > 0 and hi < len(profile)
                    ]
                    if runs:
                        lo, hi = min(
                            runs,
                            key=lambda r: abs((offset[r[0]] + offset[r[1] - 1]) / 2),
                        )
                        widths.append((hi - lo) * 0.5)
                o["source_evidence"]["source_width_px"] = (
                    float(np.median(widths))
                    if len(widths) >= 0.8 * len(centres)
                    else 99.0
                )
                o["source_evidence"]["width_measurement"] = {
                    "source_cross_sections": len(centres),
                    "bounded_runs": len(widths),
                    "centreline_coordinates_changed": False,
                }
            passed_candidates.append(o)
            if o["id"] in original_ids:
                kept.append(o)
        else:
            result["uncertainties"].append(
                {
                    "id": o["id"],
                    "geometry": o["geometry"],
                    "reason": "DENSE_SOURCE_GATE_REJECT",
                    "check": row,
                    "source_retained_for_repair": True,
                }
            )
    result["objects"] = kept
    result["dense_preexport_checks"] = checks
    if "pre_dedup_line_candidates" in result:
        result["pre_dedup_line_candidates"] = passed_candidates
    save_json(Path(out) / "lines_after_dense_gate.json", result)
    return result


@profiled("pipeline._doors")
def _doors(gray, roi, source_path, out, cache_dir):
    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    cached = False
    cache = Path(cache_dir) / "native_verified_cache.json" if cache_dir else None
    if cache and cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("source_sha256") != source_sha or data.get("roi_xyxy_px") != list(
            roi
        ):
            raise ValueError("NATIVE_COMPONENT_CACHE_SOURCE_OR_ROI_MISMATCH")
        proposals = copy.deepcopy(data["objects"])
        cached = True
        cache_evidence = {
            "path": str(cache),
            "sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
            "provenance": data["provenance"],
        }
    else:
        from .door_detector import detect_doors

        data = detect_doors(gray, roi, out, source_path)
        proposals = data["objects"]
        cache_evidence = None
    objects = []
    checks = []
    rejected = []
    for obj in proposals:
        if obj["kind"] != "DOOR":
            raise ValueError("UNSUPPORTED_VERIFIED_CACHE_KIND")
        leaves = obj["geometry"].get("leaves", [obj["geometry"]])
        points = []
        types = []
        for leaf in leaves:
            c = np.asarray(leaf["hinge"])
            r = leaf["radius_px"]
            start = leaf["start_deg_image"]
            sweep = leaf.get("sweep_deg_image", leaf["end_deg_image"] - start)
            angle = np.deg2rad(
                np.linspace(
                    start,
                    start + sweep,
                    max(3, int(abs(math.radians(sweep)) * r / 0.05) + 1),
                )
            )
            points.append(c + r * np.column_stack((np.cos(angle), np.sin(angle))))
            types.append(("ARC", 2.5))
            theta = math.radians(leaf["leaf_angle_deg_image"])
            tip = c + r * np.array([math.cos(theta), math.sin(theta)])
            points.append(np.linspace(c, tip, max(2, int(r / 0.25) + 1)))
            types.append(("LINE", 2.0))
        total = np.concatenate(points)
        lo = np.maximum(0, np.floor(total.min(axis=0)).astype(int) - 12)
        hi = np.minimum(
            [gray.shape[1], gray.shape[0]], np.ceil(total.max(axis=0)).astype(int) + 13
        )
        dist = distance_transform_edt(gray[lo[1] : hi[1], lo[0] : hi[0]] >= 128)
        tests = []
        for pts, (kind, tol) in zip(points, types):
            ds = map_coordinates(
                dist,
                [pts[:, 1] - lo[1], pts[:, 0] - lo[0]],
                order=1,
                mode="constant",
                cval=999,
            )
            tests.append(
                {
                    "type": kind,
                    "max_source_distance_px": float(ds.max()),
                    "tolerance_px": tol,
                    "pass": bool(ds.max() <= tol),
                }
            )
        okay = all(x["pass"] for x in tests)
        checks.append(
            {
                "id": obj["id"],
                "pass": okay,
                "members": tests,
                "reused_frozen_geometry": cached,
            }
        )
        if okay:
            obj.pop("handle_at_write", None)
            obj.pop("export", None)
            objects.append(obj)
        else:
            rejected.append(
                {"object": obj, "reason": "SOURCE_RECHECK_REJECT", "checks": tests}
            )
    result = {
        "objects": objects,
        "source_checks": checks,
        "uncertainties": rejected,
        "cache_hit": cached,
        "cache_evidence": cache_evidence,
        "new_door_recognition_claim": not cached,
        "not_engineering_semantic_reclassification": True,
    }
    save_json(Path(out) / "doors.json", result)
    return result


def _exclude_duplicate_door_lines(lines, doors):
    retained = []
    deferred = []
    for o in lines:
        a, b = np.asarray(o["geometry"]["start"]), np.asarray(o["geometry"]["end"])
        v = b - a
        length = np.linalg.norm(v)
        u = v / length
        n = np.array([-u[1], u[0]])
        contact = None
        for door in doors:
            for leaf in door["geometry"].get("leaves", [door["geometry"]]):
                c = np.asarray(leaf["hinge"])
                r = leaf["radius_px"]
                theta = math.radians(leaf["leaf_angle_deg_image"])
                d = c + r * np.array([math.cos(theta), math.sin(theta)])
                if abs(u @ ((d - c) / r)) < math.cos(math.radians(0.5)):
                    continue
                if max(abs((c - a) @ n), abs((d - a) @ n)) > 2:
                    continue
                t = sorted([(c - a) @ u, (d - a) @ u])
                overlap = max(0, min(length, t[1]) - max(0, t[0]))
                if overlap > 2:
                    contact = {
                        "id": o["id"],
                        "geometry": o["geometry"],
                        "door_id": door["id"],
                        "overlap_px": float(overlap),
                        "unrepresented_excess_length_px": float(
                            max(0, length - overlap)
                        ),
                        "reason": "LINE_DUPLICATES_NATIVE_DOOR_LEAF; any excess stays explicit unresolved source",
                    }
                    break
            if contact:
                break
        if contact:
            deferred.append(contact)
        else:
            retained.append(o)
    return retained, deferred


def _complete_single_line_stage(gray, texts, out, source_sha, roi, dpi, progress):
    """Recompute complete single-line adoption in the ordinary text pipeline.

    This stage takes only the current source and text observations. Evaluation
    cases, expected strings and old DXF objects never enter recognition. The
    previous stage remains immutable and its relative raw paths stay usable.
    """
    from . import single_line_labels

    out = Path(out)
    manifest_path = out / "completed_stages.json"
    stage = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = stage["text"]
    module = "app.native_objects.single_line_labels"
    producer_sha = hashlib.sha256(
        Path(single_line_labels.__file__).read_bytes()
    ).hexdigest()
    dependencies = previous.get("dependency_producers", {})
    dependencies = (
        dict(dependencies)
        if isinstance(dependencies, dict)
        else {row["module"]: row["sha256"] for row in dependencies}
    )
    if previous["producer_module"] == "app.native_objects.source_review":
        return texts
    if (
        previous["producer_module"] == module
        and previous["producer_sha256"] == producer_sha
    ) or dependencies.get(module) == producer_sha:
        # This is an authenticated completed stage from the same producer, not
        # a saved acceptance whitelist imported from another drawing.
        return texts
    upstream_path = out / previous["path"]
    upstream_root = upstream_path.parent
    previous_roots = dict(texts.get("region_evidence_roots", {}))
    previous_ids = {row["id"] for row in texts["regions"]}
    stage_dir = out / "single_line_labels"
    # Ownership may already be the imported upstream stage. Its ordinary
    # destination is rewritten after this recovery, so preserve the exact
    # input bytes before a later ownership pass can replace that path.
    upstream_snapshot = stage_dir / "upstream_completed_text.json"
    upstream_contents = upstream_path.read_bytes()
    if hashlib.sha256(upstream_contents).hexdigest() != previous["sha256"]:
        raise ValueError("SINGLE_LINE_UPSTREAM_CHANGED_BEFORE_SNAPSHOT")
    if upstream_snapshot.exists() and upstream_snapshot.read_bytes() != upstream_contents:
        raise ValueError("SINGLE_LINE_UPSTREAM_SNAPSHOT_ALREADY_DIFFERS")
    upstream_snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not upstream_snapshot.exists():
        upstream_snapshot.write_bytes(upstream_contents)
    progress("COMPLETE_SOURCE_BOUND_SINGLE_LINE_LABELS", 0.315)
    result = single_line_labels.refine_single_line_labels(
        gray,
        texts,
        stage_dir,
        roi=roi,
        dpi=dpi,
        source_sha256=source_sha,
        progress_callback=_text_progress_adapter(progress),
        evidence_root=out,
    )
    result["region_evidence_roots"] = {
        row["id"]: relative_evidence_path(
            (
                upstream_root / previous_roots.get(row["id"], ".")
                if row["id"] in previous_ids
                else stage_dir / result.get("region_evidence_roots", {}).get(
                    row["id"], "."
                )
            ).resolve(),
            stage_dir,
        )
        for row in result["regions"]
    }
    if result.get("bbox_overlay"):
        result["bbox_overlay"] = relative_evidence_path(
            upstream_root / result["bbox_overlay"], stage_dir
        )
    validate_text_regions(result, gray.shape, roi)
    saved = stage_dir / "completed_text.json"
    save_json(saved, result)
    dependencies[previous["producer_module"]] = previous["producer_sha256"]
    # The new producer reuses the existing raw recognizer integrity/score
    # helpers. Their actual code is part of this completed-stage identity.
    for dependency in (
        "text_regions", "independent_recognizer", "circle_character_recognition", "circle_glyph_resolution",
        "text_contact_geometry", "text_contact_partition", "text_contact_audit", "connections",
        "text_graph_support",
        "connection_core_routes",
        "single_line_neighbor_clearance", "single_line_text_audit", "circular_markers",
        "single_line_source_layout", "source_row_font_registry", "source_glyph_equivalence",
    ):
        dependencies["app.native_objects." + dependency] = hashlib.sha256(
            Path(__file__).with_name(dependency + ".py").read_bytes()
        ).hexdigest()
    derived = {
        "path": "single_line_labels/completed_text.json",
        "sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
        "producer_module": module,
        "producer_sha256": producer_sha,
        "dependency_producers": dependencies,
        "upstream_path": "single_line_labels/upstream_completed_text.json",
        "upstream_sha256": previous["sha256"],
        "upstream_original_path": previous["path"],
        "upstream_producer": copy.deepcopy(previous),
        "source_pixels_modified": False,
        "derived_recognition_inputs_retained": True,
        "old_adoption_or_evaluation_cases_imported": False,
    }
    stage["text"] = derived
    # A text change invalidates any old ownership and downstream assembly.
    # Source-fitted geometry may still be reused, with current text ownership
    # and the original dense source checks repeated below.
    stage.pop("assembly", None)
    save_json(stage_dir / "completed_stages.json", stage)
    save_json(manifest_path, stage)
    checkpoint_artifact("completed_single_line_labels", manifest_path)
    return result


def _text_objects(text_data, consumed, deferred, gray=None):
    result = []
    issues = []
    regions = {r["id"]: r for r in text_data["regions"]}
    for g in text_data["groups"]:
        if g["id"] in consumed:
            continue
        reviewed = g.get("source_review", {})
        if g["id"] in deferred or not (g.get("complete") or reviewed.get("accepted")):
            issues.append(
                {
                    "id": g["id"],
                    "bbox_xyxy_px": g["bbox_xyxy_px"],
                    "reason": g.get("unresolved_reasons")
                    or "ANNOTATION_GROUP_INCOMPLETE",
                    "candidate_text": g.get("text"),
                }
            )
            continue
        if reviewed.get("accepted"):
            geometry = copy.deepcopy(reviewed["geometry"])
            geometry["text"] = reviewed["text"]
            kind = geometry.pop("geometry_type")
            if kind == "MTEXT":
                # Keep each source row width rather than fit every paragraph to
                # the union box. This is downstream layout metadata only.
                if [row["text"] for row in reviewed["lines"]] != geometry["lines"]:
                    raise ValueError("REVIEW_MTEXT_LINE_GEOMETRY_ORDER_MISMATCH")
                geometry["source_line_geometries"] = [
                    copy.deepcopy(row["geometry"]) for row in reviewed["lines"]
                ]
            result.append(
                {
                    "id": g["id"],
                    "kind": kind,
                    "layer": "ANNOTATION",
                    "geometry": geometry,
                    "source_evidence": g,
                    "acceptance_mode": "EXPLICIT_SOURCE_REVIEW_NOT_AUTOMATIC_RECOGNITION",
                }
            )
            continue
        x0, y0, x1, y1 = g["bbox_xyxy_px"]
        rows = [regions[rid] for rid in g["region_ids"]]
        source_evidence = g
        if len(rows) == 1:
            recovery = rows[0].get("single_line_recovery") or g.get(
                "single_line_recovery"
            )
            if recovery is not None:
                if rows[0]["text"] != g["text"]:
                    raise ValueError("SINGLE_LINE_GROUP_LITERAL_CHANGED")
                source_evidence = copy.deepcopy(g)
                source_evidence["single_line_recovery"] = copy.deepcopy(recovery)
                x0, y0, x1, y1 = rows[0]["bbox_xyxy_px"]
                source_evidence["text_layout"] = {
                    "status": "COMPLETE_SOURCE_ROW_PORTABLE_FONT_INKBOX",
                    "bbox_xyxy_px": [x0, y0, x1, y1],
                    "source_geometry_from_verified_single_line_recovery": True,
                    "font_outline_is_not_scan_ink_equality": True,
                }
            elif gray is not None:
                from .source_text_layout import choose_source_text_layout

                layout_evidence = choose_source_text_layout(
                    rows[0], gray, roi_xyxy_px=text_data["roi_xyxy_px"]
                )
                source_evidence = copy.deepcopy(g)
                source_evidence["text_layout"] = layout_evidence
                x0, y0, x1, y1 = layout_evidence["bbox_xyxy_px"]
            geometry = {
                "text": g["text"],
                "x": x0,
                "y": y1,
                "height_px": y1 - y0,
                "width_px": x1 - x0,
            }
            kind = "TEXT"
        else:
            heights = [r["bbox_xyxy_px"][3] - r["bbox_xyxy_px"][1] for r in rows]
            tops = [r["bbox_xyxy_px"][1] for r in rows]
            geometry = {
                "text": g["text"],
                "lines": [r["text"] for r in rows],
                "x": x0,
                "y": y0,
                "height_px": float(np.median(heights)),
                "width_px": x1 - x0,
                "line_pitch_px": float(np.median(np.diff(tops))),
                "bbox_xyxy_px": [x0, y0, x1, y1],
            }
            kind = "MTEXT"
            geometry["source_line_geometries"] = [
                {
                    "bbox_xyxy_px": list(r["bbox_xyxy_px"]),
                    "x": r["bbox_xyxy_px"][0],
                    "y": r["bbox_xyxy_px"][3],
                    "width_px": r["bbox_xyxy_px"][2] - r["bbox_xyxy_px"][0],
                    "height_px": r["bbox_xyxy_px"][3] - r["bbox_xyxy_px"][1],
                }
                for r in rows
            ]
        result.append(
            {
                "id": g["id"],
                "kind": kind,
                "layer": "ANNOTATION",
                "geometry": geometry,
                "source_evidence": source_evidence,
            }
        )
    return result, issues


@profiled("pipeline._repair_index")
def _repair_index(gray, roi, objects, issues, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = roi
    source = Image.fromarray(gray[y0:y1, x0:x1])
    source.save(out / "source_roi.png")
    rows = []
    for r in range(4):
        for c in range(6):
            a = int(x0 + (x1 - x0) * c / 6)
            b = int(y0 + (y1 - y0) * r / 4)
            d = int(x0 + (x1 - x0) * (c + 1) / 6)
            e = int(y0 + (y1 - y0) * (r + 1) / 4)
            rid = f"R{r * 6 + c + 1:02d}"
            name = rid + ".png"
            Image.fromarray(gray[b:e, a:d]).save(out / name)
            rows.append({"id": rid, "bbox_xyxy_px": [a, b, d, e], "source_crop": name})
    save_json(
        out / "repair_regions.json",
        {
            "regions": rows,
            "unknown_source_not_removed": True,
            "not_coverage_or_click_count": True,
            "uncertainties": issues,
        },
    )
    cards = "".join(
        f'<section><h2>{r["id"]} — {r["bbox_xyxy_px"]}</h2><img src="{r["source_crop"]}" style="max-width:100%"></section>'
        for r in rows
    )
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>原图待修对照</title><h1>全范围原图检查</h1><p>所有未完整重建内容均为待修。编号是位置网格，不是对象数或人工操作数。正式识别并不覆盖整图。</p>'
        + cards,
        encoding="utf-8",
    )
    return rows


def run_native_objects(
    input_path,
    output_path,
    roi,
    *,
    dpi=200.0,
    progress_callback=None,
    evidence_dir=None,
    cache_dir=None,
    job_config=None,
    prepared_source=None,
    connection_checkpoint=None,
):
    """Called by the existing GUI/CLI's ProductionProcessingService."""
    cv2.setNumThreads(1)
    started = time.perf_counter()
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    from .job import make_job
    from .source_import import prepare_source, file_sha
    from .platform_stats import sample, elapsed

    job = (
        job_config
        if job_config is not None
        else make_job(
            input_path,
            output_path,
            roi,
            dpi=dpi,
            evidence_dir=evidence_dir,
            cache_dir=cache_dir,
        )
    )
    if (
        job.input_path != input_path
        or job.output_path != output_path
        or tuple(roi) != job.roi
        or float(dpi) != job.dpi
    ):
        raise ValueError("PIPELINE_REQUEST_JOB_CONFIG_MISMATCH")
    prepared = prepared_source if prepared_source is not None else prepare_source(job)
    if (
        prepared.manifest["job"] != job.payload()
        or file_sha(input_path) != prepared.source_sha256
    ):
        raise ValueError("PIPELINE_PREPARED_SOURCE_IDENTITY_MISMATCH")
    if connection_checkpoint is not None:
        from .connection_checkpoint import run_connection_checkpoint

        return run_connection_checkpoint(
            job, prepared, connection_checkpoint, progress_callback=progress_callback
        )
    gray = prepared.gray
    roi = prepared.working_roi
    cache_dir = job.cache_dir
    dpi = job.dpi
    source_sha = prepared.source_sha256
    import_manifest = prepared.manifest
    metadata_dpi = import_manifest["selection"]["source_metadata_dpi"]
    metadata_dpi_evidence = import_manifest["selection"]["source_metadata_dpi_original"]
    x0, y0, x1, y1 = roi
    resource_start = sample()
    if output_path.exists():
        raise FileExistsError("EXISTING_DXF_NOT_OVERWRITTEN:" + str(output_path))
    out = job.evidence_dir
    out.mkdir(parents=True, exist_ok=True)
    trace = []

    def progress(stage, fraction):
        check_cancel(stage)
        trace.append(
            {
                "stage": stage,
                "fraction": fraction,
                "elapsed_wall_seconds": time.perf_counter() - started,
                "job_id": job.job_id,
            }
        )
        save_json(out / "pipeline_trace.json", trace)
        if progress_callback:
            progress_callback(stage, fraction)

    stage_identity = {
        "source_sha256": source_sha,
        "roi_xyxy_px": list(roi),
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "source_array_sha256": import_manifest["working_array_sha256"],
        "job_source_identity": import_manifest["cache_identity"],
    }
    save_json(
        out / "input_contract.json",
        {
            "source_path": str(input_path),
            "source_sha256": source_sha,
            "roi_xyxy_px": list(roi),
            "source_size_px": [gray.shape[1], gray.shape[0]],
            "dpi": dpi,
            "source_metadata_dpi": metadata_dpi,
            "source_metadata_dpi_original": metadata_dpi_evidence,
            "coordinate_system": "job_working_pixels_top_left",
            "legacy_algorithm_coordinate_label": "source_pixels_top_left scoped by this job",
            "job_id": job.job_id,
            "job_config": job.payload(),
            "source_import_manifest": str(out / "import_manifest.json"),
            "coordinate_transforms": import_manifest["coordinates"],
            "source_resolution_changed": False
            if import_manifest["selection"]["format"] != "PDF"
            else None,
            "PDF_rasterized_at_explicit_DPI": import_manifest["selection"]["format"]
            == "PDF",
            "recognition_raster_rescaled_after_decode": False,
            "recognition_raster_rescaled_after_decode_scope": "immutable task working raster only",
            "local_derived_recognition_inputs": "separately recorded and replayed; never replace the task source",
            "tolerances": TOLERANCES,
            "core_reads_test_cases_or_expected_text": False,
            "engineering_scale": "UNVERIFIED_PAPER_MM_ONLY",
        },
    )
    try:
        restored_assembly = _completed_assembly_checkpoint(cache_dir, stage_identity)
        if restored_assembly is not None:
            texts = restored_assembly["texts"]
            _restore_single_line_label_evidence(cache_dir, out, texts)
            geometry = restored_assembly["geometry"]
            annotations = restored_assembly["annotations"]
            doors = restored_assembly["doors"]
            door_completion = restored_assembly["door_completion"]
            connections = restored_assembly["connections"]
            from .completion_stages import restore_connection_discovery_evidence

            connections["raw_discovery_evidence"] = (
                restore_connection_discovery_evidence(
                    cache_dir,
                    out / "connections",
                    gray,
                    binding=connections.get("raw_discovery_evidence"),
                    objects=connections["objects"],
                )
            )
            circular_markers = restored_assembly["circular_markers"]
            text_contact_completion = restored_assembly.get("text_contact_completion", {})
            _restore_text_contact_evidence(out, text_contact_completion)
            _restore_circular_marker_evidence(cache_dir, out, circular_markers)
            walls = restored_assembly["walls"]
            objects = restored_assembly["objects"]
            issues = restored_assembly["issues"]
            text_producer = restored_assembly["text_producer"]
            text_objects = restored_assembly["text_objects"]
            save_json(
                out / "assembly_resume.json",
                {
                    "previous_evidence": str(cache_dir),
                    "new_source_fits": 0,
                    "new_OCR_calls": 0,
                    "source_and_algorithm_identity_rechecked": True,
                },
            )
            save_json(
                out / "assembly.json", {"objects": objects, "uncertainties": issues}
            )
            saved = out / "completed_assembly.json"
            save_json(saved, restored_assembly)
            from app.core.native_job_manager import algorithm_fingerprint

            save_json(
                out / "completed_stages.json",
                {
                    **stage_identity,
                    "assembly": {
                        "path": "completed_assembly.json",
                        "sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
                        "algorithm_fingerprint": algorithm_fingerprint(),
                    },
                },
            )
            checkpoint_artifact(
                "restored_completed_assembly", out / "completed_stages.json"
            )
            progress("RESTORED_COMPLETE_ASSEMBLY_WITHOUT_REFITTING", 0.74)
        else:
            progress("TEXT_REGIONS_AND_COMPLETE_GROUPS", 0.05)
            text_cache = Path(cache_dir) / "text_ocr_cache" if cache_dir else None
            if text_cache is not None and not text_cache.is_dir():
                text_cache = None
            texts, resume_evidence = _completed_text_checkpoint(
                cache_dir,
                source_sha,
                roi,
                gray.shape,
                import_manifest["working_array_sha256"],
            )
            if texts is None:
                restore_partial_ocr(out / "text")
                texts = extract_text_regions(
                    gray,
                    roi,
                    out / "text",
                    progress_callback=_text_progress_adapter(progress),
                    cache_dir=text_cache,
                    dpi=dpi,
                )
            else:
                save_json(out / "text_resume.json", resume_evidence)
            # Save a portable stage result even when later assembly raises. This
            # enables a genuine continuation without repeating completed OCR.
            saved_text = (
                _restore_completed_text_assets(
                    cache_dir, out, resume_evidence["producer_row"]
                )
                if resume_evidence
                else out / "completed_text.json"
            )
            if not resume_evidence:
                save_json(saved_text, texts)
            from . import text_regions

            text_producer = (
                copy.deepcopy(resume_evidence["producer_row"])
                if resume_evidence
                else {
                    "producer_module": "app.native_objects.text_regions",
                    "producer_sha256": hashlib.sha256(
                        Path(text_regions.__file__).read_bytes()
                    ).hexdigest(),
                }
            )
            text_producer.update(
                path=saved_text.relative_to(out).as_posix(),
                sha256=hashlib.sha256(saved_text.read_bytes()).hexdigest(),
            )
            stage_manifest = {**stage_identity, "text": text_producer}
            discovery = out / "text/discovery_observations.json"
            if discovery.is_file():
                stage_manifest["discovery"] = {
                    "path": "text/discovery_observations.json",
                    "sha256": hashlib.sha256(discovery.read_bytes()).hexdigest(),
                }
            elif resume_evidence:
                previous = json.loads(Path(resume_evidence["manifest"]).read_text(encoding="utf-8"))
                if previous.get("discovery"):
                    discovery = _discovery_for_resume(cache_dir, out, texts)
                    stage_manifest["discovery"] = {
                        "path": "text/discovery_observations.json",
                        "sha256": hashlib.sha256(discovery.read_bytes()).hexdigest(),
                    }
            save_json(out / "completed_stages.json", stage_manifest)
            checkpoint_artifact("completed_text", out / "completed_stages.json")
            if resume_evidence:
                progress("RESTORED_COMPLETE_TEXT_CHECKPOINT", 0.30)
            if (
                text_producer.get("producer_module", "app.native_objects.text_regions")
                == "app.native_objects.text_regions"
            ):
                # This recovery is part of the real entry, not an external answer
                # file. A resumed derived stage is never recognised again.
                from .text_line_domains import refine_text_line_domains

                if text_cache is None:
                    text_cache = out / "discovery_cache"
                    text_cache.mkdir(parents=True, exist_ok=True)
                    discovery = _discovery_for_resume(cache_dir, out, texts)
                    save_json(
                        text_cache / "observations.json",
                        json.loads(discovery.read_text(encoding="utf-8")),
                    )
                    save_json(
                        text_cache / "manifest.json",
                        {
                            "source_array_sha256": texts["source_array_sha256"],
                            "source_size_px": [gray.shape[1], gray.shape[0]],
                            "roi_xyxy_px": list(roi),
                            "coordinate_system": "source_pixels_top_left",
                            "observations_file": "observations.json",
                            "observations_sha256": hashlib.sha256(
                                (text_cache / "observations.json").read_bytes()
                            ).hexdigest(),
                        },
                    )
                provenance = {
                    "source_path": str(input_path),
                    "source_sha256": source_sha,
                    "text_path": str(saved_text),
                    "text_sha256": hashlib.sha256(saved_text.read_bytes()).hexdigest(),
                    "producer_sha256": text_producer["producer_sha256"],
                    "manifest_path": str(out / "completed_stages.json"),
                    "manifest_sha256": hashlib.sha256(
                        (out / "completed_stages.json").read_bytes()
                    ).hexdigest(),
                    "text_evidence_dir": str(out / "text"),
                }
                texts = refine_text_line_domains(
                    gray,
                    texts,
                    out / "text_domain_recovery",
                    cache_dir=text_cache,
                    upstream_provenance=provenance,
                    progress_callback=_text_progress_adapter(progress),
                    dpi=dpi,
                )
                derived = json.loads(
                    (out / "text_domain_recovery/completed_stages.json").read_text(encoding="utf-8")
                )
                derived["text"]["path"] = "text_domain_recovery/completed_text.json"
                derived.update(stage_identity)
                if stage_manifest.get("discovery"):
                    derived["discovery"] = stage_manifest["discovery"]
                save_json(out / "completed_stages.json", derived)
                checkpoint_artifact(
                    "completed_text_domains", out / "completed_stages.json"
                )
            current_text_stage = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
            current_producer = current_text_stage["text"].get("producer_module")
            if current_producer not in (
                "app.native_objects.source_review",
                "app.native_objects.text_block_rescue",
                "app.native_objects.cross_engine_text",
                "app.native_objects.source_text_completion",
                "app.native_objects.single_line_labels",
                "app.native_objects.source_text_ownership",
            ):
                from .text_block_rescue import refine_text_blocks

                discovery = _discovery_for_resume(cache_dir, out, texts)
                texts = refine_text_blocks(
                    gray,
                    texts,
                    out / "text_block_rescue",
                    source_sha=source_sha,
                    upstream_path=out / current_text_stage["text"]["path"],
                    observation_path=discovery,
                    dpi=dpi,
                    progress_callback=_text_progress_adapter(progress),
                    completed_ocr_checkpoint=(
                        Path(cache_dir) / "text_block_rescue"
                        if cache_dir
                        and (
                            Path(cache_dir)
                            / "text_block_rescue/policy_and_selection.json"
                        ).is_file()
                        else None
                    ),
                )
                derived = json.loads(
                    (out / "text_block_rescue/completed_stages.json").read_text(encoding="utf-8")
                )
                derived["text"]["path"] = "text_block_rescue/completed_text.json"
                derived.update(stage_identity)
                if current_text_stage.get("discovery"):
                    derived["discovery"] = current_text_stage["discovery"]
                save_json(out / "completed_stages.json", derived)
                checkpoint_artifact(
                    "completed_text_blocks", out / "completed_stages.json"
                )
            current_text_stage = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
            if current_text_stage["text"].get("producer_module") not in (
                "app.native_objects.source_review",
                "app.native_objects.cross_engine_text",
                "app.native_objects.source_text_completion",
                "app.native_objects.single_line_labels",
                "app.native_objects.source_text_ownership",
            ):
                from .cross_engine_text import refine_cross_engine

                texts = refine_cross_engine(
                    gray,
                    texts,
                    out / "cross_engine_text",
                    source_sha=source_sha,
                    upstream_path=out / current_text_stage["text"]["path"],
                    dpi=dpi,
                    progress_callback=_text_progress_adapter(progress),
                )
                derived = json.loads(
                    (out / "cross_engine_text/completed_stages.json").read_text(encoding="utf-8")
                )
                derived["text"]["path"] = "cross_engine_text/completed_text.json"
                derived.update(stage_identity)
                if current_text_stage.get("discovery"):
                    derived["discovery"] = current_text_stage["discovery"]
                save_json(out / "completed_stages.json", derived)
                checkpoint_artifact(
                    "completed_cross_engine_text", out / "completed_stages.json"
                )
            current_text_stage = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
            if current_text_stage["text"].get("producer_module") not in (
                "app.native_objects.source_review",
                "app.native_objects.source_text_completion",
                "app.native_objects.single_line_labels",
                "app.native_objects.source_text_ownership",
            ):
                from .source_text_completion import refine_source_text_completion

                progress("COMPLETE_BOUNDED_SOURCE_TEXT_QUEUE", 0.31)
                texts = refine_source_text_completion(
                    gray,
                    texts,
                    out / "source_text_completion",
                    source_sha=source_sha,
                    upstream_path=out / current_text_stage["text"]["path"],
                    evidence_root=out,
                    dpi=dpi,
                    progress_callback=_text_progress_adapter(progress),
                    completed_ocr_checkpoint=(
                        Path(cache_dir) / "source_text_completion"
                        if cache_dir
                        and (
                            Path(cache_dir)
                            / "source_text_completion/frozen_manifest.json"
                        ).is_file()
                        else None
                    ),
                )
                derived = json.loads(
                    (out / "source_text_completion/completed_stages.json").read_text(encoding="utf-8")
                )
                derived["text"]["path"] = "source_text_completion/completed_text.json"
                derived.update(stage_identity)
                if current_text_stage.get("discovery"):
                    derived["discovery"] = current_text_stage["discovery"]
                save_json(out / "completed_stages.json", derived)
                checkpoint_artifact(
                    "completed_bounded_source_text_queue", out / "completed_stages.json"
                )
            texts = _complete_single_line_stage(
                gray, texts, out, source_sha, roi, dpi, progress
            )
            text_producer = copy.deepcopy(
                json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))["text"]
            )
            progress("TEXT_CONTRACT_TO_GEOMETRY", 0.32)
            geometry = _completed_geometry_checkpoint(
                cache_dir, source_sha, roi, texts, gray, out / "geometry"
            )
            if geometry is None:
                geometry = extract_lines(gray, roi, texts, out / "geometry")
            if text_producer.get("producer_module") not in (
                "app.native_objects.source_review",
                "app.native_objects.source_text_ownership",
            ):
                from . import source_text_ownership

                responsibility_root = out / "text_geometry_ownership"
                original_fits = responsibility_root / "source_fitted_dictionary.json"
                save_json(original_fits, geometry)
                from . import geometry as geometry_module

                stage_manifest = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
                stage_manifest["geometry"] = {
                    "path": "text_geometry_ownership/source_fitted_dictionary.json",
                    "sha256": hashlib.sha256(original_fits.read_bytes()).hexdigest(),
                    "producer_sha256": hashlib.sha256(
                        Path(geometry_module.__file__).read_bytes()
                    ).hexdigest(),
                    "role": "SOURCE_FITTED_DICTIONARY_REQUIRES_CURRENT_TEXT_AND_DENSE_GATE",
                    "current_text_responsibility_still_to_be_rechecked": True,
                }
                save_json(out / "completed_stages.json", stage_manifest)
                checkpoint_artifact(
                    "completed_source_fitted_dictionary_before_ownership",
                    out / "completed_stages.json",
                )
                texts, ownership_audit = (
                    source_text_ownership.reconcile_source_text_ownership(
                        texts, gray, roi, geometry, output_dir=responsibility_root,
                        evidence_root=out,
                    )
                )
                upstream_text_root = (out / text_producer["path"]).parent
                texts["region_evidence_roots"] = {
                    r["id"]: relative_evidence_path(
                        (
                            upstream_text_root
                            / texts.get("region_evidence_roots", {}).get(r["id"], ".")
                        ).resolve(),
                        responsibility_root,
                    )
                    for r in texts["regions"]
                }
                if texts.get("bbox_overlay"):
                    texts["bbox_overlay"] = relative_evidence_path(
                        upstream_text_root / texts["bbox_overlay"], responsibility_root
                    )
                raw_checks = []
                for region in texts["regions"]:
                    raw_root = (
                        responsibility_root
                        / texts["region_evidence_roots"][region["id"]]
                    )
                    for alt in region.get("completeness_evidence", {}).get(
                        "alternatives", []
                    ):
                        artifact = alt.get("raw_artifact", {})
                        raw = (
                            raw_root / (artifact.get("path") or alt["raw_tsv"])
                        ).resolve()
                        if out.resolve() not in raw.parents or not raw.is_file():
                            raise ValueError(
                                "OWNERSHIP_DERIVATION_RAW_REFERENCE_MISSING:" + str(raw)
                            )
                        actual = hashlib.sha256(raw.read_bytes()).hexdigest()
                        if artifact.get("sha256") and artifact["sha256"] != actual:
                            raise ValueError(
                                "OWNERSHIP_DERIVATION_RAW_HASH_CHANGED:" + str(raw)
                            )
                        raw_checks.append(
                            {
                                "region_id": region["id"],
                                "path": raw.relative_to(out.resolve()).as_posix(),
                                "sha256": actual,
                            }
                        )
                save_json(
                    responsibility_root / "raw_reference_path_audit.json",
                    {
                        "all_references_resolve": True,
                        "checked_references": raw_checks,
                        "raw_bytes_rewritten": False,
                        "recognition_decisions_changed": False,
                    },
                )
                validate_text_regions(texts, gray.shape, roi)
                saved_text = responsibility_root / "completed_text.json"
                save_json(saved_text, texts)
                dependencies = text_producer.get("dependency_producers", {})
                dependencies = (
                    dict(dependencies)
                    if isinstance(dependencies, dict)
                    else {d["module"]: d["sha256"] for d in dependencies}
                )
                dependencies[text_producer["producer_module"]] = text_producer[
                    "producer_sha256"
                ]
                text_producer = {
                    "path": "text_geometry_ownership/completed_text.json",
                    "sha256": hashlib.sha256(saved_text.read_bytes()).hexdigest(),
                    "producer_module": "app.native_objects.source_text_ownership",
                    "producer_sha256": hashlib.sha256(
                        Path(source_text_ownership.__file__).read_bytes()
                    ).hexdigest(),
                    "dependency_producers": dependencies,
                    "source_fitted_dictionary_path": "text_geometry_ownership/source_fitted_dictionary.json",
                    "source_fitted_dictionary_sha256": hashlib.sha256(
                        original_fits.read_bytes()
                    ).hexdigest(),
                    "source_pixels_modified": False,
                    "transcription_decisions_modified": False,
                }
                stage_manifest = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
                stage_manifest["text"] = text_producer
                save_json(out / "completed_stages.json", stage_manifest)
                checkpoint_artifact(
                    "completed_source_text_ownership", out / "completed_stages.json"
                )
                geometry = _reclassify_source_fitted_lines(
                    geometry,
                    texts,
                    gray.shape,
                    roi,
                    original_dictionary_sha256=text_producer[
                        "source_fitted_dictionary_sha256"
                    ],
                )
                save_json(out / "geometry/lines_after_source_ownership.json", geometry)
            geometry = _dense_line_gate(gray, roi, geometry, out / "geometry")
            saved_geometry = out / "completed_geometry.json"
            save_json(saved_geometry, geometry)
            from . import geometry as geometry_module

            stage_manifest = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
            stage_manifest["geometry"] = {
                "path": "completed_geometry.json",
                "sha256": hashlib.sha256(saved_geometry.read_bytes()).hexdigest(),
                "producer_sha256": hashlib.sha256(
                    Path(geometry_module.__file__).read_bytes()
                ).hexdigest(),
            }
            save_json(out / "completed_stages.json", stage_manifest)
            checkpoint_artifact("completed_geometry", out / "completed_stages.json")
            progress("COMPLETE_ROOM_ANNOTATIONS", 0.5)
            annotations = assemble_annotations(
                gray, roi, texts, geometry["objects"], out / "annotations"
            )
            progress("PRESERVE_AND_CHECK_NATIVE_DOOR", 0.57)
            doors = _doors(gray, roi, input_path, out / "doors", cache_dir)
            from .completion_stages import (
                complete_doors_with_responsibility,
                complete_connections_without_unresolved_retirement,
            )
            from .door_completion import retire_door_fragments

            progress("COMPLETE_SOURCE_DOORS_AND_EDIT_RESPONSIBILITY", 0.59)
            door_completion = complete_doors_with_responsibility(
                gray,
                roi,
                input_path,
                source_sha,
                geometry,
                doors["objects"],
                out / "door_completion",
                cache_dir,
            )
            door_objects = door_completion["objects"]
            door_partition = retire_door_fragments(
                annotations["remaining_lines"], door_objects
            )
            save_json(
                out / "door_completion/final_line_responsibility.json", door_partition
            )
            line_bank = door_partition["remaining_lines"]
            door_conflicts = door_completion["uncertainties"]
            progress("SOURCE_WALL_SPANS_CORNERS_OPENINGS", 0.63)
            walls = assemble_walls(
                gray,
                roi,
                line_bank,
                out / "walls",
                candidate_lines=geometry.get("pre_dedup_line_candidates", []),
                candidate_groups=geometry.get("line_candidate_groups", []),
            )
            from .wall_partition_gate import enforce_partition_source_gate

            walls = enforce_partition_source_gate(gray, line_bank, walls, out / "walls")
            text_objects, text_issues = _text_objects(
                texts,
                set(annotations["consumed_text_group_ids"]),
                set(annotations.get("deferred_text_group_ids", [])),
                gray=gray,
            )
            save_json(
                out / "text_layout_audit.json",
                {
                    "source_sha256": source_sha,
                    "recognition_decisions_and_source_masks_unchanged": True,
                    "objects": [
                        {
                            "id": o["id"],
                            "kind": o["kind"],
                            "geometry": o["geometry"],
                            "layout_evidence": o["source_evidence"].get("text_layout"),
                        }
                        for o in text_objects
                    ],
                },
            )
            objects = (
                walls["remaining_lines"]
                + annotations["objects"]
                + walls["objects"]
                + door_objects
                + text_objects
            )
            progress("WHOLE_SOURCE_CONNECTION_PATHS", 0.69)
            # Fresh imports use the same raw-source verification as bounded
            # continuation. A candidate mask alone is never a glyph verdict.
            # Rotated working rasters retain the existing conservative rule
            # until their raw-observation coordinate adapter is implemented.
            verified_text_observations = None
            if job.orientation_cw == 0:
                from .checkpoint_text_observations import (
                    verify_current_job_observations,
                )

                verified_text_observations = verify_current_job_observations(
                    texts, out, input_path, source_sha,
                    {"roi": list(roi), "dpi": dpi, "orientation": 0,
                     "page_number": job.page_number,
                     "frame_number": job.frame_number},
                    text_artifact_path=saved_text, gray=gray,
                )
            save_json(out / "text_graph_source_verification.json", {
                "status": (
                    "CURRENT_RAW_OBSERVATIONS_VERIFIED"
                    if verified_text_observations and verified_text_observations.get("validated")
                    else "KEEP_CONSERVATIVE_CANDIDATE_TEXT_PROTECTION"
                ),
                "verification": verified_text_observations,
                "new_OCR_calls": 0,
                "source_pixels_modified": False,
            })
            connections = complete_connections_without_unresolved_retirement(
                gray,
                roi,
                source_sha,
                objects,
                out / "connections",
                cache_dir,
                text_regions=texts,
                verified_text_observations=verified_text_observations,
            )
            retired_connection_lines = set(connections["retired_ids"])
            objects = [obj for obj in objects if obj["id"] not in retired_connection_lines]
            objects += connections["objects"]
            progress("SOURCE_CIRCULAR_MARKERS_AND_INDEPENDENT_CHARACTERS", 0.71)
            from .circular_marker_adoption import complete_circular_markers

            # Connection observations only seed source geometry. They carry no
            # approval, glyph answer or ownership of an external connection.
            round_observation_path = out / "connections/discovery/connections.json"
            observed_rounds = (
                json.loads(round_observation_path.read_text(encoding="utf-8")).get(
                    "round_boundary_observations"
                )
                if round_observation_path.is_file() else None
            )
            circular_markers = complete_circular_markers(
                gray, roi, source_sha, objects, out / "circular_markers", dpi=dpi,
                text_regions=texts, observed_rounds=observed_rounds,
                progress_callback=lambda event: progress(
                    "CIRCULAR_MARKER:" + event["stage"],
                    0.71 + 0.025 * min(1.0, event["processed"] / max(1, event["total"])),
                ),
            )
            retired_marker_members = set(circular_markers["retired_ids"])
            objects = [obj for obj in objects if obj["id"] not in retired_marker_members]
            objects += circular_markers["objects"]
            endpoint_updates = {
                obj["id"]: obj for obj in circular_markers.get(
                    "source_white_gap_protection", {}
                ).get("replacements", [])
            }
            endpoint_updates.update({
                obj["id"]: obj for obj in circular_markers.get(
                    "external_endpoint_contacts", {}
                ).get("replacements", [])
            })
            objects = [endpoint_updates.get(obj["id"], obj) for obj in objects]
            text_contact_completion = {}
            if texts.get("text_contact_geometry_plans"):
                progress("COMPLETE_INDEPENDENT_TEXT_CONTACT_PATHS", 0.74)
                from .text_contact_adoption import complete_text_contact_paths

                text_contact_completion = complete_text_contact_paths(
                    gray, roi, source_sha, objects,
                    texts["text_contact_geometry_plans"], out / "text_contact",
                )
                retired_contact_parts = set(text_contact_completion["retired_ids"])
                objects = [obj for obj in objects if obj["id"] not in retired_contact_parts]
                objects += text_contact_completion["objects"]
            objects, circular_markers = _finalize_circle_relations(
                gray, roi, objects, circular_markers, out / "circular_markers",
            )
            issues = (
                geometry["uncertainties"]
                + annotations["uncertainties"]
                + doors["uncertainties"]
                + door_conflicts
                + text_issues
            )
            issues += connections["uncertainties"]
            issues += circular_markers["uncertainties"]
            issues += text_contact_completion.get("uncertainties", [])
            issues += walls.get("uncertainties", [])
            issues += [
                {"reason": "WALL_EDIT_PARTITION_REJECTED_SOURCE_GATE", **row}
                for row in walls.get("partition_source_gate", {}).get(
                    "failed_derived_fragments", []
                )
            ]
            save_json(
                out / "assembly.json",
                {
                    "objects": objects,
                    "uncertainties": issues,
                    "door_line_conflicts": door_conflicts,
                    "counts": {
                        "room_annotations": len(annotations["objects"]),
                        "wall_segments": len(walls["objects"]),
                        "doors": len(door_objects),
                        "whole_connection_paths": len(connections["objects"]),
                        "independent_text_contact_paths": len(text_contact_completion.get("objects", [])),
                        "complete_circular_markers": circular_markers["summary"]["new_complete_markers"],
                        "circle_text_compositions": circular_markers["summary"]["circle_text_compositions"],
                        "partial_circular_boundaries": circular_markers["summary"]["new_partial_boundaries"],
                        "partial_circular_compositions": circular_markers["summary"]["partial_compositions"],
                        "TEXT": sum(o["kind"] == "TEXT" for o in text_objects),
                        "MTEXT": sum(o["kind"] == "MTEXT" for o in text_objects),
                    },
                },
            )
            from app.core.native_job_manager import algorithm_fingerprint

            assembled = {
                "texts": texts,
                "geometry": geometry,
                "annotations": annotations,
                "doors": doors,
                "door_completion": door_completion,
                "connections": connections,
                "circular_markers": circular_markers,
                "text_contact_completion": text_contact_completion,
                "walls": walls,
                "objects": objects,
                "issues": issues,
                "text_producer": text_producer,
                "text_objects": text_objects,
            }
            completed_assembly = out / "completed_assembly.json"
            save_json(completed_assembly, assembled)
            stage_manifest = json.loads((out / "completed_stages.json").read_text(encoding="utf-8"))
            stage_manifest["assembly"] = {
                "path": "completed_assembly.json",
                "sha256": hashlib.sha256(completed_assembly.read_bytes()).hexdigest(),
                "algorithm_fingerprint": algorithm_fingerprint(),
            }
            save_json(out / "completed_stages.json", stage_manifest)
            checkpoint_artifact("completed_assembly", out / "completed_stages.json")
        progress("ACTUAL_NATIVE_DXF_SAVE", 0.75)
        export_objects(objects, output_path, roi, dpi, source_sha)
        progress("SAVED_DXF_COLD_READ_AND_SOURCE_AUDIT", 0.82)
        audit = cold_audit(output_path, gray, roi, dpi, out / "cold_audit.json")
        progress("INDEPENDENT_DXF_MUPDF_RENDER", 0.9)
        preview = output_path.with_suffix(".png")
        render = render_saved(output_path, preview, roi, dpi)
        render_saved(
            output_path,
            output_path.with_name(output_path.stem + "_review.png"),
            roi,
            dpi,
            True,
        )
        _repair_index(gray, roi, objects, issues, out / "repair")
        progress("CURRENT_INPUT_BIDIRECTIONAL_QUALITY_REVIEW", 0.94)
        from .quality_review import run_quality_review

        quality = run_quality_review(
            output_path,
            gray,
            roi,
            dpi,
            objects,
            texts,
            issues,
            import_manifest,
            out,
            cold_audit=audit,
            render=render,
        )
        checkpoint_artifact(
            "completed_current_input_review", out / "quality_review.json"
        )
        passed = _saved_dxf_accepted(audit)
        report = {
            "status": "LOCAL_NATIVE_CANDIDATE_PENDING_SOURCE_QA_AND_CAD_UAT"
            if passed
            else "LOCAL_NO_GO_SOURCE_OR_STRUCTURE_AUDIT",
            "formal_entry_called_new_pipeline": True,
            "pipeline_module": __name__,
            "source_sha256": source_sha,
            "dxf_path": str(output_path),
            "preview_path": str(preview),
            "evidence_dir": str(out),
            "source_gate_pass": audit["source_gate_pass"],
            "native_modelspace_types": audit["formal_modelspace_types"],
            "expanded_native_types": audit["expanded_formal_types"],
            "room_block_definitions_are_unique": audit[
                "room_block_definitions_are_unique"
            ],
            "text_regions_consumed": geometry["text_interface"]["regions_received"],
            "source_cases_are_validation_only": True,
            "fire_classification": "UNCONFIRMED",
            "machine_wall_seconds": time.perf_counter() - started,
            "CAD_GUI": "NOT_RUN_BY_PIPELINE",
            "engineer_time": "NOT_MEASURED",
            "full_page_or_production_GO": False,
            "render": render,
            "text_stage_resources": texts.get("resources"),
            "wall_counts": walls["counts"],
            "observed_wall_corners": len(walls["corners"]),
            "observed_openings": len(walls["openings"]),
            "door_cache_hit": doors["cache_hit"],
            "existing_tolerances_not_relaxed": True,
            "door_completion": {
                "raw_candidates": door_completion["raw_candidate_count"],
                "new_complete_responsibility_objects": door_completion[
                    "new_adopted_count"
                ],
                "replay": door_completion["replay"],
            },
            "connection_completion": {
                "raw_candidates": connections["raw_candidate_count"],
                "whole_objects": len(connections["objects"]),
                "existing_entities_modified": 0,
                "replay": connections["replay"],
                "engineering_stroke_identity_proven": False,
            },
            "circular_marker_completion": circular_markers["summary"],
            "single_line_label_recovery": texts.get("single_line_label_recovery"),
            "text_contact_completion": {
                "new_complete_graphics": len(text_contact_completion.get("objects", [])),
                "retired_old_graphic_ids": text_contact_completion.get("retired_ids", []),
                "decisions": text_contact_completion.get("decisions", []),
                "actual_saved_source_checks": audit.get("text_contact_source_checks"),
                "text_and_graphic_objects_counted_separately": True,
            },
            "wall_partition_source_gate": walls.get("partition_source_gate"),
        }
        report.update(
            job_id=job.job_id,
            job_config=job.payload(),
            source_import_manifest=str(out / "import_manifest.json"),
            source_to_working_to_CAD=import_manifest["coordinates"],
            original_source_unchanged=file_sha(input_path) == source_sha,
        )
        report.update(
            quality_path=str(out / "quality_review.json"),
            quality_summary=quality["summary"],
            issue_path=str(out / "quality_issues.json"),
            source_roi_path=str(out / "quality_source_roi.png"),
            review_binding_sha256=quality["binding"]["binding_sha256"],
            visual_review_capability="local_Tesseract_and_deployed_deterministic_rules_no_chat_or_network_model",
        )
        report["source_review_branch"] = (
            text_producer.get("producer_module") == "app.native_objects.source_review"
        )
        report["source_review_is_new_automatic_recognition"] = False
        report_path = output_path.with_suffix(".report.json")
        save_json(report_path, report)
        progress("COMPLETE_WITH_EXPLICIT_UNCERTAINTIES", 1.0)
        return {**report, "report_path": str(report_path), "objects": objects}
    except NativeCancelled as exc:
        save_json(
            out / "pipeline_cancelled.json",
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "last_reached_stage": trace[-1] if trace else None,
                "completed_stage_manifest": str(out / "completed_stages.json"),
                "unpublished_draft_DXF_may_exist": output_path.is_file(),
                "old_engine_fallback_attempted": False,
            },
        )
        raise
    except Exception as exc:
        save_json(
            out / "pipeline_failure.json",
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
                "last_successful_stage": trace[-1] if trace else None,
                "old_engine_fallback_attempted": False,
            },
        )
        raise
    finally:
        save_json(
            out / "pipeline_resources.json",
            {
                "job_id": job.job_id,
                "source_sha256": source_sha,
                "resources": elapsed(resource_start),
                "scope": "pipeline after explicit import; entry resource report includes import",
            },
        )
