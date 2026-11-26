"""Cold proof of saved short text, its raw source, and independent path owners."""

from __future__ import annotations

import json
from pathlib import Path

import ezdxf
from .short_contact_partition import plan_short_contact_text
from .short_contact_text import FIELD, ADOPTION_SCHEMA, _producer, replay_short_contact_evidence
from .single_line_text_audit import (
    _expected_attributes, _same, text_attributes, resolve_saved_text_font,
)
from .text_contact_adoption import object_binding
from .text_contact_audit import _primitive_matches


def _identity(entity):
    from .cad_io import APPID

    try:
        value = json.loads(entity.get_xdata(APPID)[0].value)
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError,IndexError,ezdxf.DXFError):
        return {}


def _saved_owner_check(entity, obj, written, roi, dpi):
    checks = _primitive_matches(entity,obj["kind"],obj["geometry"],roi,dpi)
    identity = _identity(entity)
    checks.update(identity=identity.get("id")==obj["id"] and identity.get("kind")==obj["kind"],
                  handle=written.get("handle")==entity.dxf.handle,
                  layer=entity.dxf.layer==obj["layer"])
    return {"pass":all(checks.values()),"checks":checks}


def cold_short_contact_text_bindings(path,doc,gray,roi,dpi,evidence_root):
    path,root = Path(path),Path(evidence_root)
    report = {"pass":True,"checks":[],"targets":[],"new_OCR_calls":0,"new_model_calls":0}
    actual,flagged = {},set()
    for entity in doc.modelspace():
        ident = _identity(entity)
        if isinstance(ident.get("id"),str):
            actual.setdefault(ident["id"],[]).append(entity)
        if ident.get(FIELD):
            flagged.add(ident["id"] if isinstance(ident.get("id"),str) and ident["id"]
                        else "UNIDENTIFIED:"+entity.dxf.handle)
    metadata,objects,written,load_errors = {},{},{},[]
    try:
        metadata = json.loads(path.with_suffix(".objects.json").read_text())
        if not isinstance(metadata,dict):
            raise ValueError("metadata is not an object")
        objects = {o["id"]:o for o in metadata["objects"]}
        written = {r["id"]:r for r in metadata["written"]}
        if (not all(isinstance(oid,str) for oid in objects)
                or len(objects)!=len(metadata["objects"]) or len(written)!=len(metadata["written"])):
            raise ValueError("invalid or duplicate candidate identities")
    except (OSError,ValueError,TypeError,KeyError) as exc:
        load_errors.append("SHORT_CONTACT_METADATA_UNREADABLE:"+str(exc))
        objects = {oid:o for oid,o in objects.items() if isinstance(oid,str)}
    receipt_path = root/"short_contact_text/adoption.json"
    receipt,receipt_objects = None,{}
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text())
            if not isinstance(receipt,dict) or not isinstance(receipt.get("objects"),list):
                raise ValueError("adoption is not a complete object receipt")
            receipt_objects = {o["id"]:o for o in receipt["objects"]}
            if (not all(isinstance(oid,str) for oid in receipt_objects)
                    or len(receipt_objects)!=len(receipt["objects"])):
                raise ValueError("invalid or duplicate adopted identities")
        except (OSError,ValueError,TypeError,KeyError) as exc:
            receipt,receipt_objects = None,{}
            load_errors.append("SHORT_CONTACT_ADOPTION_UNREADABLE:"+str(exc))
    targets = {oid for oid,o in objects.items() if isinstance(o.get("source_evidence"),dict)
               and FIELD in o["source_evidence"]}
    targets |= flagged | set(receipt_objects)
    if not targets and receipt_path.exists() and load_errors:
        targets.add("SHORT_CONTACT_ADOPTION")
    if not targets:
        return report
    failure,partitions = None,{}
    try:
        if load_errors:
            raise ValueError(";".join(load_errors))
        if not receipt or receipt.get("schema")!=ADOPTION_SCHEMA or receipt.get("producer")!=_producer():
            raise ValueError("SHORT_CONTACT_ADOPTION_RECEIPT_MISSING_OR_CHANGED")
        if receipt.get("source_sha256")!=metadata["source_sha256"] or receipt.get("roi_xyxy_px")!=list(roi) or receipt.get("dpi")!=dpi:
            raise ValueError("SHORT_CONTACT_ADOPTION_SOURCE_BINDING_CHANGED")
        prior = receipt["prior_objects"]
        prior_by_id = {o["id"]:o for o in prior}
        for binding in receipt["source_plan"]["adopted_path_bindings"]:
            oid = binding["id"]
            if oid not in objects or object_binding(objects[oid])!=binding or object_binding(prior_by_id[oid])!=binding:
                raise ValueError("SHORT_CONTACT_INDEPENDENT_PATH_OWNER_CHANGED")
            saved_owners = actual.get(oid,[])
            if len(saved_owners)!=1 or saved_owners[0].dxftype()!="LWPOLYLINE":
                raise ValueError("SHORT_CONTACT_ACTUAL_INDEPENDENT_PATH_MISSING_OR_DUPLICATE")
            if not _saved_owner_check(saved_owners[0],objects[oid],written.get(oid,{}),roi,dpi)["pass"]:
                raise ValueError("SHORT_CONTACT_ACTUAL_SAVED_PATH_GEOMETRY_CHANGED")
        replay = plan_short_contact_text(gray,roi,prior,{"geometry_plans":receipt["contact_geometry_plans"]})
        if replay["plans"]!=receipt["source_plan"]["plans"]:
            raise ValueError("SHORT_CONTACT_COMPLETE_SOURCE_DISCOVERY_CHANGED")
        partitions = {p["id"]:p["source_partition"] for p in replay["plans"]}
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        failure = str(exc)
    for oid in sorted(targets):
        check = {"id":oid,"type":"SHORT_CONTACT_SAVED_SOURCE_AND_EDITING_RESPONSIBILITY","pass":False}
        try:
            if failure:
                raise ValueError(failure)
            obj = objects.get(oid)
            if obj is None or receipt_objects.get(oid)!=obj:
                raise ValueError("SHORT_CONTACT_SAVED_CANDIDATE_DIFFERS_FROM_ADOPTION")
            entities = actual.get(oid,[])
            if len(entities)!=1 or _identity(entities[0]).get(FIELD) is not True:
                raise ValueError("SHORT_CONTACT_SAVED_ENTITY_MISSING_DUPLICATE_OR_UNMARKED")
            entity = entities[0]
            if (written.get(oid,{}).get("handle")!=entity.dxf.handle
                    or _identity(entity).get("kind")!=obj["kind"]):
                raise ValueError("SHORT_CONTACT_SAVED_HANDLE_OR_KIND_CHANGED")
            proof = obj["source_evidence"][FIELD]
            replay = replay_short_contact_evidence(gray,roi,proof,root,partition=partitions.get(oid))
            if not replay["pass"]:
                raise ValueError(replay.get("reason","SHORT_CONTACT_SOURCE_REPLAY_FAILED"))
            _,font_path,style = resolve_saved_text_font(path,metadata,obj)
            if obj["kind"]=="TEXT":
                if entity.dxftype()!="TEXT":
                    raise ValueError("SHORT_CONTACT_LITERAL_IS_NOT_NATIVE_TEXT")
                members,expected = [entity],[obj["geometry"]]
            elif obj["kind"]=="TEXT_GROUP":
                if entity.dxftype()!="INSERT" or not entity.dxf.name.startswith("I2CAD_"+oid.replace("-","_")):
                    raise ValueError("SHORT_CONTACT_GROUP_IS_NOT_UNIQUE_NATIVE_BLOCK")
                if sum(e.dxftype()=="INSERT" and e.dxf.name==entity.dxf.name for e in doc.modelspace())!=1:
                    raise ValueError("SHORT_CONTACT_GROUP_BLOCK_SHARED_BY_ANOTHER_INSTANCE")
                if (entity.dxf.rotation!=0 or entity.dxf.xscale!=1 or entity.dxf.yscale!=1 or entity.dxf.zscale!=1):
                    raise ValueError("SHORT_CONTACT_GROUP_UNEXPECTED_INSERT_TRANSFORM")
                members = list(entity.virtual_entities())
                expected = obj["geometry"]["text_members"]
                if any(m.dxftype()!="TEXT" for m in members):
                    raise ValueError("SHORT_CONTACT_GROUP_CONTAINS_GRAPHICS_OR_NON_TEXT")
            else:
                raise ValueError("SHORT_CONTACT_OBJECT_KIND_IS_NOT_TEXT_OR_MINIMUM_TEXT_GROUP")
            if len(members)!=len(expected):
                raise ValueError("SHORT_CONTACT_COMPLETE_MEMBER_COUNT_CHANGED")
            for member,geometry in zip(members,expected):
                member_object = {"geometry":geometry,"layer":obj["layer"] if obj["kind"]=="TEXT" else "0"}
                attributes,_ = _expected_attributes(member,member_object,roi,dpi,font_path,False)
                if obj["kind"]=="TEXT_GROUP":
                    attributes["color"] = 0
                    # ezdxf materializes an inactive alignment point while
                    # translating virtual left/baseline TEXT members.  Its
                    # active insertion and halign/valign are checked below.
                    attributes.pop("align_point",None)
                actual_attributes = text_attributes(member)
                if any(not _same(actual_attributes.get(k),v) for k,v in attributes.items()):
                    raise ValueError("SHORT_CONTACT_ACTUAL_TEXT_CONTENT_OR_LAYOUT_CHANGED")
                if member.dxf.style!=style:
                    raise ValueError("SHORT_CONTACT_ACTUAL_FONT_STYLE_CHANGED")
            check.update({"pass":True,"text":proof["decision"]["text"],"kind":obj["kind"],
                          "actual_native_TEXT_members":len(members),"source_replay":replay,
                          "independent_graphic_owner_ids":[c["owner_id"] for c in proof["source_partition"]["graphic_crossings"]],
                          "original_glyph_and_shared_core_samples_replayed":True,
                          "original_and_partition_raw_conflicts_replayed":True,
                          "minimum_complete_editing_group_verified":True})
        except (ValueError,KeyError,TypeError,OSError,IndexError,ezdxf.DXFError) as exc:
            check["reason"] = str(exc)
        report["checks"].append(check)
        report["targets"].append(oid)
    report["pass"] = all(c["pass"] for c in report["checks"])
    return report
