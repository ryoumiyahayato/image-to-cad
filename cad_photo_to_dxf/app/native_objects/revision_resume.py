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
    "text_geometry_ownership",
)
_DERIVED_PRODUCERS = ("source_text_completion", "source_text_ownership")


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
    allowed = required | {"app.native_objects." + x for x in _DERIVED_PRODUCERS}
    _require(required <= set(producers) <= allowed, "REVISION_PRODUCER_SET_CHANGED")
    for module, expected in producers.items():
        _verify_file(_within(app, module.replace(".", "/") + ".py"), expected, module)


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
    from .completion_stages import text_context_sha

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
    producer_names = list(_PRODUCERS)
    if stage["text"]["producer_module"] in {
        "app.native_objects." + n for n in _DERIVED_PRODUCERS
    }:
        producer_names += list(_DERIVED_PRODUCERS)
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
            "app.native_objects.source_text_ownership",
        }
        and text_row["producer_sha256"] == producers[text_row["producer_module"]],
        "REVISION_TEXT_PRODUCER_BINDING_CHANGED",
    )
    dependencies = text_row.get("dependency_producers", [])
    items = (
        dependencies.items()
        if isinstance(dependencies, dict)
        else [(r["module"], r["sha256"]) for r in dependencies]
    )
    for module, digest in items:
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
    chain = []
    if text_row["producer_module"] in {
        "app.native_objects.source_text_completion",
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
        if text_row["producer_module"] == "app.native_objects.source_text_ownership":
            ownership_path = (
                evidence / "text_geometry_ownership/source_text_ownership_audit.json"
            )
            dictionary_path = _within(
                evidence, text_row["source_fitted_dictionary_path"]
            )
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
                and ownership["upstream_text_sha256"]
                == _canonical_digest(completion_text)
                and ownership["saved_geometry_proposals_sha256"]
                == _canonical_digest(read_json(dictionary_path))
                and ownership["source_array_sha256"] == stage["source_array_sha256"]
                and ownership["source_pixels_removed"]
                == ownership["OCR_calls"]
                == ownership["source_fits"]
                == 0,
                "REVISION_OWNERSHIP_CHAIN_CHANGED",
            )
            chain.append(
                {
                    "module": text_row["producer_module"],
                    "path": text_row["path"],
                    "sha256": text_row["sha256"],
                    "ownership_audit_sha256": file_sha(ownership_path),
                    "not_formal_adoption": True,
                }
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
    ocr, ppocr = {}, {}
    for path in selected:
        if path.suffix != ".json":
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if "specification" in data and "tsv_sha256" in data:
            ocr[path.relative_to(evidence).as_posix()] = _verify_ocr(
                path, gray, params["dpi"], engine
            )
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
