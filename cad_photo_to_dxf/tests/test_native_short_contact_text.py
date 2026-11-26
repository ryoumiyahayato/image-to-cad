"""Short source ownership, genuine competing readings, and literal group layout."""

import hashlib
import json
from copy import deepcopy

import cv2
import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects import short_contact_partition as partitioner
from app.native_objects import short_contact_text as short_text
from app.native_objects.short_contact_layout import plan_short_text_layout
from app.native_objects.short_contact_text import decide_short_contact_text, _original_word_graphic_bindings
from app.native_objects.short_contact_audit import _saved_owner_check, cold_short_contact_text_bindings
from app.native_objects.cad_io import export_objects, APPID
from app.native_objects.structure_contact_geometry import plan_structure_contact_geometry
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from app.native_objects.circular_markers import discover_circular_markers
from tests.test_native_structure_contact_geometry import _source, ROI
from scripts.windows_native_smoke import short_contact_component_reobservation_context


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
            "components":[{"tesseract":[{**view("S",glyph_box,70),"psm":10}],"model":{"prediction":_model("S")}}]}


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


def _bounded_conflict_observations(source):
    raw=_group_observations(source)
    for domain in ("original_group","ownership_group"):
        raw[domain]["tesseract"].append({**deepcopy(raw[domain]["tesseract"][0]),"psm":13})
    primary=raw["components"][1]["tesseract"][0]
    primary["words"][0].update(text="J",confidence=47.0)
    extra=deepcopy(primary)
    extra["psm"]=13
    extra["words"][0].update(text="3",confidence=96.0)
    raw["components"][1]["tesseract"].append(extra)
    return raw


def test_fixed_component_view_preserves_nonempty_competitor_and_empty_fallback(tmp_path):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_bounded_conflict_observations(source)
    before=deepcopy(raw)
    decision=decide_short_contact_text(source,raw)
    assert decision["accepted"] and decision["text"]=="S3" and raw==before
    member=decision["components"][1]
    assert member["complete_word_literal_corroboration"] is None
    proof=member["bounded_component_reobservation"]
    assert proof["primary_nonempty_literal"]=="J" and proof["additional_literal"]=="3"
    assert not proof["prior_nonempty_reading_reclassified_as_empty"]
    assert not proof["independent_OCR_engine_claimed"]
    assert member["Tesseract_raw_texts"]==["J"]
    assert decision["component_raw_competing_readings"]==[{
        "component_index":1,"engine":"Tesseract","view":10,"raw_text":"J","word_confidence":47.0,
        "strong_raw_reading":False,"original_nonempty_observation_preserved":True,
        "resolved_by_fixed_additional_view":True,"prior_nonempty_reading_reclassified_as_empty":False}]


@pytest.mark.parametrize("fault", ["no-extra","empty-extra","weak-extra","different-extra","partial-extra","two-letter-extra",
    "strong-primary","missing-primary","duplicate-extra","foreign-carrier","foreign-path","unassigned-branch",
    "different-whole-word","weak-original-model","different-component-model","already-correct-primary"])
def test_component_reobservation_does_not_relax_real_conflicts_or_source_scope(tmp_path,fault):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=deepcopy(plan["plans"][0]["source_partition"])
    raw=_bounded_conflict_observations(source)
    views=raw["components"][1]["tesseract"]
    if fault=="no-extra":
        views.pop()
    elif fault=="empty-extra":
        views[1]["words"]=[]
    elif fault=="weak-extra":
        views[1]["words"][0]["confidence"]=84.99
    elif fault=="different-extra":
        views[1]["words"][0]["text"]="8"
    elif fault=="partial-extra":
        views[1]["words"][0]["bbox_xyxy_px"][1]+=3
    elif fault=="two-letter-extra":
        views[1]["words"][0]["text"]="33"
    elif fault=="strong-primary":
        views[0]["words"][0]["confidence"]=85
    elif fault=="missing-primary":
        views.pop(0)
    elif fault=="duplicate-extra":
        views.append(deepcopy(views[1]))
    elif fault=="foreign-carrier":
        source["components"][1]["carrier_contact_evidence"]["carrier_binding"]["id"]="other-carrier"
    elif fault=="foreign-path":
        source["components"][1]["carrier_contact_evidence"]["owner_path_id"]="other-path"
    elif fault=="unassigned-branch":
        source["components"][1]["carrier_contact_evidence"]["unassigned_intervening_source_branches"]=["branch"]
    elif fault=="different-whole-word":
        raw["original_group"]["tesseract"][1]["words"][0]["text"]="$8"
    elif fault=="weak-original-model":
        model=raw["original_group"]["model"]["prediction"]
        model["model_mean_confidence"]=model["minimum_emitted_character_confidence"]=0.97
        for token in model["raw_CTC_tokens"]:
            token["score"]=0.97
        assert short_text._model_integrity(model)
    elif fault=="different-component-model":
        raw["components"][1]["model"]["prediction"]=_model("8")
    elif fault=="already-correct-primary":
        views[0]["words"][0]["text"]="3"
    decision=decide_short_contact_text(source,raw)
    assert not decision["accepted"]
    if fault in {"strong-primary","missing-primary","foreign-carrier","foreign-path","unassigned-branch",
                 "different-whole-word","weak-original-model","different-component-model","already-correct-primary"}:
        assert short_contact_component_reobservation_context(source,raw,1,"3") is None


def test_collector_appends_only_one_fixed_view_and_keeps_primary_receipts(tmp_path,monkeypatch):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_bounded_conflict_observations(source)
    extra=raw["components"][1]["tesseract"].pop()
    for observation in raw["components"]:
        observation["tesseract"][0]["new_call"]=True
    before=deepcopy(raw)
    calls=[]
    expected_image,_=partitioner.recognition_view(gray,source,1)

    def observe(image,out,root,dpi,psm):
        assert np.array_equal(image,expected_image)
        assert dpi==200 and psm==13
        calls.append((out,root,psm))
        return {**deepcopy(extra),"new_call":True}

    monkeypatch.setattr(short_text,"_tesseract_view_observation",observe)
    short_text._append_fixed_component_observations(gray,source,raw,tmp_path,tmp_path,200)
    assert len(calls)==1
    assert raw["components"][1]["tesseract"][0]==before["components"][1]["tesseract"][0]
    assert raw["components"][0]==before["components"][0]
    assert raw["original_group"]==before["original_group"] and raw["ownership_group"]==before["ownership_group"]
    assert raw["components"][1]["model"]==before["components"][1]["model"]
    with pytest.raises(ValueError,match="ADDITIONAL_VIEW_ALREADY_PRESENT"):
        short_text._append_fixed_component_observations(gray,source,raw,tmp_path,tmp_path,200)
    assert len(calls)==1


def test_external_checker_derives_trigger_before_any_additional_answer(tmp_path):
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_bounded_conflict_observations(source)
    raw["components"][1]["tesseract"].pop()
    context=short_contact_component_reobservation_context(source,raw,1,"3")
    assert context==short_text._component_reobservation_context(source,raw,1,"3")
    assert context["primary_nonempty_literal"]=="J"
    assert context["owner_path_id"] in {row["owner_id"] for row in source["graphic_crossings"]}
    assert short_contact_component_reobservation_context(source,raw,0,"S") is None
    # The extra answer cannot retroactively supply the trigger's source proof.
    raw["components"][1]["tesseract"].append({"psm":13,"words":[]})
    assert short_contact_component_reobservation_context(source,raw,1,"3")==context


def _bound_synthetic_replay_evidence(tmp_path):
    """Controlled raw bytes exercise cold contracts, never real OCR accuracy."""
    gray,prior=_carrier_attached_source()
    _,_,_,plan=_plan(tmp_path,gray,prior)
    source=plan["plans"][0]["source_partition"]
    raw=_bounded_conflict_observations(source)

    def record_json(path,value):
        path.write_text(json.dumps(value),encoding="utf-8")
        return short_text._record(path,tmp_path)

    domains=[("original_group",None),("ownership_group",None)]+[("components",i) for i in range(2)]
    for domain,index in domains:
        observation=raw[domain] if index is None else raw[domain][index]
        image,_=partitioner.recognition_view(gray,source,index,original=domain=="original_group")
        directory=tmp_path/(domain if index is None else "component-"+str(index))
        directory.mkdir()
        observation["input_array_sha256"]=hashlib.sha256(image.tobytes()).hexdigest()
        repeated=np.repeat(np.repeat(image,2,axis=0),2,axis=1)
        for view in observation["tesseract"]:
            stem=directory/("x2-p"+str(view["psm"]))
            lines=["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"]
            for word in view["words"]:
                x0,y0,x1,y1=word["bbox_xyxy_px"]
                lines.append(f"5\t1\t1\t1\t1\t1\t{x0+12}\t{y0+12}\t{x1-x0}\t{y1-y0}\t{word['confidence']}\t{word['text']}")
            stem.with_suffix(".tsv").write_text("\n".join(lines)+"\n",encoding="utf-8")
            Image.fromarray(np.pad(repeated,12,constant_values=255)).save(stem.with_suffix(".png"))
            view.update(scale=2,padding_px=12,new_call=True,
                        raw_tsv=short_text._record(stem.with_suffix(".tsv"),tmp_path),
                        recognition_image=short_text._record(stem.with_suffix(".png"),tmp_path))
            metadata={"status":"COMPLETED","return_code":0,"tsv_sha256":view["raw_tsv"]["sha256"],
                "command_executed_for_this_request":True,
                "engine_identity":{"executable_sha256":"a"*64,"traineddata_sha256":"b"*64,"synthetic_test_only":True},
                "specification":{"psm":view["psm"],"recognition_dpi":400,
                    "crop_xyxy_px":[0,0,repeated.shape[1],repeated.shape[0]],
                    "crop_array_sha256":hashlib.sha256(repeated.tobytes()).hexdigest(),
                    "external_white_padding_px":12,"source_pixels_modified":False}}
            view["metadata"]=record_json(stem.with_suffix(".json"),metadata)
        model=observation["model"]
        model_input=np.pad(image,4,constant_values=255)
        _,tensor=short_text.independent.prepare_model_input(model_input)
        model["prediction"].update(input_array_sha256=hashlib.sha256(model_input.tobytes()).hexdigest(),
                                   model_tensor_sha256=hashlib.sha256(tensor.tobytes()).hexdigest())
        Image.fromarray(model_input).save(directory/"model.png")
        model["recognition_image"]=short_text._record(directory/"model.png",tmp_path)
        model["prediction_file"]=record_json(directory/"model.json",model["prediction"])
        model["identity"]=record_json(directory/"model_identity.json",{"model_sha256":short_text.independent.MODEL_SHA256})
    decision=decide_short_contact_text(source,raw)
    assert decision["accepted"]
    evidence={"schema":short_text.SCHEMA,"policy":deepcopy(short_text.POLICY),"producer":short_text._producer(),
        "source_array_sha256":hashlib.sha256(gray.tobytes()).hexdigest(),"roi_xyxy_px":list(ROI),
        "source_partition":source,"raw_observations":raw,"recognition_dpi":200,"decision":decision,
        "expected_text_provided":False,"raw_transcription_rewritten":False,
        "layout":plan_short_text_layout(decision["text"],source,ROI,200)}
    return gray,source,evidence


@pytest.mark.parametrize("damage,reason",[
    (None,None),
    ("png","TESSERACT_IMAGE_CHANGED"),
    ("tsv","RAW_TSV_WORDS_REWRITTEN"),
    ("metadata","FIXED_OCR_SPECIFICATION_CHANGED"),
    ("engine","REOBSERVATION_ENGINE_CHANGED"),
    ("engine-missing","COMPONENT_ENGINE_IDENTITY_MISSING"),
    ("unqualified-extra","FINITE_OCR_VIEW_PLAN_CHANGED"),
    ("duplicate-extra","FINITE_OCR_VIEW_PLAN_CHANGED"),
])
def test_cold_replay_rechecks_supplement_bytes_and_preexisting_eligibility(tmp_path,monkeypatch,damage,reason):
    gray,source,evidence=_bound_synthetic_replay_evidence(tmp_path)

    def forbidden(*args,**kwargs):
        pytest.fail("Cold short-contact verification may not execute recognition")

    monkeypatch.setattr(short_text.base,"_ocr",forbidden)
    monkeypatch.setattr(short_text.independent,"IndependentRecognizer",forbidden)
    raw=evidence["raw_observations"]
    extra=raw["components"][1]["tesseract"][1]
    if damage in {"png","tsv","metadata","engine","engine-missing"}:
        key={"png":"recognition_image","tsv":"raw_tsv","metadata":"metadata","engine":"metadata","engine-missing":"metadata"}[damage]
        path=tmp_path/extra[key]["path"]
        if damage=="png":
            with Image.open(path) as image:
                changed=np.asarray(image.convert("L")).copy()
            changed[12,12]=255-int(changed[12,12])
            Image.fromarray(changed).save(path)
        elif damage=="tsv":
            path.write_text(path.read_text(encoding="utf-8").replace("\t3\n","\t8\n"),encoding="utf-8")
        else:
            value=json.loads(path.read_text(encoding="utf-8"))
            if damage=="metadata":
                value["specification"]["recognition_dpi"]=401
            elif damage=="engine-missing":
                value["engine_identity"]=None
            else:
                value["engine_identity"]["traineddata_sha256"]="c"*64
            path.write_text(json.dumps(value),encoding="utf-8")
        # Updating the file receipt alone cannot legalize altered raw evidence.
        extra[key]=short_text._record(path,tmp_path)
    elif damage=="unqualified-extra":
        source["components"][1]["carrier_contact_evidence"]["owner_path_id"]="foreign-owner"
    elif damage=="duplicate-extra":
        raw["components"][1]["tesseract"].append(deepcopy(extra))
    result=short_text.replay_short_contact_evidence(gray,ROI,evidence,tmp_path,partition=source)
    assert result["new_OCR_calls"]==result["new_model_calls"]==0
    if damage is None:
        assert result["pass"],result
    else:
        assert not result["pass"] and reason in result["reason"],result


def test_fixed_short_view_measures_engine_bytes_without_enabling_raw_cache(tmp_path,monkeypatch):
    from app.native_objects import observation_cache
    from tests.test_native_observation_cache import _configured

    cache,engine,calls=_configured(tmp_path,monkeypatch)
    monkeypatch.delenv(observation_cache.ENVIRONMENT_VARIABLE)
    image=np.full((20,30),255,np.uint8)
    image[2:6,3:8]=0
    output=tmp_path/"no-cache-view"
    view=short_text._tesseract_view_observation(image,output,tmp_path,200,13)
    metadata_path=tmp_path/view["metadata"]["path"]
    metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["engine_identity"]==observation_cache.tesseract_identity(engine)
    assert view["new_call"] and len(calls)==1 and cache.snapshot()["entry_count"]==0
    assert "raw_observation_cache" not in metadata
    assert observation_cache.configured_cache() is None
    metadata["engine_identity"]=None
    metadata_path.write_text(json.dumps(metadata),encoding="utf-8")
    before=metadata_path.read_bytes()
    reused=short_text._tesseract_view_observation(image,output,tmp_path,200,13)
    assert not reused["new_call"] and reused["words"]==view["words"]
    assert len(calls)==1 and metadata_path.read_bytes()==before


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
