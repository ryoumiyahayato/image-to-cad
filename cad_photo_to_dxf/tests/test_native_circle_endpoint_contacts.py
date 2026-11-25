"""Direct original-ink contacts, real gaps and actual saved endpoint contracts."""

from copy import deepcopy
import hashlib
import json

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects import cad_io
from app.native_objects import circle_endpoint_contacts as contacts
from app.native_objects.circular_markers import discover_circular_markers


ROI = (0, 0, 180, 160)
DPI = 200


def _source():
    gray = np.full((160, 180), 255, np.uint8)
    cv2.circle(gray, (80, 80), 20, 0, 3)
    cv2.line(gray, (75, 73), (75, 87), 0, 2)
    cv2.line(gray, (75, 73), (85, 73), 0, 2)
    cv2.line(gray, (75, 80), (82, 80), 0, 2)
    cv2.line(gray, (102, 80), (145, 80), 0, 3)
    return gray


def _circle(gray):
    row = next(row for row in discover_circular_markers(gray, ROI)["rows"] if row["geometry_accepted"])
    return {"id": row["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
            "geometry": deepcopy(row["geometry"]), "bbox_xyxy_px": row["bbox_xyxy_px"],
            "source_evidence": {**deepcopy(row["source_evidence"]), "components_complete": False}}


def _line(*, kind="CONNECTION_PATH", first=(103, 80), last=(145, 80), bulge=0):
    g = {"start": list(first), "end": list(last)} if kind == "LINE" else {
        "points": [list(first), list(last)], "bulges": [bulge, 0.0], "closed": False}
    return {"id": "independent-external-object", "kind": kind, "layer": "CONNECTIONS",
            "geometry": g,
            "source_evidence": {"source_path_points": [list(first), list(last)],
                                "control_vertex_count": 2, "raw_observation": "unchanged"}}


def _objects(gray=None, line=None):
    gray = _source() if gray is None else gray
    return gray, [_circle(gray), _line() if line is None else line]


def _restore(gray, objects):
    result = contacts.restore_circle_endpoint_contacts(gray, ROI, objects)
    replacements = {obj["id"]: obj for obj in result["replacements"]}
    return result, [replacements.get(obj["id"], obj) for obj in objects]


@pytest.mark.parametrize("kind", ["LINE", "CONNECTION_PATH"])
def test_direct_ink_contact_changes_same_external_object_and_preserves_raw_observation(kind):
    gray, objects = _objects(line=_line(kind=kind))
    original = deepcopy(objects)
    result, restored = _restore(gray, objects)
    assert result["summary"]["restored_external_endpoints"] == 1
    assert result["summary"]["new_formal_objects"] == 0
    assert result["summary"]["retired_objects"] == 0
    assert objects == original
    assert restored[0] == original[0]
    obj = restored[1]
    assert obj["id"] == original[1]["id"]
    source = deepcopy(obj["source_evidence"])
    cert = source.pop(contacts.FIELD)
    assert source == original[1]["source_evidence"]
    assert cert["original_geometry"] == original[1]["geometry"]
    assert contacts.verified_original_geometry(gray, ROI, obj, restored, obj["geometry"]) == original[1]["geometry"]
    if kind == "CONNECTION_PATH":
        assert obj["geometry"]["points"][1:] == original[1]["geometry"]["points"]
        assert obj["geometry"]["bulges"][1:] == original[1]["geometry"]["bulges"]
    replay, replayed = _restore(gray, restored)
    assert replayed == restored
    assert replay["summary"] == result["summary"]


@pytest.mark.parametrize("reverse", [False, True])
def test_terminal_bulge_is_never_modified_by_an_endpoint_extension(reverse):
    line = _line(bulge=0.01)
    if reverse:
        line["geometry"]["points"].reverse()
        line["geometry"]["bulges"] = [-0.01, 0.0]
    gray, objects = _objects(line=line)
    result, restored = _restore(gray, objects)
    assert result["summary"]["restored_external_endpoints"] == 1
    actual = restored[1]["geometry"]
    old = line["geometry"]
    if reverse:
        assert actual["points"][:-1] == old["points"]
        assert actual["bulges"][:-1] == old["bulges"]
        assert actual["bulges"][-1] == 0
    else:
        assert actual["points"][1:] == old["points"]
        assert actual["bulges"][1:] == old["bulges"]
        assert actual["bulges"][0] == 0


def test_two_real_white_columns_and_nearby_parallel_line_remain_independent():
    gray = _source()
    gray[77:84, 103:105] = 255
    line = _line(first=(105, 80))
    parallel = _line(first=(110, 88), last=(145, 88), kind="LINE")
    parallel["id"] = "neighbor"
    cv2.line(gray, (110, 88), (145, 88), 0, 1)
    objects = [_circle(gray), line, parallel]
    before = deepcopy(objects)
    result, restored = _restore(gray, objects)
    assert result["replacements"] == []
    assert restored == before and objects == before
    assert np.all(gray[77:84, 103:105] == 255)


def test_diagonal_source_contact_never_becomes_a_solid_native_bridge():
    # Extension cells can be all black while the original endpoint is on
    # the ring side of a diagonal-only contact.  The exterior witness must
    # also be continuous through original black pixel cells.
    gray, objects = _objects()
    gray[80, 104] = 255
    objects[0] = _circle(gray)
    result, restored = _restore(gray, objects)
    assert not result["replacements"]
    assert restored == objects
    assert any("ORIGINAL_WHITE_PIXEL" in row["reason"] for row in result["decisions"])


def test_unchanged_short_branch_and_neighbor_block_cannot_be_absorbed():
    gray, objects = _objects()
    cv2.line(gray, (128, 80), (128, 86), 0, 1)
    objects[0] = _circle(gray)
    branch = {"id": "short-branch", "kind": "LINE", "layer": "SHORT_STROKE",
              "geometry": {"start": [128, 80], "end": [128, 86]}, "source_evidence": {}}
    block = {"id": "neighbor-block", "kind": "WALL_SEGMENT", "layer": "WALL_SEGMENTS",
             "geometry": {"members": [{"kind": "LINE", "geometry": {"start": [103, 80], "end": [145, 80]}}]},
             "source_evidence": {"protected": True}}
    objects.extend([branch, block])
    before = deepcopy(objects)
    result, restored = _restore(gray, objects)
    assert result["summary"]["restored_external_endpoints"] == 1
    assert objects == before
    assert restored[2:] == before[2:]
    assert restored[0]["geometry"] == before[0]["geometry"]


def test_ambiguous_two_external_owners_on_same_port_are_both_kept():
    gray, objects = _objects()
    another = deepcopy(objects[1])
    another["id"] = "another-owner"
    objects.append(another)
    result, restored = _restore(gray, objects)
    assert not result["replacements"]
    assert restored == objects
    assert all("AMBIGUOUS" in row["reason"] for row in result["decisions"])


def test_far_observed_endpoint_is_reported_pending_without_increasing_adoption_limit():
    gray, objects = _objects(line=_line(first=(107, 80)))
    result, restored = _restore(gray, objects)
    assert restored == objects
    assert result["summary"]["pending_nearby_contacts"] == 1
    assert result["decisions"][0]["reason"] == "NEARBY_END_OUTSIDE_BOUNDED_CONTACT_RESTORATION_RANGE"


def _observed_core_fixture(tmp_path, *, gap=False, competing=False):
    """A thick original lead terminates outside a thinner observed ring.

    The source graph already contains the junction core.  Both the complete
    path and its core come from the ordinary planner/adopter, without an
    invented terminal certificate or a supplied character recognition result.
    """
    from app.native_objects import text_contact_geometry as planner
    from app.native_objects.text_contact_adoption import complete_text_contact_paths

    roi = [0, 0, 420, 240]
    gray = np.full((240, 420), 255, np.uint8)
    cv2.circle(gray, (330, 160), 18, 0, 2)
    cv2.polylines(gray, [np.array([(160, 20), (210, 60), (250, 90), (307, 153), (313, 159)])], False, 0, 5)
    cv2.line(gray, (240 if competing else 280, 159), (313, 159), 0, 5)
    cv2.putText(gray, "AX7", (205, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 0, 2)
    cv2.putText(gray, "F", (324, 166), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1)
    if gap:
        gray[145:172, 309:311] = 255
    context = planner.build_text_contact_source_graph(gray, roi)
    seeds = [[203, 57, 250, 78]] + ([[257, 151, 275, 166]] if competing else [])
    plans = [planner.plan_text_contact_geometry(gray, roi, seed, source_graph=context) for seed in seeds]
    circles = [{"id": row["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
                "geometry": row["geometry"], "bbox_xyxy_px": row["bbox_xyxy_px"],
                "source_evidence": {**row["source_evidence"], "components_complete": False}}
               for row in discover_circular_markers(gray, roi)["rows"] if row["geometry_accepted"]]
    adopted = complete_text_contact_paths(gray, roi, hashlib.sha256(gray.tobytes()).hexdigest(),
                                         circles, plans, tmp_path / "evidence" / "text_contact")
    assert len(circles) == 1 and len(adopted["objects"]) == (2 if competing else 1)
    return gray, roi, circles + adopted["objects"], context


def test_observed_original_terminal_core_completes_same_saved_path_beyond_plain_tail_limit(tmp_path):
    gray, roi, objects, context = _observed_core_fixture(tmp_path)
    before = deepcopy(objects)
    result = contacts.restore_circle_endpoint_contacts(gray, roi, objects, source_graph=context)
    assert len(result["replacements"]) == 1
    restored = result["replacements"][0]
    proof = restored["source_evidence"][contacts.FIELD]["ends"][0]
    assert proof["endpoint_extension_shape"] == "REPLAYED_ORIGINAL_TERMINAL_CORE_TO_OPPOSITE_RING_BRANCHES"
    plain_limit = objects[0]["source_evidence"]["ring_geometry"]["stroke_width_px"] + contacts.POLICY["existing_native_fit_allowance_px"]
    assert proof["original_radial_gap_px"] > plain_limit
    assert len(proof["ring_source_graph_ports"]) == 2
    assert proof["unselected_external_branches_retained"]
    assert proof["every_intersected_source_pixel_is_black"]
    old_points = objects[1]["geometry"]["points"]
    points = restored["geometry"]["points"]
    assert len(points) == len(old_points) + 1
    assert old_points == (points[1:] if proof["endpoint_number"] == 0 else points[:-1])
    assert objects == before
    actual = [objects[0], restored]
    path = tmp_path / "observed-core.dxf"
    cad_io.export_objects(actual, path, roi, DPI, hashlib.sha256(gray.tobytes()).hexdigest())
    rows = contacts.cold_circle_endpoint_contacts(path, ezdxf.readfile(path), gray, roi, DPI)
    assert len(rows) == 1 and rows[0]["pass"], rows
    assert contacts.restore_circle_endpoint_contacts(gray, roi, actual)["replacements"] == [restored]
    # Whole-path deletion removes its tail as part of the same native entity.
    doc = ezdxf.readfile(path)
    doc.modelspace().delete_entity(next(e for e in doc.modelspace() if cad_io.identity(e).get("id") == restored["id"]))
    doc.saveas(tmp_path / "deleted.dxf")
    assert not [e for e in ezdxf.readfile(tmp_path / "deleted.dxf").modelspace().query("LWPOLYLINE") if e.dxf.layer != "REVIEW"]
    assert len(ezdxf.readfile(tmp_path / "deleted.dxf").modelspace().query("CIRCLE")) == 1


def test_observed_core_claim_is_rebuilt_from_raw_graph_even_when_its_hashes_are_rebound(tmp_path):
    from app.native_objects.text_contact_adoption import digest

    gray, roi, objects, context = _observed_core_fixture(tmp_path)
    restored = contacts.restore_circle_endpoint_contacts(gray, roi, objects, source_graph=context)["replacements"][0]
    forged = deepcopy(restored)
    evidence = forged["source_evidence"]
    certificate = evidence[contacts.FIELD]
    end = certificate["ends"][0]["endpoint_number"]
    path_proof = evidence["text_contact_path"]
    core = path_proof["path"]["endpoint_source_cores"][end]
    core["source_core_points_px"][0][0] -= 1
    path_proof["path_sha256"] = digest(path_proof["path"])
    certificate["original_source_evidence_sha256"] = contacts._digest(contacts._original(forged)["source_evidence"])
    certificate["ends"][0]["terminal_core_source_evidence"] = deepcopy(core)
    with pytest.raises(ValueError, match="RAW_ENDPOINT_PROOF_DOES_NOT_REPLAY"):
        contacts.verified_original_geometry(gray, roi, forged, [objects[0], forged], forged["geometry"])


def test_original_white_gap_near_a_terminal_core_remains_unconnected(tmp_path):
    gray, roi, objects, context = _observed_core_fixture(tmp_path, gap=True)
    before = deepcopy(objects)
    original = gray.copy()
    result = contacts.restore_circle_endpoint_contacts(gray, roi, objects, source_graph=context)
    assert not result["replacements"]
    assert objects == before and np.array_equal(gray, original)
    assert np.all(gray[145:172, 309:311] == 255)


def test_two_distinct_original_paths_competing_for_one_core_circle_port_both_remain_pending(tmp_path):
    gray, roi, objects, context = _observed_core_fixture(tmp_path, competing=True)
    assert objects[1]["geometry"] != objects[2]["geometry"]
    before = deepcopy(objects)
    result = contacts.restore_circle_endpoint_contacts(gray, roi, objects, source_graph=context)
    assert len(result["decisions"]) == 2
    assert not result["replacements"]
    assert all(row["reason"] == "CONTACT_HAS_AMBIGUOUS_EXISTING_END_OR_CIRCLE_PORT" for row in result["decisions"])
    assert objects == before


def _oblique_source(*, gap=False):
    gray = np.full((160, 180), 255, np.uint8)
    cv2.circle(gray, (80, 80), 20, 0, 3)
    cv2.line(gray, (75, 73), (75, 87), 0, 2)
    cv2.line(gray, (75, 73), (85, 73), 0, 2)
    cv2.line(gray, (75, 80), (82, 80), 0, 2)
    first = (105, 80) if gap else (103, 80)
    cv2.polylines(gray, [np.asarray([(100, 80), first, (112, 120)], np.int32)],
                  False, 0, 3)
    if gap:
        gray[:, 103] = 255
    return gray, _line(first=first, last=(112, 120))


def test_oblique_polyline_terminal_bend_is_saved_without_changing_the_old_path(tmp_path):
    gray, line = _oblique_source()
    objects = [_circle(gray), line]
    original = deepcopy(objects)
    result, restored = _restore(gray, objects)
    assert result["summary"]["restored_external_endpoints"] == 1
    proof = restored[1]["source_evidence"][contacts.FIELD]["ends"][0]
    assert proof["endpoint_extension_shape"] == "BOUNDED_SOURCE_INK_POLYLINE_TERMINAL_BEND"
    assert proof["extension_length_px"] <= proof["maximum_extension_px"]
    assert proof["every_intersected_source_pixel_is_black"]
    assert restored[1]["geometry"]["points"][1:] == line["geometry"]["points"]
    assert objects == original
    path = tmp_path / "oblique-contact.dxf"
    cad_io.export_objects(restored, path, ROI, DPI, hashlib.sha256(gray.tobytes()).hexdigest())
    checks = contacts.cold_circle_endpoint_contacts(path, ezdxf.readfile(path), gray, ROI, DPI)
    assert len(checks) == 1 and checks[0]["pass"], checks
    assert _restore(gray, restored)[1] == restored


def test_oblique_terminal_fallback_keeps_LINE_axis_and_real_white_gap():
    gray, path = _oblique_source()
    line = _line(kind="LINE", first=path["geometry"]["points"][0],
                 last=path["geometry"]["points"][-1])
    assert not _restore(gray, [_circle(gray), line])[0]["replacements"]
    gray, path = _oblique_source(gap=True)
    before = gray.copy()
    result, restored = _restore(gray, [_circle(gray), path])
    assert not result["replacements"]
    assert restored[-1] == path and np.array_equal(gray, before)


def test_existing_circle_overlap_is_preserved_without_trimming():
    gray, objects = _objects(line=_line(first=(99, 80), kind="LINE"))
    result, restored = _restore(gray, objects)
    assert restored == objects
    assert result["replacements"] == []


def _saved(tmp_path):
    gray, objects = _objects()
    _, restored = _restore(gray, objects)
    path = tmp_path / "contact.dxf"
    cad_io.export_objects(restored, path, ROI, DPI, hashlib.sha256(gray.tobytes()).hexdigest())
    return gray, restored, path


def _rebind(path, doc=None):
    if doc is not None:
        doc.saveas(path)
    meta_path = path.with_suffix(".objects.json")
    meta = json.loads(meta_path.read_text())
    meta["dxf_sha256"] = cad_io.sha(path)
    meta_path.write_text(json.dumps(meta))
    return meta


def _cold(path, gray):
    return contacts.cold_circle_endpoint_contacts(path, ezdxf.readfile(path), gray, ROI, DPI)


def test_actual_saved_native_contact_is_part_of_the_normal_cold_source_gate(tmp_path):
    gray, restored, path = _saved(tmp_path)
    before = cad_io.sha(path)
    report = cad_io.cold_audit(path, gray, ROI, DPI, tmp_path / "audit.json")
    assert report["source_gate_pass"], report["source_checks"]
    assert report["circle_endpoint_contact_checks"][0]["pass"]
    assert report["circle_endpoint_contact_checks"][0]["actual_saved_geometry_checked"]
    assert before == cad_io.sha(path)
    entity = next(e for e in ezdxf.readfile(path).modelspace() if e.dxftype() == "LWPOLYLINE" and e.dxf.layer != "REVIEW")
    assert cad_io.identity(entity)[contacts.FIELD] is True
    assert len(entity) == len(restored[1]["geometry"]["points"])


@pytest.mark.parametrize("mutation", ["endpoint", "old_vertex", "bulge", "target_circle", "missing_target", "flag", "z_plane"])
def test_actual_saved_mutations_fail_even_after_dxf_hash_is_rebound(tmp_path, mutation):
    gray, _, path = _saved(tmp_path)
    doc = ezdxf.readfile(path)
    line = next(e for e in doc.modelspace() if cad_io.identity(e).get(contacts.FIELD))
    circle = next(e for e in doc.modelspace() if e.dxftype() == "CIRCLE")
    if mutation in ("endpoint", "old_vertex", "bulge"):
        values = list(line.get_points("xyseb"))
        i = 1 if mutation == "old_vertex" else 0
        v = list(values[i])
        v[4 if mutation == "bulge" else 0] += 0.1
        values[i] = v
        line.set_points(values, format="xyseb")
    elif mutation == "target_circle":
        circle.dxf.radius += 0.1
    elif mutation == "missing_target":
        doc.modelspace().delete_entity(circle)
    elif mutation == "flag":
        cad_io.mark(line, {"id": cad_io.identity(line)["id"], "kind": "CONNECTION_PATH"})
    elif mutation == "z_plane":
        line.dxf.elevation = 1
    _rebind(path, doc)
    rows = _cold(path, gray)
    assert rows and not all(row["pass"] for row in rows), rows


@pytest.mark.parametrize("mutation", ["remove_certificate", "raw_path", "source_pixel"])
def test_cold_proof_rejects_missing_raw_records_or_new_white_gap(tmp_path, mutation):
    gray, _, path = _saved(tmp_path)
    meta_path = path.with_suffix(".objects.json")
    meta = json.loads(meta_path.read_text())
    obj = next(o for o in meta["objects"] if contacts.FIELD in o.get("source_evidence", {}))
    if mutation == "remove_certificate":
        obj["source_evidence"].pop(contacts.FIELD)
    elif mutation == "raw_path":
        obj["source_evidence"]["source_path_points"][0][1] += 1
    else:
        gray[80, 103] = 255
    meta_path.write_text(json.dumps(meta))
    rows = _cold(path, gray)
    assert rows and not all(row["pass"] for row in rows), rows


def test_exact_supercover_does_not_skip_white_corner_cells():
    assert set(map(tuple, contacts._segment_cells([0, 0], [1, 1]))) == {(0, 0), (1, 0), (0, 1), (1, 1)}


def test_quality_counts_intact_components_separately_from_fully_resolved_markers():
    from app.native_objects.quality_review import _circular_composition_summary

    # These are counter inputs, not invented OCR approvals. Unproved native
    # circles/markers must be excluded before the composition is counted.
    rows = [
        {"id": "complete", "kind": "CIRCULAR_MARKER", "candidate_structure_matches": True, "source_geometry_gate_pass": True},
        {"id": "unresolved-lead", "kind": "CIRCULAR_MARKER", "candidate_structure_matches": True, "source_geometry_gate_pass": True},
        {"id": "unproved", "kind": "CIRCULAR_MARKER", "candidate_structure_matches": True, "source_geometry_gate_pass": False},
        {"id": "boundary-only", "kind": "CIRCLE", "candidate_structure_matches": True, "source_geometry_gate_pass": True},
    ]
    candidates = {row["id"]: {"source_evidence": {}} for row in rows}
    for key in ("unresolved-lead", "unproved"):
        candidates[key]["source_evidence"]["external_endpoint_contact_review"] = {
            "status": "NEARBY_EXTERNAL_ENDPOINT_RELATION_PENDING"}
    summary = _circular_composition_summary(rows, candidates)
    assert summary["complete_marker_objects"] == 1
    assert summary["circle_text_compositions"] == 2
    assert summary["circle_text_compositions_with_external_contacts_pending"] == 1
    assert summary["partial_circle_boundary_objects"] == 1
    assert summary["partial_compositions"] == 2


def test_two_marker_instances_keep_unique_circle_text_blocks_and_separate_leads(tmp_path):
    roi = (0, 0, 250, 160)
    gray = np.full((160, 250), 255, np.uint8)
    for x in (50, 170):
        cv2.circle(gray, (x, 80), 20, 0, 3)
        cv2.line(gray, (x - 5, 73), (x - 5, 87), 0, 2)
        cv2.line(gray, (x - 5, 73), (x + 5, 73), 0, 2)
        cv2.line(gray, (x - 5, 80), (x + 2, 80), 0, 2)
        cv2.line(gray, (x + 22, 80), (x + 60, 80), 0, 3)
    markers = []
    for row in discover_circular_markers(gray, roi)["rows"]:
        if not row["geometry_accepted"]:
            continue
        a, b, c, d = row["glyph_bbox_xyxy_px"]
        # Literal F is a synthetic exporter input here; no OCR is claimed.
        markers.append({"id": row["id"], "kind": "CIRCULAR_MARKER", "layer": "CIRCULAR_MARKERS",
                        "geometry": {"circle_geometry": row["geometry"], "text_geometry": {
                            "text": "F", "x": a, "y": d, "width_px": c - a, "height_px": d - b}},
                        "source_evidence": {**row["source_evidence"], "components_complete": True}})
    assert len(markers) == 2
    lines = []
    for index, x in enumerate((50, 170)):
        line = _line(first=(x + 23, 80), last=(x + 60, 80), kind="LINE")
        line["id"] = "external-" + str(index)
        lines.append(line)
    objects = markers + lines
    before = deepcopy(objects)
    result = contacts.restore_circle_endpoint_contacts(gray, roi, objects)
    assert result["summary"]["restored_external_endpoints"] == 2
    assert objects == before
    path = tmp_path / "two-markers.dxf"
    cad_io.export_objects(markers + result["replacements"], path, roi, DPI, "synthetic-exporter-input")
    doc = ezdxf.readfile(path)
    inserts = list(doc.modelspace().query("INSERT"))
    assert len(inserts) == 2 and inserts[0].dxf.name != inserts[1].dxf.name
    for insert in inserts:
        assert [entity.dxftype() for entity in doc.blocks.get(insert.dxf.name)] == ["CIRCLE", "TEXT"]
    assert len(doc.modelspace().query("LINE")) == 2
    old_other = cad_io.entity_data(inserts[1])
    first_text = next(e for e in doc.blocks.get(inserts[0].dxf.name) if e.dxftype() == "TEXT")
    first_text.dxf.text = "Q"
    inserts[0].translate(4, 3, 0)
    assert cad_io.entity_data(inserts[1]) == old_other
    assert next(e for e in doc.blocks.get(inserts[1].dxf.name) if e.dxftype() == "TEXT").dxf.text == "F"
