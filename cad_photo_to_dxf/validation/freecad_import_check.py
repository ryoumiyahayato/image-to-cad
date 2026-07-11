from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import traceback
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _has_nonempty_shape(item: Any) -> bool:
    try:
        shape = item.Shape
        return shape is not None and not shape.isNull()
    except Exception:
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a DXF with FreeCAD and emit machine-readable evidence."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {
        "schema_version": "freecad-import-check/2",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input.resolve()),
        "success": False,
    }
    document = None
    preference_snapshot: dict[str, object] = {}
    try:
        if not args.input.is_file():
            raise FileNotFoundError(args.input)

        import FreeCAD as App  # type: ignore[import-not-found]
        import importDXF  # type: ignore[import-not-found]

        evidence["freecad_version"] = list(App.Version())
        evidence["input_sha256"] = _sha256(args.input)
        preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        preference_snapshot = {
            "dxfShowDialog": preferences.GetBool("dxfShowDialog", True),
            "dxfUseLegacyImporter": preferences.GetBool("dxfUseLegacyImporter", False),
            "dxfUseDraftVisGroups": preferences.GetBool("dxfUseDraftVisGroups", True),
            "DxfImportMode": preferences.GetInt("DxfImportMode", 2),
            "dxfCreateSketch": preferences.GetBool("dxfCreateSketch", False),
            "dxfstarblocks": preferences.GetBool("dxfstarblocks", False),
        }
        preferences.SetBool("dxfShowDialog", False)
        preferences.SetBool("dxfUseLegacyImporter", False)
        preferences.SetBool("dxfUseDraftVisGroups", True)
        preferences.SetInt("DxfImportMode", 2)
        preferences.SetBool("dxfCreateSketch", False)
        preferences.SetBool("dxfstarblocks", False)

        document = importDXF.open(str(args.input.resolve()))
        if document is None:
            raise RuntimeError("FreeCAD DXF importer returned no document")
        document.recompute()
        objects = list(document.Objects)
        object_records = [
            {
                "name": item.Name,
                "label": item.Label,
                "type_id": item.TypeId,
                "has_shape": _has_nonempty_shape(item),
            }
            for item in objects
        ]
        shape_object_count = sum(
            1 for record in object_records if bool(record["has_shape"])
        )
        evidence["document_name"] = document.Name
        evidence["object_count"] = len(objects)
        evidence["shape_object_count"] = shape_object_count
        evidence["objects"] = object_records
        evidence["success"] = len(objects) > 0 and shape_object_count > 0
        if not objects:
            raise RuntimeError("FreeCAD imported the DXF but created no document objects")
        if shape_object_count == 0:
            raise RuntimeError(
                "FreeCAD created document objects but none contained non-empty geometry"
            )
        return_code = 0
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        evidence["error"] = str(exc)
        evidence["traceback"] = traceback.format_exc()
        return_code = 1
    finally:
        try:
            if preference_snapshot:
                import FreeCAD as App  # type: ignore[import-not-found]

                preferences = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
                preferences.SetBool(
                    "dxfShowDialog", bool(preference_snapshot["dxfShowDialog"])
                )
                preferences.SetBool(
                    "dxfUseLegacyImporter",
                    bool(preference_snapshot["dxfUseLegacyImporter"]),
                )
                preferences.SetBool(
                    "dxfUseDraftVisGroups",
                    bool(preference_snapshot["dxfUseDraftVisGroups"]),
                )
                preferences.SetInt(
                    "DxfImportMode", int(preference_snapshot["DxfImportMode"])
                )
                preferences.SetBool(
                    "dxfCreateSketch", bool(preference_snapshot["dxfCreateSketch"])
                )
                preferences.SetBool(
                    "dxfstarblocks", bool(preference_snapshot["dxfstarblocks"])
                )
                if document is not None:
                    App.closeDocument(document.Name)
        except Exception as cleanup_error:
            evidence["cleanup_error"] = str(cleanup_error)
            return_code = 1
        evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return return_code


if __name__ == "__main__":
    sys.exit(main())
