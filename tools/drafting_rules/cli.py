"""Independent saved-DXF validation and report comparison (no conversion)."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

from jsonschema import Draft202012Validator
from jsonschema import ValidationError
import ezdxf
from tools.drafting_rules.dxf_adapter import digest, sha256, snapshot
from tools.drafting_rules.engine import evaluate

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))

DATA = Path(__file__).parent / "pack"


def read_json(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON value: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def load_pack(path=DATA / "manifest.json"):
    pack = read_json(path)
    Draft202012Validator(read_json(DATA / "pack.schema.json")).validate(pack)
    sources = {s["id"]: s for s in pack["sources"]}
    if len(sources) != len(pack["sources"]) or len({r["id"] for r in pack["rules"]}) != len(pack["rules"]):
        raise ValueError("Duplicate source or rule identity")
    for rule in pack["rules"]:
        if not all(s in sources for s in rule["sources"]):
            raise ValueError("Unresolved rule source")
        if rule["classification"] == "OFFICIAL_STANDARD":
            if not all(sources[s].get("verified_full_text") and sources[s].get("edition")
                       and sources[s].get("clause") for s in rule["sources"]):
                raise ValueError("Official standard rule requires verified edition and clause")
    required = {"editable-text", "cell-fit", "source-glyph-exit", "background-protection",
                "table-line-parity", "edit-isolation"}
    if {r["id"] for r in pack["rules"] if r["state"] == "IMPLEMENTED"} != required:
        raise ValueError("Pack rules differ from this engine's supported contract")
    return pack


def validate_files(before, after, source, evidence_path, pack_path=DATA / "manifest.json"):
    evidence = read_json(evidence_path)
    Draft202012Validator(read_json(DATA / "evidence.schema.json")).validate(evidence)
    for key, path in (("before_sha256", before), ("after_sha256", after)):
        if evidence[key] != sha256(path):
            raise ValueError(f"Stale evidence: {key}")
    if evidence["source"]["sha256"] != sha256(source):
        raise ValueError("Source digest differs from evidence")
    region = evidence["source"]["region"]
    if not (region[0] < region[2] and region[1] < region[3]):
        raise ValueError("Source region must have positive width and height")
    expected_units = ezdxf.units.MM if evidence["source"]["units"] == "mm" else 0
    if any(ezdxf.readfile(p).units != expected_units for p in (before, after)):
        raise ValueError("DXF units differ from the declared coordinate contract")
    ids = [t["id"] for t in evidence["texts"]]
    handles = [t["handle"] for t in evidence["texts"]]
    if len(set(ids)) != len(ids) or len(set(handles)) != len(handles):
        raise ValueError("Duplicate text target")
    for text in evidence["texts"]:
        if "cell" in text and not (text["cell"][0] < text["cell"][2] and text["cell"][1] < text["cell"][3]):
            raise ValueError("Cell must have positive width and height")
    # JSON Schema accepts huge exponents as inf in some parsers.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite evidence")
        if isinstance(value, dict):
            for v in value.values():
                finite(v)
        elif isinstance(value, list):
            for v in value:
                finite(v)
    finite(evidence)
    pack = load_pack(pack_path)
    result = evaluate(evidence, snapshot(before), snapshot(after), pack)
    implementation = {name: sha256(Path(__file__).parent / name)
                      for name in ("engine.py", "dxf_adapter.py", "cli.py")}
    implementation["librecad_lff.py"] = sha256(ROOT / "cad_photo_to_dxf/app/ocr/librecad_lff.py")
    font = ROOT / "cad_photo_to_dxf/resources/fonts/wqy-unicode.lff"
    runtime = dict(python=platform.python_version())
    for name in ("ezdxf", "PySide6", "jsonschema"):
        try:
            runtime[name] = version(name)
        except PackageNotFoundError:
            runtime[name] = None
    result.update(pack_sha256=digest(pack), evidence_sha256=sha256(evidence_path),
                  before_sha256=sha256(before), after_sha256=sha256(after),
                  implementation_sha256=digest(implementation),
                  font_sha256=sha256(font) if font.exists() else None,
                  runtime=runtime)
    return result


def compare_reports(old, new):
    if old["pack_id"] != new["pack_id"] or old["source"] != new["source"]:
        raise ValueError("Reports have different packs or source scopes")
    def index(report):
        return {(r["rule"], r["target"]): r for r in report["results"]}
    a, b = index(old), index(new)
    changes = []
    for key in sorted(set(a) | set(b)):
        left, right = a.get(key), b.get(key)
        if left != right:
            changes.append(dict(rule=key[0], target=key[1], before=left, after=right))
    return dict(old_version=old["pack_version"], new_version=new["pack_version"],
                old_pack_sha256=old.get("pack_sha256"), new_pack_sha256=new.get("pack_sha256"),
                old_dxf_sha256=old.get("after_sha256"), new_dxf_sha256=new.get("after_sha256"),
                old_implementation_sha256=old.get("implementation_sha256"),
                new_implementation_sha256=new.get("implementation_sha256"),
                changes=changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    for name in ("before", "after", "source", "evidence", "output"):
        check.add_argument("--" + name, required=True, type=Path)
    check.add_argument("--pack", type=Path, default=DATA / "manifest.json")
    check.add_argument("--strict", action="store_true", help="ABSTAIN also gives exit 1")
    diff = sub.add_parser("compare")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)
    diff.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite reviewed evidence or an input, even on error.
    if args.output.exists():
        parser.error("Output already exists; choose a new path")
    try:
        if args.command == "validate":
            result = validate_files(args.before, args.after, args.source, args.evidence, args.pack)
            code = int(bool(result["summary"].get("FAIL") or
                            args.strict and result["summary"].get("ABSTAIN")))
        else:
            result = compare_reports(read_json(args.old), read_json(args.new))
            code = 0
    except (ValueError, OSError, ezdxf.DXFError, ValidationError) as error:
        result, code = dict(status="INPUT_ERROR", message=str(error)), 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result.get("summary", result), ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
