"""Short source ownership, genuine competing readings, and literal group layout."""

import hashlib
import json

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects import short_contact_partition as partitioner
from app.native_objects.short_contact_layout import plan_short_text_layout
from app.native_objects.short_contact_text import decide_short_contact_text, _original_word_graphic_bindings
from app.native_objects.short_contact_audit import _saved_owner_check, cold_short_contact_text_bindings
from app.native_objects.cad_io import export_objects, APPID
from app.native_objects.structure_contact_geometry import plan_structure_contact_geometry
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from app.native_objects.circular_markers import discover_circular_markers
from tests.test_native_structure_contact_geometry import _source, ROI


def _plan(tmp_path, gray=None, prior=None):
    if gray is None:
        gray,prior = _source()
    source_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    plan = plan_structure_contact_geometry(gray,ROI,prior)
    adopted = complete_text_contact_paths(gray,ROI,source_sha,prior,[plan],tmp_path/"text_contact")
    objects = prior+adopted["objects"]
    return gray,objects,adopted,partitioner.plan_short_contact_text(gray,ROI,objects,adopted)


def _carrier_attached_source(*, extra_return=False, two_groups=False):
    gray=np.full((280,400),255,np.uint8)
    cv2.circle(gray,(55,90),15,0,2)
    cv2.line(gray,(70,90),(180,70),0,2)
    cv2.line(gray,(180,70),(260,105),0,2)
    cv2.line(gray,(260,105),(260,225),0,2)
    cv2.putText(gray,"S",(242,219),cv2.FONT_HERSHEY_SIMPLEX,1.6,0,2)
    cv2.putText(gray,"3",(276,225),cv2.FONT_HERSHEY_SIMPLEX,1.1,0,1)
    start=120 if two_groups else 180
    cv2.line(gray,(start,225),(370,225),0,2)
    if two_groups:
        cv2.circle(gray,(55,140),15,0,2)
        cv2.line(gray,(70,140),(140,120),0,2)
        cv2.line(gray,(140,120),(196,150),0,2)
        cv2.line(gray,(196,150),(196,225),0,2)
        cv2.putText(gray,"S",(178,219),cv2.FONT_HERSHEY_SIMPLEX,1.6,0,2)
        cv2.putText(gray,"3",(212,219),cv2.FONT_HERSHEY_SIMPLEX,1.1,0,1)
    if extra_return:
        cv2.line(gray,(285,219),(285,225),0,1)
    prior=[{"id":"independent-receiver","kind":"LINE","layer":"GEOMETRY",
            "geometry":{"start":[start,225],"end":[370,225]}}]
    prior += [{"id":row["id"],"kind":"CIRCLE","layer":"CIRCULAR_MARKERS",
               "geometry":row["geometry"],"source_evidence":row["source_evidence"]}
              for row in discover_circular_markers(gray,ROI)["rows"] if row["geometry_accepted"]]
    return gray,prior


def test_complete_carrier_attached_glyph_keeps_free_ends_return_and_shared_bottom(tmp_path):
    gray,prior=_carrier_attached_source()
    unchanged=gray.copy()
    gray,objects,adopted,result=_plan(tmp_path,gray,prior)
    assert len(result["plans"])==1
    source=result["plans"][0]["source_partition"]
    assert result["plans"]==json.loads(json.dumps(result["plans"]))
    assert len(source["components"])==2
    component=source["components"][1]
    proof=component["carrier_contact_evidence"]
    assert proof["carrier_binding"]["id"]==prior[0]["id"]
    assert source["raw_context_finite_receiver_contacts"]
    assert source["raw_context_finite_receiver_contacts"][0]["path_ends_outside_complete_glyph_on_independent_receiver"]
    mask=partitioner._mask(component["source_runs_y_x0_x1"],component["bbox_xyxy_px"])
    for x,y in (proof["complete_side_body_skeleton_px"]+proof["complete_short_return_skeleton_px"]
                +component["carrier_shared_span_points_px"]+component["shared_core_points_px"]
                +component["original_free_endpoint_points_px"]):
        assert mask[int(y)-component["bbox_xyxy_px"][1],int(x)-component["bbox_xyxy_px"][0]]
        assert gray[int(y),int(x)]<128
    assert cv2.connectedComponents(mask.astype(np.uint8),8)[0]==2
    assert len(component["original_free_endpoint_points_px"])==2
    assert not proof["unassigned_intervening_source_branches"]
    assert np.array_equal(gray,unchanged)


def test_receiver_or_return_cannot_borrow_another_formal_objects_responsibility(tmp_path):
    gray,prior=_carrier_attached_source()
    _,objects,adopted,result=_plan(tmp_path,gray,prior)
    missing=[o for o in objects if o["id"]!=prior[0]["id"]]
    invalid=partitioner.plan_short_contact_text(gray,ROI,missing,adopted)
    assert not invalid["plans"]
    assert any(p["reason"]=="ACTUAL_FINITE_RECEIVER_BINDING_NOT_PROVEN" for p in invalid["pending"])
    component=result["plans"][0]["source_partition"]["components"][1]
    points=component["carrier_contact_evidence"]["complete_short_return_skeleton_px"]
    line={"id":"already-editable-short-return","kind":"LINE","layer":"GEOMETRY",
          "geometry":{"start":points[0],"end":points[-1]}}
    conflict=partitioner.plan_short_contact_text(gray,ROI,objects+[line],adopted)
    assert not conflict["plans"]
    assert any(p["reason"]=="COMPLETE_ADJACENT_CARRIER_GLYPH_UNRESOLVED_NO_PREFIX_ADOPTED" for p in conflict["pending"])


def test_multiple_original_returns_remain_ambiguous_instead_of_selecting_the_nearest(tmp_path):
    gray,prior=_carrier_attached_source(extra_return=True)
    _,_,_,result=_plan(tmp_path,gray,prior)
    assert not result["plans"]
    assert any(p.get("complete_return_candidates",0)>1 for p in result["pending"])


def test_neighbor_digit_is_not_copied_into_the_next_independent_source_group(tmp_path):
    gray,prior=_carrier_attached_source(two_groups=True)
    _,_,_,result=_plan(tmp_path,gray,prior)
    assert len(result["plans"])==2
    boxes=[]
    for row in result["plans"]:
        members=row["source_partition"]["components"]
        assert len(members)==2
        boxes.extend(tuple(member["bbox_xyxy_px"]) for member in members)
    assert len(set(boxes))==4


def test_complete_short_glyph_keeps_every_shared_original_core_and_its_path(tmp_path):
    gray,objects,adopted,result = _plan(tmp_path)
    assert len(result["plans"])==1
    source = result["plans"][0]["source_partition"]
    component = source["components"][0]
    mask = partitioner._mask(component["source_runs_y_x0_x1"],component["bbox_xyxy_px"])
    for x,y in component["source_skeleton_points_px"]:
        assert mask[y-component["bbox_xyxy_px"][1],x-component["bbox_xyxy_px"][0]]
        assert gray[y,x]<128
    assert component["original_free_endpoint_points_px"]
    assert component["shared_core_points_px"]
    assert source["raw_context_graphic_continuations"]
    assert all(c["source_continuity_both_sides"] for c in source["graphic_crossings"])
    assert adopted["objects"][0] in objects
    assert not result["original_source_pixels_modified"]


def test_no_adopted_independent_owner_cannot_be_replaced_with_a_crop_hint(tmp_path):
    gray,prior = _source()
    result = partitioner.plan_short_contact_text(gray,ROI,prior,{})
    assert result["plans"]==[] and result["adopted_path_bindings"]==[]


def test_existing_curved_native_neighbor_is_not_recovered_again_as_text():
    points = [[10,10],[11,11],[12,12],[13,12],[14,11],[15,10]]
    component = {"bbox_xyxy_px":[10,10,16,13],"source_skeleton_points_px":[],
                 "source_runs_y_x0_x1":[[10,10,11],[10,15,16],[11,11,12],[11,14,15],[12,12,14]]}
    obj = {"id":"already-editable-path","kind":"CONNECTION_PATH","geometry":{"points":points,"closed":False}}
    assert partitioner._covered_by_formal(component,[obj],set())==obj["id"]


def test_character_budget_never_licenses_a_prefix(tmp_path):
    gray,prior = _source()
    for x in (279,308,337,366):
        cv2.putText(gray,"3",(x,190),cv2.FONT_HERSHEY_SIMPLEX,1.1,0,2)
    _,_,_,result = _plan(tmp_path,gray,prior)
    assert not result["plans"]
    assert any(p["reason"]=="COMPLETE_SHORT_GROUP_EXCEEDS_CHARACTER_BUDGET_NO_PREFIX_ADOPTED" for p in result["pending"])


def _model(text):
    return {"raw_text":text,"model_mean_confidence":0.99,"minimum_emitted_character_confidence":0.99,
            "raw_CTC_tokens":[{"character":c,"score":0.99} for c in text]}


def _observations(source):
    box = source["components"][0]["bbox_xyxy_px"]
    glyph_box = [0,0,2*(box[2]-box[0]),2*(box[3]-box[1])]
    raw_box = source["raw_original_bbox_xyxy_px"]
    crop_box = [0,0,2*(raw_box[2]-raw_box[0]),2*(raw_box[3]-raw_box[1])]
    def view(text,box,confidence):
        return {"psm":7,"words":[{"text":text,"confidence":confidence,"bbox_xyxy_px":box}]}
    return {"original_group":{"tesseract":[view("$",crop_box,94)],"model":{"prediction":_model("$")}},
            "ownership_group":{"tesseract":[view("S",glyph_box,80)],"model":{"prediction":_model("S")}},
            "components":[{"tesseract":[view("S",glyph_box,70)],"model":{"prediction":_model("S")}}]}


def _group_observations(source):
    def view(text,box,confidence=94):
        return {"psm":7,"words":[{"text":text,"confidence":confidence,"bbox_xyxy_px":box}]}
    def size(box):
        return [0,0,2*(box[2]-box[0]),2*(box[3]-box[1])]
    return {
        "original_group":{"tesseract":[view("$3",size(source["raw_original_bbox_xyxy_px"]))],
                          "model":{"prediction":_model("$3")}},
        "ownership_group":{"tesseract":[view("S3",size(source["bbox_xyxy_px"]),80)],
                           "model":{"prediction":_model("S3")}},
        "components":[{"tesseract":[{**view(letter,size(component["bbox_xyxy_px"]),70),"psm":10}],
                       "model":{"prediction":_model(letter)}}
                      for letter,component in zip("S3",source["components"])],
    }


def test_original_raw_competitor_has_a_distinct_actual_finite_receiver_proof(tmp_path):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_group_observations(source)
    decision=decide_short_contact_text(source,raw)
    assert decision["accepted"] and decision["text"]=="S3"
    competitors=decision["raw_competing_readings"]
    assert competitors and all(r["raw_text"]=="$3" for r in competitors)
    assert all(r["original_TSV_word_bound_to_actual_finite_receiver"] for r in competitors)
    assert not any(r["source_path_continues_beyond_original_context"] for r in competitors)
    assert not any(r["original_TSV_reading_reaches_both_graphic_crop_edges"] for r in competitors)


def test_disputed_raw_word_cannot_borrow_the_digits_receiver_coverage(tmp_path):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_group_observations(source)
    whole=raw["original_group"]["tesseract"][0]["words"][0]["bbox_xyxy_px"]
    raw["original_group"]["tesseract"][0]["words"]=[
        {"text":"$","confidence":94,"bbox_xyxy_px":[0,0,60,whole[3]-24]},
        {"text":"3","confidence":94,"bbox_xyxy_px":[64,20,whole[2],whole[3]]}]
    decision=decide_short_contact_text(source,raw)
    assert not decision["accepted"]
    assert any(r.startswith("UNRESOLVED_STRONG_RAW_COMPETITOR") for r in decision["reasons"])


def test_empty_isolated_carrier_glyph_uses_only_unchanged_complete_word_literal(tmp_path):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_group_observations(source)
    raw["original_group"]["tesseract"].append({**raw["original_group"]["tesseract"][0],"psm":13})
    raw["ownership_group"]["tesseract"].append({**raw["ownership_group"]["tesseract"][0],"psm":13})
    raw["components"][1]["tesseract"][0]["words"]=[]
    decision=decide_short_contact_text(source,raw)
    assert decision["accepted"] and decision["text"]=="S3"
    proof=decision["components"][1]["complete_word_literal_corroboration"]
    assert proof["isolated_PSM10_was_empty"]
    assert len(proof["word_observations"])==4
    assert not proof["nonempty_isolated_reading_overridden"]
    assert decision["components"][1]["Tesseract_raw_texts"]==[]
    # A real competing suffix in even one complete raw word is not excused by
    # the first component's independently proved crossing stroke.
    raw["original_group"]["tesseract"][1]={"psm":13,"words":[{
        **raw["original_group"]["tesseract"][0]["words"][0],"text":"$8"}]}
    changed=decide_short_contact_text(source,raw)
    assert not changed["accepted"]
    assert changed["components"][1]["complete_word_literal_corroboration"] is None
    raw["original_group"]["tesseract"][1]["words"][0]["text"]="$3"
    box=source["components"][1]["bbox_xyxy_px"]
    raw["components"][1]["tesseract"][0]["words"]=[{
        "text":"8","confidence":75,"bbox_xyxy_px":[0,0,2*(box[2]-box[0]),2*(box[3]-box[1])]}]
    nonempty=decide_short_contact_text(source,raw)
    assert not nonempty["accepted"]
    assert nonempty["components"][1]["complete_word_literal_corroboration"] is None


def test_original_cropped_graphic_conflict_has_explicit_source_responsibility(tmp_path):
    *_,plan = _plan(tmp_path)
    source = plan["plans"][0]["source_partition"]
    decision = decide_short_contact_text(source,_observations(source))
    assert decision["accepted"] and decision["text"]=="S"
    assert all(c["source_responsibility_resolved"] for c in decision["raw_competing_readings"])
    assert all(c["original_TSV_reading_reaches_both_graphic_crop_edges"] for c in decision["raw_competing_readings"])
    assert not decision["OCR_transcriptions_rewritten"]


@pytest.mark.parametrize("competing",["B","R","8"])
def test_strong_ownership_view_competition_cannot_borrow_removed_graphic_excuse(tmp_path,competing):
    *_,plan = _plan(tmp_path)
    source = plan["plans"][0]["source_partition"]
    raw = _observations(source)
    raw["ownership_group"]["tesseract"][0]["words"][0].update(text=competing,confidence=97)
    decision = decide_short_contact_text(source,raw)
    assert not decision["accepted"]
    competitor = next(c for c in decision["raw_competing_readings"] if c["raw_text"]==competing)
    assert not competitor["source_responsibility_resolved"]
    assert competitor["disposition"]=="UNRESOLVED_STRONG_RAW_READING"


def test_original_strong_competitor_without_crop_edge_coverage_stays_pending(tmp_path):
    *_,plan = _plan(tmp_path)
    source = plan["plans"][0]["source_partition"]
    raw = _observations(source)
    raw["original_group"]["tesseract"][0]["words"][0]["bbox_xyxy_px"][1]+=6
    decision = decide_short_contact_text(source,raw)
    assert not decision["accepted"]
    assert all(not c["source_responsibility_resolved"] for c in decision["raw_competing_readings"])


def test_two_different_raw_words_cannot_union_their_crop_edges(tmp_path):
    *_,plan = _plan(tmp_path)
    source = plan["plans"][0]["source_partition"]
    original = _observations(source)["original_group"]
    box = original["tesseract"][0]["words"][0]["bbox_xyxy_px"]
    original["tesseract"][0]["words"] = [
        {"text":"$","confidence":95,"bbox_xyxy_px":[box[0],0,box[2],box[3]//2]},
        {"text":"3","confidence":95,"bbox_xyxy_px":[box[0],box[3]//2,box[2],box[3]]}]
    assert _original_word_graphic_bindings(source,original,"$3",[0])==[]


def test_raw_word_cannot_borrow_another_components_graphic_owner(tmp_path):
    *_,plan = _plan(tmp_path)
    source = plan["plans"][0]["source_partition"]
    source["raw_context_graphic_continuations"][0]["owner_id"]="a-different-path"
    decision = decide_short_contact_text(source,_observations(source))
    assert not decision["accepted"]
    assert all(not c["source_responsibility_resolved"] for c in decision["raw_competing_readings"])


def test_source_path_entering_and_leaving_same_side_is_not_crop_edge_continuation():
    owner = {"id":"same-side","geometry":{},"source_evidence":{"text_contact_path":{"path":{
        "source_path_px":[[9,10],[10,11],[10,12],[10,13],[9,14]],"contact_continuations":[]}}}}
    assert partitioner._graphic_crossings({"bbox_xyxy_px":[10,0,20,50]},[owner])==[]


def test_cold_owner_predicate_checks_actual_saved_polyline_not_only_metadata(tmp_path):
    _,objects,adopted,_ = _plan(tmp_path)
    target = adopted["objects"][0]
    path = tmp_path/"owners.dxf"
    export_objects(objects,path,ROI,200,"synthetic-source")
    metadata = json.loads(path.with_suffix(".objects.json").read_text())
    written = next(r for r in metadata["written"] if r["id"]==target["id"])
    doc = ezdxf.readfile(path)
    owner = doc.entitydb[written["handle"]]
    assert _saved_owner_check(owner,target,written,ROI,200)["pass"]
    owner.translate(1,0,0)
    doc.saveas(path)
    reopened = ezdxf.readfile(path)
    check = _saved_owner_check(reopened.entitydb[written["handle"]],target,written,ROI,200)
    assert not check["pass"] and not check["checks"]["vertices"]


def test_cold_short_stage_without_targets_does_not_take_over_legacy_metadata_failures(tmp_path):
    doc = ezdxf.new()
    path = tmp_path/"legacy.dxf"
    doc.saveas(path)
    report = cold_short_contact_text_bindings(path,doc,None,ROI,200,tmp_path)
    assert report["pass"] and report["checks"]==[]


@pytest.mark.parametrize("damaged",["missing_metadata","malformed_receipt"])
def test_marked_short_target_with_missing_or_malformed_evidence_reports_failure(tmp_path,damaged):
    doc = ezdxf.new()
    doc.appids.new(APPID)
    entity = doc.modelspace().add_text("X")
    entity.set_xdata(APPID,[(1000,json.dumps({"id":"marked-short","kind":"TEXT","short_contact_text":True}))])
    path = tmp_path/"short.dxf"
    doc.saveas(path)
    if damaged=="malformed_receipt":
        path.with_suffix(".objects.json").write_text(json.dumps({"objects":[],"written":[]}))
        (tmp_path/"short_contact_text").mkdir()
        (tmp_path/"short_contact_text/adoption.json").write_text("null")
    report = cold_short_contact_text_bindings(path,doc,None,ROI,200,tmp_path)
    assert not report["pass"] and report["targets"]==["marked-short"]
    assert "UNREADABLE" in report["checks"][0]["reason"]


def test_source_defined_short_group_uses_two_TEXT_members_when_one_changes_spacing():
    partition = {"bbox_xyxy_px":[30,30,72,56],"components":[
        {"bbox_xyxy_px":[30,30,53,56]},{"bbox_xyxy_px":[55,30,72,56]}]}
    layout = plan_short_text_layout("S3",partition,[0,0,120,100],200)
    assert layout["kind"]=="TEXT_GROUP"
    assert not layout["one_TEXT_attempt"]["checks"]["component_left_and_right_edges_match_source"]
    assert len(layout["geometry"]["text_members"])==2
    for member,component in zip(layout["members"],partition["components"]):
        assert np.allclose(member["actual_font_component_boxes"][0],component["bbox_xyxy_px"])
    assert layout["independent_paths_in_group"] is False
