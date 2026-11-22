"""Explicit, source-bound reuse of published observations for a new revision.

The new task repeats adoption, ownership and final review. Only immutable raw
observations, completed text evidence and source-fitted geometry are imported.
No published DXF, assembly, approval list or edit responsibility is a cache.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

from .execution import atomic_json, file_sha, read_json, utc_now
from .resume_checkpoint import (
    _require,
    _verify_file,
    _within,
    _verify_ocr,
    _raw_reference_checks,
)


_PRODUCERS = (
    "text_regions",
    "text_line_domains",
    "text_block_rescue",
    "cross_engine_text",
    "independent_recognizer",
    "geometry",
    "door_detector",
    "door_completion",
    "connections",
    "connection_core_routes",
    "text_graph_support",
    "checkpoint_text_observations",
    "source_endpoint_caps",
    "contracts",
    "source_import",
    "job",
)
_ROOTS = (
    "completed_text.json",
    "completed_geometry.json",
    "text",
    "text_domain_recovery",
    "text_block_rescue",
    "cross_engine_text",
    "geometry",
    "source_text_completion",
    "single_line_labels",
    "text_geometry_ownership",
)
_DERIVED_PRODUCERS = (
    "source_text_completion",
    "source_text_ownership",
    "text_confirmation",
    "text_context_ownership",
)
_SINGLE_LINE_PRODUCERS = ("single_line_labels", "circle_character_recognition")


def _dependency_items(row):
    dependencies = row.get("dependency_producers", {})
    return (
        list(dependencies.items())
        if isinstance(dependencies, dict)
        else [(item["module"], item["sha256"]) for item in dependencies]
    )


def _has_single_line_producer(row):
    module = "app.native_objects.single_line_labels"
    return row.get("producer_module") == module or any(
        name == module for name, _ in _dependency_items(row)
    )


def _revision_producer_names(row):
    names = list(_PRODUCERS)
    if row.get("producer_module") in {
        "app.native_objects." + name
        for name in (*_DERIVED_PRODUCERS, *_SINGLE_LINE_PRODUCERS)
    }:
        names += list(_DERIVED_PRODUCERS)
    if _has_single_line_producer(row):
        names += list(_SINGLE_LINE_PRODUCERS)
    return names


def _canonical_digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _producer_checks(producers):
    app = Path(__file__).resolve().parents[2]
    required = {"app.native_objects." + x for x in _PRODUCERS}
    single_line = {"app.native_objects." + x for x in _SINGLE_LINE_PRODUCERS}
    allowed = (
        required | {"app.native_objects." + x for x in _DERIVED_PRODUCERS} | single_line
    )
    _require(required <= set(producers) <= allowed, "REVISION_PRODUCER_SET_CHANGED")
    _require(
        not (set(producers) & single_line) or single_line <= set(producers),
        "REVISION_SINGLE_LINE_PRODUCER_SET_INCOMPLETE",
    )
    for module, expected in producers.items():
        _verify_file(_within(app, module.replace(".", "/") + ".py"), expected, module)


def _replay_single_line_result(observation, gray, roi, evidence):
    """Replay both adopted and explicitly rejected immutable observations.

    The production verifier intentionally never approves a rejected label.
    Its final rejection is usable here only when every saved decision, result
    and execution count also equals a fresh decision from the already checked
    raw views. A pending observation never becomes an adopted text object.
    """
    from . import single_line_labels as labels

    proof = observation.get("evidence")
    _require(isinstance(proof, dict), "REVISION_SINGLE_LINE_PROOF_MISSING")
    replay = labels.verify_single_line_label_evidence(gray, roi, proof, evidence)
    decision = labels._decision(
        proof["tesseract_views"], proof["ppocr_views"], proof["source_partition"]
    )
    _require(
        decision == proof.get("decision")
        and isinstance(observation.get("accepted"), bool)
        and observation["accepted"] is decision["accepted"]
        and observation.get("text") == decision["text"]
        and observation.get("reasons") == decision["reasons"]
        and observation.get("bbox_xyxy_px") == proof.get("source_bbox_xyxy_px")
        and observation.get("geometry") == proof.get("text_geometry"),
        "REVISION_SINGLE_LINE_SAVED_DECISION_CHANGED",
    )
    for field, views, flag in (
        ("new_Tesseract_calls", "tesseract_views", "command_executed_for_this_request"),
        ("new_model_calls", "ppocr_views", "model_inference_executed_for_this_request"),
    ):
        count = sum(view[flag] for view in proof[views])
        _require(
            observation.get(field) == proof.get(field) == count,
            "REVISION_SINGLE_LINE_EXECUTION_COUNT_CHANGED",
        )
    if decision["accepted"]:
        _require(
            replay.get("pass") is True,
            "REVISION_SINGLE_LINE_SOURCE_REPLAY_FAILED:" + str(replay),
        )
    else:
        _require(
            replay.get("pass") is False
            and replay.get("reason") == "SINGLE_LINE_RAW_DECISION_NOT_APPROVED"
            and proof.get("text_geometry") is None
            and decision["text"] is None,
            "REVISION_SINGLE_LINE_PENDING_SOURCE_REPLAY_FAILED:" + str(replay),
        )
    return {
        "accepted": decision["accepted"],
        "raw_source_and_decision_replayed": True,
        "source_replay": replay,
        "new_OCR_calls": 0,
        "new_model_calls": 0,
        "pending_observation_not_adopted": not decision["accepted"],
    }


def _verify_single_line_stage(
    evidence, text, stage, completion_text, producers, gray, published_check
):
    """Bind the additional text stage and all its raw/derived observations."""
    from . import single_line_labels as labels
    from .contracts import validate_text_regions

    module = "app.native_objects.single_line_labels"
    path = evidence / "single_line_labels/completed_text.json"
    manifest_path = evidence / "single_line_labels/completed_stages.json"
    summary_path = evidence / "single_line_labels/summary.json"
    for saved in (path, manifest_path, summary_path):
        published_check(saved)
    single, manifest, summary = (
        read_json(path),
        read_json(manifest_path),
        read_json(summary_path),
    )
    row = manifest["text"]
    _require(
        row.get("producer_module") == module
        and row.get("producer_sha256") == producers.get(module)
        and row.get("path") == "single_line_labels/completed_text.json",
        "REVISION_SINGLE_LINE_PRODUCER_CHANGED",
    )
    _verify_file(path, row["sha256"], "completed single-line text")
    for name, digest in _dependency_items(row):
        _require(
            producers.get(name) == digest, "REVISION_SINGLE_LINE_DEPENDENCY_CHANGED"
        )
    for field in (
        "source_sha256",
        "source_array_sha256",
        "source_size_px",
        "roi_xyxy_px",
    ):
        _require(
            manifest.get(field) == stage.get(field),
            "REVISION_SINGLE_LINE_SOURCE_IDENTITY_CHANGED",
        )
    validate_text_regions(single, gray.shape, stage["roi_xyxy_px"])
    _require(
        single.get("source_array_sha256") == stage["source_array_sha256"]
        and summary == single.get("single_line_label_recovery")
        and summary == text.get("single_line_label_recovery")
        and summary.get("version") == labels.POLICY["version"]
        and summary.get("source_sha256") == stage["source_sha256"]
        and summary.get("source_array_sha256") == stage["source_array_sha256"],
        "REVISION_SINGLE_LINE_SUMMARY_CHANGED",
    )
    upstream = _within(evidence, row["upstream_path"])
    _require(
        row["upstream_path"] == "single_line_labels/upstream_completed_text.json",
        "REVISION_SINGLE_LINE_EXACT_UPSTREAM_MISSING",
    )
    published_check(upstream)
    _verify_file(upstream, row["upstream_sha256"], "single-line immutable upstream")
    prior = row["upstream_producer"]
    _require(
        prior.get("producer_module")
        in {
            "app.native_objects.source_text_completion",
            "app.native_objects.source_text_ownership",
        }
        and prior.get("producer_sha256") == producers.get(prior.get("producer_module"))
        and prior.get("sha256") == row["upstream_sha256"]
        and prior.get("path") == row.get("upstream_original_path"),
        "REVISION_SINGLE_LINE_UPSTREAM_PRODUCER_CHANGED",
    )
    for name, digest in _dependency_items(prior):
        _require(
            producers.get(name) == digest,
            "REVISION_SINGLE_LINE_UPSTREAM_DEPENDENCY_CHANGED",
        )
    before = read_json(upstream)
    validate_text_regions(before, gray.shape, stage["roi_xyxy_px"])
    _require(
        before.get("source_array_sha256") == stage["source_array_sha256"],
        "REVISION_SINGLE_LINE_UPSTREAM_SOURCE_CHANGED",
    )
    if prior["producer_module"] == "app.native_objects.source_text_completion":
        _require(
            before == completion_text,
            "REVISION_SINGLE_LINE_COMPLETION_UPSTREAM_CHANGED",
        )
    else:
        ownership = before["source_text_ownership"]
        _require(
            ownership["producer_sha256"] == producers[prior["producer_module"]]
            and ownership["upstream_text_sha256"] == _canonical_digest(completion_text)
            and ownership["source_array_sha256"] == stage["source_array_sha256"]
            and ownership["source_pixels_removed"]
            == ownership["OCR_calls"]
            == ownership["source_fits"]
            == 0
            and single.get("prior_source_text_ownership") == ownership,
            "REVISION_SINGLE_LINE_PRIOR_OWNERSHIP_CHANGED",
        )
    old_regions = {region["id"]: region for region in before["regions"]}
    single_regions = {region["id"]: region for region in single["regions"]}
    _require(
        all(single_regions.get(rid) == region for rid, region in old_regions.items()),
        "REVISION_SINGLE_LINE_OLD_REGIONS_CHANGED",
    )
    single_groups = {group["id"]: group for group in single["groups"]}
    _require(
        all(
            single_groups.get(group["id"]) == group
            for group in before["groups"]
            if group.get("complete")
        ),
        "REVISION_SINGLE_LINE_OLD_COMPLETE_GROUP_CHANGED",
    )
    raw_records = summary.get("raw_evidence_files")
    _require(
        isinstance(raw_records, list) and raw_records,
        "REVISION_SINGLE_LINE_RAW_MANIFEST_MISSING",
    )
    raw_names = set()
    for record in raw_records:
        labels._read_record(evidence, record)
        name = record["path"]
        _require(
            name.startswith("single_line_labels/") and name not in raw_names,
            "REVISION_SINGLE_LINE_RAW_INVENTORY_CHANGED",
        )
        raw_names.add(name)
        published_check(_within(evidence, name))
    actual = {
        saved.relative_to(evidence).as_posix()
        for saved in (evidence / "single_line_labels").rglob("*")
        if saved.is_file()
        and saved.name
        not in {"completed_text.json", "completed_stages.json", "summary.json"}
    }
    _require(actual == raw_names, "REVISION_SINGLE_LINE_RAW_INVENTORY_CHANGED")
    attempts = summary.get("attempts", [])
    _require(
        len({attempt["id"] for attempt in attempts}) == len(attempts),
        "REVISION_SINGLE_LINE_ATTEMPT_DUPLICATE",
    )
    checks, observations, derived_tsv, model_records = [], {}, {}, {}
    for attempt in attempts:
        relative = "single_line_labels/labels/" + attempt["id"] + "/label_result.json"
        _require(relative in raw_names, "REVISION_SINGLE_LINE_RESULT_MISSING")
        observation = read_json(_within(evidence, relative))
        replay = _replay_single_line_result(
            observation, gray, stage["roi_xyxy_px"], evidence
        )
        for field in (
            "accepted",
            "text",
            "reasons",
            "bbox_xyxy_px",
            "new_Tesseract_calls",
            "new_model_calls",
        ):
            _require(
                attempt.get(field) == observation.get(field),
                "REVISION_SINGLE_LINE_ATTEMPT_CHANGED",
            )
        checks.append({"id": attempt["id"], "result_path": relative, **replay})
        observations[attempt["id"]] = observation
        proof = observation["evidence"]
        for view in proof["tesseract_views"]:
            name = view["metadata"]["path"]
            _require(
                name in raw_names and name not in derived_tsv,
                "REVISION_SINGLE_LINE_TSV_BINDING_CHANGED",
            )
            derived_tsv[name] = {
                "source_partition": proof["source_partition"],
                "normalization": view["normalization"],
                "result_path": relative,
            }
        for view in proof["ppocr_views"]:
            name = view["prediction_file"]["path"]
            _require(
                name in raw_names and name not in model_records,
                "REVISION_SINGLE_LINE_MODEL_BINDING_CHANGED",
            )
            model_records[name] = {
                "sha256": view["prediction_file"]["sha256"],
                "source_png_sha256": view["recognition_image"]["sha256"],
                "source_crop_sha256": view["normalization"]["input_array_sha256"],
                "source_transform_replayed": True,
                "result_path": relative,
            }
    recovered = summary.get("recovered_labels", [])
    accepted = {
        oid for oid, observation in observations.items() if observation["accepted"]
    }
    _require(
        {item["id"] for item in recovered} == accepted
        and len(recovered) == len(accepted) == summary.get("accepted_labels")
        and len(attempts) - len(accepted) == summary.get("pending_labels"),
        "REVISION_SINGLE_LINE_ADOPTED_INVENTORY_CHANGED",
    )
    expected_regions, expected_groups = set(), set()
    for item in recovered:
        observation = observations[item["id"]]
        rid, gid = item["region_id"], item["group_id"]
        expected_regions.add(rid)
        expected_groups.add(gid)
        for contract in (single, text):
            regions = {region["id"]: region for region in contract["regions"]}
            groups = {group["id"]: group for group in contract["groups"]}
            for saved in (regions.get(rid, {}), groups.get(gid, {})):
                _require(
                    saved.get("single_line_recovery") == observation["evidence"]
                    and saved.get("text") == observation["text"]
                    and saved.get("bbox_xyxy_px") == observation["bbox_xyxy_px"]
                    and saved.get("complete") is True,
                    "REVISION_SINGLE_LINE_ADOPTED_BINDING_CHANGED",
                )
            _require(
                groups[gid].get("region_ids") == [rid],
                "REVISION_SINGLE_LINE_GROUP_BINDING_CHANGED",
            )
    for contract in (single, text):
        _require(
            {
                region["id"]
                for region in contract["regions"]
                if "single_line_recovery" in region
            }
            == expected_regions
            and {
                group["id"]
                for group in contract["groups"]
                if "single_line_recovery" in group
            }
            == expected_groups,
            "REVISION_SINGLE_LINE_PROOF_INVENTORY_CHANGED",
        )
    return (
        single,
        {
            "module": module,
            "path": str(path.relative_to(evidence)),
            "sha256": file_sha(path),
            "upstream_path": row["upstream_path"],
            "upstream_sha256": row["upstream_sha256"],
            "source_replays": checks,
            "new_OCR_calls": 0,
            "new_model_calls": 0,
            "raw_OCR_not_repeated": True,
        },
        derived_tsv,
        model_records,
    )


def _verify_ownership_chain(
    evidence, text_row, upstream_text, producers, stage, published_check
):
    """The same ownership proof binds either old or new immediate upstream."""
    ownership_path = (
        evidence / "text_geometry_ownership/source_text_ownership_audit.json"
    )
    dictionary_path = _within(evidence, text_row["source_fitted_dictionary_path"])
    for path in (ownership_path, dictionary_path):
        published_check(path)
    ownership = read_json(ownership_path)
    _verify_file(
        dictionary_path,
        text_row["source_fitted_dictionary_sha256"],
        "source ownership fitted dictionary",
    )
    _require(
        ownership["producer_sha256"]
        == producers["app.native_objects.source_text_ownership"]
        and ownership["upstream_text_sha256"] == _canonical_digest(upstream_text)
        and ownership["saved_geometry_proposals_sha256"]
        == _canonical_digest(read_json(dictionary_path))
        and ownership["source_array_sha256"] == stage["source_array_sha256"]
        and ownership["source_pixels_removed"]
        == ownership["OCR_calls"]
        == ownership["source_fits"]
        == 0,
        "REVISION_OWNERSHIP_CHAIN_CHANGED",
    )
    return {
        "module": text_row["producer_module"],
        "path": text_row["path"],
        "sha256": text_row["sha256"],
        "ownership_audit_sha256": file_sha(ownership_path),
        "not_formal_adoption": True,
    }


def _verify_single_line_ocr(path, gray, dpi, engine, binding):
    from . import single_line_labels

    normalization = binding["normalization"]
    normalized, _ = single_line_labels._view(
        gray,
        binding["source_partition"],
        normalization["scale"],
        normalization["padding"],
    )
    # Retain every existing command, engine, source-byte, DPI and image check.
    # Only its explicitly registered source changes to the replayed local view.
    return {
        **_verify_ocr(path, normalized, dpi * normalization["scale"], engine),
        "registered_source_scope": "REPLAYED_SINGLE_LINE_DERIVED_VIEW",
        "source_transform_replayed": True,
        "source_partition_bbox_xyxy_px": binding["source_partition"]["bbox_xyxy_px"],
        "result_path": binding["result_path"],
    }


def _budget(source_state, adjustment):
    from app.core.native_job_manager import remaining_budget

    _, prior = remaining_budget(source_state["attempts"], source_state["limits"])
    path = Path(adjustment["diagnostic_resource_record"]).resolve()
    record = read_json(path)
    measured_wall = sum(
        float(r["recorded_wall_seconds"])
        for r in record["runs"]
        if r.get("recorded_wall_seconds") is not None
    )
    measured_cpu = sum(
        float(r["process_CPU_seconds"])
        for r in record["runs"]
        if r.get("process_CPU_seconds") is not None
    )
    for row in record.get("additional_measured_tests", []):
        if row.get("wall_seconds") is not None:
            measured_wall += float(row["wall_seconds"])
        if row.get("CPU_seconds") is not None:
            measured_cpu += float(row["CPU_seconds"])
    reserves = {
        k: float(adjustment[k])
        for k in (
            "unmeasured_wall_reservation_seconds",
            "unmeasured_CPU_reservation_seconds",
        )
    }
    _require(
        all(
            math.isfinite(v) and v >= 0
            for v in [measured_wall, measured_cpu, *reserves.values()]
        ),
        "REVISION_RESOURCE_ACCOUNT_INVALID",
    )
    previous = source_state.get("revision_import")
    if previous:
        # The previous revision has already charged both old workers and the
        # diagnostic account. Carry that debit once, then add its own attempts.
        # Do not silently discard ancestor consumption or charge diagnostics twice.
        inherited = previous["budget_ledger"]
        _require(
            inherited["original_contract"] == source_state["limits"]
            and inherited["diagnostic_resource_sha256"] == file_sha(path)
            and inherited["reservations_not_measurements"] == reserves,
            "REVISION_CHAIN_DIAGNOSTIC_ACCOUNT_CHANGED",
        )
        result = copy.deepcopy(inherited)
        result.update(
            prior_attempts=prior,
            inherited_revision_budget=copy.deepcopy(inherited),
            inherited_revision_receipt_sha256=previous["receipt_sha256"],
            diagnostic_charge_already_inherited_not_repeated=True,
            budget_chain_depth=int(inherited.get("budget_chain_depth", 0)) + 1,
        )
        result["CPU_seconds_budget_charge"] = (
            inherited["CPU_seconds_budget_charge"] + prior["CPU_seconds_spent"]
        )
        result["wall_seconds_budget_charge"] = (
            inherited["wall_seconds_budget_charge"] + prior["wall_seconds_spent"]
        )
        _require(
            result["CPU_seconds_budget_charge"] < source_state["limits"]["CPU_seconds"]
            and result["wall_seconds_budget_charge"]
            < source_state["limits"]["wall_seconds"],
            "REVISION_CUMULATIVE_BUDGET_EXHAUSTED",
        )
        return result
    result = {
        "original_contract": source_state["limits"],
        "prior_attempts": prior,
        "diagnostic_resource_record": str(path),
        "diagnostic_resource_sha256": file_sha(path),
        "diagnostic_measured_wall_seconds": measured_wall,
        "diagnostic_known_CPU_seconds": measured_cpu,
        "diagnostic_total_actual_CPU_seconds": record.get(
            "total_actual_diagnostic_CPU_seconds"
        ),
        "unmeasured_diagnostic_cost_present": True,
        "reservations_not_measurements": reserves,
        "budget_reset": False,
    }
    result["CPU_seconds_budget_charge"] = (
        prior["CPU_seconds_spent"]
        + measured_cpu
        + reserves["unmeasured_CPU_reservation_seconds"]
    )
    result["wall_seconds_budget_charge"] = (
        prior["wall_seconds_spent"]
        + measured_wall
        + reserves["unmeasured_wall_reservation_seconds"]
    )
    _require(
        result["CPU_seconds_budget_charge"] < source_state["limits"]["CPU_seconds"]
        and result["wall_seconds_budget_charge"]
        < source_state["limits"]["wall_seconds"],
        "REVISION_CUMULATIVE_BUDGET_EXHAUSTED",
    )
    return result


def prepare_revision_resume(
    source_job,
    target_job,
    *,
    current_parameters,
    captured_input_path,
    budget_adjustment,
):
    """Validate the published source task and copy a narrow immutable cache.

    No OCR, geometry search or candidate adoption is performed here. The new
    task's manager and worker each cold-verify the resulting receipt.
    """
    import numpy as np
    from PIL import Image
    from .job import make_job
    from .source_import import prepare_source
    from .contracts import validate_text_regions
    from .completion_stages import (
        restore_connection_discovery_evidence,
        text_context_sha,
    )

    old, job = Path(source_job).resolve(), Path(target_job).resolve()
    _require(
        old != job and old not in job.parents and job not in old.parents,
        "REVISION_REQUIRES_DISTINCT_TASK",
    )
    state, new_state = read_json(old / "state.json"), read_json(job / "state.json")
    _require(
        state["status"] == "COMPLETED_WITH_ISSUES", "REVISION_REQUIRES_PUBLISHED_SOURCE"
    )
    _require(
        new_state["status"] == "QUEUED" and new_state["attempt"] == 0,
        "REVISION_REQUIRES_UNSTARTED_TARGET",
    )
    _require(
        state["parameters"] == current_parameters == new_state["parameters"],
        "REVISION_PARAMETERS_CHANGED",
    )
    _require(
        state["limits"] == new_state["limits"], "REVISION_RESOURCE_CONTRACT_CHANGED"
    )
    source_sha = state["source_sha256"]
    _require(
        new_state["source_sha256"] == source_sha, "REVISION_SOURCE_IDENTITY_CHANGED"
    )
    _verify_file(captured_input_path, source_sha, "revision captured source")
    _verify_file(state["input_path"], source_sha, "prior captured source")
    published = Path(state["result_dxf"]).resolve().parent
    _require(old in published.parents, "REVISION_PUBLICATION_OUTSIDE_SOURCE_JOB")
    pub_path = published / "publication_manifest.json"
    publication = read_json(pub_path)
    _require(
        publication["identity"]["source_sha256"] == source_sha
        and publication["identity"]["algorithm_sha256"] == state["algorithm"]["sha256"],
        "REVISION_PUBLICATION_IDENTITY_CHANGED",
    )
    evidence = published / "evidence"
    stage_path = evidence / "completed_stages.json"
    stage = read_json(stage_path)
    _require(
        {"text", "geometry", "discovery"} <= set(stage),
        "REVISION_COMPLETED_STAGES_MISSING",
    )
    _require(stage["source_sha256"] == source_sha, "REVISION_STAGE_SOURCE_CHANGED")

    def published_check(path):
        rel = path.relative_to(published).as_posix()
        row = publication["files"].get(rel)
        _require(row is not None, "REVISION_UNPUBLISHED_EVIDENCE:" + rel)
        _verify_file(path, row["sha256"], rel)
        _require(
            path.stat().st_size == row["bytes"],
            "REVISION_PUBLISHED_SIZE_CHANGED:" + rel,
        )

    published_check(stage_path)
    producer_names = _revision_producer_names(stage["text"])
    _require(
        all(
            "app/native_objects/" + name + ".py" in state["algorithm"]["files"]
            for name in producer_names
        ),
        "REVISION_PRODUCER_BINDING_MISSING",
    )
    producers = {
        "app.native_objects." + name: state["algorithm"]["files"][
            "app/native_objects/" + name + ".py"
        ]
        for name in producer_names
    }
    _producer_checks(producers)
    text_row = stage["text"]
    _require(
        text_row["producer_module"]
        in {
            "app.native_objects.cross_engine_text",
            "app.native_objects.source_text_completion",
            "app.native_objects.single_line_labels",
            "app.native_objects.source_text_ownership",
        }
        and text_row["producer_sha256"] == producers[text_row["producer_module"]],
        "REVISION_TEXT_PRODUCER_BINDING_CHANGED",
    )
    for module, digest in _dependency_items(text_row):
        _require(producers.get(module) == digest, "REVISION_TEXT_DEPENDENCY_CHANGED")
    _require(
        stage["geometry"]["producer_sha256"]
        == producers["app.native_objects.geometry"],
        "REVISION_GEOMETRY_PRODUCER_CHANGED",
    )
    params = current_parameters
    prepared = prepare_source(
        make_job(
            captured_input_path,
            job / "unused_revision_check.dxf",
            params["roi"],
            dpi=params["dpi"],
            frame_number=params.get("frame_number"),
            page_number=params.get("page_number"),
            orientation=params.get("orientation", 0),
            job_id="revision-readonly-check",
        ),
        persist=False,
    )
    _require(
        prepared.manifest["cache_identity"] == stage["job_source_identity"],
        "REVISION_WORKING_SOURCE_CHANGED",
    )
    gray = prepared.gray
    _require(
        stage["source_array_sha256"]
        == hashlib.sha256(np.ascontiguousarray(gray).tobytes()).hexdigest(),
        "REVISION_WORKING_BYTES_CHANGED",
    )
    for name in ("text", "geometry", "discovery"):
        path = _within(evidence, stage[name]["path"])
        published_check(path)
        _verify_file(path, stage[name]["sha256"], "completed " + name)
    text_path = _within(evidence, text_row["path"])
    text = read_json(text_path)
    validate_text_regions(text, gray.shape, prepared.working_roi)
    references = _raw_reference_checks(text, text_path, evidence)
    _require(
        text["source_array_sha256"] == stage["source_array_sha256"],
        "REVISION_TEXT_SOURCE_CHANGED",
    )
    chain, single_line_tsv, single_line_models = [], {}, {}
    single_line_stage = _has_single_line_producer(text_row)
    _require(
        single_line_stage == ("single_line_label_recovery" in text)
        and (
            single_line_stage
            or not any("single_line_recovery" in region for region in text["regions"])
        ),
        "REVISION_SINGLE_LINE_STAGE_BINDING_MISSING",
    )
    if text_row["producer_module"] in {
        "app.native_objects.source_text_completion",
        "app.native_objects.single_line_labels",
        "app.native_objects.source_text_ownership",
    }:
        completion_path = evidence / "source_text_completion/completed_text.json"
        completion_manifest_path = (
            evidence / "source_text_completion/completed_stages.json"
        )
        for path in (completion_path, completion_manifest_path):
            published_check(path)
        completion_text, completion_manifest = (
            read_json(completion_path),
            read_json(completion_manifest_path),
        )
        completion_row = completion_manifest["text"]
        _verify_file(
            completion_path, completion_row["sha256"], "completed finite source text"
        )
        _require(
            completion_row["producer_module"]
            == "app.native_objects.source_text_completion"
            and completion_row["producer_sha256"]
            == producers[completion_row["producer_module"]],
            "REVISION_COMPLETION_PRODUCER_CHANGED",
        )
        cross_path = evidence / "cross_engine_text/completed_text.json"
        published_check(cross_path)
        _require(
            completion_text["producer"]["upstream_sha256"] == file_sha(cross_path),
            "REVISION_COMPLETION_UPSTREAM_CHANGED",
        )
        frozen, finished = (
            read_json(evidence / "source_text_completion/frozen_manifest.json"),
            read_json(evidence / "source_text_completion/completion_state.json"),
        )
        _require(
            finished["manifest_sha256"] == _canonical_digest(frozen)
            and finished["next_queue_index"] == len(frozen["queue"]),
            "REVISION_COMPLETION_QUEUE_UNFINISHED",
        )
        chain.append(
            {
                "module": completion_row["producer_module"],
                "path": str(completion_path.relative_to(evidence)),
                "sha256": file_sha(completion_path),
                "completed_queue_items": finished["next_queue_index"],
                "raw_OCR_not_repeated": True,
            }
        )
        ownership_upstream = completion_text
        if single_line_stage:
            (
                ownership_upstream,
                single_line_chain,
                single_line_tsv,
                single_line_models,
            ) = _verify_single_line_stage(
                evidence, text, stage, completion_text, producers, gray, published_check
            )
            chain.append(single_line_chain)
        if text_row["producer_module"] == "app.native_objects.source_text_ownership":
            chain.append(
                _verify_ownership_chain(
                    evidence,
                    text_row,
                    ownership_upstream,
                    producers,
                    stage,
                    published_check,
                )
            )
        model = read_json(cross_path)["producer"]["model_identity"]
    else:
        model = text["producer"]["model_identity"]
    _verify_file(model["model_path"], model["model_sha256"], "independent OCR model")
    if state.get("revision_import"):
        prior_import = state["revision_import"]
        _verify_file(
            prior_import["receipt_path"],
            prior_import["receipt_sha256"],
            "ancestor revision receipt",
        )
        old_import = verify_revision_receipt(
            prior_import["receipt_path"],
            target_job=old,
            source_sha256=source_sha,
            current_parameters=params,
        )
        _require(
            old_import["budget_ledger"] == prior_import["budget_ledger"],
            "REVISION_ANCESTOR_BUDGET_CHANGED",
        )
    else:
        old_import = read_json(old / "imports/checkpoint/receipt.json")
    engine = old_import["engine_identity"]
    _verify_file(
        engine["executable"],
        engine["current_executable_sha256"],
        "frozen Tesseract executable",
    )
    _verify_file(
        engine["model_path"],
        engine["current_model_sha256"],
        "frozen Tesseract language model",
    )
    selected = []
    for name in _ROOTS:
        entry = evidence / name
        paths = (
            [entry]
            if entry.is_file()
            else sorted(p for p in entry.rglob("*") if p.is_file())
        )
        for path in paths:
            _require(
                not path.is_symlink() and path.suffix.lower() not in (".dxf", ".dwg"),
                "REVISION_UNEXPECTED_CACHE_FILE",
            )
            published_check(path)
            selected.append(path)
    ocr, ppocr = {}, dict(single_line_models)
    for path in selected:
        if path.suffix != ".json":
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if "specification" in data and "tsv_sha256" in data:
            relative = path.relative_to(evidence).as_posix()
            if relative.startswith("single_line_labels/"):
                _require(
                    relative in single_line_tsv, "REVISION_UNBOUND_SINGLE_LINE_TSV"
                )
                ocr[relative] = _verify_single_line_ocr(
                    path, gray, params["dpi"], engine, single_line_tsv[relative]
                )
            else:
                ocr[relative] = _verify_ocr(path, gray, params["dpi"], engine)
        if "raw_model_output" in data and "source_png" in data:
            x0, y0, x1, y1 = data["context"]["crop_xyxy_px"]
            crop = np.ascontiguousarray(gray[y0:y1, x0:x1])
            _require(
                0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0],
                "REVISION_PP_SOURCE_BOX_INVALID",
            )
            digest = hashlib.sha256(crop.tobytes()).hexdigest()
            _require(
                data["source_array_sha256"]
                == digest
                == data["raw_model_output"]["input_array_sha256"],
                "REVISION_PP_INPUT_BYTES_CHANGED",
            )
            _require(
                path.parent.name == "model_observations",
                "REVISION_MODEL_OBSERVATION_LOCATION_INVALID",
            )
            png = _within(path.parent.parent, data["source_png"])
            _verify_file(png, data["source_png_sha256"], "independent OCR input")
            with Image.open(png) as im:
                _require(
                    np.array_equal(np.asarray(im.convert("L")), crop),
                    "REVISION_PP_SOURCE_PIXELS_CHANGED",
                )
            ppocr[path.relative_to(evidence).as_posix()] = {
                "sha256": file_sha(path),
                "source_png_sha256": file_sha(png),
                "source_crop_sha256": digest,
            }
    _require(set(single_line_tsv) <= set(ocr), "REVISION_SINGLE_LINE_TSV_NOT_RECHECKED")
    _require(
        set(old_import["OCR"]) <= set(ocr), "REVISION_HISTORICAL_OBSERVATIONS_MISSING"
    )
    for rel, row in old_import["OCR"].items():
        _require(
            ocr[rel]["meta_sha256"] == row["meta_sha256"]
            and ocr[rel]["tsv_sha256"] == row["tsv_sha256"]
            and ocr[rel]["image_sha256"] == row["image_sha256"],
            "REVISION_HISTORICAL_OBSERVATION_CHANGED:" + rel,
        )
    doors_path = evidence / "doors/doors.json"
    raw_doors_path = evidence / "door_completion/completion_result.json"
    connections_path = evidence / "connections/discovery/connections.json"
    if not connections_path.is_file():
        # A previous revision published its verified raw proposal wrapper,
        # not a fresh discovery tree. Reuse that immutable payload in turn.
        connections_path = evidence / "connections/revision_connection_proposals.json"
    assembly_path = evidence / "completed_assembly.json"
    for path in (doors_path, raw_doors_path, connections_path, assembly_path):
        published_check(path)
    doors = read_json(doors_path)
    accepted = {o["id"]: o for o in doors["objects"]}
    rejected = {r["object"]["id"]: r["object"] for r in doors["uncertainties"]}
    checks = doors["source_checks"]
    _require(
        set(accepted).isdisjoint(rejected)
        and {r["id"] for r in checks} == set(accepted) | set(rejected),
        "REVISION_DOOR_PROPOSAL_SET_CHANGED",
    )
    proposals = []
    for row in checks:
        obj = copy.deepcopy(accepted.get(row["id"]) or rejected[row["id"]])
        _require(
            obj["kind"] == "DOOR"
            and obj["source_evidence"]["source_sha256"] == source_sha
            and row["pass"] == (obj["id"] in accepted),
            "REVISION_DOOR_SOURCE_BINDING_CHANGED",
        )
        proposals.append(obj)
    identity = {
        k: copy.deepcopy(stage[k])
        for k in (
            "source_sha256",
            "source_array_sha256",
            "source_size_px",
            "roi_xyxy_px",
        )
    }
    connections_payload = read_json(connections_path)
    if connections_path.name == "revision_connection_proposals.json":
        _require(
            all(connections_payload.get(k) == v for k, v in identity.items())
            and connections_payload.get("producer_module")
            == "app.native_objects.connections"
            and connections_payload.get("producer_sha256")
            == producers["app.native_objects.connections"],
            "REVISION_ANCESTOR_CONNECTION_PROPOSALS_CHANGED",
        )
        connections_payload = connections_payload["discovery"]
    raw_connection_evidence = restore_connection_discovery_evidence(
        evidence, None, gray, discovery=connections_payload
    )
    if raw_connection_evidence is not None:
        for relative in raw_connection_evidence["files"]:
            path = _within(evidence, relative)
            published_check(path)
            if path not in selected:
                selected.append(path)
    wrappers = {
        "native_verified_cache.json": {
            "schema": "published-source-door-proposals-v8.3",
            "source_sha256": source_sha,
            "roi_xyxy_px": params["roi"],
            "job_source_identity": stage["job_source_identity"],
            "objects": proposals,
            "provenance": {
                "original_doors_sha256": file_sha(doors_path),
                "door_detector_producer_sha256": producers[
                    "app.native_objects.door_detector"
                ],
                "actual_prior_source_checks": checks,
                "old_decisions_not_inherited": True,
                "current_source_recheck_required": True,
            },
        },
        "revision_door_completion_proposals.json": {
            **identity,
            "producer_module": "app.native_objects.door_completion",
            "producer_sha256": producers["app.native_objects.door_completion"],
            "raw_generation": read_json(raw_doors_path)["raw_generation"],
            "provenance": {
                "original_sha256": file_sha(raw_doors_path),
                "old_responsibility_inherited": False,
            },
        },
        "revision_connection_proposals.json": {
            **identity,
            "producer_module": "app.native_objects.connections",
            "producer_sha256": producers["app.native_objects.connections"],
            "old_text_context_sha256": text_context_sha(
                read_json(assembly_path)["objects"]
            ),
            "old_text_context_is_current": False,
            "discovery": connections_payload,
            "raw_discovery_evidence": raw_connection_evidence,
            "provenance": {
                "original_sha256": file_sha(connections_path),
                "current_source_and_text_recheck_required": True,
            },
        },
    }
    budget = _budget(state, budget_adjustment)
    destination = job / "imports/revision"
    _require(not destination.exists(), "REVISION_IMPORT_ALREADY_EXISTS")
    destination.parent.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".revision-", dir=destination.parent))
    target = temporary / "evidence"
    files = {}
    for path in selected:
        rel = path.relative_to(evidence).as_posix()
        copied = _within(target, rel)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copied)
        _verify_file(copied, file_sha(path), rel)
        files[rel] = {
            "sha256": file_sha(copied),
            "bytes": copied.stat().st_size,
            "origin": "unchanged_published_evidence",
        }
    manifest = {k: copy.deepcopy(v) for k, v in stage.items() if k != "assembly"}
    wrappers["completed_stages.json"] = manifest
    for rel, data in wrappers.items():
        path = target / rel
        atomic_json(path, data)
        files[rel] = {
            "sha256": file_sha(path),
            "bytes": path.stat().st_size,
            "origin": "explicit_revision_candidate_wrapper",
        }
    receipt = {
        "schema": (
            "published-observation-revision-import-v8.4"
            if chain
            else "published-observation-revision-import-v8.3"
        ),
        "created_utc": utc_now(),
        "target_job": str(job),
        "captured_input_path": str(Path(captured_input_path).resolve()),
        "source_job": str(old),
        "source_sha256": source_sha,
        "parameters": params,
        "job_source_identity": stage["job_source_identity"],
        "source_array_sha256": stage["source_array_sha256"],
        "original_publication_manifest_sha256": file_sha(pub_path),
        "original_stage_manifest_sha256": file_sha(stage_path),
        "unchanged_producers": producers,
        "engine_identity": engine,
        "model_identity": model,
        "historical_OCR_count": old_import.get(
            "historical_OCR_count", len(old_import["OCR"])
        ),
        "completed_Tesseract_observation_count": len(ocr),
        "text_producer_chain": chain,
        "completed_independent_model_observation_count": len(ppocr),
        "OCR": ocr,
        "independent_OCR": ppocr,
        "raw_references": references,
        "files": files,
        "budget_ledger": budget,
        "source_completed_text_sha256": text_row["sha256"],
        "source_completed_geometry_sha256": stage["geometry"]["sha256"],
        "cache_dir": str(destination / "evidence"),
        "resume_evidence": str(destination / "evidence"),
        "assembly_review_adoption_or_old_DXF_imported": False,
        "historical_adoption_inherited": False,
        "current_source_ownership_and_review_required": True,
        "new_OCR_calls": 0,
        "new_geometry_fits": 0,
        "old_job_modified": False,
    }
    atomic_json(temporary / "receipt.json", receipt)
    os.replace(temporary, destination)
    return {
        "schema": receipt["schema"],
        "cache_dir": receipt["cache_dir"],
        "resume_evidence": receipt["resume_evidence"],
        "receipt_path": str(destination / "receipt.json"),
        "receipt_sha256": file_sha(destination / "receipt.json"),
        "source_job": str(old),
        "budget_ledger": budget,
    }


def verify_revision_receipt(
    receipt_path, *, target_job, source_sha256, current_parameters
):
    """Cold worker check. All referenced inputs, producers and cache bytes bind."""
    job, path = Path(target_job).resolve(), Path(receipt_path).resolve()
    _require(job in path.parents and path.is_file(), "REVISION_RECEIPT_OUTSIDE_TASK")
    receipt = read_json(path)
    _require(
        receipt.get("schema")
        in {
            "published-observation-revision-import-v8.3",
            "published-observation-revision-import-v8.4",
        },
        "REVISION_RECEIPT_SCHEMA_INVALID",
    )
    _require(
        receipt["target_job"] == str(job) and receipt["source_sha256"] == source_sha256,
        "REVISION_RECEIPT_SOURCE_MISMATCH",
    )
    _require(
        receipt["parameters"] == current_parameters,
        "REVISION_RECEIPT_PARAMETERS_CHANGED",
    )
    source = Path(receipt["captured_input_path"]).resolve()
    _require(job in source.parents, "REVISION_SOURCE_OUTSIDE_TARGET_TASK")
    _verify_file(source, source_sha256, "revision worker source")
    _producer_checks(receipt["unchanged_producers"])
    engine, model = receipt["engine_identity"], receipt["model_identity"]
    _verify_file(
        engine["executable"],
        engine["current_executable_sha256"],
        "revision Tesseract binary",
    )
    _verify_file(
        engine["model_path"], engine["current_model_sha256"], "revision Tesseract model"
    )
    _verify_file(
        model["model_path"], model["model_sha256"], "revision independent model"
    )
    cache = Path(receipt["cache_dir"]).resolve()
    _require(
        job in cache.parents and cache == Path(receipt["resume_evidence"]).resolve(),
        "REVISION_CACHE_OUTSIDE_TASK",
    )
    actual = {p.relative_to(cache).as_posix() for p in cache.rglob("*") if p.is_file()}
    _require(actual == set(receipt["files"]), "REVISION_CACHE_INVENTORY_CHANGED")
    for relative, row in receipt["files"].items():
        file = _within(cache, relative)
        _verify_file(file, row["sha256"], relative)
        _require(
            file.stat().st_size == row["bytes"],
            "REVISION_CACHE_SIZE_CHANGED:" + relative,
        )
    stage = read_json(cache / "completed_stages.json")
    _require(
        "assembly" not in stage and not receipt["historical_adoption_inherited"],
        "REVISION_OLD_ADOPTION_FORBIDDEN",
    )
    _require(
        stage["text"]["sha256"] == receipt["source_completed_text_sha256"]
        and stage["geometry"]["sha256"] == receipt["source_completed_geometry_sha256"],
        "REVISION_STAGE_BYTES_REDECLARED",
    )
    return receipt
