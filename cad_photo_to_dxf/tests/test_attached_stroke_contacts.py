"""Predeclared all-prior contact controls from freshly rebuilt raster sources.

These small authored fixtures exercise the additional contact gate, not held-out
recognition accuracy. No fixture reuses a graph after changing original pixels.
Full attached-stroke discovery and its original owner proof have separate tests.
"""
from copy import deepcopy
import hashlib
import json

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects import attached_stroke_contacts as contacts
from app.native_objects import attached_stroke_graph as attached
from app.native_objects import connections
from app.native_objects import cad_io
from app.native_objects.text_contact_geometry import build_text_contact_source_graph


def _scene(*, source_mutation=None, old_start=15):
    gray = np.full((121, 121), 255, np.uint8)
    cv2.line(gray, (15, 60), (105, 60), 0, 1)
    cv2.line(gray, (60, old_start), (60, 105), 0, 1)
    if source_mutation:
        source_mutation(gray)
    context = build_text_contact_source_graph(gray, [0, 0, 121, 121])
    graph = context.graph
    edge_ids = [edge["id"] for edge in graph.edges
                if np.all(graph.xy(edge["pixels"])[:, 1] == 60)]
    nodes = sorted({nid for eid in edge_ids for nid in graph.edges[eid]["nodes"]})
    cores = {nid: attached._core_proof(gray, graph, nid) for nid in nodes if len(graph.nodes[nid]["edges"]) >= 3}
    row = {"stroke_id": "authored-new-horizontal", "source_graph_edge_ids": edge_ids,
           "source_node_ids": nodes, "source_path_px": [[x, 60] for x in range(15, 106)],
           "representation": {"points": [[15, 60], [105, 60]], "bulges": [0.0, 0.0], "closed": False}}
    prior = {"id": "authored-prior-vertical", "kind": "LINE", "layer": "LINE",
             "geometry": {"start": [60, old_start], "end": [60, 105]},
             "source_evidence": {"source_path_points": [[60, y] for y in range(old_start, 106)],
                 "original_source_crop_xyxy_px": context.crop_bbox,
                 "original_source_crop_array_sha256": context.source_crop_hash,
                 "source_pixels_modified": False}}
    return gray, context, row, prior, cores


def _check(scene, priors=None, **kwargs):
    gray, context, row, prior, cores = scene
    return contacts.check_prior_native_contacts(gray, [row], [prior] if priors is None else priors,
                                               graph=context.graph, cores=cores, **kwargs)


@pytest.mark.parametrize("segmented", [False, "junction_vertex", "one_pixel_segments"])
def test_existing_owner_point_contact_retains_independent_original_ports(segmented):
    scene = _scene()
    _, context, row, prior, cores = scene
    graph = context.graph
    anchors = {nid: {"ports": [port for port in graph.nodes[nid]["edges"]
                              if port[0] not in row["source_graph_edge_ids"]]} for nid in cores}
    if segmented:
        prior["kind"] = "CONNECTION_PATH"
        points = ([[60, 15], [60, 60], [60, 105]] if segmented == "junction_vertex"
                  else [[60, y] for y in range(15, 106)])
        prior["geometry"] = {"points": points, "bulges": [0.0] * len(points), "closed": False}
    report = _check(scene, owner={"id": prior["id"]}, anchors=anchors)
    assert report["pass"], report
    assert len(report["allowed_source_point_contacts"]) == (2 if segmented else 1)
    proof = report["allowed_source_point_contacts"][0]["source_contact_proof"]
    assert len(proof["prior_member_original_ports"]) == 2
    assert len(proof["guest_original_ports"]) == 2
    assert {tuple(p["port"]) for p in proof["guest_original_ports"]}.isdisjoint(
        {tuple(p["port"]) for p in proof["prior_member_original_ports"]})
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("old_start", [15, 60])
def test_another_old_object_can_have_a_real_crossing_or_endpoint_contact(old_start):
    scene = _scene(old_start=old_start)
    report = _check(scene)
    assert report["pass"], report
    point = report["allowed_source_point_contacts"][0]
    assert point["point_px"] == [60.0, 60.0]
    assert point["source_contact_proof"]["prior_source_binding"]["original_source_path_sha256"]
    assert len(point["source_contact_proof"]["prior_member_original_ports"]) == (2 if old_start == 15 else 1)


@pytest.mark.parametrize("missing", ["all", "hash", "source_path", "modified", "borrowed_guest_path"])
def test_black_point_and_new_core_cannot_license_an_unproved_old_member(missing):
    scene = _scene()
    prior = deepcopy(scene[3])
    if missing == "all":
        prior.pop("source_evidence")
    elif missing == "hash":
        prior["source_evidence"]["original_source_crop_array_sha256"] = "0" * 64
    elif missing == "source_path":
        prior["source_evidence"].pop("source_path_points")
    elif missing == "modified":
        prior["source_evidence"]["source_pixels_modified"] = True
    else:
        prior["source_evidence"]["source_path_points"] = deepcopy(scene[2]["source_path_px"])
    report = _check(scene, [prior])
    assert not report["pass"]
    assert len(report["unexpected_point_contacts"]) == 1
    assert not report["positive_length_overlaps"]
    assert not report["allowed_source_point_contacts"]


def test_original_source_change_rebuilds_graph_and_invalidates_old_binding():
    old_scene = _scene()
    new_scene = _scene(source_mutation=lambda gray: cv2.line(gray, (8, 8), (9, 8), 0, 1))
    assert new_scene[1].graph is not old_scene[1].graph
    assert new_scene[1].source_crop_hash != old_scene[1].source_crop_hash
    report = _check(new_scene, [old_scene[3]])
    assert not report["pass"]
    reason = report["unexpected_point_contacts"][0]["source_contact_proof"]["reason"]
    assert reason == "PRIOR_MEMBER_ORIGINAL_SOURCE_BINDING_MISSING_OR_CHANGED"
    assert _check(new_scene)["pass"]


def test_positive_native_length_is_never_licensed_by_the_shared_core():
    scene = _scene()
    prior = deepcopy(scene[3])
    prior["geometry"] = {"start": [40, 60], "end": [90, 60]}
    prior["source_evidence"]["source_path_points"] = [[x, 60] for x in range(40, 91)]
    report = _check(scene, [prior])
    assert not report["pass"]
    assert len(report["positive_length_overlaps"]) == 1
    assert report["positive_length_overlaps"][0]["positive_overlap_length_px"] == 50
    assert not report["allowed_source_point_contacts"]
    # The retained production duplicate gate still has independent authority.
    quarantine, adequate = attached._native_conflicts([scene[2]], [prior], scene[0])
    assert scene[2]["stroke_id"] in set(quarantine["quarantined_ids"]) | set(adequate)


def _wall(prior, *, member_source=True):
    member = {key: deepcopy(prior[key]) for key in ("kind", "geometry", "source_evidence")}
    if not member_source:
        member.pop("source_evidence")
    return {"id": "authored-old-block", "kind": "WALL_SEGMENT", "layer": "LINE",
            "geometry": {"members": [
                {"kind": "LINE", "geometry": {"start": [5, 5], "end": [10, 5]}}, member]},
            "source_evidence": deepcopy(prior["source_evidence"])}


def test_actual_insert_line_member_is_examined_and_bound_to_member_index(tmp_path, monkeypatch):
    scene = _scene()
    block = _wall(scene[3])
    report = _check(scene, [block])
    assert report["pass"], report
    hit = report["allowed_source_point_contacts"][0]
    assert hit["object_id"] == block["id"]
    assert hit["member_index"] == 1
    assert hit["member_path"] == ["members", 1]
    # Only unused font packaging is isolated. This graphic-only export does not
    # render or measure its REVIEW labels and makes no font-verification claim.
    monkeypatch.setattr(cad_io, "_font", lambda _out: {"test_scope": "GRAPHIC_INSERT_MEMBERS_ONLY"})
    saved = tmp_path / "authored_block.dxf"
    cad_io.export_objects([block], saved, [0, 0, 121, 121], 25.4, hashlib.sha256(scene[0].tobytes()).hexdigest())
    doc = ezdxf.readfile(saved)
    actual = list(doc.modelspace().query("INSERT"))[0]
    members = list(actual.virtual_entities())
    assert len(members) == 2 and all(member.dxftype() == "LINE" for member in members)
    assert list(members[hit["member_index"]].dxf.start)[:2] == [60.0, 106.0]
    assert list(members[hit["member_index"]].dxf.end)[:2] == [60.0, 16.0]


def test_parent_block_source_does_not_grant_an_unproved_member_ownership():
    scene = _scene()
    report = _check(scene, [_wall(scene[3], member_source=False)])
    assert not report["pass"]
    assert report["unexpected_point_contacts"][0]["member_index"] == 1


@pytest.mark.parametrize("kind", ["WALL_SEGMENT", "ROOM_LABEL"])
def test_actual_writer_line_member_cannot_be_hidden_by_an_incidental_curve_label(kind):
    scene = _scene()
    member = {"kind": "CIRCLE", "geometry": {"start": [60, 15], "end": [60, 105],
                                           "center": [10, 10], "radius_px": 2}}
    geometry = ({"members": [member]} if kind == "WALL_SEGMENT" else {
        "frame_points": [[5, 5], [10, 5], [10, 10], [5, 10]],
        "text_geometry": {}, "frame_source_remainders": [member]})
    block = {"id": "authored-mislabeled-line-member", "kind": kind, "geometry": geometry}
    report = _check(scene, [block])
    assert not report["pass"]
    hit = report["unexpected_point_contacts"][0]
    assert hit["kind"] == "LINE"
    assert hit["member_index"] == (0 if kind == "WALL_SEGMENT" else 2)
    assert not report["unsupported_contacts"]


def _paint_curve(gray, obj):
    geometry = obj["geometry"]
    if obj["kind"] == "CONNECTION_PATH":
        pixels = np.rint(connections._dense_geometry(geometry)).astype(np.int32)
        cv2.polylines(gray, [pixels], False, 0, 1)
    elif obj["kind"] == "CIRCLE":
        cv2.circle(gray, tuple(geometry["center"]), int(geometry["radius_px"]), 0, 1)
    else:
        radius = int(geometry["radius_px"])
        cv2.ellipse(gray, tuple(geometry["center"]), (radius, radius), 0,
                    geometry["start_deg_image"], geometry["end_deg_image"], 0, 1)


@pytest.mark.parametrize("kind", ["CIRCLE", "ARC", "BULGE_ARC"])
def test_related_unsupported_curve_is_pending_without_a_chord_substitution(kind):
    if kind == "BULGE_ARC":
        geometry = {"points": [[40, 80], [80, 80]], "bulges": [1.0, 0.0], "closed": False}
        old = {"id": "authored-curve", "kind": "CONNECTION_PATH", "geometry": geometry}
    else:
        geometry = {"center": [60, 80], "radius_px": 20.0}
        if kind == "ARC":
            geometry.update(start_deg_image=180.0, end_deg_image=360.0, sweep_deg_image=180.0)
        old = {"id": "authored-curve", "kind": kind, "geometry": geometry}
    scene = _scene(source_mutation=lambda gray: _paint_curve(gray, old))
    report = _check(scene, [old])
    assert not report["pass"]
    assert report["unsupported_contacts"][0]["classification"] == "PENDING_UNSUPPORTED_CURVE_CONTACT"
    assert report["unsupported_contacts"][0]["actual_curve_intersection_asserted"] is False
    assert not report["unexpected_point_contacts"]
    assert not report["positive_length_overlaps"]


@pytest.mark.parametrize("kind", ["CIRCLE", "ARC", "BULGE_ARC"])
def test_remote_curve_bounds_do_not_reject_an_unrelated_candidate(kind):
    if kind == "BULGE_ARC":
        geometry = {"points": [[15, 100], [35, 100]], "bulges": [-1.0, 0.0], "closed": False}
        old = {"id": "authored-remote-curve", "kind": "CONNECTION_PATH", "geometry": geometry}
    elif kind == "ARC":
        # Its full circle reaches the new line, while this actual lower arc is
        # remote. Finite angular bounds must preserve that distinction.
        old = {"id": "authored-remote-curve", "kind": kind, "geometry": {
            "center": [60, 90], "radius_px": 30.0,
            "start_deg_image": 0.0, "end_deg_image": 180.0, "sweep_deg_image": 180.0}}
    else:
        old = {"id": "authored-remote-curve", "kind": kind,
               "geometry": {"center": [25, 100], "radius_px": 5.0}}
    report = _check(_scene(source_mutation=lambda gray: _paint_curve(gray, old)), [old])
    assert report["pass"], report
    assert report["curve_segment_pair_count"] == 1
    assert report["pairs_excluded_by_disjoint_true_geometry_bounds"] == 1
    assert not report["unsupported_contacts"]


@pytest.mark.parametrize("geometry", [
    {"center": [60, 80], "radius_px": 20.0,
     "start_deg_image": 0.0, "end_deg_image": -180.0, "sweep_deg_image": -180.0},
    {"center": [60, 80], "radius_px": 20.0,
     "start_deg_image": 90.0, "end_deg_image": -180.0, "sweep_deg_image": -270.0},
])
def test_clockwise_and_major_arc_parameter_bounds_do_not_miss_contact(geometry):
    old = {"id": "authored-clockwise-arc", "kind": "ARC", "geometry": geometry}
    scene = _scene(source_mutation=lambda gray: _paint_curve(gray, old))
    report = _check(scene, [old])
    assert not report["pass"]
    assert len(report["unsupported_contacts"]) == 1
    assert report["unsupported_contacts"][0]["curve_parameter_bbox_xyxy_px"][1] <= 60
    assert not report["unexpected_point_contacts"]


def test_arc_sweep_inconsistent_with_actual_export_cannot_prove_separation():
    # The actual start/end angles draw an upper half arc reaching the candidate.
    # A contradictory short declared sweep must not supply a smaller fake bound.
    old = {"id": "authored-inconsistent-arc", "kind": "ARC", "geometry": {
        "center": [60, 80], "radius_px": 20.0,
        "start_deg_image": 180.0, "end_deg_image": 360.0, "sweep_deg_image": 20.0}}
    report = _check(_scene(source_mutation=lambda gray: _paint_curve(gray, old)), [old])
    assert not report["pass"]
    problem = report["unsupported_contacts"][0]
    assert problem["classification"] == "PENDING_NATIVE_MEMBER_HAS_NO_RELIABLE_GEOMETRY_BOUND"
    assert problem["reason"] == "NATIVE_CONTACT_ARC_SWEEP_DIFFERS_FROM_EXPORTED_ENDPOINTS"


def test_closed_frame_last_segment_and_curve_members_are_not_lost_inside_blocks():
    scene = _scene()
    frame = {"id": "authored-frame", "kind": "ROOM_LABEL", "geometry": {
        "frame_points": [[55, 40], [65, 40], [65, 80], [55, 80]], "text_geometry": {}}}
    door = {"id": "authored-door", "kind": "DOOR", "geometry": {"native_members": [
        {"kind": "LINE", "geometry": {"start": [1, 1], "end": [5, 1]}},
        {"kind": "ARC", "geometry": {"center": [60, 80], "radius_px": 20,
            "start_deg_image": 180, "end_deg_image": 360, "sweep_deg_image": 180}}]}}
    report = _check(scene, [frame, door])
    assert not report["pass"]
    assert {hit["prior_member_segment_index"] for hit in report["unexpected_point_contacts"]} == {1, 3}
    assert report["unsupported_contacts"][0]["object_id"] == door["id"]
    assert report["unsupported_contacts"][0]["member_index"] == 1
    assert report["text_member_count_delegated_to_existing_source_gate"] == 1


def test_point_source_plan_is_deterministic_and_preserves_inputs():
    scene = _scene()
    gray, context, row, prior, cores = scene
    original = deepcopy((row, prior, cores))
    gray_bytes = gray.tobytes()
    first = _check(scene)
    second = _check(scene)
    assert first == second
    assert (row, prior, cores) == original
    assert gray.tobytes() == gray_bytes
    assert first["schema"] == contacts.SCHEMA
    assert first["producer_sha256"] == contacts.producer_sha256()
    assert context.source_crop_hash == hashlib.sha256(gray.tobytes()).hexdigest()
