"""One unpublishable native crossing group must not discard independent work."""

from copy import deepcopy
from itertools import combinations

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects import connections
from app.native_objects.cad_io import cold_audit, export_objects
from app.native_objects.completion_stages import _quarantine_native_duplicate_groups, _source_edges
from app.native_objects.connection_checkpoint import adopt_checkpoint_paths
from app.native_objects.connection_checkpoint_cad import _entity, write_checkpoint_dxf
from tests.test_native_complete_shared_core import _complete
from tests.test_native_text_graph_support import crossing_fixture, digest, extract


DPI = 200


def _item():
    item = list(crossing_fixture(stroke_width=2))
    item[0] = item[0].copy()
    cv2.polylines(item[0], [np.asarray([[260, 210], [292, 198], [323, 214], [351, 219]], np.int32)], False, 0, 1)
    item[2]["source_array_sha256"] = item[3]["source_array_sha256"] = digest(item[0])
    return item


def _make_shared_native_segment(objects):
    """Keep all real source paths, but explicitly encode a shared core edge.

    This source-supported representation is a real saved-DXF counterexample:
    distinct editable paths must not duplicate that positive native length.
    """
    a, b = next((a, b) for a, b in combinations(objects, 2) if _source_edges(a) & _source_edges(b))
    edge = sorted(_source_edges(a) & _source_edges(b))[0]
    for obj in (a, b):
        points = np.asarray(obj["source_evidence"]["source_path_points"], float)
        cut = next(i for i, (p, q) in enumerate(zip(points, points[1:]))
                   if tuple(sorted((tuple(p), tuple(q)))) == edge)
        left, _ = connections._bounded_source_polyline(points[:cut + 1])
        right, _ = connections._bounded_source_polyline(points[cut + 1:])
        native = np.vstack((left, right))
        obj["geometry"] = {"points": native.tolist(), "bulges": [0.0] * len(native), "closed": False}
        obj["source_evidence"]["control_vertex_count"] = len(native)
        assert connections._simple_chain_fit_certificate(points, obj["geometry"])["pass"]
    group = a["source_evidence"]["source_connected_group_id"]
    return {obj["id"] for obj in objects if obj["source_evidence"]["source_connected_group_id"] == group}


@pytest.fixture
def observed(tmp_path):
    item = _item()
    raw = extract(item, tmp_path / "discovery")
    assert len(raw["objects"]) == 4
    return item, raw["objects"]


def test_actual_source_ordered_crossing_representation_saves_and_cold_reads_without_duplicates(observed, tmp_path):
    item, objects = observed
    path = tmp_path / "clean/result.dxf"
    export_objects(objects, path, item[1], DPI, digest(item[0]))
    audit = cold_audit(path, item[0], item[1], DPI, tmp_path / "clean/evidence/cold_audit.json")
    assert audit["source_gate_pass"] and not audit["exact_duplicate_segments"]
    assert audit["formal_modelspace_types"] == {"LWPOLYLINE": 4}
    assert not _quarantine_native_duplicate_groups(objects)["quarantined_ids"]


def test_bad_whole_group_is_held_before_retirement_while_independent_path_and_old_line_survive(observed, tmp_path):
    item, original = observed
    objects = deepcopy(original)
    bad_group = _make_shared_native_segment(objects)
    assert len(bad_group) == 3
    # First prove the meaningful negative on a real saved native DXF.
    bad_path = tmp_path / "bad/result.dxf"
    export_objects(objects, bad_path, item[1], DPI, digest(item[0]))
    bad = cold_audit(bad_path, item[0], item[1], DPI, tmp_path / "bad/evidence/cold_audit.json")
    assert bad["source_gate_pass"] and bad["exact_duplicate_segments"]
    main = next(obj for obj in objects if obj["id"] in bad_group and obj["source_evidence"]["source_path_length_px"] > 100)
    source = main["source_evidence"]["source_path_points"]
    old = {"id": "old-line-must-remain", "kind": "LINE", "layer": "GEOMETRY",
           "geometry": {"start": source[0], "end": source[20]}, "source_evidence": {"method": "existing_native_line"}}
    before = deepcopy([objects, old])
    result = adopt_checkpoint_paths(item[0], objects, [old])
    assert len(result["objects"]) == 1 and not result["retired_ids"]
    assert set(result["native_duplicate_group_quarantine"]["quarantined_ids"]) == bad_group
    assert len(result["uncertainties"]) == 3
    assert [objects, old] == before
    baseline = tmp_path / "baseline.dxf"
    meta = export_objects([old], baseline, item[1], DPI, digest(item[0]))
    saved = tmp_path / "safe/result.dxf"
    write_checkpoint_dxf(baseline, meta, [old["id"]], result["objects"], saved, item[1], DPI, digest(item[0]))
    audit = cold_audit(saved, item[0], item[1], DPI, tmp_path / "safe/evidence/cold_audit.json")
    assert audit["source_gate_pass"] and not audit["exact_duplicate_segments"]
    old_saved = next(e for e in ezdxf.readfile(baseline).modelspace() if e.dxftype() == "LINE")
    new_saved = next(e for e in ezdxf.readfile(saved).modelspace() if e.dxftype() == "LINE")
    assert _entity(old_saved) == _entity(new_saved)


def test_ordinary_completion_uses_the_same_whole_group_quarantine(tmp_path, monkeypatch):
    original = connections.extract_connections
    group_ids = set()

    def duplicate_core(*args, **kwargs):
        raw = original(*args, **kwargs)
        group_ids.update(_make_shared_native_segment(raw["objects"]))
        return raw

    monkeypatch.setattr(connections, "extract_connections", duplicate_core)
    result = _complete(_item(), tmp_path / "connections")
    assert len(result["objects"]) == 1
    assert set(result["native_duplicate_group_quarantine"]["quarantined_ids"]) == group_ids
    assert len(group_ids) == 3
    assert all(not row["adopted"] for row in result["decisions"] if row["id"] in group_ids)


def test_identical_whole_path_alias_still_uses_duplicate_suppression_not_group_rejection(observed):
    item, objects = observed
    duplicate = deepcopy(objects[0])
    duplicate["id"] = "same-complete-native-path-alias"
    result = adopt_checkpoint_paths(item[0], [*objects, duplicate], [])
    assert len(result["objects"]) == 4
    assert result["native_duplicate_group_quarantine"]["quarantined_ids"] == []
    assert result["decisions"][-1]["decision"] == "RETAIN_EXISTING_COMPLETE_PATH_NO_DUPLICATE"
