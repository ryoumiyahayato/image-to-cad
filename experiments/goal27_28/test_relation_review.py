"""Synthetic relation transitions; real source/open/GUI are separate checks."""
from copy import deepcopy
import ezdxf
import pytest

from reconnect import ReconnectProject, collect
from relation_review import EXPLICIT, PENDING, resolve_confirmation
import local_repair


@pytest.fixture
def sample(tmp_path):
    doc = ezdxf.new("R2010"); doc.units = 4
    target = doc.modelspace().add_text("TL1", dxfattribs={"height": 2})
    other = doc.modelspace().add_text("KEEP", dxfattribs={"height": 2, "insert": (30, 0)})
    p0 = tmp_path / "before.dxf"; doc.saveas(p0)
    relation = {"status": EXPLICIT, "source_evidence": {"source_uuid": "test-region", "kind": "TEST_ONLY"}, "confirmation": {"actor": "TEST_ONLY", "explicit": True}, "source_automatic_operations": False}
    state = {"revision": 0, "current": "confirmed", "project_uuid": "test", "states": {"confirmed": {"parent": None, "relations": {target.dxf.handle: relation, other.dxf.handle: {"status": "UNRESOLVED"}}}}, "journal": [], "exports": {}, "accepted_external": []}
    project = ReconnectProject({}, state, {"confirmed": collect(p0)[0]})
    return project, doc, target, other, p0


def external_save(doc, path, label):
    doc.header["$LASTSAVEDBY"] = label
    doc.saveas(path)
    return path


def test_confirmed_relation_downgrades_with_prompt_and_no_repeat(sample, tmp_path):
    p, doc, target, _, p0 = sample
    old = deepcopy(p.state["states"]["confirmed"]["relations"][target.dxf.handle])
    p1 = external_save(doc, tmp_path / "first.dxf", "editor1")
    preview = p.preview(p0, p1)
    assert preview["content_confirmation_items"] == 0
    assert preview["relation_confirmation_items"] == preview["confirmation_items"] == 1
    assert preview["relation_changes"][0]["before_status"] == EXPLICIT
    p.accept(preview, actor="TEST_ONLY")
    relation = p.state["states"][p.state["current"]]["relations"][target.dxf.handle]
    assert relation["status"] == PENDING
    assert "source_evidence" not in relation and "permitted_source_operation" not in relation
    assert not relation["source_automatic_operations"]
    assert resolve_confirmation(p, relation["prior_confirmations"][0]) == old
    p2 = external_save(doc, tmp_path / "second.dxf", "editor2")
    preview2 = p.preview(p1, p2)
    assert preview2["relation_changes"] == []
    assert preview2["confirmation_items"] == 0
    p.accept(preview2, actor="TEST_ONLY")
    assert p.state["states"][p.state["current"]]["relations"][target.dxf.handle]["prior_confirmations"] == relation["prior_confirmations"]
    p.undo(); p.undo()
    assert p.state["current"] == "confirmed"
    assert p.state["states"]["confirmed"]["relations"][target.dxf.handle] == old


def test_copy_keeps_multiple_candidates_without_choosing_original(sample, tmp_path):
    p, doc, target, _, p0 = sample
    copy = target.copy(); doc.modelspace().add_entity(copy)
    p1 = external_save(doc, tmp_path / "copied.dxf", "copy")
    preview = p.preview(p0, p1)
    assert set(preview["relation_changes"][0]["after_candidates"]) == {target.dxf.handle, copy.dxf.handle}
    p.accept(preview, actor="TEST_ONLY")
    relations = p.state["states"][p.state["current"]]["relations"]
    for handle in (target.dxf.handle, copy.dxf.handle):
        assert relations[handle]["status"] == PENDING
        assert relations[handle]["prior_confirmations"] == [{"state": "confirmed", "member": target.dxf.handle}]
        assert relations[handle]["historical_current_member_identity"] == "NOT_PROVEN"
    p2 = external_save(doc, tmp_path / "same-copies.dxf", "copy-again")
    assert p.preview(p1, p2)["relation_confirmation_items"] == 0


def test_missing_candidate_retains_trace_through_another_local_repair(sample, tmp_path, monkeypatch):
    p, doc, target, other, p0 = sample
    handle = target.dxf.handle
    doc.modelspace().delete_entity(target)
    p1 = external_save(doc, tmp_path / "deleted.dxf", "delete")
    preview = p.preview(p0, p1)
    change = preview["relation_changes"][0]
    assert change["after_candidates"] == [] and change["after_status"] == "NO_CURRENT_CANDIDATE"
    p.accept(preview, actor="TEST_ONLY")
    unresolved = deepcopy(p.state["states"][p.state["current"]]["unresolved_relation_refs"])
    assert unresolved[0]["reference"] == {"state": "confirmed", "member": handle}
    assert resolve_confirmation(p, unresolved[0]["reference"])["confirmation"]["actor"] == "TEST_ONLY"
    monkeypatch.setattr(local_repair, "source_evidence", lambda p, uid: {"source_uuid": uid, "kind": "TEST_ONLY"})
    local, _ = local_repair.preview_repair(p, other.dxf.handle, "other-region", "KEEP2")
    local_repair.accept_repair(p, local, actor="TEST_ONLY")
    assert p.state["states"][p.state["current"]]["unresolved_relation_refs"] == unresolved


def test_pending_content_change_is_a_new_relation_review_item(sample, tmp_path):
    p, doc, target, _, p0 = sample
    p1 = external_save(doc, tmp_path / "first.dxf", "first")
    p.accept(p.preview(p0, p1), actor="TEST_ONLY")
    target.dxf.text = "TL2"
    p2 = external_save(doc, tmp_path / "changed.dxf", "changed")
    preview = p.preview(p1, p2)
    assert preview["content_confirmation_items"] == 1
    assert preview["relation_confirmation_items"] == 1
    assert preview["relation_changes"][0]["before_status"] == PENDING
