"""Actual saved contact paths keep an independently bound receiving object."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects.cad_io import export_objects, save_native_dxf
from app.native_objects.circular_markers import discover_circular_markers
from app.native_objects.contracts import save_json
from app.native_objects.pipeline import _finalize_circle_relations
from app.native_objects.structure_contact_geometry import plan_structure_contact_geometry
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from app.native_objects.text_contact_audit import (
    _saved_structural_endpoint_contacts,
    cold_text_contact_bindings,
)
from scripts.windows_native_smoke import create_structure_contact_fixture


@pytest.fixture
def source_plan(tmp_path):
    source = tmp_path / "source.png"
    font = Path(__file__).parents[1] / "resources/fonts/DejaVuSans.ttf"
    create_structure_contact_fixture(source, font)
    gray = np.asarray(Image.open(source).convert("L"))
    roi = [0, 0, gray.shape[1], gray.shape[0]]
    prior = [{
        "id": "independent-receiver", "kind": "LINE", "layer": "GEOMETRY",
        "geometry": {"start": [300.0, 330.0], "end": [580.0, 330.0]},
    }, {
        "id": "separate-gap-receiver", "kind": "LINE", "layer": "GEOMETRY",
        "geometry": {"start": [390.0, 80.0], "end": [471.0, 80.0]},
    }]
    prior += [{
        "id": row["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
        "geometry": deepcopy(row["geometry"]),
        "bbox_xyxy_px": deepcopy(row["bbox_xyxy_px"]),
        "source_evidence": {**deepcopy(row["source_evidence"]), "components_complete": False},
    } for row in discover_circular_markers(gray, roi)["rows"] if row["geometry_accepted"]]
    before = deepcopy(prior)
    plan = plan_structure_contact_geometry(gray, roi, prior)
    assert prior == before
    paths = [row for row in plan["paths"] if row["path_role"] == "ROUND_TO_CARRIER"]
    assert len(paths) == 1
    assert paths[0]["required_carrier_id"] == "independent-receiver"
    return gray, roi, prior, plan, hashlib.sha256(source.read_bytes()).hexdigest()


def _adopt_and_save(tmp_path, fixture, *, finalize=True):
    gray, roi, prior, plan, sha = fixture
    evidence = tmp_path / "evidence"
    result = complete_text_contact_paths(
        gray, roi, sha, prior, [plan], evidence / "text_contact"
    )
    assert len(result["objects"]) == 1, result["decisions"]
    assert not result["retired_ids"]
    saved = tmp_path / "result.dxf"
    active = prior + result["objects"]
    if finalize:
        circles = {
            "objects": [deepcopy(obj) for obj in prior if obj["kind"] == "CIRCLE"],
            "uncertainties": [], "decisions": [], "summary": {},
        }
        active, _ = _finalize_circle_relations(
            gray, roi, active, circles, evidence / "circular_markers"
        )
    export_objects(active, saved, roi, 200, sha)
    report = cold_text_contact_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 200, evidence
    )
    if finalize:
        assert report["pass"], report
    return saved, result


def _resave_with_current_transport_hash(path, document):
    save_native_dxf(document, path)
    sidecar = path.with_suffix(".objects.json")
    data = json.loads(sidecar.read_text())
    data["dxf_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    save_json(sidecar, data)


def test_unresolved_touching_character_does_not_block_complete_independent_path(
    tmp_path, source_plan
):
    saved, result = _adopt_and_save(tmp_path, source_plan)
    document = ezdxf.readfile(saved)
    formal = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    assert sum(entity.dxftype() == "LWPOLYLINE" for entity in formal) == 1
    assert sum(entity.dxftype() == "LINE" for entity in formal) == 2
    assert not any(entity.dxftype() in ("TEXT", "MTEXT") for entity in formal)
    observed = result["objects"][0]["source_evidence"]["text_contact_path"]["path"]
    assert len(observed["contact_continuations"]) >= 2
    assert observed["reverse_source_path_agreement"]["pass"]
    gray = source_plan[0]
    assert np.all(gray[78:83, 472:474] == 255)
    assert result["new_complete_text_labels"] == 0


def test_valid_starting_circle_does_not_license_an_unclosed_saved_path(tmp_path, source_plan):
    saved, _ = _adopt_and_save(tmp_path, source_plan, finalize=False)
    gray, roi, _, _, _ = source_plan
    audit = cold_text_contact_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 200, tmp_path / "evidence"
    )
    rows = [row for row in audit["checks"] if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE"]
    assert len(rows) == 1 and not audit["pass"]
    assert rows[0]["checks"]["actual_starting_circle_geometry_preserved"]
    assert not rows[0]["checks"]["actual_start_contacts_required_circle"]
    assert rows[0]["checks"]["actual_end_contacts_required_finite_carrier"]


def test_saved_receiving_block_uses_bound_member_not_the_nearest_member():
    document = ezdxf.new()
    space = document.modelspace()
    target = space.add_line((10, 390), (30, 390))
    circle = space.add_circle((10, 395), 5)
    block = document.blocks.new("separate-receiving-lines")
    block.add_line((31, 380), (31, 400))
    block.add_line((30, 380), (30, 400))
    carrier = space.add_blockref(block.name, (0, 0))
    right = _saved_structural_endpoint_contacts(
        target, {"kind": "LINE", "geometry": {}}, circle, carrier, [0, 0, 400, 400], 25.4,
        carrier_member_index=1,
    )
    assert right["actual_start_contacts_required_circle"]
    assert right["actual_end_contacts_required_finite_carrier"]
    wrong = _saved_structural_endpoint_contacts(
        target, {"kind": "LINE", "geometry": {}}, circle, carrier, [0, 0, 400, 400], 25.4,
        carrier_member_index=0,
    )
    assert not wrong["actual_end_contacts_required_finite_carrier"]
    assert wrong["receiving_finite_line_residual_px"] == 1


def test_prior_receiving_geometry_cannot_be_replaced_by_an_unbound_claim(
    tmp_path, source_plan
):
    gray, roi, prior, plan, sha = source_plan
    changed = deepcopy(prior)
    changed[0]["geometry"]["end"][1] += 3.0
    result = complete_text_contact_paths(
        gray, roi, sha, changed, [plan], tmp_path / "evidence/text_contact"
    )
    assert not result["objects"] and not result["retired_ids"]
    assert result["decisions"][0]["decision"] == "PENDING_INVALID_SOURCE_PLAN"


@pytest.mark.parametrize("change", ["remove_receiver", "shorten_target"])
def test_cold_read_checks_actual_complete_path_and_actual_separate_receiver(
    tmp_path, source_plan, change
):
    saved, _ = _adopt_and_save(tmp_path, source_plan)
    document = ezdxf.readfile(saved)
    if change == "remove_receiver":
        document.modelspace().delete_entity(document.modelspace().query("LINE")[0])
    else:
        target = next(entity for entity in document.modelspace().query("LWPOLYLINE")
                      if entity.dxf.layer != "REVIEW")
        vertices = list(target.get_points())
        vertices[-1] = tuple([vertices[-1][0], vertices[-1][1] + 2.0, *vertices[-1][2:]])
        target.set_points(vertices)
    _resave_with_current_transport_hash(saved, document)
    gray, roi, _, _, _ = source_plan
    audit = cold_text_contact_bindings(
        saved, ezdxf.readfile(saved), gray, roi, 200, tmp_path / "evidence"
    )
    assert not audit["pass"]
    path_checks = [row for row in audit["checks"] if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE"]
    assert any(not row["pass"] for row in path_checks)
