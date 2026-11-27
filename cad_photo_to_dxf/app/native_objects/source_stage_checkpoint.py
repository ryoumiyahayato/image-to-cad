"""Explicit, source-bound continuation of the complete pre-attached stage.

No DXF is read here. Historical attachment results only identify the stage
boundary to remove; every current attached/contact/numerical gate runs anew.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys

from .contracts import save_json
from .execution import file_sha, read_json


SCHEMA = "source-stage-checkpoint-pre-attached-v1"
CAPTURE_SCHEMA = "captured-source-stage-checkpoint-v1"
STAGES = ["text_and_raw_observations", "source_lines_and_candidates",
          "annotations", "complete_doors_and_finite_retirement_intervals",
          "complete_walls_and_remaining_lines", "connections",
          "circular_markers_and_endpoints", "carrier_reconciliation",
          "text_contact_and_transverse_paths", "short_contact_text"]
DOWNSTREAM = ["fresh_source_graph", "attached_ink", "all_prior_contacts",
              "joint_numerical_contract", "native_save", "saved_source_cold_read",
              "render", "current_input_quality_review", "independent_old_content_check"]
_RERUN_MODULES = {
    "attached_stroke_graph.py", "attached_stroke_audit.py",
    "attached_stroke_numeric.py", "attached_stroke_ink.py",
    "attached_stroke_contacts.py", "independent_saved_geometry_audit.py",
    "raw_source_responsibility_audit.py", "source_stage_checkpoint.py",
}
_SUPPLEMENTAL = ("app/geometry/source_filled_marks.py", "app/core/cancellation.py")
_CONTINUATION_EXECUTORS = ("app/native_objects/pipeline.py", "app/core/native_objects_entry.py",
                           "app/core/native_job_manager.py", "app/core/native_worker.py",
                           "app/core/processing.py", "main.py")
_NO_RESTORE_ROOT = {
    "completed_assembly.json", "completed_stages.json", "assembly.json",
    "import_manifest.json", "input_contract.json", "pipeline_trace.json",
    "pipeline_resources.json", "pipeline_failure.json", "cold_audit.json",
    "source_stage_continuation.json", "import_preview.png", "job_config.json",
    "raw_observation_usage.json", "runtime_privacy.json",
}
_REQUIRED_STATE = {"texts", "geometry", "annotations", "doors", "door_completion",
                   "connections", "circular_markers", "text_contact_completion",
                   "carrier_reconciliation", "short_contact_completion", "walls",
                   "objects", "issues", "text_producer", "text_objects"}


def _require(value, code):
    if not value:
        raise ValueError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _inside(root, name):
    rel = PurePosixPath(name)
    _require(isinstance(name, str) and "\\" not in name and not rel.is_absolute()
             and bool(rel.parts) and ".." not in rel.parts, "SOURCE_STAGE_UNSAFE_PATH")
    root = Path(root).resolve()
    path = root.joinpath(*rel.parts)
    _require(not any(p.is_symlink() for p in (path, *path.parents) if p != root.parent)
             and root in path.resolve().parents, "SOURCE_STAGE_PATH_OUTSIDE_ROOT")
    return path


def _checked(root, row):
    path = _inside(root, row["path"])
    _require(path.is_file(), "SOURCE_STAGE_ARTIFACT_MISSING:" + row["path"])
    _require(path.stat().st_size == row["bytes"] and file_sha(path) == row["sha256"],
             "SOURCE_STAGE_ARTIFACT_CHANGED:" + row["path"])
    return path


def _record(path, name):
    return {"path": name, "bytes": Path(path).stat().st_size, "sha256": file_sha(path)}


def _copy(source, destination):
    destination = Path(destination)
    _require(not destination.exists(), "SOURCE_STAGE_DESTINATION_EXISTS:" + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    _require(file_sha(source) == file_sha(destination), "SOURCE_STAGE_COPY_CHANGED")


def _calls(node, name):
    return any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
               and child.func.id == name for child in ast.walk(node))


def pipeline_projection(path):
    """Bind every reused statement, helper, import and constant, not file ranges.

    The fresh upstream block is located structurally by its final producer call
    and final append. Outer continuation dispatch and downstream calls may
    change, while the complete original sequence cannot.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    run = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "run_native_objects"), None)
    _require(run is not None, "SOURCE_STAGE_PIPELINE_ENTRY_MISSING")
    blocks = []
    for node in ast.walk(run):
        for _, value in ast.iter_fields(node):
            if not isinstance(value, list) or not value or not all(isinstance(n, ast.stmt) for n in value):
                continue
            for index, stmt in enumerate(value):
                if not (isinstance(stmt, ast.Assign) and _calls(stmt, "complete_short_contact_text")):
                    continue
                end = index + 1
                while end < len(value) and isinstance(value[end], ast.AugAssign):
                    end += 1
                _require(end == index + 3, "SOURCE_STAGE_SHORT_TEXT_BOUNDARY_CHANGED")
                _require(_calls(ast.Module(body=value[:index], type_ignores=[]), "extract_text_regions")
                         and _calls(ast.Module(body=value[:index], type_ignores=[]), "assemble_walls")
                         and _calls(ast.Module(body=value[:index], type_ignores=[]), "retire_door_fragments"),
                         "SOURCE_STAGE_UPSTREAM_SEQUENCE_INCOMPLETE")
                blocks.append(value[:end])
    _require(len(blocks) == 1, "SOURCE_STAGE_UPSTREAM_BOUNDARY_NOT_UNIQUE")
    helpers = [n for n in tree.body if n is not run]
    signature = deepcopy(run.args)
    if any(arg.arg == "source_stage_checkpoint" for arg in signature.kwonlyargs):
        index = next(i for i, arg in enumerate(signature.kwonlyargs) if arg.arg == "source_stage_checkpoint")
        _require(isinstance(signature.kw_defaults[index], ast.Constant)
                 and signature.kw_defaults[index].value is None,
                 "SOURCE_STAGE_SELECTOR_DEFAULT_CHANGED")
        signature.kwonlyargs.pop(index)
        signature.kw_defaults.pop(index)
    preamble = []
    for statement in run.body:
        if isinstance(statement, ast.Try):
            break
        preamble.append(deepcopy(statement))
    _require(preamble and len(preamble) < len(run.body), "SOURCE_STAGE_PIPELINE_PREAMBLE_MISSING")
    mutual_guard = ast.parse('if source_stage_checkpoint is not None:\n'
                             '    raise ValueError("SELECT_ONE_EXPLICIT_SOURCE_CHECKPOINT_MODE")').body[0]
    guard_dump = ast.dump(mutual_guard, include_attributes=False)

    class RemoveExplicitNewGuard(ast.NodeTransformer):
        def visit_If(self, node):
            if ast.dump(node, include_attributes=False) == guard_dump:
                return None
            return self.generic_visit(node)

    preamble = RemoveExplicitNewGuard().visit(ast.Module(body=preamble, type_ignores=[])).body
    return {"helpers_imports_constants_ast": digest([ast.dump(n, include_attributes=False) for n in helpers]),
            "entry_arguments_defaults_ast": digest(ast.dump(signature, include_attributes=False)),
            "entry_preamble_ast": digest([ast.dump(n, include_attributes=False) for n in preamble]),
            "complete_fresh_upstream_sequence_ast": digest([ast.dump(n, include_attributes=False) for n in blocks[0]]),
            "fresh_upstream_statement_count": len(blocks[0])}


def executor_identity(app_root=None):
    root = Path(app_root or Path(__file__).resolve().parents[2])
    return {name: file_sha(root / name) for name in _CONTINUATION_EXECUTORS}


def producer_closure(old_app, old_algorithm, current_app=None):
    old_app = Path(old_app).resolve()
    current_app = Path(current_app or Path(__file__).resolve().parents[2]).resolve()
    _require(old_algorithm.get("files"), "SOURCE_STAGE_HISTORICAL_PRODUCERS_MISSING")
    worker_files, snapshot_files = {}, {}
    for name, expected in sorted(old_algorithm["files"].items()):
        old = _inside(old_app, name)
        _require(old.is_file() and file_sha(old) == expected, "SOURCE_STAGE_HISTORICAL_SOURCE_CHANGED:" + name)
        if not name.startswith("app/native_objects/") or Path(name).name in _RERUN_MODULES | {"pipeline.py"}:
            continue
        now = _inside(current_app, name)
        _require(now.is_file() and file_sha(now) == expected, "SOURCE_STAGE_REUSED_PRODUCER_CHANGED:" + name)
        worker_files[name] = expected
    _require(worker_files, "SOURCE_STAGE_EMPTY_REUSED_PRODUCER_CLOSURE")
    for name in _SUPPLEMENTAL:
        old, now = _inside(old_app, name), _inside(current_app, name)
        _require(old.is_file() and now.is_file() and file_sha(old) == file_sha(now),
                 "SOURCE_STAGE_SOURCE_SNAPSHOT_DEPENDENCY_CHANGED:" + name)
        snapshot_files[name] = file_sha(old)
    old_pipeline = pipeline_projection(old_app / "app/native_objects/pipeline.py")
    _require(old_pipeline == pipeline_projection(current_app / "app/native_objects/pipeline.py"),
             "SOURCE_STAGE_UPSTREAM_PIPELINE_CHANGED")
    return {"historical_worker_recorded_native_files": worker_files,
            "supplemental_frozen_source_snapshot_files": snapshot_files,
            "supplemental_files_were_in_historical_worker_fingerprint": False,
            "pipeline_projection": old_pipeline,
            "excluded_downstream_modules_always_rerun": sorted(_RERUN_MODULES)}


def _normalized_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_distribution_identity(pins, historical):
    """Bind installed production source and native code, even at equal versions."""
    recorded = {_normalized_name(k): v for k, v in historical.items()}
    code, binaries = {}, {}
    for name, expected in sorted(pins.items()):
        dist = importlib.metadata.distribution(name)
        _require(dist.version == expected == recorded.get(_normalized_name(name)),
                 "SOURCE_STAGE_RUNTIME_DEPENDENCY_CHANGED:" + name)
        members = list(dist.files or ())
        _require(members, "SOURCE_STAGE_RUNTIME_DISTRIBUTION_FILES_MISSING:" + name)
        for relative in members:
            label = str(relative)
            native = label.endswith((".so", ".pyd", ".dll", ".dylib")) or ".so." in Path(label).name
            if not (label.endswith(".py") or native):
                continue
            path = dist.locate_file(relative)
            _require(Path(path).is_file(), "SOURCE_STAGE_RUNTIME_CODE_MISSING:" + name + ":" + label)
            key = name + ":" + label
            code[key] = file_sha(path)
            if native:
                binaries[key] = code[key]
    _require(code, "SOURCE_STAGE_RUNTIME_CODE_CLOSURE_EMPTY")
    return {"recorded_historical_and_current_package_versions": pins,
            "current_distribution_code_sha256": code,
            "current_native_binary_sha256": binaries}


def dependency_identity(environment, resource_map, app_root=None):
    """No image OCR/inference; pin current bytes without inventing old binaries."""
    app_root = Path(app_root or Path(__file__).resolve().parents[2])
    lock = app_root / "requirements-native.lock"
    pins = {}
    for line in lock.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name, version = line.strip().split("==")
            pins[name] = version
    distribution_identity = locked_distribution_identity(pins, environment["packages"])
    _require(platform.python_version() == environment["python"].split()[0], "SOURCE_STAGE_PYTHON_CHANGED")
    _require(platform.system() == environment["uname"][0] and platform.machine() == environment["uname"][4],
             "SOURCE_STAGE_RUNTIME_PLATFORM_CHANGED")
    executable = Path(__import__("os").environ.get("I2CAD_TESSERACT") or shutil.which("tesseract") or "")
    _require(executable.is_file() and file_sha(executable) == environment["tesseract"]["executable_sha256"],
             "SOURCE_STAGE_OCR_EXECUTABLE_CHANGED")
    language_info = subprocess.run([str(executable), "--list-langs"], capture_output=True, text=True, check=True)
    match = re.search(r'"([^"\n]+)"', language_info.stdout + language_info.stderr)
    _require(match is not None, "SOURCE_STAGE_OCR_LANGUAGE_PATH_UNKNOWN")
    language_path = Path(match.group(1)) / "eng.traineddata"
    _require(language_path.is_file() and file_sha(language_path) == environment["tesseract"]["traineddata_sha256"],
             "SOURCE_STAGE_OCR_LANGUAGE_CHANGED")
    spec = importlib.util.find_spec("rapidocr")
    _require(spec is not None and bool(spec.origin), "SOURCE_STAGE_MODEL_PACKAGE_MISSING")
    model = Path(spec.origin).parent / "models/PP-OCRv6_rec_small.onnx"
    _require(model.is_file() and file_sha(model) == environment["model"]["model_sha256"] == resource_map["model"]["sha256"],
             "SOURCE_STAGE_MODEL_CHANGED")
    fonts = {}
    for row in resource_map["font_files"]:
        name = row["relative_path"]
        path = _inside(app_root / "resources/fonts", name)
        expected = row["worktree_copy"]["sha256"]
        _require(path.is_file() and file_sha(path) == expected, "SOURCE_STAGE_FONT_RESOURCE_CHANGED:" + name)
        fonts[name] = expected
    _require(fonts, "SOURCE_STAGE_FONT_RESOURCE_IDENTITY_MISSING")
    return {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
            **distribution_identity,
            "requirements_lock_sha256": file_sha(lock),
            "current_python_executable_sha256": file_sha(Path(sys.executable).resolve()),
            "historical_distribution_code_or_python_executable_bytes": "NOT_RECORDED_NOT_INFERRED",
            "historical_native_binary_or_CPU_dispatch_identity": "NOT_RECORDED_NOT_INFERRED",
            "native_binary_scope": "current checkpoint preparation through capture and execution only",
            "ocr_executable_sha256": file_sha(executable), "ocr_language_sha256": file_sha(language_path),
            "model_sha256": file_sha(model), "font_resources_sha256": fonts,
            "new_image_OCR_calls": 0, "new_model_inferences": 0}


def _object_binding(obj):
    evidence = obj.get("source_evidence", {})
    row = {key: deepcopy(obj[key]) for key in ("id", "kind", "layer", "geometry")}
    row["source_evidence"] = {key: deepcopy(evidence.get(key)) for key in (
        "source_path_points", "original_source_crop_xyxy_px", "original_source_crop_array_sha256",
        "source_pixels_modified", "text_contact_path")}
    for key in ("short_contact_text", "text_layout", "text_geometry"):
        if key in evidence:
            row["source_evidence"][key] = deepcopy(evidence[key])
    return row


def project_upstream(assembly, plan, adoption):
    """Remove precisely the old stage's declared additions, never CAD entities."""
    _require(assembly.get("attached_stroke_completion") == adoption and adoption.get("plan") == plan,
             "SOURCE_STAGE_OLD_ATTACHMENT_RECEIPT_CHANGED")
    _require(adoption.get("retired_ids") == [], "SOURCE_STAGE_OLD_ATTACHMENT_RETIRED_PRIOR_CONTENT")
    adopted = adoption.get("objects")
    _require(isinstance(adopted, list), "SOURCE_STAGE_OLD_ADOPTED_OBJECTS_MISSING")
    added = {obj["id"]: obj for obj in adopted}
    _require(len(added) == len(adopted), "SOURCE_STAGE_DUPLICATE_OLD_ADOPTED_ID")
    final = {obj["id"]: obj for obj in assembly["objects"]}
    _require(len(final) == len(assembly["objects"]) and all(final.get(k) == v for k, v in added.items()),
             "SOURCE_STAGE_OLD_ADOPTED_OBJECT_BINDING_FAILED")
    _require(len(plan["paths"]) == len(adopted), "SOURCE_STAGE_OLD_ADOPTED_PATH_COUNT_MISMATCH")
    _require({row["stroke_id"] for row in plan["paths"]} == set(added), "SOURCE_STAGE_OLD_PATH_OBJECT_ID_MISMATCH")
    for obj in adopted:
        evidence = obj["source_evidence"].get("attached_stroke_graph", {})
        _require(evidence.get("path") in plan["paths"] and evidence.get("plan_sha256") == digest_legacy(plan),
                 "SOURCE_STAGE_OLD_ATTACHED_PATH_BINDING_FAILED")
    state = {key: deepcopy(value) for key, value in assembly.items() if key != "attached_stroke_completion"}
    state["objects"] = [deepcopy(obj) for obj in assembly["objects"] if obj["id"] not in added]
    _require(set(state) == _REQUIRED_STATE, "SOURCE_STAGE_UPSTREAM_STATE_FIELDS_CHANGED_OR_MISSING")
    bindings = [_object_binding(obj) for obj in sorted(state["objects"], key=lambda obj: obj["id"])]
    _require(bindings == plan.get("prior_object_bindings") == adoption.get("prior_object_bindings"),
             "SOURCE_STAGE_COMPLETE_PRIOR_BINDING_MISMATCH")
    _require(digest_legacy(bindings) == plan.get("prior_object_bindings_sha256"),
             "SOURCE_STAGE_PRIOR_BINDING_DIGEST_FAILED")
    _require(not any(obj.get("source_evidence", {}).get("attached_stroke_graph") for obj in state["objects"]),
             "SOURCE_STAGE_ATTACHED_RESULT_REUSE_FORBIDDEN")
    return state, sorted(added)


def digest_legacy(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def verify_declared_raw_files(state, evidence_root):
    """Require every explicitly attested raw asset of all reused source stages."""
    checked = set()

    def visit(value):
        if isinstance(value, dict):
            records = value.get("raw_evidence_files")
            if records is not None:
                _require(isinstance(records, list), "SOURCE_STAGE_RAW_MANIFEST_INVALID")
                for row in records:
                    _require(isinstance(row, dict) and isinstance(row.get("path"), str)
                             and isinstance(row.get("sha256"), str), "SOURCE_STAGE_RAW_REFERENCE_INVALID")
                    path = _inside(evidence_root, row["path"])
                    _require(path.is_file() and file_sha(path) == row["sha256"],
                             "SOURCE_STAGE_RAW_REFERENCE_MISSING_OR_CHANGED:" + row["path"])
                    checked.add(row["path"])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(state)
    return sorted(checked)


def _source_identity(source, parameters, stage, *, app_root=None):
    from .job import make_job
    from .source_import import prepare_source

    job = make_job(source, Path(source).parent / "unused_source_checkpoint_validation.dxf", parameters["roi"],
                   dpi=parameters["dpi"], page_number=parameters.get("page_number"),
                   frame_number=parameters.get("frame_number"), orientation=parameters.get("orientation", 0),
                   job_id="source-stage-checkpoint-validation")
    prepared = prepare_source(job, persist=False)
    _require(stage.get("source_sha256") == prepared.source_sha256
             and stage.get("source_array_sha256") == prepared.manifest["working_array_sha256"]
             and stage.get("job_source_identity") == prepared.manifest["cache_identity"]
             and stage.get("roi_xyxy_px") == list(prepared.working_roi),
             "SOURCE_STAGE_ORIGINAL_SOURCE_IDENTITY_CHANGED")
    return {"source_sha256": prepared.source_sha256,
            "working_array_sha256": prepared.manifest["working_array_sha256"],
            "cache_identity": prepared.manifest["cache_identity"],
            "parameters": deepcopy(parameters), "unit": job.payload()["unit"],
            "scale_evidence": job.payload()["scale_evidence"],
            "working_roi_xyxy_px": list(prepared.working_roi)}


def build_checkpoint(*, evidence, request, previous_source, environment, resources, source, output):
    """Create a new explicit checkpoint from an attested completed source run."""
    evidence, previous_source, output = Path(evidence).resolve(), Path(previous_source).resolve(), Path(output).resolve()
    old_request, old_stage = read_json(request), read_json(evidence / "completed_stages.json")
    old_environment, old_resources = read_json(environment), read_json(resources)
    row = old_stage.get("assembly")
    _require(isinstance(row, dict), "SOURCE_STAGE_COMPLETED_ASSEMBLY_MISSING")
    original = _inside(evidence, row["path"])
    _require(file_sha(original) == row["sha256"] and row["algorithm_fingerprint"] == old_request["algorithm"],
             "SOURCE_STAGE_COMPLETED_ASSEMBLY_PRODUCER_BINDING_FAILED")
    _require(file_sha(source) == old_request["source_sha256"], "SOURCE_STAGE_SOURCE_FILE_CHANGED")
    identity = _source_identity(source, old_request["parameters"], old_stage)
    closure = producer_closure(previous_source, old_request["algorithm"])
    dependencies = dependency_identity(old_environment, old_resources)
    plan = read_json(evidence / "attached_strokes/plan.json")
    adoption = read_json(evidence / "attached_strokes/adoption.json")
    state, removed = project_upstream(read_json(original), plan, adoption)
    raw_references = verify_declared_raw_files(state, evidence)
    _require(not output.exists(), "SOURCE_STAGE_OUTPUT_ALREADY_EXISTS")
    output.mkdir(parents=True)
    copied = []
    origin_files = {
        "origin/completed_assembly.json": original,
        "origin/completed_stages.json": evidence / "completed_stages.json",
        "origin/attached_plan.json": evidence / "attached_strokes/plan.json",
        "origin/attached_adoption.json": evidence / "attached_strokes/adoption.json",
        "origin/request.json": Path(request), "origin/environment.json": Path(environment),
        "origin/resources.json": Path(resources),
    }
    source_names = set(old_request["algorithm"]["files"]) | set(_SUPPLEMENTAL)
    for name in sorted(source_names):
        origin_files["origin/source/" + name] = _inside(previous_source, name)
    for name, path in origin_files.items():
        _copy(path, output / name)
        copied.append(_record(output / name, name))
    restored = []
    for path in sorted(evidence.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(evidence)
        if (relative.parts[0] in {"attached_strokes", "repair", "temporary", "__pycache__"}
                or relative.name.startswith("quality_") or relative.name in _NO_RESTORE_ROOT):
            continue
        name = "evidence/" + relative.as_posix()
        _copy(path, output / name)
        copied.append(_record(output / name, name))
        restored.append(relative.as_posix())
    save_json(output / "upstream_state.json", state)
    copied.append(_record(output / "upstream_state.json", "upstream_state.json"))
    manifest = {"schema": SCHEMA, "boundary": "AFTER_SHORT_CONTACT_BEFORE_ATTACHED",
                "source": identity, "historical_worker_algorithm": old_request["algorithm"],
                "producer_closure": closure, "runtime_and_resources": dependencies,
                "checkpoint_validator_sha256": file_sha(__file__),
                "continuation_executor_sha256": executor_identity(),
                "upstream_state_sha256": digest(state), "restored_evidence_paths": restored,
                "declared_raw_evidence_paths": raw_references,
                "artifacts": copied, "reused_stages": STAGES, "downstream_required": DOWNSTREAM,
                "excluded_historical_stage_object_ids": removed,
                "old_DXF_read": False, "new_OCR_calls": 0,
                "historical_CPU_BLAS_binary_dispatch": "NOT_RECORDED_NOT_INFERRED"}
    save_json(output / "manifest.json", manifest)
    return output / "manifest.json"


def verify_checkpoint(manifest_path, *, source, parameters, expected_sha256=None):
    path = Path(manifest_path).resolve()
    if expected_sha256 is not None:
        _require(file_sha(path) == expected_sha256, "SOURCE_STAGE_MANIFEST_CHANGED_AFTER_CAPTURE")
    manifest = read_json(path)
    _require(manifest.get("schema") == SCHEMA and manifest.get("boundary") == "AFTER_SHORT_CONTACT_BEFORE_ATTACHED",
             "SOURCE_STAGE_CONTRACT_UNSUPPORTED")
    _require(manifest.get("checkpoint_validator_sha256") == file_sha(__file__), "SOURCE_STAGE_VALIDATOR_CHANGED")
    _require(manifest.get("continuation_executor_sha256") == executor_identity(), "SOURCE_STAGE_CONTINUATION_EXECUTOR_CHANGED")
    _require(manifest["source"]["parameters"] == parameters and manifest["source"]["unit"] == "paper_mm",
             "SOURCE_STAGE_REQUEST_PARAMETERS_OR_UNITS_CHANGED")
    names = [row["path"] for row in manifest["artifacts"]]
    _require(len(set(names)) == len(names), "SOURCE_STAGE_DUPLICATE_ARTIFACT_PATH")
    actual = {p.relative_to(path.parent).as_posix() for p in path.parent.rglob("*") if p.is_file()}
    _require(actual == set(names) | {path.name}, "SOURCE_STAGE_ARTIFACT_SET_CHANGED")
    for row in manifest["artifacts"]:
        _checked(path.parent, row)
    old_request = read_json(path.parent / "origin/request.json")
    old_stage = read_json(path.parent / "origin/completed_stages.json")
    _require(manifest["historical_worker_algorithm"] == old_request["algorithm"], "SOURCE_STAGE_HISTORICAL_ALGORITHM_CHANGED")
    _require(old_stage["assembly"]["algorithm_fingerprint"] == old_request["algorithm"]
             and file_sha(path.parent / "origin/completed_assembly.json") == old_stage["assembly"]["sha256"],
             "SOURCE_STAGE_ORIGIN_ASSEMBLY_CHANGED")
    _require(_source_identity(source, parameters, old_stage) == manifest["source"], "SOURCE_STAGE_INPUT_BINDING_CHANGED")
    _require(producer_closure(path.parent / "origin/source", old_request["algorithm"]) == manifest["producer_closure"],
             "SOURCE_STAGE_PRODUCER_CLOSURE_CHANGED")
    _require(dependency_identity(read_json(path.parent / "origin/environment.json"), read_json(path.parent / "origin/resources.json"))
             == manifest["runtime_and_resources"], "SOURCE_STAGE_RUNTIME_OR_RESOURCE_BYTES_CHANGED")
    state, removed = project_upstream(read_json(path.parent / "origin/completed_assembly.json"),
                                      read_json(path.parent / "origin/attached_plan.json"),
                                      read_json(path.parent / "origin/attached_adoption.json"))
    _require(state == read_json(path.parent / "upstream_state.json") and digest(state) == manifest["upstream_state_sha256"]
             and removed == manifest["excluded_historical_stage_object_ids"], "SOURCE_STAGE_COMPLETE_FINITE_STATE_CHANGED")
    _require(manifest["restored_evidence_paths"] == sorted(name[len("evidence/"):] for name in names if name.startswith("evidence/")),
             "SOURCE_STAGE_RESTORE_ASSET_SET_CHANGED")
    _require(verify_declared_raw_files(state, path.parent / "evidence") == manifest["declared_raw_evidence_paths"],
             "SOURCE_STAGE_DECLARED_RAW_ASSETS_CHANGED")
    _require(manifest["reused_stages"] == STAGES and manifest["downstream_required"] == DOWNSTREAM
             and manifest["old_DXF_read"] is False, "SOURCE_STAGE_EXECUTION_BOUNDARY_CHANGED")
    return manifest


def capture_checkpoint(manifest_path, job_directory, source_sha256, parameters):
    job = Path(job_directory).resolve()
    source = next((job / "inputs").glob("source.*"))
    destination = job / "imports/source-stage-checkpoint"
    try:
        _require(file_sha(source) == source_sha256, "SOURCE_STAGE_CAPTURED_INPUT_CHANGED")
        before = file_sha(manifest_path)
        manifest = verify_checkpoint(manifest_path, source=source, parameters=parameters, expected_sha256=before)
        _require(not destination.exists(), "SOURCE_STAGE_CAPTURE_DESTINATION_EXISTS")
        for row in manifest["artifacts"]:
            _copy(_checked(Path(manifest_path).resolve().parent, row), destination / row["path"])
        _copy(manifest_path, destination / "manifest.json")
        _require(file_sha(manifest_path) == before, "SOURCE_STAGE_CHANGED_DURING_CAPTURE")
        binding = {"schema": CAPTURE_SCHEMA, "manifest_path": str(destination / "manifest.json"),
                   "manifest_sha256": before, "source_sha256": source_sha256,
                   "parameters": deepcopy(parameters), "execution_mode": "SOURCE_STAGE_CHECKPOINT_CONTINUATION",
                   "reused_stages": STAGES, "downstream_required": DOWNSTREAM}
        save_json(job / "source_stage_checkpoint_capture.json", {"status": "CAPTURED_VALIDATED_SOURCE_CHECKPOINT", **binding})
        return binding
    except Exception as exc:
        save_json(job / "source_stage_checkpoint_capture_failure.json", {
            "status": "REJECTED", "schema": CAPTURE_SCHEMA, "error_type": type(exc).__name__,
            "reason": str(exc), "fresh_fit_fallback_attempted": False, "source_sha256": source_sha256})
        raise


def verify_captured_checkpoint(binding, job_directory, source_sha256, parameters):
    job, path = Path(job_directory).resolve(), Path(binding["manifest_path"]).resolve()
    _require(binding.get("schema") == CAPTURE_SCHEMA and path == job / "imports/source-stage-checkpoint/manifest.json",
             "SOURCE_STAGE_CAPTURE_BINDING_INVALID")
    _require(binding["source_sha256"] == source_sha256 and binding["parameters"] == parameters,
             "SOURCE_STAGE_CAPTURED_REQUEST_CHANGED")
    source = next((job / "inputs").glob("source.*"))
    return verify_checkpoint(path, source=source, parameters=parameters, expected_sha256=binding["manifest_sha256"])


def restore_for_pipeline(binding, job, prepared, output):
    path, output = Path(binding["manifest_path"]), Path(output)
    manifest = verify_checkpoint(path, source=job.input_path, parameters=binding["parameters"],
                                 expected_sha256=binding["manifest_sha256"])
    _require(prepared.source_sha256 == manifest["source"]["source_sha256"]
             and prepared.manifest["cache_identity"] == manifest["source"]["cache_identity"]
             and list(prepared.working_roi) == manifest["source"]["working_roi_xyxy_px"],
             "SOURCE_STAGE_PREPARED_SOURCE_CHANGED")
    for name in manifest["restored_evidence_paths"]:
        _copy(_inside(path.parent / "evidence", name), _inside(output, name))
    state = read_json(path.parent / "upstream_state.json")
    stages = read_json(path.parent / "origin/completed_stages.json")
    stages.pop("assembly")
    save_json(output / "completed_stages.json", stages)
    receipt = {"schema": "source-stage-continuation-execution-v1", "status": "UPSTREAM_RESTORED_DOWNSTREAM_NOT_RUN",
               "execution_mode": "SOURCE_STAGE_CHECKPOINT_CONTINUATION", "checkpoint_manifest_sha256": file_sha(path),
               "source": manifest["source"], "producer_closure": manifest["producer_closure"],
               "runtime_and_resources": manifest["runtime_and_resources"], "reused_stages": STAGES,
               "upstream_state_sha256": digest(state), "prior_object_count": len(state["objects"]),
               "downstream": {name: "NOT_RUN" for name in DOWNSTREAM},
               "old_attached_result_reused": False, "old_DXF_read": False,
               "new_upstream_fits": 0, "new_OCR_calls": 0, "new_model_inferences": 0,
               "uncached_fresh_path": "RETAINED_WITH_KNOWN_HISTORICAL_GEOMETRY_DRIFT_LIMITATION"}
    save_json(output / "source_stage_continuation.json", receipt)
    return state


def update_execution(output, **states):
    path = Path(output) / "source_stage_continuation.json"
    if not path.is_file():
        return
    receipt = read_json(path)
    _require(set(states) <= set(DOWNSTREAM), "SOURCE_STAGE_UNKNOWN_EXECUTION_STAGE")
    receipt["downstream"].update(states)
    receipt["status"] = "SOURCE_STAGE_CONTINUATION_WITH_CURRENT_DOWNSTREAM_EXECUTION"
    save_json(path, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    for option in ("evidence", "request", "previous-source", "environment", "resources", "source", "output"):
        create.add_argument("--" + option, required=True, type=Path)
    args = parser.parse_args()
    result = build_checkpoint(**{k: v for k, v in vars(args).items() if k != "command"})
    print(json.dumps({"manifest": str(result), "sha256": file_sha(result), "schema": SCHEMA}))


if __name__ == "__main__":
    main()
