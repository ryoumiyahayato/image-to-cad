"""Terminal-loop assembly avoids retraces without weakening cold duplicate gates."""

from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.native_worker import _saved_candidate_gates
from app.native_objects.cad_io import cold_audit, export_objects, mark
from app.native_objects.connections import _dense_geometry, extract_connections


ROI = [0, 0, 160, 160]
DPI = 200


def _source(rotation):
    ink = np.zeros((160, 160), np.uint8)
    ink[80, 20:130] = 1
    cv2.rectangle(ink, (129, 79), (132, 81), 1, 1)
    return np.ascontiguousarray(np.rot90(ink, rotation))


def _saved(folder, rotation=0):
    ink = _source(rotation)
    gray = np.where(ink, 0, 255).astype(np.uint8)
    original = gray.copy()
    found = extract_connections(gray, ROI, [], folder / "evidence/connections/discovery")
    assert len(found["objects"]) == 1
    obj = found["objects"][0]
    assert obj["source_evidence"]["whole_path_class"] == "COMPLETE_STROKE_WITH_TERMINAL_LOOP"
    export_objects(found["objects"], folder / "result.dxf", ROI, DPI, hashlib.sha256(gray.tobytes()).hexdigest())
    assert np.array_equal(gray, original)
    return ink, gray, obj


@pytest.mark.parametrize("rotation", [0, 1, 2, 3])
def test_saved_terminal_loop_keeps_all_ink_and_white_hole_without_repeated_segments(tmp_path, rotation):
    ink, gray, obj = _saved(tmp_path, rotation)
    counts = Counter(tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(
        obj["source_evidence"]["source_path_points"], obj["source_evidence"]["source_path_points"][1:]))
    assert all(count == 1 for count in counts.values())
    raster = np.zeros_like(ink)
    dense = np.rint(_dense_geometry(obj["geometry"], 0.1)).astype(np.int32)
    cv2.polylines(raster, [dense], False, 1, 1)
    assert np.all(raster[ink != 0])
    holes = np.zeros_like(ink)
    holes[80, 130:132] = 1
    holes = np.rot90(holes, rotation)
    assert not np.any(raster[holes != 0])
    audit = cold_audit(tmp_path / "result.dxf", gray, ROI, DPI, tmp_path / "evidence/cold_audit.json")
    assert audit["source_gate_pass"]
    assert not audit["ezdxf_errors"] and not audit["ezdxf_in_memory_fixes"]
    assert audit["exact_duplicate_segments"] == audit["all_repeated_segments"] == []
    assert audit["certified_same_owner_retraces"] == []  # No exemption was needed.
    doc = ezdxf.readfile(tmp_path / "result.dxf")
    entity = next(e for e in doc.modelspace() if e.dxf.layer == "CONNECTIONS")
    assert entity.dxftype() == "LWPOLYLINE" and not entity.closed
    assert len(entity) == len(obj["geometry"]["points"])


@pytest.mark.parametrize("damage", ["same-owner-backtrack", "second-entity-duplicate"])
def test_saved_gate_still_rejects_unproved_or_cross_entity_terminal_duplicates(tmp_path, damage):
    _, gray, _ = _saved(tmp_path)
    path = tmp_path / "result.dxf"
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace() if e.dxf.layer == "CONNECTIONS")
    if damage == "same-owner-backtrack":
        points = list(entity.get_points("xyb"))
        entity.set_points([*points, points[-2], points[-1]], format="xyb")
    else:
        duplicate = entity.copy()
        doc.modelspace().add_entity(duplicate)
        mark(duplicate, {"id": "distinct-duplicate-owner", "kind": "CONNECTION_PATH"})
    doc.saveas(path)
    meta = json.loads(path.with_suffix(".objects.json").read_text())
    meta["dxf_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".objects.json").write_text(json.dumps(meta))
    audit = cold_audit(path, gray, ROI, DPI, tmp_path / "evidence/cold_audit.json")
    assert audit["exact_duplicate_segments"]
    assert audit["certified_same_owner_retraces"] == []
    with pytest.raises(ValueError, match="SAVED_SOURCE_OR_DXF_GATE_REJECTED"):
        _saved_candidate_gates(tmp_path, {"input_path": str(Path(__file__))})
