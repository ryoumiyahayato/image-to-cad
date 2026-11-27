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
import importlib.util
import inspect
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from copy import deepcopy
from datetime import datetime
from io import StringIO
from pathlib import Path

EXPECTED_PLAN_SCHEMA = "source-attached-stroke-graph-plan-v4-bounded-source"
EXPECTED_COMPONENT_SCHEMA = "source-finite-component-responsibility-v2-bounded-field"
DPI = 200
DEFAULT_REPO = Path(__file__).resolve().parents[2]
CONTEXT_FIELDS = ("review", "unmarked_modelspace_entities", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header",
                  "non_modelspace_entities")
HEADER_SAVE_METADATA = ("$TDUPDATE", "$TDUUPDATE", "$VERSIONGUID", "$HANDSEED")


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
    runtime = Path(tempfile.gettempdir()) / "image-to-cad-issue63-runtime" / digest(str(output))[:16]
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", ORT_DISABLE_TELEMETRY="1",
        OMP_NUM_THREADS="1", OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
        XDG_CACHE_HOME=str(runtime / "cache"), MPLCONFIGDIR=str(runtime / "matplotlib"))


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
    return {"type": entity.dxftype(), "tags": [[tag.code, _exact(tag.value)] for tag in tags]}


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


def raw_header(path, encoding):
    """Read the persisted header, before Drawing's read-time metadata changes."""
    from ezdxf.lldxf.tagger import ascii_tags_loader, tag_compiler

    variables, current, inside = {}, None, False
    with Path(path).open("r", encoding=encoding, errors="surrogateescape") as stream:
        tags = iter(tag_compiler(ascii_tags_loader(stream)))
        for tag in tags:
            if not inside:
                if tag == (0, "SECTION"):
                    name = next(tags)
                    if name == (2, "HEADER"):
                        inside = True
                continue
            if tag == (0, "ENDSEC"):
                return variables
            if tag.code == 9:
                current = tag.value
                variables.setdefault(current, []).append([])
            elif current is None:
                raise ValueError("RAW_DXF_HEADER_VALUE_WITHOUT_VARIABLE")
            else:
                variables[current][-1].append([tag.code, _exact(tag.value)])
    raise ValueError("ACTUAL_ASCII_DXF_HEADER_NOT_COMPLETE")


def read_saved_document(path):
    """Read a copy for editing, preserving its actual creation timestamp.

    ezdxf 1.4.5 resets TDCREATE when reading a Drawing. Restore this one header
    value from the original file before ordinary serialization of the copy;
    neither the input file nor serialized output bytes are patched.
    """
    import ezdxf

    doc = ezdxf.readfile(path)
    original = raw_header(path, doc.output_encoding).get("$TDCREATE")
    if original is not None:
        if len(original) != 1 or len(original[0]) != 1 or original[0][0][0] != 40:
            raise ValueError("UNEXPECTED_ACTUAL_TDCREATE_HEADER_REPRESENTATION")
        value = original[0][0][1]
        doc.header["$TDCREATE"] = float.fromhex(value["binary64"]) if isinstance(value, dict) else value
    return doc


def writer_metadata_record(doc):
    """Locate one named ezdxf save marker without exempting its dictionary."""
    metadata = doc.rootdict.get("EZDXF_META")
    marker = metadata.get("WRITTEN_BY_EZDXF") if metadata is not None and metadata.dxftype() == "DICTIONARY" else None
    if marker is None:
        return None
    return {"root_dictionary_handle": doc.rootdict.dxf.handle,
            "metadata_dictionary_handle": metadata.dxf.handle, "dictionary_key": "WRITTEN_BY_EZDXF",
            "handle": marker.dxf.handle, "record": entity_record(marker)}


def snapshot_doc(doc):
    entities = native_entities(doc)
    if not doc.filename or not Path(doc.filename).is_file():
        raise ValueError("PERSISTED_SNAPSHOT_REQUIRES_ACTUAL_SAVED_DXF_FILE")
    header = raw_header(doc.filename, doc.output_encoding)
    modelspace_handles = {entity.dxf.handle for entity in doc.modelspace()}
    review = [entity_record(entity) for entity in doc.modelspace() if entity.dxf.layer == "REVIEW"]
    return {"formal": {oid: entity_record(entity) for oid, entity in sorted(entities.items())},
        "review": sorted(review, key=lambda row: json.dumps(row, sort_keys=True)),
        "unmarked_modelspace_entities": {entity.dxf.handle: entity_record(entity)
            for entity in doc.modelspace() if entity.dxf.handle not in {item.dxf.handle for item in entities.values()}},
        "blocks": {block.name: {"record": entity_record(block.block_record),
            "begin": entity_record(block.block), "end": entity_record(block.endblk),
            "members": [entity_record(entity) for entity in block]}
            for block in doc.blocks if not block.name.startswith(("*Model_Space", "*Paper_Space"))},
        "styles": {entity.dxf.name: entity_record(entity) for entity in doc.styles},
        "layers": {entity.dxf.name: entity_record(entity) for entity in doc.layers},
        "linetypes": {entity.dxf.name: entity_record(entity) for entity in doc.linetypes},
        # This also binds APPID/DIMSTYLE/UCS/VIEW/VPORT tables, dictionaries,
        # layouts, block members and attached attributes. No non-target resource
        # is silently dropped merely because it is not one of the common tables.
        "non_modelspace_entities": {entity.dxf.handle: entity_record(entity)
            for entity in doc.entitydb.values() if entity.is_alive
            and entity.dxf.handle not in modelspace_handles},
        "units_and_coordinate_header": {key: value for key, value in sorted(header.items())
            if key not in HEADER_SAVE_METADATA},
        "header_save_metadata": {key: header.get(key) for key in HEADER_SAVE_METADATA},
        "header_read_from": "ACTUAL_SAVED_ASCII_DXF_HEADER_TAGS",
        "writer_bookkeeping": writer_metadata_record(doc),
        "excluded_database_metadata": list(HEADER_SAVE_METADATA),
        "entity_handles_owner_handles_and_all_non_modelspace_resources_compared": True}


def writer_time_delta(before, after):
    """Allow only the timestamp substring in the same named marker's code 1.

    Its dictionary, key, handle, owner, DXF subclass and every other tag remain
    under the exact resource comparison. A changed version or malformed marker
    is not treated as save bookkeeping.
    """
    previous, current = before.get("writer_bookkeeping"), after.get("writer_bookkeeping")
    result = {"named_path": "ROOT/EZDXF_META/WRITTEN_BY_EZDXF", "before": previous, "after": current,
              "changed": previous != current, "permitted_timestamp_change": False,
              "all_other_resource_tags_remain_subject_to_exact_comparison": True}
    if previous is None or current is None:
        return result
    if {key: value for key, value in previous.items() if key != "record"} != {
            key: value for key, value in current.items() if key != "record"}:
        return result
    old, new = previous["record"], current["record"]
    old_values = [value for code, value in old["tags"] if code == 1]
    new_values = [value for code, value in new["tags"] if code == 1]
    if (old["type"] != "DICTIONARYVAR" or new["type"] != "DICTIONARYVAR"
            or len(old_values) != 1 or len(new_values) != 1
            or not all(isinstance(value, str) for value in old_values + new_values)
            or {**old, "tags": [[code, value] for code, value in old["tags"] if code != 1]}
            != {**new, "tags": [[code, value] for code, value in new["tags"] if code != 1]}):
        return result
    old_parts, new_parts = old_values[0].rsplit(" @ ", 1), new_values[0].rsplit(" @ ", 1)
    if len(old_parts) != 2 or len(new_parts) != 2 or old_parts[0] != new_parts[0]:
        return result
    try:
        datetime.fromisoformat(old_parts[1])
        datetime.fromisoformat(new_parts[1])
    except ValueError:
        return result
    result.update(permitted_timestamp_change=True, marker_handle=previous["handle"],
                  preserved_library_version=old_parts[0], before_timestamp=old_parts[1], after_timestamp=new_parts[1])
    return result


def strict_preservation(before, after, new_ids=(), allowed_added_layers=()):
    old_ids, actual_ids, new_ids = set(before["formal"]), set(after["formal"]), set(new_ids)
    checks = {"actual_id_set_exact": actual_ids == old_ids | new_ids,
        "new_ids_disjoint_from_prior": not old_ids.intersection(new_ids),
        "all_prior_entities_exact": all(after["formal"].get(oid) == record
            for oid, record in before["formal"].items())}
    bookkeeping = writer_time_delta(before, after)
    for field in CONTEXT_FIELDS:
        expected = before[field]
        actual = after[field]
        if field == "layers" and allowed_added_layers:
            checks["only_declared_diagnostic_layers_added"] = (
                set(actual) - set(expected) <= set(allowed_added_layers))
            actual = {key: value for key, value in actual.items() if key in expected}
        if field == "non_modelspace_entities" and allowed_added_layers:
            additions = {key: value for key, value in actual.items() if key not in expected}
            allowed = set(allowed_added_layers)
            checks["only_declared_layer_resource_entities_added"] = all(
                value["type"] == "LAYER" and next((v for code, v in value["tags"] if code == 2), None) in allowed
                for value in additions.values())
            actual = {key: value for key, value in actual.items() if key in expected}
        if field == "non_modelspace_entities" and bookkeeping["permitted_timestamp_change"]:
            actual = dict(actual)
            handle = bookkeeping["marker_handle"]
            if handle in actual and handle in expected:
                # The full before/after marker remains in both snapshots and
                # in the receipt; only its validated timestamp differs here.
                actual[handle] = {**actual[handle], "tags": [[code, value] if code != 1
                    else next(tag for tag in expected[handle]["tags"] if tag[0] == 1)
                    for code, value in actual[handle]["tags"]]}
            checks[field + "_exact_except_recorded_writer_timestamp"] = actual == expected
        else:
            checks[field + "_exact"] = actual == expected
    return {"checks": checks, "pass": all(checks.values()), "prior_count": len(old_ids),
        "new_count": len(new_ids), "excluded_database_metadata": before["excluded_database_metadata"],
        "header_save_metadata_before": before["header_save_metadata"],
        "header_save_metadata_after": after["header_save_metadata"],
        "tool_writer_timestamp_receipt": bookkeeping,
        "protected_scope": "ALL_PRIOR_ENTITIES_REVIEW_BLOCKS_FONTS_STYLES_LAYERS_AND_RESOURCE_TAGS_EXACT; "
            "ONLY_DECLARED_SAVE_HEADER_FIELDS_AND_NAMED_TOOL_WRITER_TIMESTAMP_REPORTED_SEPARATELY",
        "source_responsibility": "NOT_ESTABLISHED_BY_GEOMETRY_PRESERVATION"}


def memory_identity(gray, prior, circles):
    return {"source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
            "source_shape": list(gray.shape), "source_dtype": str(gray.dtype),
            "prior_source_bindings_sha256": digest(prior), "prior_count": len(prior),
            "circle_source_objects_sha256": digest(circles), "circle_count": len(circles)}


def resource_snapshot(output):
    import resource

    memory = {}
    if Path("/proc/meminfo").is_file():
        memory = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                  for line in Path("/proc/meminfo").read_text().splitlines()
                  if line.split(":", 1)[0] in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}}
    usage = shutil.disk_usage(output)
    return {"memory": memory, "disk_total_bytes": usage.total, "disk_free_bytes": usage.free,
            "process_peak_rss_kib_on_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "pid": os.getpid(), "heavy_tasks_run_serially": True}


def interface_status():
    from app.native_objects import attached_stroke_graph as attached
    from app.native_objects.finite_component_source_audit import (
        audit_saved_source_component,
    )

    complete = inspect.signature(attached.complete_attached_strokes)
    audit = inspect.signature(audit_saved_source_component)
    checks = {"planner_v4": attached.SCHEMA == EXPECTED_PLAN_SCHEMA,
              "complete_entry_accepts_circle_sources": "circle_source_objects" in complete.parameters,
              "independent_reader_accepts_v2_resources": all(key in audit.parameters for key in
                  ("source_model", "prior_source_bindings", "circle_source_objects")),
              "bounded_component_module_present": importlib.util.find_spec(
                  "app.native_objects.bounded_source_component") is not None}
    return {"schema": "issue63-actual-entrypoint-readiness-v1", "checks": checks, "ready": all(checks.values()),
            "planner_schema": attached.SCHEMA, "expected_plan_schema": EXPECTED_PLAN_SCHEMA,
            "expected_component_schema": EXPECTED_COMPONENT_SCHEMA,
            "complete_signature": str(complete), "independent_audit_signature": str(audit),
            "importability_is_not_source_acceptance": True}


def bind_saved_sidecar(path, *, source_path, source_array_sha256, roi, dpi, objects, target_ids, status,
                       prior_source_bindings=(), circle_source_objects=(), font_bindings=None,
                       baseline_dxf=None, allowed_added_layers=(), planner_source_sha256=None,
                       coordinate_frame="PAPER_MM_AT_DECLARED_ROI", input_binding_files=None):
    """Bind complete supplied provenance to actual persisted DXF bytes and tags.

    The saved entity inventory includes all baseline objects/resources even if
    a historical source binding was not supplied for a remote context object.
    Such missing source bindings stay explicit; they are never synthesized.
    """
    import ezdxf

    path, source_path = Path(path).resolve(), Path(source_path).resolve()
    actual_hash = sha(path)
    doc = ezdxf.readfile(path)
    actual = native_entities(doc)
    ids = [row["id"] for row in objects]
    if len(ids) != len(set(ids)) or not set(ids) <= set(actual) or not set(target_ids) <= set(ids):
        raise ValueError("SIDECAR_OBJECT_IDENTITIES_DO_NOT_BIND_ACTUAL_SAVED_DRAWING")
    persisted = snapshot_doc(doc)
    if sha(path) != actual_hash:
        raise ValueError("DXF_CHANGED_WHILE_BINDING_PERSISTED_SIDECAR")
    metadata = {"schema": "issue63-actual-saved-context-sidecar-v1", "dxf_path": str(path),
        "dxf_sha256": actual_hash, "source_path": str(source_path), "source_sha256": sha(source_path),
        "source_array_sha256": source_array_sha256, "roi_xyxy_px": list(roi), "dpi": dpi,
        "planner_source_sha256": planner_source_sha256,
        "planner_source_identity_is_separate_from_file_identity": True,
        "coordinate_frame": coordinate_frame, "unit": "paper_mm" if doc.units == 4 else "source_pixels",
        "objects": deepcopy(objects), "target_ids": sorted(target_ids), "status": status,
        "adoption_claimed_by_sidecar": False, "all_actual_saved_ids": sorted(actual),
        "source_bindings_not_supplied_for_saved_ids": sorted(set(actual) - set(ids)),
        "written": [{"id": oid, "type": entity.dxftype(), "handle": entity.dxf.handle,
                     "layer": entity.dxf.layer, "persisted_entity_record": entity_record(entity)}
                    for oid, entity in sorted(actual.items())],
        "persisted_content": persisted, "persisted_content_sha256": digest(persisted),
        "prior_source_bindings": deepcopy(list(prior_source_bindings)),
        "circle_source_objects": deepcopy(list(circle_source_objects)),
        "prior_source_bindings_sha256": digest(prior_source_bindings),
        "circle_source_objects_sha256": digest(circle_source_objects),
        "font_bindings": deepcopy(font_bindings or {}), "input_binding_files": deepcopy(input_binding_files or {}),
        "baseline_dxf_path": str(Path(baseline_dxf).resolve()) if baseline_dxf is not None else None,
        "baseline_dxf_sha256": sha(baseline_dxf) if baseline_dxf is not None else None,
        "allowed_added_layers": list(allowed_added_layers), "objects_are_provenance_not_source_approval": True}
    sidecar = path.with_suffix(".objects.json")
    write(sidecar, metadata)
    return {"path": str(sidecar), "sha256": sha(sidecar), "dxf_sha256": actual_hash,
            "actual_saved_entity_count": len(actual), "source_sha256": metadata["source_sha256"]}


def cold_saved_sidecar(path, *, run_source_audit=True):
    """Independently bind sidecar/context and optionally run actual v2 source audit.

    A completed negative source verdict is valid evidence for a pending drawing.
    It is never an accepted source model. Adopted targets require acceptance_pass.
    """
    import ezdxf
    import numpy as np
    from PIL import Image

    path = Path(path).resolve()
    sidecar_path = path.with_suffix(".objects.json")
    record = json.loads(sidecar_path.read_text(encoding="utf-8"))
    source_path = Path(record["source_path"])
    source_bytes_before, dxf_bytes_before = sha(source_path), sha(path)
    with Image.open(source_path) as image:
        source = np.asarray(image.convert("L"))
    before_memory = memory_identity(source, record["prior_source_bindings"], record["circle_source_objects"])
    doc = ezdxf.readfile(path)
    actual = snapshot_doc(doc)
    checks = {"actual_dxf_hash": dxf_bytes_before == record["dxf_sha256"],
        "actual_source_file_hash": source_bytes_before == record["source_sha256"],
        "actual_source_array_hash": before_memory["source_array_sha256"] == record["source_array_sha256"],
        "saved_content_digest_matches_sidecar": digest(actual) == record["persisted_content_sha256"],
        "saved_content_exactly_matches_sidecar": actual == record["persisted_content"],
        "all_actual_saved_identities_bound": sorted(actual["formal"]) == record["all_actual_saved_ids"],
        "prior_bindings_digest_matches": digest(record["prior_source_bindings"]) == record["prior_source_bindings_sha256"],
        "circle_objects_digest_matches": digest(record["circle_source_objects"]) == record["circle_source_objects_sha256"],
        "external_binding_files_unchanged": all(sha(item["path"]) == item["sha256"]
            for item in record.get("input_binding_files", {}).values())}
    baseline = None
    if record["baseline_dxf_path"] is not None:
        baseline_path = Path(record["baseline_dxf_path"])
        checks["actual_baseline_bytes_match"] = sha(baseline_path) == record["baseline_dxf_sha256"]
        baseline = strict_preservation(snapshot_doc(ezdxf.readfile(baseline_path)), actual,
                                       record["target_ids"], record["allowed_added_layers"])
        checks["all_persisted_prior_entities_and_resources_protected"] = baseline["pass"]
    audit = {"status": "NOT_RUN_BINDING_VALIDATION_ONLY", "pass": None}
    audit_completed = False
    if run_source_audit and record["coordinate_frame"] == "PAPER_MM_AT_DECLARED_ROI" and record["target_ids"]:
        from app.native_objects.finite_component_source_audit import (
            audit_saved_source_component,
        )

        audit = audit_saved_source_component(path, source_path, record["roi_xyxy_px"], record["dpi"],
            record["target_ids"], source_model="v2", prior_source_bindings=record["prior_source_bindings"],
            circle_source_objects=record["circle_source_objects"], font_bindings=record["font_bindings"],
            expected_dxf_sha256=record["dxf_sha256"], expected_source_sha256=record["source_sha256"])
        audit_completed = isinstance(audit, dict) and isinstance(audit.get("pass"), bool)
        checks["independent_source_audit_completed"] = audit_completed
    elif run_source_audit:
        audit = {"status": "NOT_APPLICABLE_NO_PAPER_TARGETS", "pass": None}
    checks["source_array_prior_and_circles_unchanged"] = before_memory == memory_identity(
        source, record["prior_source_bindings"], record["circle_source_objects"])
    checks["input_and_actual_dxf_bytes_unchanged"] = source_bytes_before == sha(source_path) and dxf_bytes_before == sha(path)
    return {"schema": "issue63-fresh-saved-context-and-independent-source-v1", "pid": os.getpid(),
        "file": str(path), "dxf_sha256": dxf_bytes_before, "sidecar_sha256": sha(sidecar_path),
        "source_sha256": source_bytes_before, "checks": checks, "pass": all(checks.values()),
        "prior_strict_preservation": baseline, "source_audit": audit,
        "independent_source_audit_completed": audit_completed,
        "acceptance_pass": all(checks.values()) and audit.get("pass") is True,
        "pending_rejection_is_evidence_not_adoption": True, "producer_pass_consumed": False}


def sidecar_smoke(repo, output):
    """Small persisted binding/resource controls; no real source or probe stage."""
    import ezdxf
    import numpy as np
    from app.native_objects.cad_io import APPID, save_native_dxf
    from app.native_objects.finite_source_junction import SharedCoordinateTransform
    from PIL import Image

    snapshot_entrypoints(repo, output, {"mode": "SMALL_PERSISTED_CONTEXT_BINDING_CONTROLS", "output": str(output)})
    gray = np.full((32, 32), 255, dtype=np.uint8)
    gray[7:10, 3:21], gray[8:21, 13:16] = 0, 0
    source = output / "source.png"
    Image.fromarray(gray).save(source)
    roi, dpi = [0, 0, 32, 32], 200
    prior = {"id": "AUTHORED_PRIOR", "kind": "LINE", "layer": "0",
             "geometry": {"start": [3, 8], "end": [20, 8]}}
    candidate = {"id": "AUTHORED_PENDING", "kind": "LINE", "layer": "NOT_ADOPTED",
                 "geometry": {"start": [14, 8], "end": [14, 20]}}
    prior_path = output / "prior_bindings.json"
    write(prior_path, [prior])
    doc = ezdxf.new("R2013")
    doc.units = 4
    # A deliberately older authored timestamp catches accidental use of
    # Drawing's current read-time creation date on every later copy.
    doc.header["$TDCREATE"] = 2460000.5
    doc.appids.new(APPID)
    doc.styles.new("KEEP_STYLE", dxfattribs={"font": "txt.shx"})
    block = doc.blocks.new("KEEP_UNUSED_BLOCK")
    block.add_line((3, 4), (5, 6))
    append_native_object(doc, prior, SharedCoordinateTransform(roi, dpi))
    baseline = output / "prior.dxf"
    save_native_dxf(doc, baseline)
    doc = read_saved_document(baseline)
    doc.layers.new("NOT_ADOPTED", dxfattribs={"color": 1})
    append_native_object(doc, candidate, SharedCoordinateTransform(roi, dpi))
    paths = {}
    for name in ("positive", "resource_corruption", "stale_dxf_binding", "stale_source_binding", "pending_source_review"):
        path = output / (name + ".dxf")
        save_native_dxf(doc, path)
        if name == "resource_corruption":
            changed = read_saved_document(path)
            changed.styles.get("KEEP_STYLE").dxf.font = "changed-font.shx"
            save_native_dxf(changed, path)
        bind_saved_sidecar(path, source_path=source, source_array_sha256=hashlib.sha256(gray.tobytes()).hexdigest(),
            roi=roi, dpi=dpi, objects=[prior, candidate], target_ids=[candidate["id"]], status="NOT_ADOPTED",
            prior_source_bindings=[prior], baseline_dxf=baseline, allowed_added_layers=["NOT_ADOPTED"],
            input_binding_files={"prior_bindings": {"path": str(prior_path), "sha256": sha(prior_path)}})
        if name == "stale_dxf_binding":
            changed = read_saved_document(path)
            native_entities(changed)[candidate["id"]].dxf.end = (3, 4, 0)
            save_native_dxf(changed, path)
        if name == "stale_source_binding":
            sidecar = path.with_suffix(".objects.json")
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["source_array_sha256"] = "0" * 64
            # This separately named deliberate corruption is part of the input
            # control, not an overwrite of an earlier verified checkpoint.
            sidecar.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        paths[name] = path
    mixed = output / "mixed_context"
    mixed.mkdir()
    host = {"id": "AUTHORED_NEW_HOST", "kind": "LINE", "layer": "0",
            "geometry": {"start": [4, 25], "end": [25, 25]}}
    host_row = {"stroke_id": host["id"], "representation": {"points": [[4, 25], [25, 25]],
                "bulges": [0, 0], "closed": False}}
    guest_row = {"stroke_id": "AUTHORED_NEW_PENDING", "representation": {"points": [[14, 25], [14, 29]],
                 "bulges": [0, 0], "closed": False}}
    authored_plan = {"roi_xyxy_px": roi, "paths": [host_row],
                     "components": [{"candidate_paths": [host_row, guest_row]}]}
    drawings = save_local_drawings(mixed, authored_plan, [host], sha(source), baseline, source_path=source,
        source_array_sha256=hashlib.sha256(gray.tobytes()).hexdigest(), prior_source_bindings=[prior])
    pending_path = mixed / "NOT_ADOPTED_BASELINE_CONTEXT_REVIEW.dxf"
    paths[pending_path.stem] = pending_path
    write(output / "MIXED_CONTEXT_CONTROL.json", {"scope": "AUTHORED_SAVE_BINDING_ONLY_NOT_MODEL_ADOPTION",
        "expected_context_ids": [prior["id"], host["id"]], "expected_pending_ids": [guest_row["stroke_id"]],
        "drawings": drawings})
    results = {}
    for name, path in paths.items():
        log_path = output.parent / (output.name + "-" + name + ".log")
        with log_path.open("x", encoding="utf-8") as log:
            command = [sys.executable, str(Path(__file__).resolve()), "--repo", str(repo),
                "--output", str(output), "--cold-sidecar", str(path)]
            if name != "pending_source_review":
                command.append("--binding-only")
            child = subprocess.run(command, check=False,
                stdout=log, stderr=subprocess.STDOUT, timeout=60)
        report = json.loads((output / (name + ".COLD.json")).read_text(encoding="utf-8"))
        expected = name in {"positive", "pending_source_review", pending_path.stem}
        case_checks = {"binding_result_expected": report["pass"] is expected,
                       "child_exit_expected": child.returncode == (0 if expected else 1),
                       "independent_reader_process": report["pid"] != os.getpid()}
        if name == "pending_source_review":
            case_checks["actual_pending_source_audit_completed"] = report["independent_source_audit_completed"]
        if name == pending_path.stem:
            actual = json.loads(path.with_suffix(".objects.json").read_text(encoding="utf-8"))
            case_checks["old_prior_and_new_adopted_host_retained"] = (
                set(actual["all_actual_saved_ids"]) == {prior["id"], host["id"], guest_row["stroke_id"]}
                and {row["id"] for row in actual["prior_source_bindings"]} == {prior["id"], host["id"]}
                and report["prior_strict_preservation"]["prior_count"] == 2)
        results[name] = {"expected_binding_pass": expected, "actual_binding_pass": report["pass"],
                         "child_returncode": child.returncode, "child_pid": report["pid"],
                         "checks": report["checks"], "external_log": str(log_path), "log_sha256": sha(log_path),
                         "control_checks": case_checks, "source_acceptance_pass": report["acceptance_pass"],
                         "adoption_claimed": False, "pass": all(case_checks.values())}
    report = {"schema": "issue63-persisted-context-sidecar-smoke-v1", "results": results,
              "pass": all(item["pass"] for item in results.values()), "parent_pid": os.getpid(),
              "independent_source_model": "ONE_SMALL_PENDING_DRAWING_AUDITED_NO_ADOPTION_CLAIM",
              "quarter_and_eight_probes": "NOT_RUN", "interface_status": interface_status()}
    write(output / "SIDECAR_SMOKE.json", report)
    return 0 if report["pass"] else 1


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
    from app.native_objects.cad_io import save_native_dxf

    edits = []
    for oid in ids:
        for operation in ("delete", "move"):
            doc = read_saved_document(original)
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
        protected = strict_preservation(
            {**before, "formal": {key: value for key, value in before["formal"].items() if key != oid}},
            {**after, "formal": {key: value for key, value in after["formal"].items() if key != oid}})
        checks = {"file_sha256": sha(path) == edit["sha256"], "actual_id_set_exact": set(after["formal"]) == expected_ids,
            "all_non_target_entities_exact": {key: value for key, value in after["formal"].items() if key != oid}
                == {key: value for key, value in before["formal"].items() if key != oid},
            "all_non_target_context_and_resources_protected": protected["pass"]}
        if operation == "delete":
            checks["whole_target_deleted"] = oid not in after["formal"]
        else:
            expected_doc = read_saved_document(original_path)
            native_entities(expected_doc)[oid].translate(*edit["translation_mm"])
            stream = StringIO()
            expected_doc.write(stream)
            stream.seek(0)
            expected = entity_record(native_entities(ezdxf.read(stream))[oid])
            checks["whole_target_translation_exact"] = after["formal"].get(oid) == expected
        reports.append({**edit, "checks": checks, "pass": all(checks.values()),
            "non_target_protection": protected,
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
        "per_body_model_receipts": [{"body_id": body["stroke_id"], "body_role": body.get("body_role"),
            "original_constant_width_present": "width" in body, "original_constant_width": body.get("width"),
            "bounded_width_field_present": "bounded_width_field" in body,
            "bounded_width_field": body.get("bounded_width_field")}
            for body in component.get("finite_component_responsibility", {}).get("bodies", [])],
        "additional_model_diagnostics": {key: value for key, value in component.items()
            if any(marker in key.lower() for marker in ("constant_width", "bounded_field", "legacy_model"))},
        "shared_finite_vertex_construction": component.get("shared_finite_vertex_construction"),
        "prior_native_contact_check": component.get("prior_native_contact_check")}
        for component in plan.get("components", []) if component.get("candidate_paths")]


def _mapping(entity, oid, status):
    return {"object_id": oid, "handle": entity.dxf.handle, "status": status,
            "layer": entity.dxf.layer, "in_memory_entity_record": entity_record(entity)}


def persisted_mappings(path, mappings):
    import ezdxf

    saved = native_entities(ezdxf.readfile(path))
    result = []
    for mapping in mappings:
        entity = saved[mapping["object_id"]]
        if entity.dxf.handle != mapping["handle"]:
            raise ValueError("SAVED_NATIVE_ENTITY_HANDLE_CHANGED_DURING_SERIALIZATION")
        actual = entity_record(entity)
        result.append({**mapping, "persisted_entity_record": actual,
                       "serialization_changed_tags": actual != mapping["in_memory_entity_record"]})
    return result


def save_local_drawings(out, plan, adopted_objects, source_sha, baseline_dxf, *, source_path,
                        source_array_sha256, prior_source_bindings=(), circle_source_objects=(),
                        font_bindings=None, input_binding_files=None):
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
        if str(body.get("body_role", "")).startswith("NECESSARY_PRIOR_")
        and isinstance(body.get("representation"), dict)}

    def sidecar(path, objects, ids, status, *, baseline=None, layers=(), frame="PAPER_MM_AT_DECLARED_ROI",
                context_prior=None):
        return bind_saved_sidecar(path, source_path=source_path, source_array_sha256=source_array_sha256,
            roi=plan["roi_xyxy_px"], dpi=DPI, objects=objects, target_ids=ids, status=status,
            prior_source_bindings=prior_source_bindings if context_prior is None else context_prior,
            circle_source_objects=circle_source_objects,
            font_bindings=font_bindings, baseline_dxf=baseline, allowed_added_layers=layers,
            planner_source_sha256=source_sha, coordinate_frame=frame, input_binding_files=input_binding_files)

    files = []
    for include_context in (False, True):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = 0
        doc.appids.new(APPID)
        for name, color in (("NOT_ADOPTED", 1), ("LOCAL_STAGE_ADOPTED", 3), ("CONTEXT_PRIOR", 8)):
            doc.layers.new(name, dxfattribs={"color": color})
        mappings, pixel_objects = [], []
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
            pixel_objects.append({"id": identity, "kind": "CONNECTION_PATH", "geometry": geometry,
                                  "layer": layer, "status": status})
        name = "LOCAL_CANDIDATES_WITH_CONTEXT.dxf" if include_context else "LOCAL_CANDIDATES_ONLY.dxf"
        path = out / name
        save_native_dxf(doc, path)
        mappings = persisted_mappings(path, mappings)
        binding = sidecar(path, pixel_objects, sorted(rows), "PIXEL_DIAGNOSTIC_ONLY",
                          frame="UNCHANGED_SOURCE_PIXEL_COORDINATES_Y_DOWN")
        files.append({"file": name, "sha256": sha(path), "size_bytes": path.stat().st_size,
            "sidecar": binding,
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
    edits = []
    context_baseline = Path(baseline_dxf)
    current_prior = [*prior_source_bindings, *adopted_objects]
    if adopted_objects:
        doc = read_saved_document(baseline_dxf)
        mappings = []
        for obj in adopted_objects:
            if obj["layer"] not in doc.layers:
                raise ValueError("ACTUAL_ADOPTED_LAYER_MISSING_FROM_BASELINE")
            entity, _ = append_native_object(doc, obj, mapper)
            mappings.append(_mapping(entity, obj["id"], "LOCAL_STAGE_ADOPTED"))
        path = out / "LOCAL_STAGE_ACTUAL_ADOPTED_WITH_BASELINE.dxf"
        save_native_dxf(doc, path)
        mappings = persisted_mappings(path, mappings)
        binding = sidecar(path, current_prior, sorted(adopted_ids),
                          "PRODUCER_ADOPTED_REQUIRES_INDEPENDENT_ACCEPTANCE", baseline=baseline_dxf)
        files.append({"file": path.name, "sha256": sha(path), "size_bytes": path.stat().st_size,
            "sidecar": binding,
            "target_ids": sorted(adopted_ids), "context_source_dxf_sha256": baseline_sha,
            "context_source_dxf_path": str(Path(baseline_dxf).resolve()),
            "source_sha256": source_sha, "entities": mappings, "all_modelspace_entity_count": len(doc.modelspace()),
            "coordinate_frame": "PAPER_MM_AT_DECLARED_ROI", "dpi": DPI, "units": "paper_mm",
            "engineering_scale": "UNVERIFIED", "ordinary_whole_region_result": False,
            "formal_new_objects_claimed_from_this_local_file": False,
            "purpose": "ACTUAL_LOCAL_STAGE_ADOPTED_OBJECTS_WITH_UNCHANGED_BASELINE"})
        edits = save_edits(path, out, sorted(adopted_ids), "REAL_LOCAL_STAGE_ADOPTED_OBJECT")
        context_baseline = path
    pending = [row for oid, row in rows.items() if oid not in adopted_ids]
    if pending:
        # A pending guest keeps every current adopted host. Its source audit
        # must reconstruct those neighbors from this actual saved context.
        doc = read_saved_document(context_baseline)
        layer = "NOT_ADOPTED_ISSUE63"
        if layer not in doc.layers:
            doc.layers.new(layer, dxfattribs={"color": 1})
        mappings, proposals = [], []
        for row in pending:
            kind, geometry = _native_object(row["representation"])
            obj = {"id": row["stroke_id"], "kind": kind, "layer": layer, "geometry": geometry}
            proposals.append(obj)
            entity, _ = append_native_object(doc, obj, mapper)
            mappings.append(_mapping(entity, obj["id"], "NOT_ADOPTED"))
        path = out / "NOT_ADOPTED_BASELINE_CONTEXT_REVIEW.dxf"
        save_native_dxf(doc, path)
        mappings = persisted_mappings(path, mappings)
        binding = sidecar(path, [*current_prior, *proposals], [obj["id"] for obj in proposals],
                          "NOT_ADOPTED_DIAGNOSTIC_ONLY", baseline=context_baseline, layers=[layer],
                          context_prior=current_prior)
        files.append({"file": path.name, "sha256": sha(path), "size_bytes": path.stat().st_size,
            "sidecar": binding,
            "target_ids": [row["stroke_id"] for row in pending], "context_source_dxf_sha256": sha(context_baseline),
            "context_source_dxf_path": str(context_baseline.resolve()),
            "current_adopted_context_ids": sorted(adopted_ids),
            "source_sha256": source_sha, "entities": mappings, "all_modelspace_entity_count": len(doc.modelspace()),
            "coordinate_frame": "PAPER_MM_AT_DECLARED_ROI", "dpi": DPI, "units": "paper_mm",
            "engineering_scale": "UNVERIFIED", "ordinary_whole_region_result": False,
            "formal_new_objects_claimed_from_this_local_file": False, "allowed_added_layers": [layer],
            "purpose": "UNADOPTED_CANDIDATES_OVER_ACTUAL_BASELINE_FOR_INDEPENDENT_SOURCE_REVIEW"})
    if sha(baseline_dxf) != baseline_sha:
        raise ValueError("ORIGINAL_BASELINE_BYTES_CHANGED")
    write(out / "SHARED_COORDINATE_TRANSFORM.json", mapper.receipt())
    report = {"files": files, "candidate_ids": sorted(rows), "adopted_ids": sorted(adopted_ids),
        "pending_ids": sorted(set(rows) - adopted_ids), "baseline_sha256": baseline_sha,
        "baseline_path": str(Path(baseline_dxf).resolve()), "edits": edits,
        "edit_status": "LOCAL_REAL_EDITS_SAVED" if edits else "NOT_APPLICABLE_NO_NEW_ADOPTED_OBJECTS"}
    write(out / "LOCAL_DRAWINGS.json", report)
    return report


def cold_drawings(out):
    import ezdxf

    records = json.loads((out / "LOCAL_DRAWINGS.json").read_text(encoding="utf-8"))
    if sha(records["baseline_path"]) != records["baseline_sha256"]:
        raise ValueError("ACTUAL_BASELINE_BYTES_CHANGED_BEFORE_COLD_READ")
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
            baseline = Path(record["context_source_dxf_path"])
            check["context_baseline_bytes_match"] = sha(baseline) == record["context_source_dxf_sha256"]
            check["baseline_protection"] = strict_preservation(snapshot_doc(ezdxf.readfile(baseline)), snapshot_doc(doc), record["target_ids"],
                record.get("allowed_added_layers", ()))
        bound = cold_saved_sidecar(out / record["file"])
        check["bound_source_and_actual_saved_context"] = bound
        check["sidecar_bytes_match"] = sha(record["sidecar"]["path"]) == record["sidecar"]["sha256"]
        if record["file"] == "LOCAL_STAGE_ACTUAL_ADOPTED_WITH_BASELINE.dxf":
            check["adopted_targets_independently_accepted"] = bound["acceptance_pass"]
        check["pass"] = all(check[key] for key in ("sha256_matches", "entity_count_exact", "every_new_saved_entity_exact"))
        check["pass"] = check["pass"] and check.get("baseline_protection", {"pass": True})["pass"]
        check["pass"] = check["pass"] and check.get("context_baseline_bytes_match", True)
        check["pass"] = (check["pass"] and bound["pass"] and check["sidecar_bytes_match"]
                         and check.get("adopted_targets_independently_accepted", True))
        checks.append(check)
    edits = cold_edit_checks(out / "LOCAL_STAGE_ACTUAL_ADOPTED_WITH_BASELINE.dxf", out, records["edits"]) if records["edits"] else []
    report = {"schema": "issue63-local-saved-geometry-cold-read-v1", "fresh_process": True,
        "checks": checks, "edits": edits, "edit_status": records["edit_status"],
        "pass": all(row["pass"] for row in checks + edits),
        "independent_source_audit_invocation_count": sum(
            int(row["bound_source_and_actual_saved_context"]["independent_source_audit_completed"]) for row in checks),
        "source_complete_responsibility": "ACTUAL_SAVED_PAPER_TARGETS_INDEPENDENTLY_AUDITED_IN_V2",
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
    prior = json.loads(Path(inputs["prior_plan"]["path"]).read_text(encoding="utf-8"))["prior_object_bindings"]
    circles = [json.loads(Path(value["path"]).read_text(encoding="utf-8"))
               for key, value in inputs.items() if key.startswith("circle_source_object_")]
    memory_before = memory_identity(gray, prior, circles)
    replay = attached.verify_attached_stroke_graph_plan(gray, identity["roi_xyxy_px"], plan, source_graph=None)
    exact_checks = replay.get("checks", {})
    saved = cold_drawings(out)
    memory_after = memory_identity(gray, prior, circles)
    checks = {"input_files_unchanged": all(sha(row["path"]) == row["sha256"] for row in inputs.values()),
        "source_prior_and_circle_memory_unchanged": memory_before == memory_after,
        "plan_schema": plan.get("schema") == EXPECTED_PLAN_SCHEMA,
        "all_actual_saved_plan_fields_compared": bool(exact_checks) and set(exact_checks) == set(plan),
        "all_actual_saved_plan_field_comparisons_pass": bool(exact_checks) and all(value is True for value in exact_checks.values()),
        "source_replay_pass": replay.get("pass") is True and replay.get("reason") == "EXACT_ATTACHED_GRAPH_SOURCE_REPLAY",
        "source_files_unchanged": before == source_files(repo), "actual_saved_geometry_and_edits_pass": saved["pass"]}
    report = {"schema": "issue63-fresh-process-source-and-saved-replay-v1", "pass": all(checks.values()),
        "checks": checks, "actual_saved_plan_fields": sorted(plan), "actual_saved_plan_field_count": len(plan),
        "actually_compared_fields": sorted(exact_checks), "verification": replay, "saved_dxf": saved,
        "source_files_sha256": before, "plan_sha256": sha(plan_path), "new_OCR_calls": 0,
        "input_memory_before": memory_before, "input_memory_after": memory_after,
        "numeric_replay_tolerance_added": False, "producer_replay_invocation_count": 1,
        "source_audit_invocation_count": saved["independent_source_audit_invocation_count"],
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
    readiness = interface_status()
    write(args.output / "INTERFACE_STATUS.json", readiness)
    if not readiness["ready"]:
        raise ValueError("BOUNDED_SOURCE_STAGE_INTERFACES_NOT_READY")
    started = time.perf_counter()
    resources_before = resource_snapshot(args.output)
    old = json.loads(args.prior_plan.read_text(encoding="utf-8"))
    prior = old["prior_object_bindings"]
    circles = [json.loads(path.read_text(encoding="utf-8")) for path in args.circle_source_object]
    fonts = json.loads(args.font_bindings_json.read_text(encoding="utf-8")) if args.font_bindings_json else {}
    paths = {"source": args.source, "prior_plan": args.prior_plan, "baseline_dxf": args.baseline_dxf}
    if args.font_bindings_json:
        paths["font_bindings_json"] = args.font_bindings_json
    paths.update({f"circle_source_object_{index}": path for index, path in enumerate(args.circle_source_object)})
    inputs = {key: {"path": str(path.resolve()), "sha256": sha(path), "size_bytes": path.stat().st_size}
              for key, path in paths.items()}
    args._input_file_bindings = inputs
    args._source_file_bindings = before
    write(args.output / "INPUT_IDENTITY.json", {"files": inputs, "roi_xyxy_px": old["roi_xyxy_px"],
        "dpi": DPI, "circle_source_object_count": len(circles), "input_files_are_read_only": True})
    if attached.SCHEMA != EXPECTED_PLAN_SCHEMA:
        raise ValueError("NEW_BOUNDED_SOURCE_PLAN_SCHEMA_REQUIRED")
    with Image.open(args.source) as image:
        gray = np.asarray(image.convert("L"))
    memory_before = memory_identity(gray, prior, circles)
    write(args.output / "INPUT_MEMORY_BEFORE.json", memory_before)
    args._input_memory_objects = gray, prior, circles
    args._input_memory_before = memory_before
    print("Rebuilding the unchanged source graph", flush=True)
    context = contact.build_text_contact_source_graph(gray, old["roi_xyxy_px"])
    if (context.crop_bbox != old["original_source_crop_xyxy_px"]
            or context.source_crop_hash != old["original_source_crop_array_sha256"]):
        raise ValueError("ORIGINAL_SOURCE_SCOPE_DOES_NOT_MATCH_PRIOR_BINDINGS")
    graph_seconds = time.perf_counter() - started
    print("Running the bounded-source local stage", flush=True)
    adoption = attached.complete_attached_strokes(gray, old["roi_xyxy_px"], inputs["source"]["sha256"],
        prior, args.output / "attached", source_graph=context, circle_source_objects=circles)
    plan = adoption["plan"]
    write(args.output / "MODEL_RECEIPTS.json", model_receipts(plan))
    saved = save_local_drawings(args.output, plan, adoption["objects"], inputs["source"]["sha256"], args.baseline_dxf,
        source_path=args.source, source_array_sha256=memory_before["source_array_sha256"],
        prior_source_bindings=prior, circle_source_objects=circles, font_bindings=fonts, input_binding_files=inputs)
    log_path = args.output.parent / (args.output.name + "-strict_replay.log")
    with log_path.open("x", encoding="utf-8") as log:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
            "--output", str(args.output), "--cold-replay"], stdout=log, stderr=subprocess.STDOUT,
            check=False, timeout=args.replay_timeout_seconds)
    strict_path = args.output / "STRICT_SOURCE_REPLAY.json"
    strict = json.loads(strict_path.read_text(encoding="utf-8")) if strict_path.exists() else {}
    memory_after = memory_identity(gray, prior, circles)
    write(args.output / "INPUT_MEMORY_AFTER.json", memory_after)
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
        "source_array_prior_and_circles_unchanged": memory_before == memory_after,
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
        "resources_before": resources_before, "resources_after": resource_snapshot(args.output),
        "input_memory_before": memory_before, "input_memory_after": memory_after,
        "cold_process_log": {"path": str(log_path), "sha256": sha(log_path)},
        "execution_identity": git_identity(args.repo), "source_files_sha256": before,
        "producer_sha256": plan.get("producer_sha256"), "additional_producer_sha256": plan.get("additional_producer_sha256"),
        "local_dxf_cold_process_exit_code": completed.returncode, "new_real_object_delete_move": saved["edit_status"],
        "valid_baseline_replaced": False, "ordinary_joint_run": "NOT_RUN_IN_THIS_LOCAL_STAGE",
        "independent_physical_source_certificate": "ACTUAL_SAVED_PAPER_TARGETS_AUDITED_IN_COLD_PROCESS"}
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
    parser.add_argument("--font-bindings-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-timeout-seconds", type=float, default=900)
    parser.add_argument("--cold-replay", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sidecar-smoke", action="store_true", help="Run only small actual-DXF binding controls.")
    parser.add_argument("--cold-sidecar", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--binding-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.repo, args.output = args.repo.resolve(), args.output.resolve()
    configure(args.repo, args.output)
    if args.cold_sidecar is not None:
        report = cold_saved_sidecar(args.cold_sidecar, run_source_audit=not args.binding_only)
        write(args.output / (args.cold_sidecar.stem + ".COLD.json"), report)
        return 0 if report["pass"] else 1
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
    if not args.sidecar_smoke and any(getattr(args, key) is None for key in ("source", "prior_plan", "baseline_dxf")):
        parser.error("--source, --prior-plan and --baseline-dxf are required for a new local stage.")
    if args.replay_timeout_seconds <= 0:
        parser.error("Replay timeout must be positive.")
    args.output.mkdir(parents=True)
    try:
        return sidecar_smoke(args.repo, args.output) if args.sidecar_smoke else run_stage(args)
    except Exception as exc:
        write(args.output / "STAGE_EXECUTION_ERROR.json", {"pass": False, "type": type(exc).__name__,
            "message": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        final_integrity = {"schema": "issue63-local-stage-final-input-integrity-v1",
                           "failure_outputs_preserved": True}
        if hasattr(args, "_input_memory_objects"):
            after = memory_identity(*args._input_memory_objects)
            if not (args.output / "INPUT_MEMORY_AFTER.json").exists():
                write(args.output / "INPUT_MEMORY_AFTER.json", after)
            final_integrity["input_memory_before"] = args._input_memory_before
            final_integrity["input_memory_after"] = after
            final_integrity["source_prior_and_circle_memory_unchanged"] = args._input_memory_before == after
        if hasattr(args, "_input_file_bindings"):
            final_integrity["input_files_unchanged"] = all(
                Path(value["path"]).is_file() and sha(value["path"]) == value["sha256"]
                for value in args._input_file_bindings.values())
            final_integrity["source_files_unchanged"] = args._source_file_bindings == source_files(args.repo)
        write(args.output / "FINAL_INTEGRITY.json", final_integrity)
        write(args.output / "FILE_MANIFEST.json", {"files": file_manifest(args.output), "includes_failed_stage_outputs": True})


if __name__ == "__main__":
    sys.exit(main())
