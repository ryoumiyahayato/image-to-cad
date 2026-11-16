"""One explicitly confirmed source-supported TEXT repair in the current CAD.

The immutable ReviewProject supplies source validation and region coordinates.
It is not re-exported over user geometry. No cross-snapshot identity is inferred.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

import cad_delta as delta
from reconnect import ReviewProject, collect, write_files


@contextmanager
def source_project(project):
    with TemporaryDirectory(prefix="g28-repair-source-") as tmp:
        path = Path(tmp) / "source.icreview"
        with ZipFile(path, "w") as archive:
            for name, value in project.core.items():
                archive.writestr(name, value)
        original = ReviewProject.open(path)  # Existing source integrity checks.
        try:
            if original.snapshot_uuid != project.state["source_snapshot"]:
                raise ValueError("SOURCE_SNAPSHOT_MISMATCH")
            yield original
        finally:
            original.close()


def source_evidence(project, source_uuid):
    """Re-read the selected source region, with recorded surrounding context."""
    import cv2
    from app.core.image_loader import load_image
    from app.geometry.pdf_text_suggestions import _render_crop

    with source_project(project) as original:
        binding = next((b for b in original.bindings if b["text_source_uuid"] == source_uuid), None)
        if binding is None:
            raise ValueError("UNKNOWN_SOURCE_REGION")
        source = original.manifest["source"]
        x, y, w, h = binding["original_candidate"]["bbox"]
        width, height = original.baseline.source_size_px
        padding = max(16, h)
        box = [max(0, x-padding), max(0, y-padding), min(width, x+w+padding), min(height, y+h+padding)]
        path = Path(source["path"])
        dpi = source["cache_identity"]["dpi"]
        page_number = source["physical_page"]
        if path.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(path) as pdf:
                page = pdf[page_number-1]
                try:
                    crop = _render_crop(page, box, dpi/72, (height, width))
                finally:
                    page.close()
        else:
            frame = load_image(path, grayscale=True)
            if frame.shape != (height, width):
                raise ValueError("SOURCE_FRAME_SIZE_CHANGED")
            crop = frame[box[1]:box[3], box[0]:box[2]]
        ok, png = cv2.imencode(".png", crop)
        if not ok or crop.size == 0:
            raise ValueError("SOURCE_CROP_FAILED")
        return {
            "kind": "FRESH_SOURCE_REGION", "snapshot_uuid": original.snapshot_uuid,
            "source_uuid": source_uuid, "path": str(path), "physical_page": page_number,
            "dpi": dpi, "original_bbox_xywh": [x, y, w, h], "observed_box_xyxy": box,
            "original_ocr_text": binding["original_candidate"]["text"],
            "png_base64": base64.b64encode(png.tobytes()).decode("ascii"),
            "historical_current_member_identity": "NOT_PROVEN",
        }


def current_texts(project):
    with TemporaryDirectory(prefix="g28-current-texts-") as tmp:
        snapshot = delta.read(write_files(tmp, project.payloads[project.state["current"]]))
        return [row for row in snapshot.rows if row["content"]["type"] == "TEXT"]


def _patched(project, member, new_text):
    if not isinstance(new_text, str) or not new_text.strip() or any(ord(c) < 32 for c in new_text):
        raise ValueError("Single-line nonempty native text required")
    with TemporaryDirectory(prefix="g28-local-repair-") as tmp:
        old_files = project.payloads[project.state["current"]]
        before = write_files(Path(tmp)/"before", old_files)
        after = write_files(Path(tmp)/"after", old_files)
        doc = delta.ezdxf.readfile(after)
        entity = doc.entitydb.get(member)
        if entity is None or entity.dxftype() != "TEXT" or entity not in doc.modelspace():
            raise ValueError("Select a current modelspace TEXT member")
        if entity.dxf.text == new_text:
            raise ValueError("NO_TEXT_CHANGE")
        old_content = delta.content(entity)
        entity.dxf.text = new_text
        doc.saveas(after)
        files, snapshot = collect(after)
        result = delta.compare(before, snapshot)
        old = delta.read(before)
        # A local TEXT operation must not mutate other entities, their source
        # tags, tables, or dependencies. These are runtime transaction checks.
        if set(e.dxf.handle for e in old.doc.modelspace()) != set(e.dxf.handle for e in snapshot.doc.modelspace()):
            raise ValueError("LOCAL_REPAIR_CHANGED_MEMBERS")
        def serialized_tags(entity):
            collector = delta.TagCollector(dxfversion=doc.dxfversion, optional=False)
            entity.export_dxf(collector)
            return collector.tags

        for e in old.doc.modelspace():
            newer = snapshot.doc.entitydb[e.dxf.handle]
            # ezdxf omits optional attributes equal to DXF defaults on save.
            # Use its own serializer for that equivalence; no geometry tolerance.
            if e.dxf.handle != member and serialized_tags(e) != serialized_tags(newer):
                raise ValueError("LOCAL_REPAIR_CHANGED_OTHER_MEMBER")
        new_content = delta.content(snapshot.doc.entitydb[member])
        if delta.fields_changed(old_content, new_content) != [{"field": "text", "before": old_content["text"], "after": new_text}]:
            raise ValueError("LOCAL_REPAIR_CHANGED_LAYOUT")
        if old.metadata != snapshot.metadata or {k:v for k,v in old_files.items() if k != "drawing.dxf"} != {k:v for k,v in files.items() if k != "drawing.dxf"}:
            raise ValueError("LOCAL_REPAIR_CHANGED_DOCUMENT")
        return files, old_content, new_content, result


def preview_repair(project, member, source_uuid, new_text):
    evidence = source_evidence(project, source_uuid)
    files, before, after, _ = _patched(project, member, new_text)
    # This explicit current-member selection is not an input to the matcher.
    return {
        "kind": "LOCAL_SOURCE_TEXT_REPAIR", "project_uuid": project.state["project_uuid"],
        "revision": project.state["revision"], "base": project.state["current"],
        "member": member, "before": before, "after": after, "source_evidence": evidence,
        "confirmation": "REQUIRED_CURRENT_MEMBER_AND_SOURCE_REGION",
        "scope": "TEXT_STRING_ONLY_KEEP_CURRENT_PLACEMENT",
    }, files


def accept_repair(project, preview, *, actor):
    if actor not in {"AGENT_REVIEWED", "HUMAN_REVIEWED", "TEST_ONLY"}:
        raise ValueError("Explicit review actor required")
    if (preview["project_uuid"], preview["revision"], preview["base"]) != (project.state["project_uuid"], project.state["revision"], project.state["current"]):
        raise ValueError("LOCAL_REPAIR_VERSION_CONFLICT")
    fresh, files = preview_repair(project, preview["member"], preview["source_evidence"]["source_uuid"], preview["after"]["text"])
    if fresh != preview:
        raise ValueError("LOCAL_REPAIR_INPUT_CHANGED")
    parent = project.state["current"]
    member, key = preview["member"], str(uuid4())
    relations = deepcopy(project.state["states"][parent]["relations"])
    previous = deepcopy(relations.get(member, {}))
    confirmation = {"actor": actor, "at": datetime.now(timezone.utc).isoformat(), "scope": preview["scope"], "explicit": True}
    relations[member] = {
        **previous, "status": "EXPLICIT_CURRENT_MEMBER_SOURCE_TEXT_REPAIR",
        "historical_current_member_identity": "NOT_PROVEN",
        "current_member_continuity": "EXPLICIT_LOCAL_TRANSACTION",
        "source_evidence": deepcopy(preview["source_evidence"]), "confirmation": confirmation,
        "current_geometry_is_source_observation": False, "source_automatic_operations": False,
        "permitted_source_operation": "PREVIEW_AND_EXPLICITLY_CONFIRM_LOCAL_TEXT",
    }
    project.payloads[key] = files
    project.state["states"][key] = {"parent": parent, "relations": relations, "origin": "local-source-text-repair", "unresolved_relation_refs": deepcopy(project.state["states"][parent].get("unresolved_relation_refs", []))}
    project.state["current"] = key
    project.state["revision"] += 1
    project.state["journal"].append({
        "event": "LOCAL_SOURCE_TEXT_REPAIR", "state": key, "parent": parent, "member": member,
        "before": preview["before"]["text"], "after": preview["after"]["text"],
        "confirmation": confirmation, "source_uuid": preview["source_evidence"]["source_uuid"],
        "confirmed_historical_identities": 0,
    })
    return True


def main():
    import argparse
    from reconnect import ReconnectProject, atomic_bytes, encoded
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preview")
    p.add_argument("--project", required=True); p.add_argument("--member", required=True)
    p.add_argument("--source-uuid", required=True); p.add_argument("--text", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("accept")
    p.add_argument("--project", required=True); p.add_argument("--preview", required=True)
    p.add_argument("--actor", required=True, choices=["HUMAN_REVIEWED", "AGENT_REVIEWED", "TEST_ONLY"])
    args = parser.parse_args()
    project = ReconnectProject.open(args.project)
    project.disk_revision = project.state["revision"]
    if args.command == "preview":
        preview, _ = preview_repair(project, args.member, args.source_uuid, args.text)
        atomic_bytes(args.output, encoded(preview))
        print("LOCAL_REPAIR_PREVIEW", args.output)
    else:
        accept_repair(project, json.loads(Path(args.preview).read_text(encoding="utf-8")), actor=args.actor)
        project.save()
        print("LOCAL_REPAIR_SAVED", args.project)


if __name__ == "__main__":
    main()
