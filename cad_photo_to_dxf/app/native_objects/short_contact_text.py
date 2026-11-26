"""One bounded ordinary completion pass for source-supported short contact text.

Recognition sees both the untouched source and a separately recorded ownership
view.  A complete component PSM 10 reading corroborates each literal character
of a strict whole-group model observation.  Original competing readings never
disappear: continuing graphic ink cannot acquire invented character endpoints
at a crop edge.  Geometry, raw observations, decisions and layout are replayed
independently by the saved-file audit.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image

from . import independent_recognizer as independent
from . import text_regions as base
from .circle_character_recognition import _model_integrity, _raw_tsv_integrity
from .contracts import save_json
from .execution import check_cancel
from . import short_contact_partition as partitioner
from .short_contact_partition import recognition_view
from . import short_contact_layout as layouts


FIELD = "short_contact_text"
SCHEMA = "native-short-contact-text-evidence-v1"
ADOPTION_SCHEMA = "native-short-contact-text-adoption-v1"
POLICY = {
    "version": "complete-short-contact-components-raw-literal-v1",
    "whole_group_model_mean_confidence": 0.98,
    "whole_group_model_minimum_character_confidence": 0.95,
    "whole_group_model_rule_unchanged_from_complete_single_line": True,
    "Tesseract_component_PSM": 10,
    "Tesseract_context_PSMs": [7, 13],
    "Tesseract_scale": 2,
    "Tesseract_external_white_padding_px": 12,
    "PP_external_white_padding_px": 4,
    "Tesseract_component_bbox_tolerance_px": 1.0,
    "Tesseract_word_score": "recorded_advisory_aggregate_not_character_veto",
    "adoption_basis": "complete_source_components_and_strict_whole_group_model_with_literal_component_corroboration",
    "all_raw_competing_readings_retained": True,
    "unbounded_graphic_cannot_become_a_finite_glyph_at_crop_edges": True,
    "shared_source_ink_can_have_separate_editing_responsibilities": True,
    "new_targets_are_not_character_references": True,
    "source_or_recognition_pixels_invented": False,
    "completion_passes": 1,
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _producer():
    return {"module":__name__,"sha256":_sha(__file__),
            "partition_sha256":_sha(partitioner.__file__),"layout_sha256":_sha(layouts.__file__),
            "ocr_sha256":_sha(base.__file__),"model_sha256":_sha(independent.__file__)}


def _record(path, root):
    path, root = Path(path),Path(root)
    return {"path":path.resolve().relative_to(root.resolve()).as_posix(),
            "bytes":path.stat().st_size,"sha256":_sha(path)}


def _read(root, record):
    root = Path(root).resolve()
    path = root / record["path"]
    if (not path.resolve().is_relative_to(root) or path.is_symlink()
            or path.stat().st_size != record["bytes"] or _sha(path)!=record["sha256"]):
        raise ValueError("SHORT_CONTACT_BOUND_EVIDENCE_BYTES_CHANGED")
    return path.read_bytes()


def _words(raw, width, height, psm):
    if not _raw_tsv_integrity(raw):
        raise ValueError("SHORT_CONTACT_RAW_TSV_INTEGRITY_FAILED")
    pad = POLICY["Tesseract_external_white_padding_px"]
    rows = base._parse_tsv(raw.decode("utf-8"),[-pad,-pad,width-pad,height-pad],"short-component",psm)
    return [{key:row[key] for key in ("text","confidence","bbox_xyxy_px")} for row in rows]


def _view_observations(image, out, root, dpi, recognizer, psms):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    result = {"input_array_sha256":base.source_array_sha256(image),"tesseract":[],"model":None}
    scale,pad = POLICY["Tesseract_scale"],POLICY["Tesseract_external_white_padding_px"]
    repeated = np.repeat(np.repeat(image,scale,axis=0),scale,axis=1)
    for psm in psms:
        name = "x2-p"+str(psm)
        _, metadata = base._ocr(repeated,[0,0,repeated.shape[1],repeated.shape[0]],psm,
                                out,name,None,padding_px=pad,dpi=int(dpi)*scale)
        raw = (out/(name+".tsv")).read_bytes()
        result["tesseract"].append({"psm":psm,"scale":scale,"padding_px":pad,
            "raw_tsv":_record(out/(name+".tsv"),root),
            "recognition_image":_record(out/(name+".png"),root),
            "metadata":_record(out/(name+".json"),root),
            "words":_words(raw,repeated.shape[1],repeated.shape[0],psm),
            "new_call":bool(metadata.get("command_executed_for_this_request"))})
    model_image = np.pad(image,POLICY["PP_external_white_padding_px"],constant_values=255)
    model_files = [out/name for name in ("model.png","model.json","model_identity.json")]
    reused = False
    if all(path.is_file() for path in model_files):
        prediction = json.loads(model_files[1].read_text())
        identity = json.loads(model_files[2].read_text())
        _,tensor = independent.prepare_model_input(model_image)
        if (identity.get("model_sha256")!=recognizer.identity.get("model_sha256")
                or identity.get("policy")!=recognizer.identity.get("policy")
                or not _model_integrity(prediction)
                or prediction.get("model_tensor_sha256")!=hashlib.sha256(tensor.tobytes()).hexdigest()
                or not np.array_equal(np.asarray(Image.open(model_files[0]).convert("L")),model_image)):
            raise ValueError("SHORT_CONTACT_EXISTING_RAW_MODEL_OBSERVATION_DIFFERS")
        reused = True
    else:
        prediction = recognizer.recognize(model_image)
        Image.fromarray(model_image).save(out/"model.png")
        save_json(out/"model.json",prediction)
        save_json(out/"model_identity.json",recognizer.identity)
    result["model"] = {"prediction":prediction,"prediction_file":_record(out/"model.json",root),
                       "recognition_image":_record(out/"model.png",root),
                       "identity":_record(out/"model_identity.json",root),
                       "observation_receipt":({"same_raw_observation_reused":True,"model_inference_executed_for_this_request":False}
                           if reused else deepcopy(getattr(recognizer,"last_observation",{})))}
    return result


def _strong_model(observation):
    return (_model_integrity(observation) and bool(observation.get("raw_CTC_tokens"))
            and observation["model_mean_confidence"]>=POLICY["whole_group_model_mean_confidence"]
            and observation["minimum_emitted_character_confidence"]>=POLICY["whole_group_model_minimum_character_confidence"])


def _original_word_graphic_bindings(partition, observation, value, differing):
    """Bind each disputed literal to its own raw word and continuing owner.

    Opposite crop edges from unrelated words or another nearby path cannot
    supply a missing endpoint for the disputed component.
    """
    box = partition["raw_original_bbox_xyxy_px"]
    scale = POLICY["Tesseract_scale"]
    height = scale * (box[3] - box[1])
    bindings = []
    for component_index in differing:
        component = partition["components"][component_index]
        owner_ids = set(component.get("independent_path_owner_ids", []))
        shared = {tuple(p) for p in component["shared_core_points_px"]}
        found = None
        for view in observation["tesseract"]:
            words = view["words"]
            if "".join(w["text"] for w in words) != value:
                continue
            offset = 0
            for word_index, word in enumerate(words):
                start, stop = offset, offset + len(word["text"])
                offset = stop
                if not start <= component_index < stop:
                    continue
                word_box = word["bbox_xyxy_px"]
                if word_box[1] > scale or word_box[3] < height - scale:
                    continue
                for crossing in partition.get("raw_context_graphic_continuations", []):
                    if (crossing["owner_id"] not in owner_ids
                            or not crossing.get("single_contiguous_source_visit")
                            or crossing.get("source_box_crossed_sides") not in
                                (["TOP", "BOTTOM"], ["BOTTOM", "TOP"])
                            or not shared.intersection(map(tuple, crossing.get("shared_core_points_used", [])))):
                        continue
                    edge_points = [crossing["first_original_point_inside"],
                                   crossing["last_original_point_inside"]]
                    if not all(word_box[0] - scale <= scale * (p[0] - box[0]) <= word_box[2] + scale
                               for p in edge_points):
                        continue
                    found = {"component_index":component_index,"word_index":word_index,
                             "word_literal":word["text"],"literal_index_in_word":component_index-start,
                             "word_bbox_xyxy_in_scaled_original_crop":word_box,
                             "Tesseract_PSM":view["psm"],"owner_id":crossing["owner_id"],
                             "source_box_crossed_sides":crossing["source_box_crossed_sides"],
                             "original_point_before_crop":crossing["original_point_before_glyph"],
                             "original_point_after_crop":crossing["original_point_after_glyph"],
                             "recorded_shared_core_points":crossing["shared_core_points_used"],
                             "same_word_same_component_same_source_owner":True}
                    break
                if found:
                    break
            if found:
                break
        if found is None:
            return []
        bindings.append(found)
    return bindings


def decide_short_contact_text(partition, raw):
    """Decide literal content from complete components; never a supplied name."""
    reasons, component_records, competitors = [],[],[]
    components = partition["components"]
    model = raw["ownership_group"]["model"]["prediction"]
    text = model.get("raw_text","")
    if not _strong_model(model):
        reasons.append("STRICT_WHOLE_GROUP_MODEL_CHARACTER_GATE_NOT_MET")
    if len(text)!=len(components) or not text or any(not c.isprintable() or c.isspace() for c in text):
        reasons.append("WHOLE_RAW_LITERAL_DOES_NOT_COVER_EVERY_SOURCE_COMPONENT")
    if len(raw["components"])!=len(components):
        reasons.append("COMPLETE_COMPONENT_RECOGNITION_RECORD_MISSING")
    for i,(component,observation) in enumerate(zip(components,raw["components"])):
        expected = text[i] if i<len(text) else None
        box = component["bbox_xyxy_px"]
        size = [0,0,2*(box[2]-box[0]),2*(box[3]-box[1])]
        words = observation["tesseract"][0]["words"]
        complete = (len(words)==1 and len(words[0]["text"])==1
                    and max(abs(a-b) for a,b in zip(words[0]["bbox_xyxy_px"],size))
                        <=2*POLICY["Tesseract_component_bbox_tolerance_px"])
        corroborated = complete and words[0]["text"]==expected
        pm = observation["model"]["prediction"]
        model_conflict = (_strong_model(pm) and pm.get("raw_text")!=expected)
        if not corroborated:
            reasons.append("COMPONENT_LITERAL_HAS_NO_COMPLETE_TESSERACT_CORROBORATION:"+str(i))
        if model_conflict:
            reasons.append("CONFLICTING_STRICT_COMPONENT_MODEL:"+str(i))
        component_records.append({"component_index":i,"literal":expected,
            "Tesseract_raw_texts":[w["text"] for w in words],
            "Tesseract_aggregate_word_scores":[w["confidence"] for w in words],
            "component_model_raw_text":pm.get("raw_text"),
            "whole_source_component_bbox_covered":bool(complete),
            "literal_corroborated":bool(corroborated),
            "strict_component_model_conflict":bool(model_conflict)})
    contact_components = {i for i,c in enumerate(components) if c["shared_core_points_px"]}
    source_responsibility = (bool(partition["graphic_crossings"])
        and all(c["original_free_endpoint_points_px"] for c in components if c["shared_core_points_px"])
        and partition["all_side_glyph_skeleton_and_shared_core_samples_retained"] is True
        and all(c["source_continuity_both_sides"] and c["glyph_box_is_not_path_terminal"]
                for c in partition["graphic_crossings"]))
    if not source_responsibility:
        reasons.append("COMPLETE_GLYPH_AND_GRAPHIC_SOURCE_RESPONSIBILITY_NOT_PROVEN")
    for domain in ("original_group","ownership_group"):
        observation = raw[domain]
        values = [("Tesseract",v["psm"],"".join(w["text"] for w in v["words"]),
                   min((w["confidence"] for w in v["words"]),default=0)>=85)
                  for v in observation["tesseract"]]
        pm = observation["model"]["prediction"]
        values.append(("PP-OCR",None,pm.get("raw_text",""),_strong_model(pm)))
        for engine,view,value,strong in values:
            if not value or value==text:
                continue
            differing = [i for i,(a,b) in enumerate(zip(value,text)) if a!=b]
            same_count = len(value)==len(text)
            contact_only = same_count and bool(differing) and set(differing)<=contact_components
            # A whole-source crop still contains a graphic continuing past
            # both ends of the finite glyph. Assigning that stroke to text
            # would invent terminal caps. The compact side glyph preserves
            # every original branch and shared junction sample instead.
            # A disagreement on the already separated ownership image cannot
            # be excused by the graphic removed from a different input.  A
            # strong reading there remains a real competing transcription.
            bindings = (_original_word_graphic_bindings(partition,raw["original_group"],value,differing)
                        if domain=="original_group" and contact_only else [])
            original_line_cut = bool(bindings) and len(bindings)==len(differing)
            resolved = bool(source_responsibility and contact_only and original_line_cut)
            explanation = ("INDEPENDENT_CONTINUING_GRAPHIC_HAS_NO_FINITE_CHARACTER_ENDPOINTS"
                           if resolved else "LOW_CONFIDENCE_CONTEXT_READING_RETAINED"
                           if not strong else "UNRESOLVED_STRONG_RAW_READING")
            competitors.append({"domain":domain,"engine":engine,"view":view,"raw_text":value,
                "strong_raw_reading":bool(strong),"competing_component_indices":differing,
                "source_responsibility_resolved":resolved,"disposition":explanation,
                "original_TSV_reading_reaches_both_graphic_crop_edges":original_line_cut,
                "original_word_graphic_edge_bindings":bindings,
                "source_path_continues_beyond_original_context":original_line_cut,
                "semantic_identity_claimed":False})
            if strong and not resolved:
                reasons.append("UNRESOLVED_STRONG_RAW_COMPETITOR:"+domain+":"+value)
    return {"accepted":not reasons,"text":text if not reasons else None,"proposed_raw_text":text,
            "reasons":sorted(set(reasons)),"components":component_records,
            "raw_competing_readings":competitors,
            "all_original_and_derived_readings_retained":True,
            "adoption_basis":POLICY["adoption_basis"],
            "independent_path_and_complete_glyph_responsibility":bool(source_responsibility),
            "same_source_target_to_target_support":False,
            "OCR_transcriptions_rewritten":False,
            "engineering_or_symbol_semantics_inferred":False}


def _raw_replay(gray, partition, raw, evidence_root):
    for domain,index in [("original_group",None),("ownership_group",None)]+[("components",i) for i in range(len(partition["components"]))]:
        observation = raw[domain] if index is None else raw[domain][index]
        image,_ = recognition_view(gray,partition,index,original=domain=="original_group")
        if observation["input_array_sha256"]!=base.source_array_sha256(image):
            raise ValueError("SHORT_CONTACT_RAW_INPUT_DOES_NOT_REPLAY_SOURCE_PARTITION")
        repeated = np.repeat(np.repeat(image,2,axis=0),2,axis=1)
        expected_psms = [POLICY["Tesseract_component_PSM"]] if domain=="components" else POLICY["Tesseract_context_PSMs"]
        if [v["psm"] for v in observation["tesseract"]]!=expected_psms:
            raise ValueError("SHORT_CONTACT_FINITE_OCR_VIEW_PLAN_CHANGED")
        for view in observation["tesseract"]:
            payload = _read(evidence_root,view["raw_tsv"])
            words = _words(payload,repeated.shape[1],repeated.shape[0],view["psm"])
            if words!=view["words"]:
                raise ValueError("SHORT_CONTACT_RAW_TSV_WORDS_REWRITTEN")
            actual = np.asarray(Image.open(BytesIO(_read(evidence_root,view["recognition_image"]))).convert("L"))
            expected = np.pad(repeated,POLICY["Tesseract_external_white_padding_px"],constant_values=255)
            if not np.array_equal(actual,expected):
                raise ValueError("SHORT_CONTACT_TESSERACT_IMAGE_CHANGED")
            metadata = json.loads(_read(evidence_root,view["metadata"]))
            if metadata.get("return_code")!=0 or metadata.get("status")!="COMPLETED" or metadata.get("tsv_sha256")!=hashlib.sha256(payload).hexdigest():
                raise ValueError("SHORT_CONTACT_TESSERACT_RAW_METADATA_CHANGED")
        model = observation["model"]
        prediction = json.loads(_read(evidence_root,model["prediction_file"]))
        expected = np.pad(image,POLICY["PP_external_white_padding_px"],constant_values=255)
        actual = np.asarray(Image.open(BytesIO(_read(evidence_root,model["recognition_image"]))).convert("L"))
        _,tensor = independent.prepare_model_input(expected)
        identity = json.loads(_read(evidence_root,model["identity"]))
        if (prediction!=model["prediction"] or not _model_integrity(prediction)
                or not np.array_equal(actual,expected)
                or prediction.get("input_array_sha256")!=hashlib.sha256(expected.tobytes()).hexdigest()
                or prediction.get("model_tensor_sha256")!=hashlib.sha256(tensor.tobytes()).hexdigest()
                or identity.get("model_sha256")!=independent.MODEL_SHA256):
            raise ValueError("SHORT_CONTACT_MODEL_SOURCE_OR_RAW_CTC_CHANGED")


def complete_short_contact_text(gray, roi, source_sha, objects, text_regions, out, *, dpi=200,
                                source_graph=None, contact_completion=None, recognizer=None):
    """Produce independent complete TEXT groups after graphic adoption, once."""
    output,root = Path(out),Path(out).parent
    output.mkdir(parents=True,exist_ok=True)
    plan = partitioner.plan_short_contact_text(gray,roi,objects,contact_completion or {},source_graph=source_graph)
    save_json(output/"plan.json",plan)
    save_json(output/"policy_frozen_before_recognition.json",{"policy":POLICY,"partition_policy":partitioner.POLICY,"producer":_producer()})
    result = {"schema":ADOPTION_SCHEMA,"policy":deepcopy(POLICY),"producer":_producer(),
              "source_sha256":source_sha,"source_array_sha256":base.source_array_sha256(gray),
              "roi_xyxy_px":list(roi),"dpi":dpi,"objects":[],"retired_ids":[],
              "pending":deepcopy(plan["pending"]),"decisions":[],"source_plan":plan,
              "completion_passes":1,"prior_complete_objects_modified":False,
              "original_source_pixels_modified":False,"new_targets_used_as_references":False}
    relevant = {b["id"] for b in plan["adopted_path_bindings"]}
    result["prior_objects"] = [{**{k:deepcopy(o[k]) for k in ("id","kind","layer","geometry")},
        **({"bbox_xyxy_px":deepcopy(o["bbox_xyxy_px"])} if "bbox_xyxy_px" in o else {}),
        **({"source_evidence":{"text_contact_path":deepcopy(o["source_evidence"]["text_contact_path"])}} if o["id"] in relevant else {})}
        for o in objects]
    keys = {o["source_evidence"]["text_contact_path"]["plan_sha256"] for o in objects if o["id"] in relevant}
    result["contact_geometry_plans"] = {key:deepcopy(contact_completion["geometry_plans"][key]) for key in keys}
    actual_tesseract_calls,actual_model_calls = 0,0
    for item in plan["plans"]:
        check_cancel("COMPLETE_SHORT_CONTACT_TEXT")
        directory = output/"groups"/item["id"]
        directory.mkdir(parents=True,exist_ok=True)
        if recognizer is None:
            recognizer = independent.IndependentRecognizer()
        partition = item["source_partition"]
        original,_ = recognition_view(gray,partition,original=True)
        owned,_ = recognition_view(gray,partition)
        Image.fromarray(original).save(directory/"original_source.png")
        Image.fromarray(owned).save(directory/"owned_source_ink.png")
        raw = {"original_group":_view_observations(original,directory/"original",root,dpi,recognizer,POLICY["Tesseract_context_PSMs"]),
               "ownership_group":_view_observations(owned,directory/"ownership",root,dpi,recognizer,POLICY["Tesseract_context_PSMs"]),
               "components":[]}
        for i in range(len(partition["components"])):
            image,_ = recognition_view(gray,partition,i)
            raw["components"].append(_view_observations(image,directory/("component-"+str(i)),root,dpi,recognizer,[POLICY["Tesseract_component_PSM"]]))
        all_observations = [raw["original_group"],raw["ownership_group"],*raw["components"]]
        actual_tesseract_calls += sum(int(view["new_call"]) for observation in all_observations for view in observation["tesseract"])
        actual_model_calls += sum(int(observation["model"].get("observation_receipt",{}).get(
            "model_inference_executed_for_this_request",True)) for observation in all_observations)
        decision = decide_short_contact_text(partition,raw)
        evidence = {"schema":SCHEMA,"policy":deepcopy(POLICY),"producer":_producer(),
                    "source_sha256":source_sha,"source_array_sha256":result["source_array_sha256"],
                    "roi_xyxy_px":list(roi),"source_partition":deepcopy(partition),
                    "raw_observations":raw,"decision":decision,"recognition_dpi":dpi,
                    "original_source":_record(directory/"original_source.png",root),
                    "ownership_view":_record(directory/"owned_source_ink.png",root),
                    "expected_text_provided":False,"raw_transcription_rewritten":False}
        if decision["accepted"]:
            layout = layouts.plan_short_text_layout(decision["text"],partition,roi,dpi)
            evidence["layout"] = layout
            obj = {"id":item["id"],"kind":layout["kind"],"layer":"ANNOTATION",
                   "geometry":deepcopy(layout["geometry"]),"bbox_xyxy_px":partition["bbox_xyxy_px"],
                   "source_evidence":{FIELD:evidence},
                   "editing_scope":"one complete character group; independently adopted graphics remain separate",
                   "status":"COMPLETE_SOURCE_SUPPORTED_SHORT_CONTACT_TEXT"}
            result["objects"].append(obj)
        else:
            result["pending"].append({"id":item["id"],"bbox_xyxy_px":partition["bbox_xyxy_px"],
                                      "reason":"SHORT_CONTACT_TRANSCRIPTION_PENDING","reasons":decision["reasons"]})
        save_json(directory/"result.json",evidence)
        result["decisions"].append({"id":item["id"],"bbox_xyxy_px":partition["bbox_xyxy_px"],
                                    "accepted":decision["accepted"],"text":decision["text"],
                                    "reasons":decision["reasons"],"evidence":_record(directory/"result.json",root)})
        save_json(output/"progress.json",{"decisions":result["decisions"],"source_sha256":source_sha})
    result["summary"] = {"discovered_groups":len(plan["plans"]),"accepted_complete_groups":len(result["objects"]),
                          "pending_items":len(result["pending"]),"new_OCR_calls":actual_tesseract_calls,
                          "new_model_calls":actual_model_calls,"recognition_counts_include_pending_groups":True}
    save_json(output/"adoption.json",result)
    return result


def replay_short_contact_evidence(gray,roi,evidence,evidence_root,*,partition=None):
    result = {"pass":False,"new_OCR_calls":0,"new_model_calls":0}
    try:
        if evidence.get("schema")!=SCHEMA or evidence.get("policy")!=POLICY or evidence.get("producer")!=_producer():
            raise ValueError("SHORT_CONTACT_PRODUCER_OR_POLICY_CHANGED")
        if evidence.get("roi_xyxy_px")!=list(roi) or evidence.get("source_array_sha256")!=base.source_array_sha256(gray):
            raise ValueError("SHORT_CONTACT_SOURCE_IDENTITY_CHANGED")
        if evidence.get("expected_text_provided") is not False or evidence.get("raw_transcription_rewritten") is not False:
            raise ValueError("SHORT_CONTACT_LITERAL_SOURCE_CONTRACT_CHANGED")
        if partition is None or partition!=evidence["source_partition"]:
            raise ValueError("SHORT_CONTACT_INDEPENDENT_SOURCE_PARTITION_DID_NOT_REPLAY")
        _raw_replay(gray,partition,evidence["raw_observations"],evidence_root)
        decision = decide_short_contact_text(partition,evidence["raw_observations"])
        if not decision["accepted"] or decision!=evidence["decision"]:
            raise ValueError("SHORT_CONTACT_SAVED_TRANSCRIPTION_DECISION_DOES_NOT_REPLAY")
        layout = layouts.plan_short_text_layout(decision["text"],partition,roi,evidence["recognition_dpi"])
        if layout!=evidence["layout"]:
            raise ValueError("SHORT_CONTACT_SOURCE_COMPONENT_LAYOUT_CHANGED")
        result.update({"pass":True,"text":decision["text"],"layout":layout,
                       "complete_original_components_replayed":True,"original_and_derived_raw_replayed":True,
                       "all_competing_readings_retained_and_rechecked":True})
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        result["reason"] = str(exc)
    return result


def restore_short_contact_evidence(cache_dir,out,completion):
    if not completion:
        return
    if completion.get("schema")!=ADOPTION_SCHEMA:
        raise ValueError("SHORT_CONTACT_RESTORE_SCHEMA_CHANGED")
    source,destination = Path(cache_dir)/"short_contact_text",Path(out)/"short_contact_text"
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        target = destination/path.relative_to(source)
        if target.exists() and target.read_bytes()!=path.read_bytes():
            raise ValueError("SHORT_CONTACT_RESTORE_WOULD_OVERWRITE_DIFFERENT_EVIDENCE")
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            shutil.copyfile(path,target)
    saved = destination/"adoption.json"
    if not saved.is_file() or json.loads(saved.read_text())!=completion:
        raise ValueError("SHORT_CONTACT_RESTORE_ADOPTION_RECEIPT_MISSING_OR_CHANGED")
