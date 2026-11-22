"""Compare an actual portable EXE with its source revision on a generated input.

Run this helper from a copy outside the source checkout. It executes the source
CLI first, then temporarily hides the application's original source directory
and executes a detached copy of the shipped bundle with a clean environment.
All recognition/adoption is the ordinary manager/worker pipeline. The known
fixture content is checked only after saving; it is never an OCR hint.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_fixture(path: Path, font_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 560, 400), outline=0, width=3)
    draw.line((100, 280, 400, 280), fill=0, width=3)
    # Same permitted generated fixture as maintenance/native_cli_smoke.py;
    # an explicit shipped font makes generation independent of host fonts.
    font = ImageFont.truetype(str(font_path), 24)
    draw.text((120, 130), "ROOM 17", font=font, fill=0)
    image.save(path, dpi=(200, 200))


def canonical_value(value):
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): canonical_value(v) for k, v in sorted(value.items())}
    try:
        return [canonical_value(item) for item in value]
    except TypeError:
        return str(value)


def entity_geometry(entity, document) -> dict:
    attributes = dict(entity.dxf.all_existing_dxf_attribs())
    for key in ("handle", "owner", "paperspace", "material_handle", "plotstyle_handle"):
        attributes.pop(key, None)
    result = {"type": entity.dxftype(), "attributes": canonical_value(attributes)}
    if entity.dxftype() == "LWPOLYLINE":
        result["points"] = canonical_value(list(entity.get_points("xyseb")))
    if entity.dxftype() == "POLYLINE":
        result["points"] = canonical_value([vertex.dxf.location for vertex in entity.vertices])
    if entity.dxftype() == "INSERT":
        result["members"] = [entity_geometry(member, document) for member in document.blocks[entity.dxf.name]]
    return result


def inspect_result(work: Path, source_sha: str, *, frozen: bool) -> dict:
    import ezdxf

    target = work / "native.dxf"
    document = ezdxf.readfile(target)
    audit = document.audit()
    if audit.errors or audit.fixes or document.units != 4:
        raise AssertionError("Actual saved DXF failed cold audit/paper-mm units")
    entities = [entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"]
    types = Counter(entity.dxftype() for entity in entities)
    if types["LINE"] != 5 or any(types[kind] for kind in ("HATCH", "IMAGE")):
        raise AssertionError("Controlled input lost expected real native line geometry")
    texts = []
    for entity in entities:
        members = list(entity.virtual_entities()) if entity.dxftype() == "INSERT" else [entity]
        texts += [member.dxf.text for member in members if member.dxftype() == "TEXT"]
        texts += [member.plain_text() for member in members if member.dxftype() == "MTEXT"]
    if "ROOM 17" not in texts:
        raise AssertionError("Controlled input did not save its complete editable native text")
    companion = target.with_suffix(".native")
    objects = json.loads((companion / "result.objects.json").read_text(encoding="utf-8"))
    font = objects["font"]
    if digest(companion / font["font"]) != font["sha256"] or not (companion / font["bundled_license"]).is_file():
        raise AssertionError("Saved native text has missing or changed bundled font/license")
    cold = json.loads((companion / "evidence/cold_audit.json").read_text(encoding="utf-8"))
    if not cold["source_gate_pass"] or not cold["dxf_unchanged"]:
        raise AssertionError("Actual published native result failed its saved source audit")
    entry = json.loads((companion / "result.entry_trace.json").read_text(encoding="utf-8"))
    if entry["mode"] != "native-objects" or entry["legacy_processing_called"] or entry["legacy_export_called"] or entry["source_sha256"] != source_sha:
        raise AssertionError("EXE did not enter the source-bound native pipeline")
    states = list((work / "jobs").glob("*/state.json"))
    if len(states) != 1:
        raise AssertionError("Smoke did not create exactly one real managed task")
    state = json.loads(states[0].read_text(encoding="utf-8"))
    if state["status"] != "COMPLETED_WITH_ISSUES" or state.get("connection_checkpoint") or state.get("checkpoint_import"):
        raise AssertionError("Smoke did not complete ordinary native recognition")
    if state["raw_observation_cache"]["entry_count"] != 0:
        raise AssertionError("Smoke inherited an old recognition cache")
    command = state["attempts"][0]["command"]
    if "--native-worker" not in command or (frozen and (len(command) != 3 or not command[0].lower().endswith(".exe"))):
        raise AssertionError("Native conversion bypassed the actual packaged worker")
    if frozen and "frozen_application_executable" not in state["algorithm"]["files"]:
        raise AssertionError("Packaged native result was not bound to the EXE")
    policies = list((companion / "evidence").rglob("policy_frozen_before_recognition.json"))
    policies = [json.loads(path.read_text(encoding="utf-8")) for path in policies]
    engines = [row["engine"] for row in policies if "engine" in row]
    if not engines:
        raise AssertionError("No actual Tesseract producer evidence was saved")
    if not list((companion / "evidence").rglob("*.tsv")):
        raise AssertionError("No actual raw OCR observation was saved")
    models = [json.loads(path.read_text(encoding="utf-8")) for path in (companion / "evidence").rglob("model_identity.json")]
    if not models or not all(row.get("providers") == ["CPUExecutionProvider"] for row in models):
        raise AssertionError("Native flow did not initialize its bundled independent model")
    model_summary = json.loads((companion / "evidence/cross_engine_text/summary.json").read_text(encoding="utf-8"))
    if model_summary["actual_model_calls"] <= 0:
        raise AssertionError("Native flow did not execute its independent recognizer")
    snapshot = sorted([entity_geometry(entity, document) for entity in entities], key=lambda row: json.dumps(row, sort_keys=True))
    write_json(work / "geometry.json", {"entities": snapshot})
    return {
        "dxf_sha256": digest(target),
        "formal_entity_count": len(entities),
        "formal_types": dict(sorted(types.items())),
        "editable_texts": texts,
        "geometry_sha256": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
        "geometry": snapshot,
        "entry_trace": entry,
        "worker_command": command,
        "task_status": state["status"],
        "algorithm": state["algorithm"],
        "tesseract_engines": engines,
        "independent_models": models,
        "actual_independent_model_calls": model_summary["actual_model_calls"],
        "initial_raw_observation_count": 0,
        "actual_source_ocr_saved": True,
        "export_font": font,
        "cold_audit_errors": 0,
        "cold_audit_fixes": 0,
    }


def run_cli(command: list[str], source: Path, work: Path, environment: dict) -> None:
    work.mkdir()
    arguments = command + [
        "--headless", "--mode", "native-objects", "--input", str(source),
        "--roi", "0", "0", "640", "480", "--dpi", "200", "--orientation", "0",
        "--output", str(work / "native.dxf"), "--jobs-dir", str(work / "jobs"),
        "--cpu-seconds", "300", "--wall-seconds", "360", "--verbose",
    ]
    write_json(work / "command.json", {"arguments": arguments, "started_unix": time.time()})
    with (work / "stdout.txt").open("w", encoding="utf-8") as out, (work / "stderr.txt").open("w", encoding="utf-8") as err:
        process = subprocess.run(arguments, cwd=work, env=environment, stdout=out, stderr=err, timeout=400, check=False)
    write_json(work / "process.json", {"exit_code": process.returncode, "finished_unix": time.time()})
    if process.returncode:
        raise RuntimeError(f"Actual native CLI failed: {process.returncode}; evidence retained in {work}")


def clean_environment() -> dict:
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "I2CAD_RAW_OBSERVATION_CACHE", "I2CAD_TESSERACT", "TESSDATA_PREFIX", "I2CAD_JOBS_ROOT"):
        environment.pop(key, None)
    environment.update(OMP_NUM_THREADS="1", OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONNOUSERSITE="1")
    return environment


def run(executable: Path, source_main: Path, work: Path, expected_version: str) -> dict:
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    app_root = source_main.resolve().parent
    original_executable = executable.resolve()
    package = work / "detached-package"
    shutil.copytree(original_executable.parent, package)
    executable = package / original_executable.name
    bundle = package / "_internal"
    manifest = json.loads((bundle / "resources/native-build.json").read_text(encoding="utf-8"))
    product = json.loads((bundle / "docs/product/product_status.generated.json").read_text(encoding="utf-8"))
    if manifest["application_version"] != expected_version or product["status"] != "LOCAL_NO_GO" or product["running_pipeline"] != "native-objects":
        raise AssertionError("Packaged product metadata has wrong version")
    for relative, expected in manifest["application_sources"].items():
        if digest(app_root / relative) != expected or digest(bundle / relative) != expected:
            raise AssertionError("Packaged code evidence differs from same-version source: " + relative)
    fixture = work / "controlled-source.png"
    create_fixture(fixture, bundle / "resources/fonts/DejaVuSans.ttf")
    source_sha = digest(fixture)
    environment = clean_environment()
    run_cli([sys.executable, str(source_main.resolve())], fixture, work / "source-run", environment)
    source_result = inspect_result(work / "source-run", source_sha, frozen=False)
    # Only this controlled CI checkout is hidden, and always restored. The
    # helper, fixture and detached bundle are outside it before this point.
    if app_root in work.parents or Path(__file__).resolve().is_relative_to(app_root):
        raise ValueError("Run the smoke helper and evidence outside the source directory")
    hidden = app_root.with_name(app_root.name + ".native-smoke-hidden-" + uuid.uuid4().hex)
    profile = work / "clean-user-profile"
    profile.mkdir()
    environment.update(
        PATH=str(Path(os.environ["SystemRoot"]) / "System32") + os.pathsep + os.environ["SystemRoot"],
        USERPROFILE=str(profile), APPDATA=str(profile / "AppData/Roaming"),
        LOCALAPPDATA=str(profile / "AppData/Local"),
    )
    environment.pop("HOME", None)
    for key in ("APPDATA", "LOCALAPPDATA"):
        Path(environment[key]).mkdir(parents=True)
    app_root.rename(hidden)
    try:
        if app_root.exists():
            raise AssertionError("Original application source is still available")
        run_cli([str(executable)], fixture, work / "exe-run", environment)
        exe_result = inspect_result(work / "exe-run", source_sha, frozen=True)
    finally:
        hidden.rename(app_root)
    if source_result["geometry"] != exe_result["geometry"]:
        raise AssertionError("Packaged native geometry/text differs from same-version source; both actual DXFs retained")
    if digest(fixture) != source_sha:
        raise AssertionError("Native conversion changed the generated input")
    for engine in exe_result["tesseract_engines"]:
        if not Path(engine["executable"]).resolve().is_relative_to(bundle):
            raise AssertionError("EXE used an external Tesseract installation")
    for model in exe_result["independent_models"]:
        if not Path(model["model_path"]).resolve().is_relative_to(bundle):
            raise AssertionError("EXE used a model outside its bundle")
    if not Path(exe_result["export_font"]["source"]).resolve().is_relative_to(bundle):
        raise AssertionError("EXE used an export font outside its bundle")
    for result in (source_result, exe_result):
        result.pop("geometry")
    report = {
        "status": "PASS", "schema": "windows-native-exe-smoke-v1",
        "application_version": expected_version, "source_commit": manifest["source_commit"],
        "source_sha256": source_sha, "executable_sha256": digest(executable),
        "same_source_saved_geometry_and_text_equal": True,
        "source_result": source_result, "exe_result": exe_result,
        "original_application_source_hidden_during_EXE_execution": True,
        "source_directory_restored": app_root.is_dir(),
        "EXE_PATH_contains_only_windows_system_directories": True,
        "EXE_clean_user_profile": True,
        "bundled_source_audit_resources_match_checkout": True,
        "explicit_cache_or_adoption_whitelist": False,
        "expected_text_sent_to_recognizer": False,
        "generated_controlled_input_only_not_real_drawing_quality_acceptance": True,
        "product_GO": False,
    }
    write_json(work / "native-smoke.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--source-main", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    try:
        report = run(args.executable, args.source_main, args.work_dir, args.expected_version)
    except BaseException as exc:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.work_dir / "native-smoke-failure.json", {"status": "FAILED", "type": type(exc).__name__, "message": str(exc), "product_GO": False})
        raise
    print(json.dumps({key: report[key] for key in ("status", "source_commit", "source_sha256", "same_source_saved_geometry_and_text_equal")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
