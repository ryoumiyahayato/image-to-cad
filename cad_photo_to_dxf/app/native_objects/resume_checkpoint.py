"""Explicit import of source-bound, unfinished text observations into a new job.

This imports no geometry, drawing, approval list or final review.  The old job is
never modified.  A completed text stage remains at its original relative path;
moving it to the evidence root would invalidate its region evidence roots.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .execution import atomic_json, file_sha, read_json, utc_now


class CheckpointImportError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise CheckpointImportError(code)


def _within(root, relative):
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    _require(
        candidate != root and root in candidate.parents,
        "CHECKPOINT_PATH_ESCAPES_ROOT:" + str(relative),
    )
    _require(
        not (root / relative).is_symlink(),
        "CHECKPOINT_SYMLINK_NOT_ALLOWED:" + str(relative),
    )
    return candidate


def _digest_array(array):
    import numpy as np

    return hashlib.sha256(
        memoryview(np.ascontiguousarray(array, dtype=np.uint8))
    ).hexdigest()


def _verify_file(path, expected, label):
    _require(Path(path).is_file(), "CHECKPOINT_FILE_MISSING:" + label)
    actual = file_sha(path)
    _require(actual == expected, "CHECKPOINT_HASH_MISMATCH:" + label)
    return actual


def _current_engine(historical):
    """Check recorded version/location; explicitly preserve missing old digests."""
    binary = Path(os.environ.get("I2CAD_TESSERACT") or shutil.which("tesseract") or "")
    _require(binary.is_file(), "CHECKPOINT_ENGINE_UNAVAILABLE")
    version_call = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, timeout=20
    )
    language_call = subprocess.run(
        [str(binary), "--list-langs"], capture_output=True, text=True, timeout=20
    )
    _require(
        version_call.returncode == 0 and language_call.returncode == 0,
        "CHECKPOINT_ENGINE_INSPECTION_FAILED",
    )
    version = (version_call.stdout or version_call.stderr).splitlines()[0]
    languages = language_call.stdout + language_call.stderr
    _require(version == historical.get("version"), "CHECKPOINT_ENGINE_VERSION_CHANGED")
    _require(
        binary.resolve() == Path(historical.get("executable", "")).resolve(),
        "CHECKPOINT_ENGINE_LOCATION_CHANGED",
    )
    old_location = re.search(r'in "([^"]+)"', historical.get("list_langs_output", ""))
    location = re.search(r'in "([^"]+)"', languages)
    _require(
        old_location is not None and location is not None,
        "CHECKPOINT_LANGUAGE_DATA_LOCATION_UNRESOLVED",
    )
    _require(
        Path(location.group(1)).resolve() == Path(old_location.group(1)).resolve(),
        "CHECKPOINT_LANGUAGE_DATA_LOCATION_CHANGED",
    )
    _require("eng" in languages.splitlines(), "CHECKPOINT_ENG_MODEL_UNAVAILABLE")
    model = Path(location.group(1)) / "eng.traineddata"
    _require(model.is_file(), "CHECKPOINT_ENG_MODEL_FILE_MISSING")
    return {
        "engine_version": version,
        "executable": str(binary.resolve()),
        "current_executable_sha256": file_sha(binary),
        "model_path": str(model.resolve()),
        "current_model_sha256": file_sha(model),
        "historical_executable_sha256": None,
        "historical_model_sha256": None,
        "historical_model_digest_status": "HISTORICAL_MODEL_DIGEST_NOT_CAPTURED",
        "historical_model_byte_identity_proven": False,
        "reuse_scope": "saved raw observations with exact source/configuration binding; not new or independent OCR",
        "current_source_and_adoption_review_required": True,
    }


def _verify_ocr(meta_path, gray, expected_dpi, engine):
    import numpy as np
    from PIL import Image

    meta = read_json(meta_path)
    _require(
        meta.get("status") == "COMPLETED" and meta.get("return_code") == 0,
        "INCOMPLETE_OCR_NOT_IMPORTABLE:" + meta_path.name,
    )
    spec = meta.get("specification", {})
    box = spec.get("crop_xyxy_px", [])
    _require(
        len(box) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in box),
        "OCR_INVALID_SOURCE_BOX",
    )
    x0, y0, x1, y1 = box
    _require(
        0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0],
        "OCR_SOURCE_BOX_OUTSIDE_INPUT",
    )
    crop = gray[y0:y1, x0:x1]
    _require(
        _digest_array(crop) == spec.get("crop_array_sha256"),
        "OCR_SOURCE_CROP_CHANGED:" + meta_path.name,
    )
    _require(
        spec.get("recognition_dpi") == expected_dpi and spec.get("language") == "eng",
        "OCR_DPI_OR_LANGUAGE_CHANGED",
    )
    _require(
        spec.get("pixel_scale") == [1, 1]
        and spec.get("source_pixels_modified") is False
        and spec.get("padding_replaces_source_pixels") is False,
        "OCR_SOURCE_TRANSFORM_NOT_ALLOWED",
    )
    pad = spec.get("external_white_padding_px")
    _require(
        isinstance(pad, int) and not isinstance(pad, bool) and 0 <= pad <= 128,
        "OCR_INVALID_PADDING",
    )
    tsv, png = meta_path.with_suffix(".tsv"), meta_path.with_suffix(".png")
    _verify_file(tsv, meta.get("tsv_sha256"), tsv.name)
    _verify_file(png, meta.get("image_sha256"), png.name)
    expected = np.pad(crop, pad, constant_values=255) if pad else crop
    with Image.open(png) as image:
        actual = np.asarray(image.convert("L"))
        _require(
            actual.shape == expected.shape and np.array_equal(actual, expected),
            "OCR_SAVED_IMAGE_NOT_SOURCE_CROP:" + png.name,
        )
    command = meta.get("command", [])
    _require(
        len(command) == 12
        and command[2:]
        == [
            "stdout",
            "-l",
            "eng",
            "--oem",
            "1",
            "--psm",
            str(spec.get("psm")),
            "--dpi",
            str(expected_dpi),
            "tsv",
        ],
        "OCR_COMMAND_CONFIGURATION_CHANGED:" + meta_path.name,
    )
    _require(
        Path(command[0]).resolve() == Path(engine["executable"]).resolve()
        and meta.get("engine_version") == engine["engine_version"],
        "OCR_ENGINE_CONFIGURATION_CHANGED:" + meta_path.name,
    )
    return {
        "meta_sha256": file_sha(meta_path),
        "image_sha256": file_sha(png),
        "tsv_sha256": file_sha(tsv),
        "specification": spec,
        "input_pixels_equal_registered_source": True,
        "status": "VERIFIED_COMPLETED_OBSERVATION",
    }


def _producer_checks(stage, source_algorithm, app_root):
    row = stage["text"]
    allowed = {
        "app.native_objects.text_regions",
        "app.native_objects.text_line_domains",
    }
    _require(
        row.get("producer_module") in allowed,
        "ONLY_PRE_REVIEW_TEXT_STAGE_IMPORT_ALLOWED",
    )
    dependencies = row.get("dependency_producers", {})
    deps = (
        list(dependencies.items())
        if isinstance(dependencies, dict)
        else [(x["module"], x["sha256"]) for x in dependencies]
    )
    all_rows = [(row["producer_module"], row["producer_sha256"]), *deps]
    # Cropping, source interpretation and all earlier text policies must also be unchanged.
    for name in (
        "text_regions",
        "text_line_domains",
        "text_block_rescue",
        "contracts",
        "source_import",
    ):
        module = "app.native_objects." + name
        relative = module.replace(".", "/") + ".py"
        _require(
            relative in source_algorithm["files"],
            "CHECKPOINT_PRODUCER_BINDING_MISSING:" + relative,
        )
        all_rows.append((module, source_algorithm["files"][relative]))
    result = {}
    for module, expected in all_rows:
        _require(
            module.startswith("app.native_objects.")
            and re.fullmatch(r"[A-Za-z_]+", module.rsplit(".", 1)[1]),
            "CHECKPOINT_PRODUCER_INVALID",
        )
        path = app_root / (module.replace(".", "/") + ".py")
        _verify_file(path, expected, module)
        result[module] = expected
    return result


def _raw_reference_checks(text, text_path, evidence):
    rows = []
    for region in text["regions"]:
        _require(
            not region.get("accepted"),
            "OLD_ADOPTION_DECISION_NOT_IMPORTABLE:" + region["id"],
        )
        root = (
            text_path.parent
            / text.get("region_evidence_roots", {}).get(region["id"], ".")
        ).resolve()
        _require(
            root == evidence or evidence in root.parents,
            "REGION_EVIDENCE_ROOT_ESCAPES_CHECKPOINT",
        )
        for alt in region.get("completeness_evidence", {}).get("alternatives", []):
            artifact = alt.get("raw_artifact", {})
            relative = artifact.get("path") or alt.get("raw_tsv")
            _require(relative is not None, "OCR_ALTERNATIVE_WITHOUT_RAW_ARTIFACT")
            raw = (root / relative).resolve()
            _require(
                evidence in raw.parents and raw.is_file(),
                "OCR_ALTERNATIVE_SOURCE_MISSING:" + str(raw),
            )
            expected = artifact.get("sha256")
            if expected:
                _verify_file(raw, expected, str(raw.relative_to(evidence)))
            else:
                meta = read_json(raw.with_suffix(".json"))
                _verify_file(raw, meta.get("tsv_sha256"), raw.name)
            rows.append(
                {
                    "region_id": region["id"],
                    "context_id": alt.get("context_id"),
                    "path": raw.relative_to(evidence).as_posix(),
                    "sha256": file_sha(raw),
                }
            )
    return rows


def validate_checkpoint_import(
    source_job,
    *,
    stop_record,
    current_parameters,
    captured_input_path,
    expected_source_sha256=None,
):
    """Read-only validation; no OCR invocation, no mutation, no inherited review."""
    from .job import make_job
    from .source_import import prepare_source

    source_job, stop_record = Path(source_job).resolve(), Path(stop_record).resolve()
    state = read_json(source_job / "state.json")
    stop = read_json(stop_record)
    _require(
        stop.get("status") == "RESOURCE_STOP_NO_FINAL_QUARTER_DXF",
        "CHECKPOINT_IS_NOT_RECORDED_UNFINISHED_RESOURCE_STOP",
    )
    _require(
        state.get("parameters") == current_parameters,
        "CHECKPOINT_TASK_PARAMETERS_CHANGED",
    )
    _require(
        state.get("production_GO") is False, "CHECKPOINT_UNEXPECTED_PRODUCTION_ADOPTION"
    )
    source = Path(captured_input_path).resolve()
    expected = expected_source_sha256 or state["source_sha256"]
    _require(expected == state["source_sha256"], "CHECKPOINT_EXPECTED_SOURCE_CHANGED")
    _verify_file(source, expected, "captured input")
    original = source_job / "inputs" / Path(state["input_path"]).name
    _verify_file(original, expected, "old captured input")
    params = current_parameters
    evidence = (
        source_job / "attempts" / f"{int(state['attempt']):04d}" / "staging/evidence"
    )
    stage_path = evidence / "completed_stages.json"
    _verify_file(
        stage_path,
        stop["last_successful_stage_manifest_sha256"],
        "last completed stage manifest",
    )
    stage = read_json(stage_path)
    _require(
        not any(key in stage for key in ("geometry", "assembly", "review")),
        "ONLY_UNFINISHED_TEXT_CHECKPOINT_ALLOWED",
    )
    text_path = _within(evidence, stage["text"]["path"])
    _verify_file(text_path, stop["last_completed_text_sha256"], "last completed text")
    _require(
        stage["text"]["sha256"] == stop["last_completed_text_sha256"],
        "CHECKPOINT_TEXT_MANIFEST_DISAGREEMENT",
    )
    config = make_job(
        source,
        source_job / "unused_validation_output.dxf",
        params["roi"],
        dpi=params["dpi"],
        frame_number=params.get("frame_number"),
        page_number=params.get("page_number"),
        orientation=params.get("orientation", 0),
        job_id="checkpoint-readonly-validation",
        cache_dir=evidence,
    )
    prepared = prepare_source(config, persist=False)
    _require(
        stage.get("job_source_identity") == prepared.manifest["cache_identity"],
        "CHECKPOINT_FULL_SOURCE_IDENTITY_CHANGED",
    )
    _require(
        stage.get("source_array_sha256") == prepared.manifest["working_array_sha256"],
        "CHECKPOINT_WORKING_ARRAY_CHANGED",
    )
    text = read_json(text_path)
    _require(
        text.get("source_array_sha256") == prepared.manifest["working_array_sha256"],
        "CHECKPOINT_TEXT_WORKING_ARRAY_CHANGED",
    )
    _require(
        text.get("roi_xyxy_px") == list(prepared.working_roi),
        "CHECKPOINT_TEXT_ROI_CHANGED",
    )
    app_root = Path(__file__).resolve().parents[2]
    producers = _producer_checks(stage, state["algorithm"], app_root)
    upstream = evidence / "completed_text.json"
    _verify_file(
        upstream, stage["text"].get("upstream_text_sha256"), "upstream original text"
    )
    initial_text = read_json(upstream)
    engine = _current_engine(initial_text["engine"])
    discovery = _within(evidence, stage["discovery"]["path"])
    _verify_file(discovery, stage["discovery"]["sha256"], "discovery observations")
    raw_references = _raw_reference_checks(text, text_path, evidence)
    ocr, counts, allowed_ocr = {}, Counter(), set()
    for directory in (
        "text/discovery_ocr",
        "text/local_ocr",
        "text_domain_recovery/local_ocr",
        "text_block_rescue/local_ocr",
    ):
        for meta_path in sorted((evidence / directory).glob("*.json")):
            relative = meta_path.relative_to(evidence).as_posix()
            ocr[relative] = _verify_ocr(meta_path, prepared.gray, params["dpi"], engine)
            counts[directory] += 1
            for suffix in (".json", ".png", ".tsv", ".stderr.txt"):
                path = meta_path.with_suffix(suffix)
                if path.is_file():
                    allowed_ocr.add(path.relative_to(evidence).as_posix())
    _require(bool(ocr), "CHECKPOINT_HAS_NO_COMPLETED_OCR")
    block_path = evidence / "text_block_rescue/policy_and_selection.json"
    block = read_json(block_path)
    _require(
        block.get("source_sha256") == expected
        and block.get("source_array_sha256")
        == prepared.manifest["working_array_sha256"],
        "BLOCK_CHECKPOINT_SOURCE_CHANGED",
    )
    _require(
        block.get("upstream_sha256") == file_sha(text_path),
        "BLOCK_CHECKPOINT_UPSTREAM_CHANGED",
    )
    _require(
        block.get("observations_sha256") == file_sha(discovery),
        "BLOCK_CHECKPOINT_DISCOVERY_CHANGED",
    )
    _require(
        block.get("producer_sha256")
        == producers["app.native_objects.text_block_rescue"],
        "BLOCK_CHECKPOINT_PRODUCER_CHANGED",
    )
    planned = {}
    for i, group in enumerate(block["selected"], 1):
        _require(
            set(group["region_ids"]) <= {r["id"] for r in text["regions"]},
            "BLOCK_PLAN_UNKNOWN_REGION",
        )
        for j, spec in enumerate(group["passes"], 1):
            name = f"text_block_rescue/local_ocr/B{i:03d}-C{j}-p{spec['psm']}.json"
            planned[name] = {
                "group_id": group["group_id"],
                "region_ids": group["region_ids"],
                **spec,
            }
    partial = {}
    recorded = {
        Path(row["path"]).name: row
        for row in stop.get("completed_partial_block_OCR", [])
    }
    for name, row in ocr.items():
        if not name.startswith("text_block_rescue/"):
            continue
        _require(name in planned, "PARTIAL_BLOCK_OCR_NOT_IN_PLAN:" + name)
        spec = row["specification"]
        _require(
            spec["crop_xyxy_px"] == planned[name]["crop_xyxy_px"]
            and spec["psm"] == planned[name]["psm"],
            "PARTIAL_BLOCK_CANDIDATE_IDENTITY_CHANGED:" + name,
        )
        record = recorded.get(Path(name).name)
        _require(
            record is not None
            and record["sha256"] == row["meta_sha256"]
            and record["TSV_sha256"] == row["tsv_sha256"]
            and record["specification"] == spec,
            "PARTIAL_BLOCK_STOP_RECORD_CHANGED:" + name,
        )
        partial[name] = planned[name]
    _require(len(partial) == len(recorded), "PARTIAL_BLOCK_STOP_RECORD_COUNT_CHANGED")
    files = {
        "completed_stages.json",
        "completed_text.json",
        "text_block_rescue/policy_and_selection.json",
    }
    for folder in ("text", "text_domain_recovery", "discovery_cache"):
        for path in (evidence / folder).rglob("*"):
            if not path.is_file():
                continue
            _require(not path.is_symlink(), "CHECKPOINT_SYMLINK_NOT_ALLOWED")
            rel = path.relative_to(evidence).as_posix()
            _require(
                path.suffix in (".json", ".png", ".tsv", ".txt"),
                "UNEXPECTED_TEXT_EVIDENCE_FILE:" + rel,
            )
            if path.parent.name in ("local_ocr", "discovery_ocr"):
                if rel in allowed_ocr:
                    files.add(rel)
            else:
                files.add(rel)
    files |= allowed_ocr
    manifest = {
        rel: {
            "sha256": file_sha(_within(evidence, rel)),
            "bytes": _within(evidence, rel).stat().st_size,
        }
        for rel in sorted(files)
    }
    incomplete = [
        p.relative_to(evidence).as_posix()
        for p in (evidence / "text_block_rescue/local_ocr").iterdir()
        if p.is_file() and p.relative_to(evidence).as_posix() not in allowed_ocr
    ]
    return {
        "schema": "source-bound-text-checkpoint-import-v8",
        "validated_utc": utc_now(),
        "source_job": str(source_job),
        "source_evidence": str(evidence),
        "source_sha256": expected,
        "parameters": current_parameters,
        "job_source_identity": prepared.manifest["cache_identity"],
        "old_algorithm_sha256": state["algorithm"]["sha256"],
        "unchanged_producers": producers,
        "stop_record": {
            "path": str(stop_record),
            "sha256": file_sha(stop_record),
            "status": stop["status"],
        },
        "old_resource_consumption": stop["resource_guard"],
        "text_relative_path": stage["text"]["path"],
        "text_sha256": file_sha(text_path),
        "engine_identity": engine,
        "completed_OCR_count": len(ocr),
        "completed_OCR_by_directory": dict(counts),
        "OCR": ocr,
        "raw_references": raw_references,
        "partial_block_candidates": partial,
        "block_planned_OCR_count": len(planned),
        "block_unfinished_OCR_count": len(planned) - len(partial),
        "incomplete_artifacts_not_reused": incomplete,
        "files": manifest,
        "approved_objects_imported": 0,
        "geometry_assembly_review_or_DXF_imported": False,
        "historical_adoption_inherited": False,
        "current_final_review_required": True,
        "new_OCR_calls": 0,
        "old_job_modified": False,
    }


def prepare_checkpoint_import(
    source_job,
    target_job,
    *,
    stop_record,
    current_parameters,
    captured_input_path,
    expected_source_sha256=None,
):
    """Copy verified observations into a new task after all checks succeed."""
    target_job = Path(target_job).resolve()
    _require(target_job.is_dir(), "NEW_TARGET_JOB_MISSING")
    state = read_json(target_job / "state.json")
    _require(
        state.get("attempt") == 0 and state.get("status") == "QUEUED",
        "CHECKPOINT_IMPORT_REQUIRES_NEW_QUEUED_TASK",
    )
    _require(
        Path(captured_input_path).resolve().parent == target_job / "inputs",
        "CHECKPOINT_TARGET_INPUT_NOT_CAPTURED_IN_JOB",
    )
    _require(
        state.get("source_sha256") == file_sha(captured_input_path),
        "CHECKPOINT_TARGET_SOURCE_STATE_CHANGED",
    )
    _require(
        state.get("parameters") == current_parameters,
        "CHECKPOINT_TARGET_PARAMETERS_CHANGED",
    )
    destination = target_job / "imports/checkpoint"
    _require(not destination.exists(), "CHECKPOINT_IMPORT_ALREADY_EXISTS")
    report = validate_checkpoint_import(
        source_job,
        stop_record=stop_record,
        current_parameters=current_parameters,
        captured_input_path=captured_input_path,
        expected_source_sha256=expected_source_sha256,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".checkpoint-import-", dir=destination.parent)
    )
    evidence = staging / "evidence"
    try:
        old = Path(report["source_evidence"])
        for relative, row in report["files"].items():
            src = _within(old, relative)
            _verify_file(src, row["sha256"], relative)
            dst = _within(evidence, relative)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            _verify_file(dst, row["sha256"], relative)
        report.update(
            target_job=str(target_job),
            copied_evidence=str(destination / "evidence"),
            imported_job_id=state["job_id"],
            copied_files=len(report["files"]),
        )
        atomic_json(staging / "receipt.json", report)
        os.rename(staging, destination)
    except Exception:
        # Failed material remains explicitly unpublished for diagnosis.
        atomic_json(
            staging / "IMPORT_FAILED.json",
            {"status": "FAILED_UNPUBLISHED", "target_job": str(target_job)},
        )
        raise
    receipt = destination / "receipt.json"
    return {
        "cache_dir": str(destination / "evidence"),
        "resume_evidence": str(destination / "evidence"),
        "receipt_path": str(receipt),
        "receipt_sha256": file_sha(receipt),
        "completed_OCR_count": report["completed_OCR_count"],
        "old_resource_consumption": report["old_resource_consumption"],
        "historical_model_digest_status": report["engine_identity"][
            "historical_model_digest_status"
        ],
    }


def verify_import_receipt(
    receipt_path, *, target_job, source_sha256, current_parameters
):
    """Worker-side recheck of the task-bound immutable import and every file."""
    target_job, receipt_path = Path(target_job).resolve(), Path(receipt_path).resolve()
    _require(
        receipt_path == target_job / "imports/checkpoint/receipt.json",
        "CHECKPOINT_RECEIPT_OUTSIDE_TASK_IMPORT",
    )
    receipt = read_json(receipt_path)
    _require(
        receipt.get("schema") == "source-bound-text-checkpoint-import-v8",
        "CHECKPOINT_RECEIPT_SCHEMA",
    )
    _require(
        receipt.get("target_job") == str(target_job)
        and receipt.get("source_sha256") == source_sha256
        and receipt.get("parameters") == current_parameters,
        "CHECKPOINT_RECEIPT_TASK_IDENTITY_CHANGED",
    )
    _require(
        receipt.get("historical_adoption_inherited") is False
        and receipt.get("approved_objects_imported") == 0
        and receipt.get("geometry_assembly_review_or_DXF_imported") is False,
        "CHECKPOINT_RECEIPT_UNAUTHORIZED_CONTENT",
    )
    evidence = target_job / "imports/checkpoint/evidence"
    _require(
        receipt.get("copied_evidence") == str(evidence),
        "CHECKPOINT_RECEIPT_EVIDENCE_PATH_CHANGED",
    )
    actual = {
        p.relative_to(evidence).as_posix() for p in evidence.rglob("*") if p.is_file()
    }
    _require(actual == set(receipt["files"]), "CHECKPOINT_IMPORTED_FILE_SET_CHANGED")
    for relative, row in receipt["files"].items():
        _verify_file(_within(evidence, relative), row["sha256"], relative)
    app_root = Path(__file__).resolve().parents[2]
    for module, expected in receipt["unchanged_producers"].items():
        _verify_file(
            _within(app_root, module.replace(".", "/") + ".py"), expected, module
        )
    engine = receipt["engine_identity"]
    _verify_file(
        engine["executable"],
        engine["current_executable_sha256"],
        "v8 current OCR binary",
    )
    _verify_file(
        engine["model_path"],
        engine["current_model_sha256"],
        "v8 current language model",
    )
    return receipt
