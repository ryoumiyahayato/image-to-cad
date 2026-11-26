"""Saved independent crossing strokes preserve staged source responsibility."""

from copy import deepcopy
import hashlib
import json

import ezdxf
import pytest

from app.native_objects.cad_io import export_objects, save_native_dxf
from app.native_objects.contracts import save_json
from app.native_objects.pipeline import _finalize_circle_relations
from app.native_objects.text_contact_adoption import (
    complete_text_contact_paths,
    merge_contact_completions,
)
from app.native_objects.text_contact_audit import cold_text_contact_bindings
from app.native_objects.transverse_stroke_geometry import plan_transverse_stroke_geometry
from tests.test_native_transverse_stroke_geometry import ROI, _source, _structure_stage


def _adopt_saved(tmp_path):
    gray = _source()
    context, prior, first_plan = _structure_stage(gray)
    sha = hashlib.sha256(gray.tobytes()).hexdigest()
    evidence = tmp_path / "evidence"
    first = complete_text_contact_paths(
        gray, ROI, sha, prior, [first_plan], evidence / "text_contact"
    )
    assert len(first["objects"]) == 1, first["decisions"]
    active = [obj for obj in prior if obj["id"] not in first["retired_ids"]] + first["objects"]
    next_plan = plan_transverse_stroke_geometry(gray, ROI, active, source_graph=context)
    second = complete_text_contact_paths(
        gray, ROI, sha, active, [next_plan], evidence / "transverse_strokes"
    )
    assert len(second["objects"]) == 3, second["decisions"]
    assert not second["retired_ids"]
    combined = merge_contact_completions(first, second, evidence / "text_contact")
    active += second["objects"]
    circles = {"objects": [deepcopy(obj) for obj in prior if obj["kind"] == "CIRCLE"],
               "uncertainties": [], "decisions": [], "summary": {}}
    active, _ = _finalize_circle_relations(gray, ROI, active, circles, evidence / "circular_markers")
    saved = tmp_path / "result.dxf"
    export_objects(active, saved, ROI, 200, sha)
    report = cold_text_contact_bindings(saved, ezdxf.readfile(saved), gray, ROI, 200, evidence)
    assert report["pass"], report
    return gray, saved, first, second, combined


def test_actual_staged_adoption_saves_three_complete_independent_LINES(tmp_path):
    _, saved, first, second, combined = _adopt_saved(tmp_path)
    doc = ezdxf.readfile(saved)
    entities = {json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)["id"]: entity
                for entity in doc.modelspace() if entity.dxf.layer != "REVIEW"}
    assert len(combined["adoption_stages"]) == 2
    assert all(entities[obj["id"]].dxftype() == "LINE" for obj in second["objects"])
    assert entities[first["objects"][0]["id"]].dxftype() == "LWPOLYLINE"


@pytest.mark.parametrize("tamper", ["missing_preceding_owner", "change_stage_context", "truncate_line"])
def test_cold_staged_check_rejects_lost_owner_context_or_shortened_saved_stroke(tmp_path, tamper):
    gray, saved, first, second, combined = _adopt_saved(tmp_path)
    manifest = tmp_path / "evidence/text_contact/adoption.json"
    doc = ezdxf.readfile(saved)
    if tamper == "change_stage_context":
        combined["adoption_stages"][1]["prior_object_bindings"] = deepcopy(
            combined["adoption_stages"][0]["prior_object_bindings"]
        )
        save_json(manifest, combined)
    else:
        wanted = first["objects"][0]["id"] if tamper == "missing_preceding_owner" else second["objects"][0]["id"]
        entity = next(entity for entity in doc.modelspace()
                      if json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)["id"] == wanted)
        if tamper == "missing_preceding_owner":
            doc.modelspace().delete_entity(entity)
        else:
            entity.dxf.end = entity.dxf.start.lerp(entity.dxf.end, 0.5)
        save_native_dxf(doc, saved)
        sidecar = saved.with_suffix(".objects.json")
        metadata = json.loads(sidecar.read_text())
        metadata["dxf_sha256"] = hashlib.sha256(saved.read_bytes()).hexdigest()
        save_json(sidecar, metadata)
    report = cold_text_contact_bindings(saved, ezdxf.readfile(saved), gray, ROI, 200, tmp_path / "evidence")
    assert not report["pass"]


def test_merge_refuses_a_stage_that_did_not_see_the_preceding_complete_path(tmp_path):
    _, _, first, second, _ = _adopt_saved(tmp_path)
    invalid = deepcopy(second)
    invalid["prior_object_bindings"] = deepcopy(first["prior_object_bindings"])
    with pytest.raises(ValueError, match="CONTEXT_CHAIN_INVALID"):
        merge_contact_completions(first, invalid, tmp_path / "invalid")
