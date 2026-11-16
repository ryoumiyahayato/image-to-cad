"""Local transaction tests. Source rendering is tested on the real project separately."""
from copy import deepcopy
import ezdxf
import pytest

import local_repair as repair
from reconnect import ReconnectProject, collect


@pytest.fixture
def project(tmp_path, monkeypatch):
    doc = ezdxf.new("R2010"); doc.units = 4
    target = doc.modelspace().add_text("L1", dxfattribs={"insert": (3, 4), "height": 2})
    other = doc.modelspace().add_text("USER_EDIT", dxfattribs={"insert": (12, 4), "color": 3})
    doc.modelspace().add_line((0, 0), (10, 7))
    path = tmp_path / "source.dxf"; doc.saveas(path)
    files, _ = collect(path)
    state = {"revision": 0, "current": "baseline", "project_uuid": "test", "source_snapshot": "source", "states": {"baseline": {"parent": None, "relations": {target.dxf.handle: {"status": "UNRESOLVED"}, other.dxf.handle: {"status": "USER_MODIFIED", "source_automatic_operations": False}}}}, "journal": [], "exports": {}, "accepted_external": []}
    p = ReconnectProject({}, state, {"baseline": files})
    # This synthetic seam is not evidence of source validation or real GUI use.
    monkeypatch.setattr(repair, "source_evidence", lambda p, uuid: {"source_uuid": uuid, "kind": "TEST_ONLY"})
    return p, target.dxf.handle, other.dxf.handle


def test_local_repair_preserves_other_relations_and_is_reversible(project):
    p, target, other = project
    before = deepcopy(p.state)
    report, files = repair.preview_repair(p, target, "region", "TL1")
    assert p.state == before
    assert repair.accept_repair(p, report, actor="TEST_ONLY")
    current = p.state["states"][p.state["current"]]
    assert current["relations"][other] == before["states"]["baseline"]["relations"][other]
    assert current["relations"][target]["historical_current_member_identity"] == "NOT_PROVEN"
    assert current["relations"][target]["confirmation"]["actor"] == "TEST_ONLY"
    assert p.state["accepted_external"] == []
    assert next(r for r in repair.current_texts(p) if r["handle"] == target)["content"]["text"] == "TL1"
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        repair.accept_repair(p, report, actor="TEST_ONLY")
    p.undo()
    assert p.payloads[p.state["current"]] == p.payloads["baseline"]
    assert p.state["states"][p.state["current"]]["relations"] == before["states"]["baseline"]["relations"]


def test_changed_source_evidence_does_not_mutate_current(project, monkeypatch):
    p, target, _ = project
    report, _ = repair.preview_repair(p, target, "region", "TL1")
    before = deepcopy(p.state)
    monkeypatch.setattr(repair, "source_evidence", lambda p, uuid: {"source_uuid": uuid, "kind": "CHANGED_TEST_EVIDENCE"})
    with pytest.raises(ValueError, match="INPUT_CHANGED"):
        repair.accept_repair(p, report, actor="TEST_ONLY")
    assert p.state == before


def test_unknown_member_noop_and_implicit_confirmation_are_rejected(project):
    p, target, _ = project
    before = deepcopy(p.state)
    with pytest.raises(ValueError, match="NO_TEXT_CHANGE"):
        repair.preview_repair(p, target, "region", "L1")
    with pytest.raises(ValueError, match="current modelspace TEXT"):
        repair.preview_repair(p, "unknown", "region", "TL1")
    report, _ = repair.preview_repair(p, target, "region", "TL1")
    with pytest.raises(ValueError, match="Explicit review actor"):
        repair.accept_repair(p, report, actor="AUTO")
    assert p.state == before
