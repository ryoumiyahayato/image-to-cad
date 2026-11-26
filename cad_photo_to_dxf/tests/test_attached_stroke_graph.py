"""Complete graph strokes at proved crossings and finite attachments.

These are authored source fixtures with known stroke boundaries, not hidden
real-page coordinates or a transcription oracle.  Every graphic owner is
created by the existing structure planner and actual native adoption first.
"""

from copy import deepcopy
import hashlib
import json
import time

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects import attached_stroke_graph as attached
from app.native_objects import connections
from app.native_objects import structure_contact_geometry as structure
from app.native_objects.attached_stroke_audit import cold_attached_stroke_bindings
from app.native_objects.cad_io import APPID, export_objects, save_native_dxf
from app.native_objects.circle_endpoint_contacts import _segment_cells
from app.native_objects.contracts import save_json
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from tests.test_native_mtext_source_layout import source_objects as _mtext_prior_objects
from tests.test_native_transverse_stroke_geometry import ROI, _structure_stage


def _source(*, variant="attached"):
    """Three slanted strokes and one side attachment around a real owner."""
    gray = np.full((280, 400), 255, np.uint8)
    cv2.circle(gray, (55, 90), 15, 0, 2)
    cv2.line(gray, (70, 90), (180, 90), 0, 2)
    cv2.line(gray, (180, 90), (260, 105), 0, 2)
    cv2.line(gray, (260, 105), (260, 225), 0, 2)
    cv2.putText(gray, "S", (242, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 2)
    cv2.line(gray, (180, 225), (370, 225), 0, 2)
    for x in (110, 130, 150):
        cv2.line(gray, (x + 4, 50), (x - 4, 125), 0, 2)
    if variant == "y":
        cv2.line(gray, (106, 125), (88, 140), 0, 2)
        cv2.line(gray, (106, 125), (124, 140), 0, 2)
    else:
        cv2.line(gray, (106, 125), (104, 145), 0, 2)
        cv2.line(gray, (106, 125), (175, 125), 0, 2)
    if variant == "white_gap":
        gray[121:130, 160:166] = 255
    elif variant == "nearby_disconnected_cap":
        cv2.line(gray, (180, 125), (194, 125), 0, 2)
    elif variant == "short_fourth_arm":
        # Three source pixels beyond the contact leave a genuine 2 px graph
        # edge after thinning, below the 4 px finite-direction minimum.
        cv2.line(gray, (126, 125), (126, 128), 0, 1)
    elif variant == "continues_below_attachment":
        cv2.line(gray, (126, 125), (125, 145), 0, 2)
    elif variant == "white_hole":
        # A genuine hole in a side stroke, away from the already adopted
        # main-path crossing. Two valid local tangent pairs cannot erase it.
        gray[104:115, 124:134] = 255
        cv2.rectangle(gray, (126, 105), (131, 112), 0, 1)
        cv2.line(gray, (128, 102), (128, 105), 0, 1)
        cv2.line(gray, (128, 112), (127, 116), 0, 1)
    return gray


def _prior(tmp_path, *, variant="attached"):
    gray = _source(variant=variant)
    context, initial, plan = _structure_stage(gray)
    targets = [p for p in plan["paths"] if p["path_role"] == "ROUND_TO_CARRIER"]
    assert len(targets) == 1, plan["pending"]
    source_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    first = complete_text_contact_paths(
        gray, ROI, source_sha, initial, [plan], tmp_path / "owner"
    )
    assert len(first["objects"]) == 1, first["decisions"]
    assert first["objects"][0]["kind"] == "CONNECTION_PATH"
    prior = [o for o in initial if o["id"] not in first["retired_ids"]]
    prior += first["objects"]
    return gray, context, prior, source_sha


def _plan(tmp_path, *, variant="attached"):
    gray, context, prior, source_sha = _prior(tmp_path, variant=variant)
    plan = attached.plan_attached_stroke_graph(gray, ROI, prior, source_graph=context)
    return gray, context, prior, source_sha, plan


def _geometry_key(row):
    geometry = row["representation"]
    points = tuple(tuple(round(float(v), 9) for v in p) for p in geometry["points"])
    return min(points, points[::-1])


def _near(point, target, tolerance=2.5):
    return np.linalg.norm(np.asarray(point, float) - target) <= tolerance


def _touches_start(row, target):
    points = row["source_path_px"]
    return _near(points[0], target) or _near(points[-1], target)


def _assert_source_supported(gray, row):
    raw = np.asarray(row["source_path_px"], float)
    assert len(raw) >= 2
    assert np.isfinite(raw).all()
    assert np.array_equal(raw, np.rint(raw))
    assert np.max(np.max(np.abs(np.diff(raw, axis=0)), axis=1)) <= 1
    xy = raw.astype(int)
    assert np.all(gray[xy[:, 1], xy[:, 0]] < 128)
    geometry = row["representation"]
    assert not geometry["closed"]
    assert len(geometry["points"]) == len(geometry["bulges"])
    assert not any(geometry["bulges"])
    # Original black cells, not a distance transform across a real gap.
    for a, b in zip(geometry["points"], geometry["points"][1:]):
        cells = np.asarray(_segment_cells(a, b), int)
        assert np.all(gray[cells[:, 1], cells[:, 0]] < 128)


def _graph_geometry(context):
    graph = context.graph
    return {
        "nodes": {i: {k: deepcopy(node.get(k)) for k in
                       ("pixels", "edges", "pairing", "terminal", "core_topology")}
                  for i, node in graph.nodes.items()},
        "edges": deepcopy(graph.edges),
        "skeleton_sha": hashlib.sha256(graph.skel.tobytes()).hexdigest(),
    }


def test_complete_attached_network_preserves_real_free_and_attached_boundaries(tmp_path):
    gray, context, prior, _, plan = _plan(tmp_path)
    assert plan["schema"] == "source-attached-stroke-graph-plan-v1"
    assert len(plan["paths"]) == 4, (plan["components"], plan["pending"])
    expected = [
        ((114, 50), (104, 145), "OBSERVED_FREE_SOURCE_ENDPOINT"),
        ((134, 50), (126, 125), "OBSERVED_COMPLETE_STROKE_ATTACHMENT"),
        ((154, 50), (146, 125), "OBSERVED_COMPLETE_STROKE_ATTACHMENT"),
    ]
    used = []
    for start, end, expected_end in expected:
        selected = [p for p in plan["paths"] if _touches_start(p, start)]
        assert len(selected) == 1
        row = selected[0]
        used.append(row)
        endpoints = [row["representation"]["points"][i] for i in (0, -1)]
        assert any(_near(p, start) for p in endpoints)
        assert any(_near(p, end) for p in endpoints)
        kinds = [e["kind"] for e in row["endpoint_evidence"]]
        assert kinds.count("OBSERVED_FREE_SOURCE_ENDPOINT") == (2 if expected_end == "OBSERVED_FREE_SOURCE_ENDPOINT" else 1)
        assert expected_end in kinds
    connector = next(p for p in plan["paths"] if p not in used)
    endpoints = [connector["representation"]["points"][i] for i in (0, -1)]
    assert any(_near(p, (106, 125)) for p in endpoints)
    assert any(_near(p, (175, 125)) for p in endpoints)
    assert sorted(e["kind"] for e in connector["endpoint_evidence"]) == [
        "OBSERVED_COMPLETE_STROKE_ATTACHMENT", "OBSERVED_FREE_SOURCE_ENDPOINT"
    ]
    for row in plan["paths"]:
        _assert_source_supported(gray, row)
        assert row["required_crossing_path_id"] == prior[-1]["id"]
    assert attached.verify_attached_stroke_graph_plan(
        gray, ROI, plan, source_graph=context
    )["pass"]


def test_planner_keeps_original_ink_graph_prior_objects_and_old_pair_limits(tmp_path):
    gray, context, prior, _ = _prior(tmp_path)
    old_gray, old_prior, old_graph = gray.copy(), deepcopy(prior), _graph_geometry(context)
    old_limits = (structure.POLICY["maximum_pair_deviation_deg"], structure.POLICY["minimum_pair_margin_deg"])
    attached.plan_attached_stroke_graph(gray, ROI, prior, source_graph=context)
    assert np.array_equal(gray, old_gray)
    assert prior == old_prior
    assert _graph_geometry(context) == old_graph
    assert old_limits == (20.0, 18.0)
    assert (structure.POLICY["maximum_pair_deviation_deg"], structure.POLICY["minimum_pair_margin_deg"]) == old_limits


def test_input_owner_and_port_enumeration_order_cannot_choose_another_decomposition(tmp_path):
    gray, context, prior, _, first = _plan(tmp_path)
    reordered = deepcopy(context)
    reordered.graph.nodes = dict(reversed(list(reordered.graph.nodes.items())))
    for node in reordered.graph.nodes.values():
        node["edges"] = list(reversed(node["edges"]))
    second = attached.plan_attached_stroke_graph(
        gray, ROI, prior[::-1], source_graph=reordered
    )
    assert sorted(_geometry_key(p) for p in second["paths"]) == sorted(
        _geometry_key(p) for p in first["paths"]
    )


def test_true_white_gap_is_not_closed_by_a_nearby_attachment(tmp_path):
    gray, _, _, _, plan = _plan(tmp_path, variant="white_gap")
    assert np.all(gray[121:130, 160:166] == 255)
    for row in plan["paths"]:
        _assert_source_supported(gray, row)
        raw = np.asarray(row["source_path_px"])
        near_connector = raw[(raw[:, 1] > 120) & (raw[:, 1] < 130)]
        if len(near_connector):
            assert not (near_connector[:, 0].min() < 160 and near_connector[:, 0].max() >= 166)


def test_y_competition_cannot_be_resolved_by_truncating_at_the_junction(tmp_path):
    _, _, _, _, plan = _plan(tmp_path, variant="y")
    assert not any(_touches_start(row, (114, 50)) for row in plan["paths"])
    assert plan["pending"], plan["components"]


def test_disconnected_collinear_ink_does_not_extend_or_invalidate_the_real_free_cap(tmp_path):
    gray, _, _, _, plan = _plan(tmp_path, variant="nearby_disconnected_cap")
    assert len(plan["paths"]) == 4, (plan["components"], plan["pending"])
    assert np.all(gray[124:127, 177:179] == 255)
    connector = [p for p in plan["paths"] if _touches_start(p, (175, 125))]
    assert len(connector) == 1
    assert max(p[0] for p in connector[0]["representation"]["points"]) < 179
    for row in plan["paths"]:
        _assert_source_supported(gray, row)


def test_same_cycle_adjacency_distinguishes_solid_original_core_from_real_white_hole():
    """Unit proof fixture, deliberately independent of thinning/adoption.

    The source graph has identical retained cycle edges in both observations.
    Only original ink changes; valid tangent pairs cannot license filling its
    enclosed white cell. This is not an end-to-end source graph claim.
    """
    skeleton = np.zeros((121, 121), np.uint8)
    for x, y in ((60, 59), (61, 60), (60, 61), (59, 60)):
        skeleton[y, x] = 1
    for start, end in (
        ((60, 15), (60, 59)), ((61, 60), (105, 60)),
        ((60, 61), (60, 105)), ((15, 60), (59, 60)),
    ):
        cv2.line(skeleton, start, end, 1, 1)
    observations = []
    for filled in (True, False):
        gray = 255 * (1 - skeleton)
        gray[60, 60] = 0 if filled else 255
        graph = connections._SourceGraph(
            skeleton.astype(bool), [0, 0], [], [0, 0, 121, 121],
            time.process_time(), source_ink=gray < 128,
        )
        junctions = [node for node in graph.nodes.values() if len(node["edges"]) == 4]
        assert len(junctions) == 1
        node = junctions[0]
        assert node["core_topology"]["cycle_rank"] == 1
        before = deepcopy(node)
        proof = attached._core_proof(gray, graph, node["id"])
        assert proof["pass"] is filled
        assert bool(proof["enclosed_original_white_components"]) is not filled
        assert len(proof["all_source_core_adjacencies"]) == node["core_topology"]["edges"]
        assert node == before
        observations.append(proof)
    assert observations[0]["all_source_core_adjacencies"] == observations[1]["all_source_core_adjacencies"]


def test_short_fourth_arm_is_not_ignored_to_claim_a_three_port_attachment(tmp_path):
    _, context, _, _, plan = _plan(tmp_path, variant="short_fourth_arm")
    near = [n for n in context.graph.nodes.values() if _near(n["center"], (126, 125), 4)]
    assert any(len(n["edges"]) >= 4 or n["internal_source_endpoint_count"] for n in near)
    assert not any(_touches_start(row, (134, 50)) for row in plan["paths"])
    assert plan["pending"], plan["components"]


def test_observed_forward_continuation_is_never_relabelled_as_an_attached_endpoint(tmp_path):
    _, _, _, _, plan = _plan(tmp_path, variant="continues_below_attachment")
    for row in plan["paths"]:
        if _touches_start(row, (134, 50)):
            endpoints = [row["representation"]["points"][i] for i in (0, -1)]
            assert not any(_near(p, (126, 125)) for p in endpoints)
            assert any(_near(p, (125, 145)) for p in endpoints)


def test_real_white_hole_is_not_collapsed_by_two_valid_direction_pairs(tmp_path):
    gray, _, _, _, plan = _plan(tmp_path, variant="white_hole")
    assert np.all(gray[107:111, 127:131] == 255)
    # This prototype only licenses filled, bounded shared raster cores.
    # A new explicit hole-preserving contract would need separate validation.
    assert not any(_touches_start(row, (134, 50)) for row in plan["paths"])
    assert plan["pending"], plan["components"]


@pytest.mark.parametrize("change", ["absent", "duplicate", "source_hash", "core_receipt"])
def test_incomplete_or_ambiguous_native_owner_cannot_license_attached_strokes(tmp_path, change):
    gray, context, prior, sha = _prior(tmp_path)
    if change == "absent":
        prior = prior[:-1]
    elif change == "duplicate":
        duplicate = deepcopy(prior[-1])
        duplicate["id"] = "other-complete-owner"
        prior.append(duplicate)
    elif change == "source_hash":
        prior[-1]["source_evidence"]["original_source_crop_array_sha256"] = "0" * 64
    else:
        receipt = prior[-1]["source_evidence"]["text_contact_path"]
        for contact in receipt["path"]["contact_continuations"]:
            if contact.get("source_core_pixels"):
                contact["source_core_pixels"][0][0] += 4
        receipt["path_sha256"] = structure._digest(receipt["path"])
    before = deepcopy(prior)
    manifest = attached.complete_attached_strokes(
        gray, ROI, sha, prior, tmp_path / "new", source_graph=context
    )
    assert not manifest["objects"], manifest["decisions"]
    assert manifest["retired_ids"] == []
    assert prior == before


@pytest.mark.parametrize("change", ["truncate", "binding", "source"])
def test_independent_replay_rejects_changed_path_owner_or_original_source(tmp_path, change):
    gray, context, _, _, original = _plan(tmp_path)
    assert original["paths"]
    plan = deepcopy(original)
    if change == "truncate":
        row = plan["paths"][0]
        points = row["representation"]["points"]
        points[-1] = ((np.asarray(points[-1]) + points[0]) / 2).tolist()
    elif change == "binding":
        plan["prior_object_bindings"][-1]["id"] += "-changed"
    else:
        gray = gray.copy()
        gray[124:127, 160:165] = 255
        context = None
    assert not attached.verify_attached_stroke_graph_plan(
        gray, ROI, plan, source_graph=context
    )["pass"]


def _native_entities(doc):
    return {json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)["id"]: entity
            for entity in doc.modelspace() if entity.dxf.layer != "REVIEW"}


def _saved_geometry(entity):
    kind = entity.dxftype()
    if kind == "LINE":
        geometry = (tuple(entity.dxf.start), tuple(entity.dxf.end))
    elif kind == "LWPOLYLINE":
        geometry = (tuple(entity.get_points("xyseb")), bool(entity.closed))
    elif kind == "CIRCLE":
        geometry = (tuple(entity.dxf.center), entity.dxf.radius)
    else:
        raise AssertionError("Unexpected synthetic native type: " + kind)
    return kind, entity.dxf.layer, geometry


def test_actual_adoption_saves_whole_objects_and_each_edit_preserves_other_geometry(tmp_path):
    gray, context, prior, sha = _prior(tmp_path)
    manifest = attached.complete_attached_strokes(
        gray, ROI, sha, prior, tmp_path / "new", source_graph=context
    )
    assert len(manifest["objects"]) == 4, manifest["decisions"]
    assert manifest["retired_ids"] == []
    saved = tmp_path / "complete.dxf"
    export_objects(prior + manifest["objects"], saved, ROI, 200, sha)
    original = _native_entities(ezdxf.readfile(saved))
    assert len(original) == len(prior) + 4
    original_geometry = {key: _saved_geometry(e) for key, e in original.items()}
    for row in manifest["objects"]:
        oid = row["id"]
        assert original[oid].dxftype() in ("LINE", "LWPOLYLINE")
        for operation in ("delete", "move"):
            doc = ezdxf.readfile(saved)
            entities = _native_entities(doc)
            if operation == "delete":
                doc.modelspace().delete_entity(entities[oid])
            else:
                entities[oid].translate(7.0, -3.0, 0.0)
            edited = tmp_path / (oid + "-" + operation + ".dxf")
            save_native_dxf(doc, edited)
            reopened = _native_entities(ezdxf.readfile(edited))
            expected_ids = set(original) - ({oid} if operation == "delete" else set())
            assert set(reopened) == expected_ids
            assert {key: _saved_geometry(e) for key, e in reopened.items() if key != oid} == {
                key: value for key, value in original_geometry.items() if key != oid
            }
            if operation == "move":
                expected = original[oid].copy()
                expected.translate(7.0, -3.0, 0.0)
                assert _saved_geometry(reopened[oid]) == _saved_geometry(expected)


def _complete_saved(tmp_path):
    gray, context, prior, sha = _prior(tmp_path)
    evidence = tmp_path / "evidence"
    manifest = attached.complete_attached_strokes(
        gray, ROI, sha, prior, evidence / "attached_strokes", source_graph=context
    )
    assert len(manifest["objects"]) == 4, manifest["decisions"]
    saved = tmp_path / "complete.dxf"
    export_objects(prior + manifest["objects"], saved, ROI, 200, sha)
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, ROI, 200, evidence
    )
    assert report["pass"], report
    assert len(report["targets"]) == 4
    assert all(row["pass"] for row in report["prior_object_checks"])
    return gray, saved, prior, manifest, evidence


def test_actual_saved_plan_replays_complete_paths_and_all_preceding_objects(tmp_path):
    _complete_saved(tmp_path)


@pytest.mark.parametrize("change", [
    "missing_manifest", "missing_plan", "truncate_actual", "move_prior",
    "strip_marker", "strip_all_xdata", "missing_path", "change_prior_binding",
])
def test_cold_saved_audit_rejects_lost_or_changed_evidence_and_native_members(tmp_path, change):
    gray, saved, prior, manifest, evidence = _complete_saved(tmp_path)
    receipt_path = evidence / "attached_strokes/adoption.json"
    if change == "missing_manifest":
        receipt_path.unlink()
    elif change == "missing_plan":
        (evidence / "attached_strokes/plan.json").unlink()
    elif change == "change_prior_binding":
        changed = json.loads(receipt_path.read_text(encoding="utf-8"))
        changed["prior_object_bindings"][-1]["id"] += "-changed"
        save_json(receipt_path, changed)
    else:
        doc = ezdxf.readfile(saved)
        entities = _native_entities(doc)
        target = entities[manifest["objects"][0]["id"]]
        if change == "truncate_actual":
            if target.dxftype() == "LINE":
                target.dxf.end = target.dxf.start.lerp(target.dxf.end, 0.5)
            else:
                vertices = list(target.get_points("xyseb"))
                endpoint = tuple((a + b) / 2 for a, b in zip(vertices[0][:2], vertices[-1][:2]))
                vertices[-1] = (*endpoint, *vertices[-1][2:])
                target.set_points(vertices, format="xyseb")
        elif change == "move_prior":
            entities[prior[-1]["id"]].translate(2.0, 0.0, 0.0)
        elif change == "strip_marker":
            identity = json.loads(target.get_xdata(APPID)[0].value)
            del identity["attached_stroke_graph"]
            target.set_xdata(APPID, [(1000, json.dumps(identity))])
        elif change == "strip_all_xdata":
            target.discard_xdata(APPID)
        elif change == "missing_path":
            doc.modelspace().delete_entity(target)
        save_native_dxf(doc, saved)
        # Keep the outer byte binding current. The audit must reject the
        # changed native contents, not merely a stale top-level file hash.
        sidecar_path = saved.with_suffix(".objects.json")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["dxf_sha256"] = hashlib.sha256(saved.read_bytes()).hexdigest()
        save_json(sidecar_path, sidecar)
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, ROI, 200, evidence
    )
    assert not report["pass"], report


def _saved_zero_adoption_mtext(tmp_path):
    """A zero-result stage must retain the ordinary multiline text contract."""
    gray = np.full((100, 100), 255, np.uint8)
    roi = [0, 0, 100, 100]
    prior = _mtext_prior_objects(27)
    sha = hashlib.sha256(gray.tobytes()).hexdigest()
    evidence = tmp_path / "evidence"
    manifest = attached.complete_attached_strokes(
        gray, roi, sha, prior, evidence / "attached_strokes"
    )
    assert manifest["objects"] == []
    assert manifest["retired_ids"] == []
    assert {row["id"] for row in manifest["prior_object_bindings"]} == {
        row["id"] for row in prior
    }
    saved = tmp_path / "zero-adoption.dxf"
    export_objects(prior, saved, roi, 25.4, sha)
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )
    assert report["pass"], report
    assert report["targets"] == []
    assert len(report["prior_object_checks"]) == len(prior)
    assert all(row["pass"] for row in report["prior_object_checks"])
    return gray, roi, saved, evidence


def test_zero_adoption_preserves_saved_ordinary_mtext_contract(tmp_path):
    _saved_zero_adoption_mtext(tmp_path)


def test_zero_adoption_missing_receipt_cannot_hide_as_legacy_when_source_plan_remains(tmp_path):
    gray, roi, saved, evidence = _saved_zero_adoption_mtext(tmp_path)
    plan_path = evidence / "attached_strokes/plan.json"
    sidecar_path = saved.with_suffix(".objects.json")
    before = {path: path.read_bytes() for path in (saved, sidecar_path, plan_path)}
    (evidence / "attached_strokes/adoption.json").unlink()
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )
    assert {path: path.read_bytes() for path in before} == before
    assert report["targets"] == []
    assert not report["pass"], report
    assert any(not row["pass"] and row.get("reason") == "ATTACHED_STROKE_RECEIPT_MISSING_OR_INVALID"
               for row in report["checks"])


def _published_stage_declaration(saved, evidence, source_sha):
    """Use the actual publication envelope's source/file declaration fields.

    This is a cold-stage test, not a complete job-manager publication fixture.
    Every listed file and digest is real; no audit verdict is supplied.
    """
    sidecar = saved.with_suffix(".objects.json")
    return {
        "source_sha256": source_sha,
        "DXF_sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (saved, sidecar)},
        "evidence_files": {
            "evidence/" + path.relative_to(evidence).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(evidence.rglob("*.json"))
        },
        "commit_marker": saved.name,
        "DXF_is_published_last": True,
    }


@pytest.mark.parametrize("declaration", ["completed_assembly", "published_envelope"])
def test_zero_adoption_lost_stage_directory_is_rejected_when_execution_was_declared(tmp_path, declaration):
    gray, roi, saved, evidence = _saved_zero_adoption_mtext(tmp_path)
    stage = evidence / "attached_strokes"
    receipt = json.loads((stage / "adoption.json").read_text(encoding="utf-8"))
    if declaration == "completed_assembly":
        declaration_path = evidence / "completed_assembly.json"
        sidecar = json.loads(saved.with_suffix(".objects.json").read_text(encoding="utf-8"))
        # These are the actual completed-assembly fields consumed by this
        # cold stage, including the full real zero-adoption completion.
        save_json(declaration_path, {
            "objects": sidecar["objects"], "issues": [],
            "attached_stroke_completion": receipt,
        })
    else:
        declaration_path = saved.with_suffix(".export.json")
        save_json(declaration_path, _published_stage_declaration(saved, evidence, receipt["source_sha256"]))
    assert cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )["pass"]
    kept = (saved, saved.with_suffix(".objects.json"), declaration_path)
    before = {path: path.read_bytes() for path in kept}
    for name in ("adoption.json", "plan.json"):
        (stage / name).unlink()
    stage.rmdir()
    assert not stage.exists()
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )
    assert {path: path.read_bytes() for path in before} == before
    assert report["targets"] == []
    assert not report["pass"], report
    assert any(not row["pass"] and row.get("reason") == "ATTACHED_STROKE_RECEIPT_MISSING_OR_INVALID"
               for row in report["checks"])


def test_legacy_without_executed_attached_stage_retains_compatibility(tmp_path):
    gray = np.full((100, 100), 255, np.uint8)
    roi = [0, 0, 100, 100]
    prior = _mtext_prior_objects(27)
    sha = hashlib.sha256(gray.tobytes()).hexdigest()
    saved = tmp_path / "legacy.dxf"
    export_objects(prior, saved, roi, 25.4, sha)
    evidence = tmp_path / "evidence"
    # Actual old-style assembly/publication fields, with no declaration that
    # the later attached-stroke stage ran. Never call its completion here.
    save_json(evidence / "completed_assembly.json", {"objects": prior, "issues": []})
    save_json(saved.with_suffix(".export.json"), _published_stage_declaration(saved, evidence, sha))
    assert not (evidence / "attached_strokes").exists()
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )
    assert report["pass"], report
    assert report["targets"] == []
    assert report["checks"] == []


@pytest.mark.parametrize(("declaration", "invalid", "reason"), [
    ("completed_assembly", [], "ATTACHED_STROKE_COMPLETED_ASSEMBLY_DECLARATION_INVALID:"),
    ("published_envelope", {"evidence_files": []}, "ATTACHED_STROKE_PUBLISHED_EXPORT_DECLARATION_INVALID:"),
])
def test_zero_adoption_lost_stage_with_malformed_declaration_cannot_return_legacy_success(
        tmp_path, declaration, invalid, reason):
    gray, roi, saved, evidence = _saved_zero_adoption_mtext(tmp_path)
    stage = evidence / "attached_strokes"
    for name in ("adoption.json", "plan.json"):
        (stage / name).unlink()
    stage.rmdir()
    declaration_path = (evidence / "completed_assembly.json" if declaration == "completed_assembly"
                        else saved.with_suffix(".export.json"))
    save_json(declaration_path, invalid)
    kept = (saved, saved.with_suffix(".objects.json"))
    before = {path: path.read_bytes() for path in kept}
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )
    assert not stage.exists()
    assert {path: path.read_bytes() for path in before} == before
    assert report["targets"] == []
    assert not report["pass"], report
    assert any(not row["pass"] and row.get("reason", "").startswith(reason)
               for row in report["checks"])


@pytest.mark.parametrize("change", ["text", "flow_direction", "width"])
def test_zero_adoption_cold_audit_still_rejects_changed_mtext(tmp_path, change):
    gray, roi, saved, evidence = _saved_zero_adoption_mtext(tmp_path)
    doc = ezdxf.readfile(saved)
    note = doc.modelspace().query("MTEXT").first
    assert note.dxf.hasattr("flow_direction")
    if change == "text":
        note.text = note.text.replace("SAMPLE", "ALTERED", 1)
    elif change == "width":
        note.dxf.width += 1.0
    else:
        note.dxf.discard("flow_direction")
    if change == "flow_direction":
        # Deliberately bypass the production serializer, which itself rejects
        # this corruption, to exercise a cold reader of an external file.
        doc.saveas(saved)
        assert not ezdxf.readfile(saved).modelspace().query("MTEXT").first.dxf.hasattr("flow_direction")
    else:
        save_native_dxf(doc, saved)
    sidecar_path = saved.with_suffix(".objects.json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["dxf_sha256"] = hashlib.sha256(saved.read_bytes()).hexdigest()
    save_json(sidecar_path, sidecar)
    report = cold_attached_stroke_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 25.4, evidence
    )
    assert not report["pass"], report
    checks = {row["id"]: row for row in report["prior_object_checks"]}
    assert checks["synthetic-note"]["sidecar_matches_prior_source_and_geometry"]
    assert not checks["synthetic-note"]["actual_saved_geometry_and_all_members_match"]
    assert checks["synthetic-neighbor"]["pass"]


@pytest.mark.parametrize("encoding", ["line", "reversed_line", "segmented", "reversed_segmented"])
def test_existing_whole_native_stroke_blocks_rediscovery_in_any_direction_or_segmentation(encoding):
    source = np.full((50, 50), 255, np.uint8)
    cv2.line(source, (10, 20), (30, 20), 0, 1)
    row = {
        "stroke_id": "synthetic-discovery",
        "representation": {"points": [[10, 20], [30, 20]], "bulges": [0, 0], "closed": False},
        "source_path_px": [[x, 20] for x in range(10, 31)],
    }
    if encoding.endswith("line"):
        points = [[10, 20], [30, 20]]
        if encoding.startswith("reversed"):
            points.reverse()
        old = {"id": "synthetic-prior", "kind": "LINE",
               "geometry": {"start": points[0], "end": points[1]}}
    else:
        points = [[10, 20], [20, 20], [30, 20]]
        if encoding.startswith("reversed"):
            points.reverse()
        old = {"id": "synthetic-prior", "kind": "CONNECTION_PATH",
               "geometry": {"points": points, "bulges": [0] * len(points), "closed": False}}
    quarantine, adequate = attached._native_conflicts([row], [old], source)
    assert row["stroke_id"] in set(quarantine["quarantined_ids"]) | set(adequate)


@pytest.mark.parametrize("points", [[[10, 23], [30, 23]], [[20, 10], [20, 30]]])
def test_distinct_parallel_ink_and_true_point_crossing_are_not_native_length_duplicates(points):
    source = np.full((50, 50), 255, np.uint8)
    cv2.line(source, (10, 20), (30, 20), 0, 1)
    cv2.line(source, tuple(points[0]), tuple(points[1]), 0, 1)
    row = {
        "stroke_id": "synthetic-discovery",
        "representation": {"points": [[10, 20], [30, 20]], "bulges": [0, 0], "closed": False},
        "source_path_px": [[x, 20] for x in range(10, 31)],
    }
    old = {"id": "synthetic-prior", "kind": "LINE",
           "geometry": {"start": points[0], "end": points[1]}}
    quarantine, adequate = attached._native_conflicts([row], [old], source)
    assert quarantine["quarantined_ids"] == []
    assert adequate == []
