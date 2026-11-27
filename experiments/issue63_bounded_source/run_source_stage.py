"""Rebuild a bounded-source local stage without replacing the ordinary drawing.

Only prior bindings, their source scope, and complete circle source objects are
inputs to the producer. Old candidate paths and old PASS values are not inputs.
The separate process replays every actual saved plan field, then reads the
actual drawings and each independent whole-object edit. A successful producer
replay is not an independent physical source certificate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from io import StringIO
from pathlib import Path

EXPECTED_PLAN_SCHEMA = "source-attached-stroke-graph-plan-v4-bounded-source"
EXPECTED_COMPONENT_SCHEMA = "source-finite-component-responsibility-v2-bounded-field"
DPI = 200
DEFAULT_REPO = Path(__file__).resolve().parents[2]
CONTEXT_FIELDS = ("review", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header")


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, set):
        return [plain(item) for item in sorted(value, key=repr)]
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    return value


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(plain(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def configure(repo, output):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo / "cad_photo_to_dxf"))
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", ORT_DISABLE_TELEMETRY="1",
        OMP_NUM_THREADS="1", OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
        XDG_CACHE_HOME=str(output / "runtime-cache"), MPLCONFIGDIR=str(output / "matplotlib"))


def source_files(repo):
    files = list((repo / "cad_photo_to_dxf/app").rglob("*.py"))
    files += list((repo / "docs/native").glob("ISSUE63_*.md"))
    files += list(Path(__file__).resolve().parent.glob("*.py"))
    return {str(path.relative_to(repo)): sha(path) for path in sorted(set(files))}


def git_identity(repo):
    def read(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=repo, text=True).strip()
    return {"head": read("rev-parse", "HEAD"), "head_tree": read("rev-parse", "HEAD^{tree}"),
            "worktree_dirty": bool(read("status", "--porcelain")),
            "uncommitted_execution_is_bound_by_exact_source_file_hashes": True}


def snapshot_entrypoints(repo, output, arguments):
    directory = output / "executed_entrypoints"
    directory.mkdir()
    entries = []
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        destination = directory / path.name
        shutil.copyfile(path, destination)
        entries.append({"source": str(path.relative_to(repo)), "snapshot": str(destination.relative_to(output)),
                        "size_bytes": path.stat().st_size, "sha256": sha(path)})
    write(output / "EXECUTION_ENTRY.json", {"entries": entries, "arguments": arguments,
        "python_executable": sys.executable, "python_version": sys.version, "git": git_identity(repo)})


def file_manifest(output):
    return {str(path.relative_to(output)): {"size_bytes": path.stat().st_size, "sha256": sha(path)}
            for path in sorted(output.rglob("*")) if path.is_file() and path.name != "FILE_MANIFEST.json"}


def _exact(value):
    """Exact persisted binary64 values; no decimal rounding or epsilon."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NONFINITE_SAVED_DXF_VALUE")
        return {"binary64": value.hex()}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _exact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)) or hasattr(value, "__iter__"):
        return [_exact(item) for item in value]
    raise TypeError(type(value).__name__)


def entity_record(entity):
    from ezdxf.lldxf.tagwriter import TagCollector

    tags = TagCollector.dxftags(entity, dxfversion=entity.doc.dxfversion)
    return {"type": entity.dxftype(), "tags": [[tag.code, _exact(tag.value)]
        for tag in tags if tag.code not in (5, 105, 330)]}


def native_entities(doc):
    from app.native_objects.cad_io import APPID

    result = {}
    for entity in doc.modelspace():
        if entity.dxf.layer == "REVIEW":
            continue
        chunks = [tag.value for tag in entity.get_xdata(APPID) if tag.code == 1000]
        identity = json.loads("".join(chunks))
        oid = identity.get("id")
        if not isinstance(oid, str) or not oid or oid in result:
            raise ValueError("INVALID_OR_DUPLICATE_SAVED_NATIVE_IDENTITY")
        result[oid] = entity
    return result


def snapshot_doc(doc):
    entities = native_entities(doc)
    review = [entity_record(entity) for entity in doc.modelspace() if entity.dxf.layer == "REVIEW"]
    return {"formal": {oid: entity_record(entity) for oid, entity in sorted(entities.items())},
        "review": sorted(review, key=lambda row: json.dumps(row, sort_keys=True)),
        "blocks": {block.name: {"record": entity_record(block.block_record),
            "begin": entity_record(block.block), "end": entity_record(block.endblk),
            "members": [entity_record(entity) for entity in block]}
            for block in doc.blocks if not block.name.startswith(("*Model_Space", "*Paper_Space"))},
        "styles": {entity.dxf.name: entity_record(entity) for entity in doc.styles},
        "layers": {entity.dxf.name: entity_record(entity) for entity in doc.layers},
        "linetypes": {entity.dxf.name: entity_record(entity) for entity in doc.linetypes},
        "units_and_coordinate_header": {key: _exact(doc.header.get(key)) for key in
            ("$INSUNITS", "$MEASUREMENT", "$LUNITS", "$AUNITS", "$INSBASE")},
        "excluded_database_metadata": ["entity handle (5/105)", "owner handle (330)",
            "unlisted header timestamps/GUID/handseed"]}


def strict_preservation(before, after, new_ids=(), allowed_added_layers=()):
    old_ids, actual_ids, new_ids = set(before["formal"]), set(after["formal"]), set(new_ids)
    checks = {"actual_id_set_exact": actual_ids == old_ids | new_ids,
        "new_ids_disjoint_from_prior": not old_ids.intersection(new_ids),
        "all_prior_entities_exact": all(after["formal"].get(oid) == record
            for oid, record in before["formal"].items())}
    for field in CONTEXT_FIELDS:
        expected = before[field]
        actual = after[field]
        if field == "layers" and allowed_added_layers:
            checks["only_declared_diagnostic_layers_added"] = (
                set(actual) - set(expected) <= set(allowed_added_layers))
            actual = {key: value for key, value in actual.items() if key in expected}
        checks[field + "_exact"] = actual == expected
    return {"checks": checks, "pass": all(checks.values()), "prior_count": len(old_ids),
        "new_count": len(new_ids), "excluded_database_metadata": before["excluded_database_metadata"],
        "source_responsibility": "NOT_ESTABLISHED_BY_GEOMETRY_PRESERVATION"}


def append_native_object(doc, obj, transform):
    """Only new independent strokes use the shared transform; priors stay intact."""
    from app.native_objects.cad_io import mark

    geometry = obj["geometry"]
    attrs = {"layer": obj["layer"], "color": 256}
    if obj["kind"] == "LINE":
        entity = doc.modelspace().add_line(transform(geometry["start"]), transform(geometry["end"]), dxfattribs=attrs)
    elif obj["kind"] == "CONNECTION_PATH":
        points, bulges = geometry["points"], geometry["bulges"]
        if len(points) < 2 or len(points) != len(bulges) or geometry.get("closed", False):
            raise ValueError("NEW_LOCAL_PATH_MUST_BE_ONE_COMPLETE_OPEN_CHAIN")
        entity = doc.modelspace().add_lwpolyline([(*transform(point), -float(bulge))
            for point, bulge in zip(points, bulges)], format="xyb", close=False, dxfattribs=attrs)
    else:
        raise ValueError("NEW_LOCAL_OBJECT_KIND_NOT_IN_DECLARED_SCOPE:" + str(obj["kind"]))
    mark(entity, obj)
    return entity, {"id": obj["id"], "kind": obj["kind"], "type": entity.dxftype(),
                    "handle": entity.dxf.handle, "block_members": []}


def save_edits(original, output, ids, label):
    import ezdxf
    from app.native_objects.cad_io import save_native_dxf

    edits = []
    for oid in ids:
        for operation in ("delete", "move"):
            doc = ezdxf.readfile(original)
            entity = native_entities(doc)[oid]
            delta = [7.0, -3.0, 0.0]
            if operation == "delete":
                doc.modelspace().delete_entity(entity)
            else:
                entity.translate(*delta)
            destination = output / "edits" / (oid + "-" + operation + ".dxf")
            destination.parent.mkdir(exist_ok=True)
            if destination.exists():
                raise ValueError("EDIT_DESTINATION_ALREADY_EXISTS")
            save_native_dxf(doc, destination)
            edits.append({"id": oid, "operation": operation, "file": destination.relative_to(output).as_posix(),
                "sha256": sha(destination), "translation_mm": delta if operation == "move" else None,
                "scope": label, "operation_mode": "PROGRAMMATIC_EZDXF_SAVE_NOT_CAD_GUI"})
    return edits


def cold_edit_checks(original_path, output, edits):
    import ezdxf

    original = ezdxf.readfile(original_path)
    before = snapshot_doc(original)
    reports = []
    for edit in edits:
        path = output / edit["file"]
        after = snapshot_doc(ezdxf.readfile(path))
        oid, operation = edit["id"], edit["operation"]
        expected_ids = set(before["formal"]) - ({oid} if operation == "delete" else set())
        checks = {"file_sha256": sha(path) == edit["sha256"], "actual_id_set_exact": set(after["formal"]) == expected_ids,
            "all_non_target_entities_exact": {key: value for key, value in after["formal"].items() if key != oid}
                == {key: value for key, value in before["formal"].items() if key != oid},
            **{field + "_exact": before[field] == after[field] for field in CONTEXT_FIELDS}}
        if operation == "delete":
            checks["whole_target_deleted"] = oid not in after["formal"]
        else:
            expected_doc = ezdxf.readfile(original_path)
            native_entities(expected_doc)[oid].translate(*edit["translation_mm"])
            stream = StringIO()
            expected_doc.write(stream)
            stream.seek(0)
            expected = snapshot_doc(ezdxf.read(stream))
            checks["whole_target_translation_exact"] = after["formal"].get(oid) == expected["formal"].get(oid)
        reports.append({**edit, "checks": checks, "pass": all(checks.values()),
            "excluded_database_metadata": before["excluded_database_metadata"]})
    return reports


def all_candidates(plan):
    rows = {row["stroke_id"]: row for component in plan.get("components", [])
            for row in component.get("candidate_paths", [])}
    rows.update({row["stroke_id"]: row for row in plan.get("paths", [])})
    return rows


def model_receipts(plan):
    """Retain complete current and diagnostic receipts, without rerunning old rules."""
    return [{"component_id": component["component_id"],
        "component_status": component.get("status"), "failed_adoption_gates": component.get("failed_adoption_gates", []),
        "actual_component_fields": sorted(component),
        "finite_component_responsibility": component.get("finite_component_responsibility"),
        "additional_model_diagnostics": {key: value for key, value in component.items()
            if any(marker in key.lower() for marker in ("constant_width", "bounded_field", "legacy_model"))},
        "shared_finite_vertex_construction": component.get("shared_finite_vertex_construction"),
        "prior_native_contact_check": component.get("prior_native_contact_check")}
        for component in plan.get("components", []) if component.get("candidate_paths")]


def _mapping(entity, oid, status):
    return {"object_id": oid, "handle": entity.dxf.handle, "status": status,
            "layer": entity.dxf.layer, "persisted_entity_record": entity_record(entity)}


def save_local_drawings(out, plan, adopted_objects, source_sha, baseline_dxf):
    import ezdxf
    from app.native_objects.cad_io import APPID, save_native_dxf
    from app.native_objects.finite_source_junction import SharedCoordinateTransform
    from app.native_objects.text_contact_adoption import _native_object

    rows = all_candidates(plan)
    adopted_ids = {obj["id"] for obj in adopted_objects}
    if adopted_ids != {row["stroke_id"] for row in plan["paths"]}:
        raise ValueError("ADOPTED_OBJECTS_DIFFER_FROM_PLAN_PATHS")
    mapper = SharedCoordinateTransform(plan["roi_xyxy_px"], DPI)
    neighbors = {body["stroke_id"]: body for component in plan["components"]
        for body in component.get("finite_component_responsibility", {}).get("bodies", [])
        if body.get("body_role") == "NECESSARY_PRIOR_FINITE_NEIGHBOR" and isinstance(body.get("representation"), dict)}
    files = []
    for include_context in (False, True):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = 0
        doc.appids.new(APPID)
        for name, color in (("NOT_ADOPTED", 1), ("LOCAL_STAGE_ADOPTED", 3), ("CONTEXT_PRIOR", 8)):
            doc.layers.new(name, dxfattribs={"color": color})
        mappings = []
        for identity, row in [*rows.items(), *(neighbors.items() if include_context else [])]:
            geometry = row["representation"]
            context = identity in neighbors
            status = "PRIOR_CONTEXT_ONLY" if context else "LOCAL_STAGE_ADOPTED" if identity in adopted_ids else "NOT_ADOPTED"
            layer = "CONTEXT_PRIOR" if context else status
            points = geometry["points"]
            bulges = geometry.get("bulges", [0.0] * len(points))
            entity = doc.modelspace().add_lwpolyline([(*point, bulge) for point, bulge in zip(points, bulges)],
                format="xyb", close=bool(geometry.get("closed", False)), dxfattribs={"layer": layer})
            entity.set_xdata(APPID, [(1000, json.dumps({"id": identity, "kind": "CONNECTION_PATH"}))])
            mappings.append(_mapping(entity, identity, status))
        name = "LOCAL_CANDIDATES_WITH_CONTEXT.dxf" if include_context else "LOCAL_CANDIDATES_ONLY.dxf"
        path = out / name
        save_native_dxf(doc, path)
        files.append({"file": name, "sha256": sha(path), "size_bytes": path.stat().st_size,
            "target_ids": sorted(rows), "context_ids": sorted(neighbors) if include_context else [],
            "source_sha256": source_sha, "entities": mappings, "all_modelspace_entity_count": len(doc.modelspace()),
            "coordinate_frame": "UNCHANGED_SOURCE_PIXEL_COORDINATES_Y_DOWN", "units": "PIXELS_NOT_PAPER_MM",
            "ordinary_whole_region_result": False, "formal_new_objects_claimed_from_this_local_file": False})
    baseline_sha = sha(baseline_dxf)
    baseline_doc = ezdxf.readfile(baseline_dxf)
    if baseline_doc.units != 4:
        raise ValueError("BASELINE_CONTEXT_MUST_BE_ACTUAL_PAPER_MM")
    baseline_snapshot = snapshot_doc(baseline_doc)
    write(out / "BASELINE_SAVED_CONTENT.json", baseline_snapshot)
    pending = [row for oid, row in rows.items() if oid not in adopted_ids]
    if pending:
        doc = ezdxf.readfile(baseline_dxf)
        layer = "NOT_ADOPTED_ISSUE63"
        if layer not in doc.layers:
            doc.layers.new(layer, dxfattribs={"color": 1})
        mappings = []
        for row in pending:
            kind, geometry = _native_object(row["representation"])
            obj = {"id": row["stroke_id"], "kind": kind, "layer": layer, "geometry": geometry}
            entity, _ = append_native_object(doc, obj, mapper)
            mappings.append(_mapping(entity, obj["id"], "NOT_ADOPTED"))
        path = out / "NOT_ADOPTED_BASELINE_CONTEXT_REVIEW.dxf"
        save_native_dxf(doc, path)
        files.append({"file": path.name, "sha256": sha(path), "size_bytes": path.stat().st_size,
            "target_ids": [row["stroke_id"] for row in pending], "context_source_dxf_sha256": baseline_sha,
            "source_sha256": source_sha, "entities": mappings, "all_modelspace_entity_count": len(doc.modelspace()),
            "coordinate_frame": "PAPER_MM_AT_DECLARED_ROI", "dpi": DPI, "units": "paper_mm",
            "engineering_scale": "UNVERIFIED", "ordinary_whole_region_result": False,
            "formal_new_objects_claimed_from_this_local_file": False, "allowed_added_layers": [layer],
            "purpose": "UNADOPTED_CANDIDATES_OVER_ACTUAL_BASELINE_FOR_INDEPENDENT_SOURCE_REVIEW"})
    edits = []
    if adopted_objects:
        doc = ezdxf.readfile(baseline_dxf)
        mappings = []
        for obj in adopted_objects:
            if obj["layer"] not in doc.layers:
                raise ValueError("ACTUAL_ADOPTED_LAYER_MISSING_FROM_BASELINE")
            entity, _ = append_native_object(doc, obj, mapper)
            mappings.append(_mapping(entity, obj["id"], "LOCAL_STAGE_ADOPTED"))
        path = out / "LOCAL_STAGE_ACTUAL_ADOPTED_WITH_BASELINE.dxf"
        save_native_dxf(doc, path)
        files.append({"file": path.name, "sha256": sha(path), "size_bytes": path.stat().st_size,
            "target_ids": sorted(adopted_ids), "context_source_dxf_sha256": baseline_sha,
            "source_sha256": source_sha, "entities": mappings, "all_modelspace_entity_count": len(doc.modelspace()),
            "coordinate_frame": "PAPER_MM_AT_DECLARED_ROI", "dpi": DPI, "units": "paper_mm",
            "engineering_scale": "UNVERIFIED", "ordinary_whole_region_result": False,
            "formal_new_objects_claimed_from_this_local_file": False,
            "purpose": "ACTUAL_LOCAL_STAGE_ADOPTED_OBJECTS_WITH_UNCHANGED_BASELINE"})
        edits = save_edits(path, out, sorted(adopted_ids), "REAL_LOCAL_STAGE_ADOPTED_OBJECT")
    if sha(baseline_dxf) != baseline_sha:
        raise ValueError("ORIGINAL_BASELINE_BYTES_CHANGED")
    write(out / "SHARED_COORDINATE_TRANSFORM.json", mapper.receipt())
    report = {"files": files, "candidate_ids": sorted(rows), "adopted_ids": sorted(adopted_ids),
        "pending_ids": sorted(set(rows) - adopted_ids), "baseline_sha256": baseline_sha, "edits": edits,
        "edit_status": "LOCAL_REAL_EDITS_SAVED" if edits else "NOT_APPLICABLE_NO_NEW_ADOPTED_OBJECTS"}
    write(out / "LOCAL_DRAWINGS.json", report)
    return report


def cold_drawings(out):
    import ezdxf

    records = json.loads((out / "LOCAL_DRAWINGS.json").read_text(encoding="utf-8"))
    before = json.loads((out / "BASELINE_SAVED_CONTENT.json").read_text(encoding="utf-8"))
    checks = []
    for record in records["files"]:
        doc = ezdxf.readfile(out / record["file"])
        rows = []
        for expected in record["entities"]:
            entity = doc.entitydb.get(expected["handle"])
            rows.append({"object_id": expected["object_id"], "pass": entity is not None
                and entity_record(entity) == expected["persisted_entity_record"]})
        check = {"file": record["file"], "sha256_matches": sha(out / record["file"]) == record["sha256"],
            "entity_count_exact": len(doc.modelspace()) == record["all_modelspace_entity_count"],
            "every_new_saved_entity_exact": all(row["pass"] for row in rows), "rows": rows}
        if record.get("context_source_dxf_sha256"):
            check["baseline_protection"] = strict_preservation(before, snapshot_doc(doc), record["target_ids"],
                record.get("allowed_added_layers", ()))
        check["pass"] = all(check[key] for key in ("sha256_matches", "entity_count_exact", "every_new_saved_entity_exact"))
        check["pass"] = check["pass"] and check.get("baseline_protection", {"pass": True})["pass"]
        checks.append(check)
    edits = cold_edit_checks(out / "LOCAL_STAGE_ACTUAL_ADOPTED_WITH_BASELINE.dxf", out, records["edits"]) if records["edits"] else []
    report = {"schema": "issue63-local-saved-geometry-cold-read-v1", "fresh_process": True,
        "checks": checks, "edits": edits, "edit_status": records["edit_status"],
        "pass": all(row["pass"] for row in checks + edits),
        "source_complete_responsibility": "SEPARATE_INDEPENDENT_AUDIT_REQUIRED",
        "ordinary_whole_region_result": False, "gui": "NOT_RUN"}
    write(out / "LOCAL_SAVED_GEOMETRY_COLD_READ.json", report)
    return report


def strict_replay(repo, out):
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from PIL import Image

    cv2.setNumThreads(1)
    identity = json.loads((out / "INPUT_IDENTITY.json").read_text(encoding="utf-8"))
    inputs = identity["files"]
    plan_path = out / "attached/plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    before = source_files(repo)
    with Image.open(inputs["source"]["path"]) as image:
        gray = np.asarray(image.convert("L"))
    replay = attached.verify_attached_stroke_graph_plan(gray, identity["roi_xyxy_px"], plan, source_graph=None)
    exact_checks = replay.get("checks", {})
    saved = cold_drawings(out)
    checks = {"input_files_unchanged": all(sha(row["path"]) == row["sha256"] for row in inputs.values()),
        "plan_schema": plan.get("schema") == EXPECTED_PLAN_SCHEMA,
        "all_actual_saved_plan_fields_compared": bool(exact_checks) and set(exact_checks) == set(plan),
        "all_actual_saved_plan_field_comparisons_pass": bool(exact_checks) and all(value is True for value in exact_checks.values()),
        "source_replay_pass": replay.get("pass") is True and replay.get("reason") == "EXACT_ATTACHED_GRAPH_SOURCE_REPLAY",
        "source_files_unchanged": before == source_files(repo), "actual_saved_geometry_and_edits_pass": saved["pass"]}
    report = {"schema": "issue63-fresh-process-source-and-saved-replay-v1", "pass": all(checks.values()),
        "checks": checks, "actual_saved_plan_fields": sorted(plan), "actual_saved_plan_field_count": len(plan),
        "actually_compared_fields": sorted(exact_checks), "verification": replay, "saved_dxf": saved,
        "source_files_sha256": before, "plan_sha256": sha(plan_path), "new_OCR_calls": 0,
        "numeric_replay_tolerance_added": False, "source_audit_invocation_count": 1,
        "independent_physical_source_certificate": "NOT_CLAIMED_BY_THIS_PRODUCER_REPLAY"}
    write(out / "STRICT_SOURCE_REPLAY.json", report)
    return 0 if report["pass"] else 1


def run_stage(args):
    import cv2
    import numpy as np
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects import text_contact_geometry as contact
    from PIL import Image

    cv2.setNumThreads(1)
    before = source_files(args.repo)
    snapshot_entrypoints(args.repo, args.output, {key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items() if key != "circle_source_object"}
        | {"circle_source_object": [str(path) for path in args.circle_source_object]})
    started = time.perf_counter()
    old = json.loads(args.prior_plan.read_text(encoding="utf-8"))
    circles = [json.loads(path.read_text(encoding="utf-8")) for path in args.circle_source_object]
    paths = {"source": args.source, "prior_plan": args.prior_plan, "baseline_dxf": args.baseline_dxf}
    paths.update({f"circle_source_object_{index}": path for index, path in enumerate(args.circle_source_object)})
    inputs = {key: {"path": str(path.resolve()), "sha256": sha(path), "size_bytes": path.stat().st_size}
              for key, path in paths.items()}
    write(args.output / "INPUT_IDENTITY.json", {"files": inputs, "roi_xyxy_px": old["roi_xyxy_px"],
        "dpi": DPI, "circle_source_object_count": len(circles), "input_files_are_read_only": True})
    if attached.SCHEMA != EXPECTED_PLAN_SCHEMA:
        raise ValueError("NEW_BOUNDED_SOURCE_PLAN_SCHEMA_REQUIRED")
    with Image.open(args.source) as image:
        gray = np.asarray(image.convert("L"))
    print("Rebuilding the unchanged source graph", flush=True)
    context = contact.build_text_contact_source_graph(gray, old["roi_xyxy_px"])
    if (context.crop_bbox != old["original_source_crop_xyxy_px"]
            or context.source_crop_hash != old["original_source_crop_array_sha256"]):
        raise ValueError("ORIGINAL_SOURCE_SCOPE_DOES_NOT_MATCH_PRIOR_BINDINGS")
    graph_seconds = time.perf_counter() - started
    print("Running the bounded-source local stage", flush=True)
    adoption = attached.complete_attached_strokes(gray, old["roi_xyxy_px"], inputs["source"]["sha256"],
        old["prior_object_bindings"], args.output / "attached", source_graph=context, circle_source_objects=circles)
    plan = adoption["plan"]
    write(args.output / "MODEL_RECEIPTS.json", model_receipts(plan))
    saved = save_local_drawings(args.output, plan, adoption["objects"], inputs["source"]["sha256"], args.baseline_dxf)
    with (args.output / "strict_replay.log").open("x", encoding="utf-8") as log:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
            "--output", str(args.output), "--cold-replay"], stdout=log, stderr=subprocess.STDOUT,
            check=False, timeout=args.replay_timeout_seconds)
    strict_path = args.output / "STRICT_SOURCE_REPLAY.json"
    strict = json.loads(strict_path.read_text(encoding="utf-8")) if strict_path.exists() else {}
    summaries = []
    for component in plan["components"]:
        proof = component.get("finite_component_responsibility")
        if not isinstance(proof, dict):
            continue
        summaries.append({"component_id": component["component_id"], "status": proof.get("status"),
            "schema": proof.get("schema"), "schema_matches": proof.get("schema") == EXPECTED_COMPONENT_SCHEMA,
            "pass": proof.get("pass"), "failure_reasons": proof.get("failure_reasons", []),
            "candidate_ids": proof.get("candidate_ids", []), "actual_proof_fields": sorted(proof),
            "proof_sha256": digest(proof), "black_ledger_count": len(proof.get("pixel_ledger", [])),
            "white_ledger_count": len(proof.get("white_ledger", [])), "observation_closed": proof.get("observation_closed"),
            "shared_vertex_construction": component.get("shared_finite_vertex_construction"),
            "failed_adoption_gates": component.get("failed_adoption_gates", [])})
    checks = {"input_files_unchanged": all(sha(row["path"]) == row["sha256"] for row in inputs.values()),
        "source_files_unchanged_during_run": before == source_files(args.repo),
        "strict_source_and_saved_replay_pass": strict.get("pass") is True,
        "local_cold_process_exit_code_zero": completed.returncode == 0,
        "all_present_component_schemas_match": all(row["schema_matches"] for row in summaries)}
    report = {"schema": "issue63-complete-bounded-source-local-stage-v1", "scope": "LOCAL_STAGE_NOT_ORDINARY_WHOLE_REGION",
        "pass": all(checks.values()), "checks": checks, "inputs": inputs,
        "original_source_crop_array_sha256": context.source_crop_hash, "roi_xyxy_px": old["roi_xyxy_px"],
        "prior_binding_count": len(old["prior_object_bindings"]), "circle_source_object_count": len(circles),
        "old_proposed_paths_imported": False, "fresh_source_graph": True,
        "candidate_count": len(saved["candidate_ids"]), "new_stage_adopted_count": len(adoption["objects"]),
        "pending_count": len(saved["pending_ids"]), "components": summaries,
        "actual_saved_plan_fields": sorted(plan), "actual_saved_plan_field_count": len(plan),
        "model_receipts": "MODEL_RECEIPTS.json", "new_OCR_calls": 0, "new_model_inferences": 0,
        "graph_seconds": graph_seconds, "total_seconds": time.perf_counter() - started,
        "execution_identity": git_identity(args.repo), "source_files_sha256": before,
        "producer_sha256": plan.get("producer_sha256"), "additional_producer_sha256": plan.get("additional_producer_sha256"),
        "local_dxf_cold_process_exit_code": completed.returncode, "new_real_object_delete_move": saved["edit_status"],
        "valid_baseline_replaced": False, "ordinary_joint_run": "NOT_RUN_IN_THIS_LOCAL_STAGE",
        "independent_physical_source_certificate": "SEPARATE_ACTUAL_SAVED_AUDIT_REQUIRED"}
    write(args.output / "STAGE_SUMMARY.json", report)
    print(json.dumps({"pass": report["pass"], "candidates": report["candidate_count"],
        "adopted": report["new_stage_adopted_count"], "seconds": report["total_seconds"]}, indent=2))
    return 0 if report["pass"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--prior-plan", type=Path)
    parser.add_argument("--baseline-dxf", type=Path)
    parser.add_argument("--circle-source-object", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-timeout-seconds", type=float, default=900)
    parser.add_argument("--cold-replay", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.repo, args.output = args.repo.resolve(), args.output.resolve()
    configure(args.repo, args.output)
    if args.cold_replay:
        try:
            return strict_replay(args.repo, args.output)
        except Exception as exc:
            path = args.output / "STRICT_SOURCE_REPLAY_ERROR.json"
            if not path.exists():
                write(path, {"pass": False, "type": type(exc).__name__, "message": str(exc),
                    "traceback": traceback.format_exc()})
            raise
    if args.output.exists():
        parser.error("Output must be a new directory; earlier evidence is never overwritten.")
    if any(getattr(args, key) is None for key in ("source", "prior_plan", "baseline_dxf")):
        parser.error("--source, --prior-plan and --baseline-dxf are required for a new local stage.")
    if args.replay_timeout_seconds <= 0:
        parser.error("Replay timeout must be positive.")
    args.output.mkdir(parents=True)
    try:
        return run_stage(args)
    except Exception as exc:
        write(args.output / "STAGE_EXECUTION_ERROR.json", {"pass": False, "type": type(exc).__name__,
            "message": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        write(args.output / "FILE_MANIFEST.json", {"files": file_manifest(args.output), "includes_failed_stage_outputs": True})


if __name__ == "__main__":
    sys.exit(main())
