"""Exercise the delivered Windows recovery scripts and real EXE font service.

This is automated Windows/file-level evidence. It deliberately does not label
process startup, PDF conversion, or ezdxf editing as a LibreCAD GUI edit test.
Private production drawings never enter this public Actions check.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.portable_delivery import make_delivery, sha256_file  # noqa: E402


LIBRECAD_VERSION = "2.2.1.6"
LIBRECAD_URL = (
    "https://github.com/LibreCAD/LibreCAD/releases/download/v2.2.1.6/"
    "LibreCAD-v2.2.1.6-win64-msvc.exe"
)
LIBRECAD_SHA256 = "0cd876d0e3fbfcdcdb85e5019080aca243908f4ad5c3b3c93a55ee9ba154f95b"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_process(command: list[str] | str, *, cwd: Path, timeout: int = 120) -> dict:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("QT_PLUGIN_PATH", None)
    completed = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, timeout=timeout,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", errors="replace")[-12000:],
        "stderr": completed.stderr.decode("utf-8", errors="replace")[-12000:],
    }


def restore_command(script: Path, report: Path, *, launch: bool) -> str:
    # cmd /s /c needs its own outer quote pair around a quoted script path.
    # Windows filenames cannot contain a double quote. No untrusted flags or
    # manifest content are interpolated into this test-only invocation.
    flags = "-NoPause" + ("" if launch else " -NoLaunch")
    return f'"{os.environ["COMSPEC"]}" /d /s /c ""{script}" {flags} -ReportPath "{report}""'


def link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def stop_test_process(pid: int) -> None:
    import psutil

    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        process.terminate()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs([process, *children], timeout=8)
        for item in alive:
            item.kill()
    except psutil.NoSuchProcess:
        pass


def restore_case(
    *, delivery: Path, directory: Path, manifest: dict, include_parts: bool = True,
    include_archive: bool = False, launch: bool = False, omit_part: str | None = None,
    damage_part: str | None = None, conflict_zip: bool = False, conflict_directory: bool = False,
) -> dict:
    directory.mkdir(parents=True)
    for name in ("Restore-Windows-portable.cmd", "Restore-Windows-portable.ps1", "PORTABLE_RESTORE_MANIFEST.json"):
        shutil.copyfile(delivery / name, directory / name)
    if include_parts:
        for item in manifest["parts"]:
            if item["file"] == omit_part:
                continue
            source, target = delivery / item["file"], directory / item["file"]
            if item["file"] == damage_part:
                shutil.copyfile(source, target)
                with target.open("r+b") as stream:
                    first = stream.read(1)
                    stream.seek(0)
                    stream.write(bytes([first[0] ^ 0xFF]))
            else:
                link_or_copy(source, target)
    archive = directory / manifest["original_file"]
    if include_archive:
        link_or_copy(delivery / manifest["original_file"], archive)
    sentinels: dict[Path, str] = {}
    if conflict_zip:
        archive.write_bytes(b"USER_EXISTING_DIFFERENT_ZIP_DO_NOT_OVERWRITE")
        sentinels[archive] = sha256_file(archive)
    if conflict_directory:
        existing = directory / manifest["extract_directory"]
        existing.mkdir()
        sentinel = existing / "CADPhotoToDXF.exe"
        sentinel.write_bytes(b"USER_EXISTING_DIFFERENT_PROGRAM_DO_NOT_OVERWRITE")
        sentinels[sentinel] = sha256_file(sentinel)
    if damage_part:
        sentinels[directory / damage_part] = sha256_file(directory / damage_part)
    report_path = directory / "restore-report.json"
    command = restore_command(directory / "Restore-Windows-portable.cmd", report_path, launch=launch)
    execution = run_process(command, cwd=directory, timeout=900)
    report = read_json(report_path)
    report["execution"] = execution
    report["preexisting_files_unchanged"] = all(sha256_file(path) == value for path, value in sentinels.items())
    if not report["preexisting_files_unchanged"]:
        raise AssertionError("Recovery changed an existing user file")
    if any(directory.glob(".cadphoto-assembling-*")) or any(directory.glob(".cadphoto-extracting-*")):
        raise AssertionError("Recovery left its own partial output behind")
    write_json(report_path, report)
    return report


def check_restoration(delivery: Path, work: Path, manifest: dict) -> tuple[Path, dict]:
    work.mkdir(parents=True)
    cases = {}
    first_part = manifest["parts"][0]["file"]
    for name, options, expected in (
        ("missing-part", {"omit_part": first_part}, "MISSING_PART"),
        ("damaged-part", {"damage_part": first_part}, "PART_MISMATCH"),
        ("existing-different-zip", {"conflict_zip": True}, "EXISTING_ZIP_CONFLICT"),
        ("existing-different-directory", {"include_parts": False, "include_archive": True, "conflict_directory": True}, "EXISTING_DIRECTORY_CONFLICT"),
    ):
        report = restore_case(delivery=delivery, directory=work / name, manifest=manifest, **options)
        cases[name] = report
        if report["status"] != "FAILED" or report["code"] != expected or report["execution"]["returncode"] == 0:
            raise AssertionError(f"Recovery negative case {name} did not fail correctly: {report}")
        if name in {"missing-part", "damaged-part"} and (work / name / manifest["original_file"]).exists():
            raise AssertionError("Recovery published a ZIP before all parts passed")
    positive_directory = work / "fresh Windows directory"
    positive = restore_case(delivery=delivery, directory=positive_directory, manifest=manifest, launch=True)
    cases["fresh-directory-parts-restore-extract-launch"] = positive
    if positive["status"] != "PREPARED" or positive["execution"]["returncode"] or not positive["launched"]:
        raise AssertionError(f"Actual Windows restoration/EXE launch failed: {positive}")
    stop_test_process(positive["process_id"])
    restored = positive_directory / manifest["extract_directory"]
    # Ordinary second execution must retain program files and any user-added file.
    sentinel = restored / "existing-user-note.txt"
    sentinel.write_text("Keep this user file unchanged.\n", encoding="utf-8")
    sentinel_hash = sha256_file(sentinel)
    repeat_path = positive_directory / "repeat-report.json"
    repeat_execution = run_process(
        restore_command(positive_directory / "Restore-Windows-portable.cmd", repeat_path, launch=False),
        cwd=positive_directory, timeout=900,
    )
    repeat = read_json(repeat_path)
    repeat["execution"] = repeat_execution
    repeat["additional_user_file_unchanged"] = sha256_file(sentinel) == sentinel_hash
    cases["repeat-existing-identical-archive-and-directory"] = repeat
    if (repeat["status"] != "PREPARED" or repeat_execution["returncode"] or not repeat["archive_reused"]
            or not repeat["directory_reused"] or not repeat["additional_user_file_unchanged"]):
        raise AssertionError("Repeated recovery was not stable")
    result = {
        "status": "PASS", "actual_windows_execution": True,
        "archive_sha256": manifest["original_sha256"], "archive_bytes": manifest["original_bytes"],
        "program_file_count": len(manifest["files"]), "cases": cases,
        "manual_gui_interaction": "NOT_RUN",
    }
    write_json(work / "restoration-checks.json", result)
    return restored / "CADPhotoToDXF.exe", result


def install_librecad(work: Path) -> tuple[Path, dict]:
    installer = work / "LibreCAD-v2.2.1.6-win64-msvc.exe"
    request = Request(LIBRECAD_URL, headers={"User-Agent": "Image-to-CAD-Windows-delivery-check"})
    with urlopen(request, timeout=60) as source, installer.open("xb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    if sha256_file(installer) != LIBRECAD_SHA256:
        raise AssertionError("Official fixed LibreCAD installer hash differs")
    destination = work / "librecad-2.2.1.6"
    if " " in str(destination):
        raise ValueError("NSIS CI installation directory must not contain spaces")
    execution = run_process([str(installer), "/S", "/D=" + str(destination)], cwd=work, timeout=180)
    executable = destination / "LibreCAD.exe"
    if execution["returncode"] or not executable.is_file():
        raise AssertionError(f"Verified LibreCAD installer failed: {execution}")
    receipt = {
        "official_url": LIBRECAD_URL, "installer_sha256": LIBRECAD_SHA256,
        "version": LIBRECAD_VERSION, "executable": str(executable),
        "executable_sha256": sha256_file(executable), "execution": execution,
    }
    write_json(work / "librecad-installation.json", receipt)
    return executable, receipt


def cad_command(executable: Path, action: str, result: Path, cad: Path, work: Path, name: str) -> dict:
    report_path = work / f"{name}.json"
    execution = run_process([
        str(executable), "cad-fonts", action, "--result", str(result),
        "--cad-executable", str(cad), "--report", str(report_path),
    ], cwd=work, timeout=180)
    if not report_path.is_file():
        raise AssertionError(f"Actual packaged font command did not write its report: {execution}")
    report = read_json(report_path)
    report["execution"] = execution
    write_json(report_path, report)
    return report


def directory_snapshot(directory: Path) -> dict[str, dict]:
    if not directory.exists():
        return {}
    return {
        str(path.relative_to(directory)): {"sha256": sha256_file(path), "mtime_ns": path.stat().st_mtime_ns}
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def cad_processes(executable: Path) -> dict[int, dict]:
    import psutil

    found = {}
    for process in psutil.process_iter(["pid", "exe", "create_time"]):
        try:
            if process.info["exe"] and Path(process.info["exe"]).resolve() == executable.resolve():
                found[process.pid] = process.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    return found


def render_pdf(cad: Path, dxf: Path, output: Path, work: Path) -> dict:
    execution = run_process([
        str(cad), "dxf2pdf", "--fit", "--paper", "210x297", "--monochrome",
        "--outfile", str(output), str(dxf),
    ], cwd=work, timeout=180)
    if execution["returncode"] or not output.is_file() or output.stat().st_size < 100:
        raise AssertionError(f"Actual LibreCAD dxf2pdf failed: {execution}")
    import pymupdf

    with pymupdf.open(output) as document:
        if len(document) != 1:
            raise AssertionError("Controlled CAD font probe unexpectedly spans multiple PDF pages")
        page = document[0]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image_path = output.with_suffix(".png")
        pixmap.save(image_path)
        drawings = page.get_drawings()
        if not drawings:
            raise AssertionError("LibreCAD PDF did not contain drawn text outlines")
        paths = sum(len(item.get("items", [])) for item in drawings)
    return {
        "execution": execution, "pdf": str(output), "pdf_sha256": sha256_file(output),
        "rendered_png": str(image_path), "png_sha256": sha256_file(image_path),
        "drawn_path_segments": paths, "evidence_class": "ACTUAL_LIBRECAD_FILE_LEVEL_RENDER_NOT_GUI",
    }


def make_font_probes(directory: Path, native_result: Path) -> list[Path]:
    import ezdxf

    original = ezdxf.readfile(native_result)
    result = []
    for style in ("I2CAD_SOURCE_ROW", "I2CAD_TEXT"):
        members = [entity for entity in original.modelspace().query("TEXT") if entity.dxf.style == style]
        if not members:
            raise AssertionError("Existing real EXE conversion lacks its expected style: " + style)
        document = ezdxf.new("R2010")
        document.units = 4
        document.styles.new(style, dxfattribs={"font": original.styles.get(style).dxf.font})
        text = members[0].dxf.text
        document.modelspace().add_text(text, dxfattribs={"style": style, "height": 6, "insert": (5, 10)})
        # Fixed registration frame keeps fit-to-page comparable before/after.
        document.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 30), (0, 30)], close=True)
        path = directory / f"font-probe-{style}.dxf"
        document.saveas(path)
        result.append(path)
    return result


def file_edit_isolation(original: Path, work: Path) -> dict:
    import ezdxf

    document = ezdxf.readfile(original)
    target = next(entity for entity in document.modelspace().query("TEXT") if entity.dxf.style == "I2CAD_SOURCE_ROW")
    target_handle = target.dxf.handle

    def stable_entities(doc):
        result = {}
        from ezdxf.lldxf.tagwriter import TagCollector
        for entity in doc.modelspace():
            if entity.dxf.handle != target_handle:
                result[entity.dxf.handle] = [(tag.code, str(tag.value)) for tag in TagCollector.dxftags(entity)]
        return result

    before = stable_entities(document)
    content = target.dxf.text
    target.dxf.text = "TEST-A7,03"
    edited = work / "file-edit-TEXT.dxf"
    document.saveas(edited)
    reopened = ezdxf.readfile(edited)
    if reopened.entitydb[target_handle].dxf.text != "TEST-A7,03" or stable_entities(reopened) != before:
        raise AssertionError("File-level TEXT edit changed independent neighbors")
    document = ezdxf.readfile(original)
    document.modelspace().delete_entity(document.entitydb[target_handle])
    deleted = work / "file-delete-TEXT.dxf"
    document.saveas(deleted)
    reopened = ezdxf.readfile(deleted)
    if target_handle in reopened.entitydb or stable_entities(reopened) != before:
        raise AssertionError("File-level TEXT deletion changed independent neighbors")
    return {
        "status": "PASS", "original_content": content, "edited_content": "TEST-A7,03",
        "changed_handle": target_handle, "unchanged_other_entities": len(before),
        "edited_file": str(edited), "deleted_file": str(deleted),
        "evidence_class": "EZDXF_FILE_LEVEL_SAVE_REOPEN_NOT_LIBRECAD_GUI",
        "source_approval_inherited_by_edited_content": False,
    }


def check_fonts(executable: Path, native_result: Path, work: Path) -> dict:
    import psutil
    from PySide6.QtCore import QSettings, QStandardPaths

    work.mkdir(parents=True)
    cad, installation = install_librecad(work)
    documents = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    if not documents.is_absolute():
        raise AssertionError("Qt did not return the real Windows Documents Known Folder")
    font_directory = documents / "librecad" / "fonts"
    for name in ("I2CAD_TEXT.lff", "I2CAD_SOURCE_ROW.lff"):
        if (font_directory / name).exists():
            raise AssertionError("Windows check is not a clean first-use font condition: " + str(font_directory / name))
    font_directory.mkdir(parents=True, exist_ok=True)
    sentinel_font = font_directory / "UserExistingFont.lff"
    if sentinel_font.exists():
        raise AssertionError("Existing user sentinel path must not be overwritten")
    sentinel_font.write_text("# Format: LibreCAD Font 1\n# Name: User Existing Font\n# LetterSpacing: 1\n[0041]\n0,0;4,9;8,0\n", encoding="utf-8")
    sentinel_digest = sha256_file(sentinel_font)
    settings = QSettings("LibreCAD", "LibreCAD")
    setting_key = "DeliveryCheck/ExistingUserValue"
    if settings.contains(setting_key):
        raise AssertionError("Existing settings sentinel must not be overwritten")
    settings.setValue(setting_key, "Preserve this unrelated user setting")
    settings.sync()

    def settings_snapshot():
        settings.sync()
        return {key: repr(settings.value(key)) for key in settings.allKeys()}

    result_path = work / "native-result.dxf"
    shutil.copyfile(native_result, result_path)
    shutil.copytree(native_result.with_suffix(".native"), result_path.with_suffix(".native"))
    initial_result_hash = sha256_file(result_path)
    probes = make_font_probes(work, result_path)
    before_pdfs = {path.stem: render_pdf(cad, path, work / (path.stem + "-before.pdf"), work) for path in probes}
    initial = cad_command(executable, "inspect", result_path, cad, work, "01-inspect-fresh")
    if initial["status"] != "NOT_PREPARED" or initial["execution"]["returncode"] != 2 or not initial["can_prepare"]:
        raise AssertionError(f"Fresh actual font inspection did not find missing fonts: {initial}")
    missing_cad = cad_command(executable, "inspect", result_path, work / "missing-cad.exe", work, "02-missing-cad")
    if missing_cad["can_launch"] or missing_cad.get("launch_requested"):
        raise AssertionError("Missing CAD executable was reported launchable")
    conflict = font_directory / "I2CAD_SOURCE_ROW.lff"
    conflict.write_bytes(b"Existing different font: must not be overwritten")
    conflict_hash = sha256_file(conflict)
    conflict_before = directory_snapshot(font_directory)
    settings_before = settings_snapshot()
    conflict_result = cad_command(executable, "prepare", result_path, cad, work, "03-font-conflict")
    if conflict_result["status"] != "FAILED" or sha256_file(conflict) != conflict_hash:
        raise AssertionError("Font preparation overwrote or accepted conflicting user font")
    if directory_snapshot(font_directory) != conflict_before or settings_snapshot() != settings_before:
        raise AssertionError("Failed font preparation partially changed user resources/settings")
    conflict.unlink()  # Only the conflict file created above by this check.
    before_processes = set(cad_processes(cad))
    launched = subprocess.Popen([str(cad), str(result_path)], cwd=work)
    owned_cad: set[int] = {launched.pid}
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (set(cad_processes(cad)) - before_processes):
            time.sleep(0.2)
        owned_cad.update(set(cad_processes(cad)) - before_processes)
        if not owned_cad or launched.poll() is not None:
            raise AssertionError("Actual LibreCAD startup failed before restart-state test")
        time.sleep(1)
        settings_before = settings_snapshot()
        prepared_running = cad_command(executable, "prepare", result_path, cad, work, "04-prepare-running-cad")
        if prepared_running["status"] != "REOPEN_REQUIRED" or prepared_running["execution"]["returncode"] != 3:
            raise AssertionError(f"Copying fonts into a running CAD was falsely reported active: {prepared_running}")
        installed_snapshot = directory_snapshot(font_directory)
        if not all((font_directory / name).is_file() for name in ("I2CAD_TEXT.lff", "I2CAD_SOURCE_ROW.lff")):
            raise AssertionError("Actual packaged EXE did not prepare both required LibreCAD styles")
        repeated_running = cad_command(executable, "prepare", result_path, cad, work, "05-repeat-running-cad")
        if repeated_running["status"] != "REOPEN_REQUIRED" or directory_snapshot(font_directory) != installed_snapshot:
            raise AssertionError("Repeated font preparation was not stable or lost restart requirement")
        if settings_snapshot() != settings_before or sha256_file(sentinel_font) != sentinel_digest:
            raise AssertionError("Font preparation changed existing fonts or settings")
    finally:
        for pid in owned_cad:
            stop_test_process(pid)
    ready = cad_command(executable, "inspect", result_path, cad, work, "06-inspect-after-close")
    repeated_ready = cad_command(executable, "prepare", result_path, cad, work, "07-repeat-after-close")
    if (ready["status"] != "PREPARED" or repeated_ready["status"] != "PREPARED"
            or ready["execution"]["returncode"] or repeated_ready["execution"]["returncode"]
            or directory_snapshot(font_directory) != installed_snapshot):
        raise AssertionError("Prepared fonts were not stable after closing old LibreCAD")
    after_pdfs = {path.stem: render_pdf(cad, path, work / (path.stem + "-after.pdf"), work) for path in probes}
    for name in before_pdfs:
        if before_pdfs[name]["png_sha256"] == after_pdfs[name]["png_sha256"]:
            raise AssertionError("Actual LibreCAD kept the same fallback font after preparation: " + name)
    actual_pdf = render_pdf(cad, result_path, work / "prepared-native-result.pdf", work)
    before_open = set(cad_processes(cad))
    opened = cad_command(executable, "open", result_path, cad, work, "08-open-prepared-cad")
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (set(cad_processes(cad)) - before_open):
            time.sleep(0.2)
        after_open = cad_processes(cad)
        if opened["execution"]["returncode"] or not opened["launch_requested"] or not (set(after_open) - before_open):
            raise AssertionError("Actual EXE open command failed to launch prepared LibreCAD")
        for pid in set(after_open) - before_open:
            if not psutil.Process(pid).is_running():
                raise AssertionError("Launched LibreCAD exited unexpectedly")
    finally:
        for pid in set(cad_processes(cad)) - before_open:
            stop_test_process(pid)
    edits = file_edit_isolation(result_path, work)
    for name in ("file-edit-TEXT", "file-delete-TEXT"):
        render_pdf(cad, work / f"{name}.dxf", work / f"{name}.pdf", work)
    if sha256_file(result_path) != initial_result_hash or sha256_file(native_result) != initial_result_hash:
        raise AssertionError("Font preparation or opening modified the original result")
    import ezdxf

    saved = ezdxf.readfile(result_path)
    report = {
        "status": "PASS", "actual_windows_execution": True,
        "actual_executable": str(executable), "actual_executable_sha256": sha256_file(executable),
        "target_cad": installation, "actual_documents_folder": str(documents),
        "fresh_required_fonts_missing_at_start": True,
        "existing_unrelated_font_and_settings_unchanged": True,
        "font_preparation_repeat_stable": True, "running_cad_requires_reopen": True,
        "original_result_unchanged": True, "dxf_sha256": initial_result_hash,
        "entity_types": dict(Counter(entity.dxftype() for entity in saved.modelspace())),
        "reports": {
            "fresh": initial, "missing_cad": missing_cad, "conflict": conflict_result,
            "prepare_running": prepared_running, "repeat_running": repeated_running,
            "after_close": ready, "repeat_after_close": repeated_ready, "open": opened,
        },
        "font_style_before_preparation": before_pdfs, "font_style_after_preparation": after_pdfs,
        "actual_prepared_dxf_pdf": actual_pdf, "file_edit_isolation": edits,
        "manual_windows_gui_real_user_dxf": {
            "status": "NOT_RUN",
            "reason": "GitHub runner is accessible for processes/files, not this session's Windows desktop controls. Public controlled fixture only; private real DXF was not uploaded.",
            "not_claimed": "Manual selection, text editing, deletion, normal LibreCAD save/exit/reopen on the real main drawing.",
        },
        "compatibility": "Existing XDATA/zscale=0 LIMITED and strict-three/cross-platform failures are unchanged.",
        "product_status": "LOCAL_NO_GO",
    }
    write_json(work / "cad-font-delivery-checks.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--native-result", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This evidence command must run on real Windows, not a simulated platform.")
    args.work.mkdir(parents=True, exist_ok=False)
    progress_path = args.work / "delivery-smoke.json"
    report = {
        "schema": "windows-cad-user-delivery-smoke-v1", "source_commit": args.source_commit,
        "application_version": args.version, "status": "RUNNING", "completed": [],
        "windows_manual_gui": "NOT_RUN", "product_status": "LOCAL_NO_GO",
    }
    write_json(progress_path, report)
    try:
        report["stage"] = "build-exact-delivery-archive"
        write_json(progress_path, report)
        manifest = make_delivery(
            package=args.executable.resolve().parent, destination=args.delivery.resolve(),
            source_commit=args.source_commit, version=args.version,
        )
        report["archive"] = {key: manifest[key] for key in ("original_file", "original_bytes", "original_sha256", "parts")}
        report["completed"].append("exact-archive-and-split-verification")
        report["stage"] = "actual-windows-restoration"
        write_json(progress_path, report)
        restored_executable, restoration = check_restoration(args.delivery.resolve(), args.work / "restoration", manifest)
        build_metadata = read_json(restored_executable.parent / "_internal/resources/native-build.json")
        if (build_metadata["source_commit"] != args.source_commit
                or build_metadata["application_version"] != args.version):
            raise AssertionError("Restored executable bundle metadata differs from the requested source/version")
        report["restored_build_identity"] = {
            "source_commit": build_metadata["source_commit"],
            "application_version": build_metadata["application_version"],
            "executable_sha256": sha256_file(restored_executable),
        }
        report["restoration"] = {key: restoration[key] for key in ("status", "archive_sha256", "archive_bytes", "program_file_count")}
        report["completed"].append("actual-cmd-restore-negative-cases-extract-exe-launch-repeat")
        report["stage"] = "actual-packaged-font-service-and-librecad"
        write_json(progress_path, report)
        fonts = check_fonts(restored_executable, args.native_result.resolve(), args.work / "fonts")
        report["font_delivery"] = {key: fonts[key] for key in ("status", "dxf_sha256", "manual_windows_gui_real_user_dxf", "file_edit_isolation")}
        report["completed"].append("actual-exe-font-prepare-restart-open-librecad-file-render")
        report["status"] = "PASS"
        report["stage"] = "completed"
        write_json(progress_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        report.update(status="FAIL", error=str(error), traceback=traceback.format_exc())
        write_json(progress_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
