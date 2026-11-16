"""Isolated external-CAD extension of ReviewProject, not the production GUI.

The existing immutable four-entry project is retained. The extension stores the
current editable CAD, relations and reversible transactions in the same ZIP.
It never regenerates CAD from the original OCR after accepting an external edit.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
from tempfile import TemporaryDirectory, NamedTemporaryFile
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

import cad_delta as delta
from relation_review import project_relations

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))
from app.core.review_project import ReviewProject
from app.core.cache import load_trace_cache
from app.core.processing import ProductionProcessingConfig, build_processing_cache_key
from app.core.scale_calibrator import ScaleCalibration

CORE = {"project.json", "corrections.json", "snapshot.npz", "review-frame.png"}
STATE = "external-cad/state.json"
VERSION = "external-cad-extension-v1"


@contextmanager
def exclusive_save(path):
    """Single-file transaction exclusion; no background scheduler/service."""
    lock = Path(str(path) + ".lock")
    token = str(uuid4()).encode("ascii")
    try:
        with lock.open("xb") as handle:
            handle.write(token)
    except FileExistsError:
        raise ValueError("PROJECT_SAVE_BUSY") from None
    try:
        yield
    finally:
        if lock.exists() and lock.read_bytes() == token:
            lock.unlink()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2).encode("utf-8")


def atomic_bytes(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix="." + path.name, suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            f.write(payload); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def safe_member(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe archive member")


def collect(dxf):
    snapshot = delta.read(dxf)
    if snapshot.missing:
        raise ValueError("MISSING_DEPENDENCIES: " + json.dumps(snapshot.missing))
    if {r["type"] for r in delta.referenced_content(snapshot.doc)[0]} - delta.SUPPORTED:
        raise ValueError("Unsupported entity requires explicit adapter support")
    files = {"drawing.dxf": Path(dxf).read_bytes()}
    for asset in snapshot.assets.values():
        name = asset["filename"].replace("\\", "/")
        safe_member(name)
        if name == "drawing.dxf" or (name in files and files[name] != asset["bytes"]):
            raise ValueError("Dependency name collision")
        files[name] = asset["bytes"]
    return files, snapshot


def write_files(directory, files):
    directory = Path(directory)
    for name, value in files.items():
        safe_member(name)
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    return directory / "drawing.dxf"


class ReconnectProject:
    def __init__(self, core, state, payloads, path=None):
        self.core, self.state, self.payloads = core, state, payloads
        self.path = Path(path).resolve() if path else None
        self.disk_revision = state["revision"]

    @classmethod
    def create(cls, run, dxf, *, source_scene=False):
        run = Path(run)
        info = json.loads((run / "entities.json").read_text(encoding="utf-8"))
        # Ordinary entry accepts the actual existing export alongside its cache.
        # Isolated G26 scenes need an explicit scope flag and acquire no claim
        # to be the production FinalStructure's exported geometry.
        if not source_scene and Path(dxf).read_bytes() != (run / "drawing.dxf").read_bytes():
            raise ValueError("P0_D0_MISMATCH: use the actual production export")
        stored = load_trace_cache(run / "trace.npz")
        # Reuse the recorded identity. ReviewProject performs its own unchanged
        # built-in source integrity validation; no new hash manifest is made.
        key = build_processing_cache_key(input_content_sha256=info["source_sha256"], page_index=info["page"] - 1, config=ProductionProcessingConfig(source_dpi=info["dpi"]))
        project = ReviewProject.create(stored.final_structure, source_path=info["source"], cache_key=key.payload(), calibration=ScaleCalibration((0, 0), (1, 0), 25.4 / info["dpi"]), origin="G27 frozen existing conversion; external CAD extension")
        try:
            with TemporaryDirectory(prefix="g28-core-save-") as tmp:
                core_path = Path(tmp) / "core.icreview"
                project.save(core_path)
                with ZipFile(core_path) as z:
                    core = {name: z.read(name) for name in CORE}
        finally:
            project.close()
        files, snapshot = collect(dxf)
        state_id = str(uuid4())
        relations = {r["handle"]: {"status": "BASELINE_EXPORTED_CONTENT", "historical_source": r["source"], "source_record_validity": r["source_validity"], "source_automatic_operations": False} for r in snapshot.rows}
        state = {"format": VERSION, "revision": 0, "current": state_id, "project_uuid": str(uuid4()), "source_snapshot": json.loads(core["project.json"])["snapshot_uuid"], "cad_scope": "G26_SOURCE_SCENE_NOT_PRODUCTION_GEOMETRY" if source_scene else "EXISTING_PRODUCTION_EXPORT", "states": {state_id: {"parent": None, "relations": relations, "origin": str(Path(dxf).resolve())}}, "journal": [], "exports": {}, "accepted_external": []}
        return cls(core, state, {state_id: files})

    @classmethod
    def open(cls, path):
        with ZipFile(path) as z:
            if z.testzip() is not None:
                raise ValueError("Corrupt project ZIP")
            names = z.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive member")
            for name in names:
                safe_member(name)
            state = json.loads(z.read(STATE))
            if state.get("format") != VERSION:
                raise ValueError("Unsupported external CAD extension version")
            core = {name: z.read(name) for name in CORE}
            payloads = {}
            expected = CORE | {STATE}
            for key in state["states"]:
                prefix = f"external-cad/states/{key}/"
                members = [name for name in names if name.startswith(prefix)]
                payloads[key] = {name[len(prefix):]: z.read(name) for name in members}
                expected.update(members)
                if "drawing.dxf" not in payloads[key]:
                    raise ValueError("Missing editable state")
            if set(names) != expected or state["current"] not in payloads:
                raise ValueError("Incomplete project extension")
        with TemporaryDirectory(prefix="g28-core-open-") as tmp:
            path0 = Path(tmp) / "core.icreview"
            with ZipFile(path0, "w") as z:
                for name, value in core.items():
                    z.writestr(name, value)
            original = ReviewProject.open(path0)
            try:
                if original.snapshot_uuid != state["source_snapshot"]:
                    raise ValueError("Source snapshot mismatch")
            finally:
                original.close()
            current_path = write_files(Path(tmp) / "current", payloads[state["current"]])
            collect(current_path)
        return cls(core, state, payloads, path)

    def save(self, path=None):
        path = Path(path or self.path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_save(path):
            self._save_locked(path)

    def _save_locked(self, path):
        if path.suffix != ".icreview":
            raise ValueError("Choose an explicit .icreview file")
        source_path = Path(json.loads(self.core["project.json"])["source"]["path"]).resolve()
        if path == source_path:
            raise ValueError("Cannot overwrite original source")
        # Optimistic concurrency protects the last usable save.
        if self.path and self.path.exists() and path == self.path:
            with ZipFile(self.path) as z:
                disk = json.loads(z.read(STATE))
            expected = getattr(self, "disk_revision", disk["revision"])
            if disk["revision"] != expected or disk["project_uuid"] != self.state["project_uuid"]:
                raise ValueError("PROJECT_VERSION_CONFLICT")
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=1) as z:
            for name, value in self.core.items():
                z.writestr(name, value)
            z.writestr(STATE, encoded(self.state))
            for key, files in self.payloads.items():
                for name, value in files.items():
                    safe_member(name)
                    z.writestr(f"external-cad/states/{key}/{name}", value)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, suffix=".icreview", delete=False) as f:
            staging = Path(f.name)
            f.write(buffer.getvalue()); f.flush(); os.fsync(f.fileno())
        try:
            checked = type(self).open(staging)
            if checked.state != self.state:
                raise ValueError("Project readback mismatch")
            os.replace(staging, path)
            self.path = path
            self.disk_revision = self.state["revision"]
        finally:
            if staging.exists():
                staging.unlink()

    def export(self, directory):
        directory = Path(directory).resolve()
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError("Use an empty export directory")
        current = self.state["current"]
        path = write_files(directory, self.payloads[current])
        collect(path)
        self.state["exports"][str(path)] = current
        self.state["revision"] += 1
        return path

    def find_base(self, files):
        if self.payloads[self.state["current"]] == files:
            return self.state["current"]
        candidates = [key for key, known in self.payloads.items() if known == files]
        if not candidates:
            raise ValueError("EXPORT_VERSION_UNKNOWN: D0 is not a project CAD state")
        return candidates[-1]

    def preview(self, before, after):
        before_files, _ = collect(before)
        after_files, _ = collect(after)
        base = self.find_base(before_files)
        # Deduplicate an accepted edge on the active lineage, not any payload
        # ever seen. Current D0 -> historical D1 is a restore candidate.
        ancestors = set()
        key = self.state["current"]
        while key is not None:
            ancestors.add(key)
            key = self.state["states"][key]["parent"]
        repeated = base != self.state["current"] and any(
            key in ancestors
            and self.state["states"][key]["parent"] == base
            and self.payloads[key] == after_files
            for key in self.state["accepted_external"]
        )
        if self.payloads[self.state["current"]] == after_files or repeated:
            return {"format": VERSION, "project_uuid": self.state["project_uuid"], "revision": self.state["revision"], "base": base, "before": str(Path(before).resolve()), "after": str(Path(after).resolve()), "status": "ALREADY_ACCEPTED", "confirmation_items": 0}
        with TemporaryDirectory(prefix="g28-preview-input-") as tmp:
            p0 = write_files(Path(tmp) / "before", before_files)
            p1 = write_files(Path(tmp) / "after", after_files)
            after_snapshot = delta.read(p1)
            report = delta.compare(p0, after_snapshot)
            _, _, relation_changes = project_relations(self, base, after_snapshot.rows, report)
        report["before"] = str(Path(before).resolve())
        report["after"] = str(Path(after).resolve())
        conflicts = []
        if self.state["current"] != base:
            with TemporaryDirectory(prefix="g28-local-delta-") as tmp:
                current_path = write_files(tmp, self.payloads[self.state["current"]])
                local = delta.compare(before, current_path)
            touched_local = {c["before"] for c in local["changes"]} | set(local["removed_or_unmatched"])
            touched_external = {c["before"] for c in report["changes"]} | set(report["removed_or_unmatched"])
            conflicts = sorted(touched_local & touched_external)
            # Nonconflicting branches are not merged by this minimal adapter.
            # They remain readable with a clear stale-base decision.
            status = "OBJECT_CONFLICT" if conflicts else "STALE_BASE_REQUIRES_MERGE"
        else:
            status = "READY_FOR_REVIEW"
        content_items = sum(len(report[k]) for k in ("changes", "ambiguous", "removed_or_unmatched", "added_or_unmatched", "document_changes"))
        preview = {"format": VERSION, "project_uuid": self.state["project_uuid"], "revision": self.state["revision"], "base": base, "before": str(Path(before).resolve()), "after": str(Path(after).resolve()), "status": status, "conflicting_members": conflicts, "confirmation_items": content_items + len(relation_changes), "content_confirmation_items": content_items, "relation_confirmation_items": len(relation_changes), "relation_changes": relation_changes, "delta": report}
        self._preview_payload = (deepcopy(preview), after_files)
        return preview

    def accept(self, preview, *, actor):
        if preview["project_uuid"] != self.state["project_uuid"] or preview["revision"] != self.state["revision"]:
            raise ValueError("PREVIEW_VERSION_CONFLICT")
        fresh = self.preview(preview["before"], preview["after"])
        if fresh != preview:
            raise ValueError("INPUT_CHANGED_SINCE_PREVIEW")
        if fresh["status"] == "ALREADY_ACCEPTED":
            return False
        if fresh["status"] != "READY_FOR_REVIEW":
            raise ValueError(fresh["status"])
        if actor not in {"AGENT_REVIEWED", "HUMAN_REVIEWED", "TEST_ONLY"}:
            raise ValueError("Explicit review actor required")
        # Accept the bytes actually compared by fresh preview, not a later
        # reread of a file that an editor could replace between these steps.
        files = self._preview_payload[1]
        with TemporaryDirectory(prefix="g28-accept-input-") as tmp:
            snapshot = delta.read(write_files(tmp, files))
        parent = self.state["current"]
        relations, unresolved, relation_changes = project_relations(self, parent, snapshot.rows, fresh["delta"])
        key = str(uuid4())
        self.payloads[key] = files
        self.state["states"][key] = {"parent": parent, "relations": relations, "origin": preview["after"], "removed_or_unresolved_prior_members": preview["delta"]["removed_or_unmatched"], "unresolved_relation_refs": unresolved}
        self.state["current"] = key
        self.state["accepted_external"].append(key)
        self.state["revision"] += 1
        self.state["journal"].append({"event": "EXTERNAL_CAD_ACCEPT", "at": datetime.now(timezone.utc).isoformat(), "actor": actor, "state": key, "parent": parent, "confirmation_items": preview["confirmation_items"], "relation_changes": relation_changes, "confirmed_source_identities": 0})
        return True

    def undo(self):
        current = self.state["current"]
        parent = self.state["states"][current]["parent"]
        if parent is None:
            raise ValueError("No transaction to undo")
        self.state["current"] = parent
        self.state["revision"] += 1
        self.state["accepted_external"] = [key for key in self.state["accepted_external"] if key != current]
        self.state["journal"].append({"event": "UNDO_EXTERNAL_CAD", "state": current, "restored": parent})

    def edit_text(self, member, text, *, actor):
        """One current-project edit, used to exercise a real divergent branch.

        Member is local to the currently stored CAD, never a matching hint.
        This is an isolated project API, not a general CAD editor.
        """
        with TemporaryDirectory(prefix="g28-project-text-") as tmp:
            before = write_files(Path(tmp) / "before", self.payloads[self.state["current"]])
            after = write_files(Path(tmp) / "after", self.payloads[self.state["current"]])
            doc = delta.ezdxf.readfile(after)
            entity = doc.entitydb.get(member)
            if entity is None or entity.dxftype() not in {"TEXT", "MTEXT"}:
                raise ValueError("Current member is not native text")
            if entity.dxftype() == "TEXT":
                entity.dxf.text = text
            else:
                entity.text = text
            doc.saveas(after)
            preview = self.preview(before, after)
            if self.accept(preview, actor=actor):
                self.state["journal"][-1]["event"] = "PROJECT_TEXT_EDIT"
                self.state["journal"][-1]["member"] = member
                self.state["accepted_external"].remove(self.state["current"])
                return preview
            return preview


def main():
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create"); create.add_argument("--run", required=True); create.add_argument("--d0", required=True); create.add_argument("--project", required=True); create.add_argument("--source-scene", action="store_true")
    preview = sub.add_parser("preview"); preview.add_argument("--project", required=True); preview.add_argument("--before", required=True); preview.add_argument("--after", required=True); preview.add_argument("--output", required=True)
    accept = sub.add_parser("accept"); accept.add_argument("--project", required=True); accept.add_argument("--preview", required=True); accept.add_argument("--actor", required=True, choices=["AGENT_REVIEWED", "HUMAN_REVIEWED", "TEST_ONLY"])
    export = sub.add_parser("export"); export.add_argument("--project", required=True); export.add_argument("--directory", required=True)
    undo = sub.add_parser("undo"); undo.add_argument("--project", required=True)
    edit = sub.add_parser("edit-text"); edit.add_argument("--project", required=True); edit.add_argument("--member", required=True); edit.add_argument("--text", required=True); edit.add_argument("--actor", required=True, choices=["AGENT_REVIEWED", "HUMAN_REVIEWED", "TEST_ONLY"])
    args = parser.parse_args()
    if args.command == "create":
        if Path(args.project).exists():
            raise FileExistsError(args.project)
        project = ReconnectProject.create(args.run, args.d0, source_scene=args.source_scene); project.save(args.project)
        print("CREATED", args.project)
        return
    project = ReconnectProject.open(args.project)
    project.disk_revision = project.state["revision"]
    if args.command == "preview":
        result = project.preview(args.before, args.after)
        atomic_bytes(args.output, encoded(result)); print(result["status"], result["confirmation_items"])
    elif args.command == "accept":
        result = project.accept(json.loads(Path(args.preview).read_text(encoding="utf-8")), actor=args.actor)
        if result:
            project.save()
        print("ACCEPTED" if result else "ALREADY_ACCEPTED")
    elif args.command == "export":
        path = project.export(args.directory); project.save(); print(path)
    elif args.command == "undo":
        project.undo(); project.save(); print("UNDONE")
    elif args.command == "edit-text":
        report = project.edit_text(args.member, args.text, actor=args.actor)
        project.save(); print("PROJECT_TEXT_EDIT", report["confirmation_items"])


if __name__ == "__main__":
    main()
