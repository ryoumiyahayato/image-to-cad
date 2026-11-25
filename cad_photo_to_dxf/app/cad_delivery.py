"""Prepare result-bound LibreCAD fonts without changing drawings or CAD settings.

LibreCAD 2.2.1.6 searches the Windows Documents/librecad/fonts directory
first (the redirected Qt DocumentsLocation, not a guessed USERPROFILE path).
On Linux its first user font directory is ~/.librecad/fonts.  TEXT uses the
style basename, not the STYLE table's TTF filename.  Files being present is
only preparation: a process which predates their installation must restart.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

from app.cad_font_resources import (
    LIBRECAD_VERSION,
    NATIVE_LIBRECAD_FONTS,
    check_librecad_character_coverage,
    ensure_librecad_resource,
    inspect_librecad_resource,
)
from app.native_objects.source_row_font_registry import SOURCE_ROW_DERIVATIVE


LOGGER = logging.getLogger(__name__)
_LAUNCH_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()
_CODES = {"PREPARED": 0, "NOT_PREPARED": 2, "REOPEN_REQUIRED": 3, "FAILED": 1}


class PreparationError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(code)
        self.code, self.message, self.details = code, message, details


def _identity(path: Path) -> dict:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha256(data).hexdigest()}


def _matches(path: Path, spec: dict) -> bool:
    return path.is_file() and _identity(path) == {key: spec[key] for key in ("bytes", "sha256")}


def _bundle_fonts() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "resources" / "fonts"


def _cache_dir() -> Path:
    from PySide6.QtCore import QStandardPaths

    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not root:
        raise PreparationError("USER_DATA_UNAVAILABLE", "无法找到可用的用户数据目录。")
    return Path(root) / "ImageToCAD" / "cad-font-resources-v1"


def _font_directory() -> Path:
    from PySide6.QtCore import QStandardPaths

    if sys.platform in {"win32", "darwin"}:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if not documents:
            raise PreparationError("DOCUMENTS_UNAVAILABLE", "无法读取当前用户的文档位置，字体尚未准备。")
        return Path(documents) / "librecad" / "fonts"
    return Path.home() / ".librecad" / "fonts"


def _source_file(parent: Path, name: str, alternatives=()) -> Path:
    for directory in (parent, _bundle_fonts()):
        for filename in (name, *alternatives):
            path = directory / filename
            if path.exists():
                if not path.is_file():
                    break
                return path
    raise PreparationError("FONT_SOURCE_MISSING", "结果所需的配套字体或许可不完整，请重新解压完整结果包。", filename=name)


def _require_identity(path: Path, spec: dict) -> None:
    if not _matches(path, spec):
        raise PreparationError("FONT_RESOURCE_MISMATCH", "配套字体资源与固定版本不一致，未更改任何已有字体。",
                               path=str(path), expected=spec, actual=_identity(path))


def _drawing_fonts(path: Path) -> list[dict]:
    import ezdxf

    if not path.is_file() or path.suffix.lower() != ".dxf":
        raise PreparationError("RESULT_NOT_FOUND", "请选择可以读取的 DXF 结果文件。")
    doc = ezdxf.readfile(path)
    styles: dict[str, dict] = {}
    for entity in doc.entitydb.values():
        if not entity.is_alive or entity.dxftype() not in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            continue
        name = entity.dxf.get("style", "Standard")
        if name not in doc.styles:
            raise PreparationError("STYLE_NOT_FOUND", "图纸中有文字引用了不存在的样式，无法确认字体。", style=name)
        style = doc.styles.get(name)
        # MTEXT has formatting/overrides that cannot be asserted by checking a
        # TEXT font. Keep this delivery entry explicit about its supported scope.
        if entity.dxftype() == "MTEXT":
            raise PreparationError("MTEXT_FONT_UNVERIFIED", "此图包含尚未纳入字体准备核验的多行文字，请保留原图。")
        record = styles.setdefault(name, {"style": name, "font": style.dxf.font,
                                          "entities": 0, "characters": set()})
        record["entities"] += 1
        record["characters"].update(entity.dxf.text)
    for record in styles.values():
        record["characters"] = "".join(sorted(record["characters"]))
    return list(styles.values())


def _native_resource(required: dict, parent: Path, create: bool) -> dict:
    source = _source_file(parent, "DejaVuSans.ttf")
    identity = _identity(source)
    spec = NATIVE_LIBRECAD_FONTS.get(identity["sha256"])
    if spec is None or identity["bytes"] != spec["bytes"]:
        raise PreparationError("NATIVE_FONT_SOURCE_MISMATCH", "普通文字的配套字体版本不匹配，原文件保持不变。", source=str(source))
    license_path = _source_file(source.parent, "FONT_LICENSE_DejaVu.txt", ("DejaVuSans.LICENSE.txt",))
    _require_identity(license_path, spec["license"])
    caches = [parent / "librecad-native", _bundle_fonts() / "librecad-native", _cache_dir()]
    record = None
    for cache in dict.fromkeys(caches):
        candidate = inspect_librecad_resource(source, cache)
        if candidate["status"] == "verified":
            record = candidate
            break
    if record is None and create:
        record = ensure_librecad_resource(source, _cache_dir(), source_license=license_path)
    if record is None:
        # Inspection is read-only; the resource can be generated offline on
        # Prepare. Check the real source cmap now, without inventing glyphs.
        from fontTools.ttLib import TTFont

        with TTFont(source) as font:
            present = set(font.getBestCmap())
        missing = [f"U+{ord(char):04X}" for char in required["characters"] if ord(char) not in present]
        if missing:
            raise PreparationError("GLYPHS_UNAVAILABLE", "固定字体缺少此图所用字符，不能确认无缺字显示。", missing=missing)
        record = {"status": "missing", "font": "I2CAD_TEXT.lff", "style": "I2CAD_TEXT",
                  "profile": spec["profile"], "source": identity, **spec["lff"],
                  "license": {"file": "I2CAD_TEXT.LICENSE.txt", **spec["derived_license"]},
                  "cad_loaded": False}
    else:
        coverage = check_librecad_character_coverage(record, required["characters"])
        if not coverage["complete"]:
            raise PreparationError("GLYPHS_UNAVAILABLE", "固定字体缺少此图字符，或字符排布尚未验证。", coverage=coverage)
        record["character_check"] = coverage
    return record


def _row_resource(required: dict, parent: Path) -> dict:
    spec = SOURCE_ROW_DERIVATIVE
    source = _source_file(parent, spec["font"]["file"])
    _require_identity(source, spec["font"])
    lff = _source_file(parent, spec["lff"]["file"])
    _require_identity(lff, spec["lff"])
    license_path = _source_file(parent, spec["export_license"], (spec["license"]["file"],))
    _require_identity(license_path, spec["license"])
    present = {int(value, 16) for value in re.findall(r"^\[([0-9A-Fa-f]+)\]", lff.read_text(encoding="utf-8"), re.M)} | {32}
    missing = [f"U+{ord(char):04X}" for char in required["characters"] if ord(char) not in present]
    if missing:
        raise PreparationError("GLYPHS_UNAVAILABLE", "编号字体缺少此图使用的字符，不能确认无缺字显示。", missing=missing)
    return {"status": "verified", "font": lff.name, "style": spec["style"], "path": str(lff),
            "profile": spec["profile"], **_identity(lff), "source": _identity(source),
            "license": {"path": str(license_path), "file": spec["license"]["file"], **_identity(license_path)},
            "character_check": {"complete": True, "missing": []}, "cad_loaded": False}


def _resources(required: list[dict], parent: Path, create=False) -> list[dict]:
    resources = []
    for item in required:
        name, font = item["style"].upper(), item["font"].replace("\\", "/").split("/")[-1]
        # LibreCAD 2.2.1.6 writeTextstyles() writes the style name back into
        # STYLE.font on an ordinary save. Accept only these known aliases so
        # the same entry can reopen a user's edited copy. Both forms still
        # run the identical pinned source, license and glyph checks below.
        if name == "I2CAD_TEXT" and font.casefold() in {"dejavusans.ttf", "i2cad_text"}:
            resource = _native_resource(item, parent, create)
        elif name == "I2CAD_SOURCE_ROW" and font.casefold() in {"osifont-cad-metrics.ttf", "i2cad_source_row"}:
            resource = _row_resource(item, parent)
        else:
            raise PreparationError("UNSUPPORTED_TEXT_STYLE", "此图有尚未绑定配套资源的文字样式，无法保证字体正确。",
                                   style=item["style"], font=item["font"])
        resource["entities"] = item["entities"]
        resource["characters"] = item["characters"]
        resources.append(resource)
    return resources


def _candidate_cads() -> list[Path]:
    candidates = []
    found = shutil.which("librecad")
    if found:
        candidates.append(Path(found))
    if sys.platform == "win32":
        import winreg

        keys = ((r"SOFTWARE\LibreCAD", ""),
                (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\LibreCAD", "InstallLocation"))
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                for key, value in keys:
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                            directory = Path(winreg.QueryValueEx(handle, value)[0])
                        candidates.extend((directory / "LibreCAD.exe", directory / "librecad.exe"))
                    except OSError:
                        pass
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            directory = os.environ.get(variable)
            if directory:
                candidates.append(Path(directory) / "LibreCAD" / "LibreCAD.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreCAD.app/Contents/MacOS/LibreCAD"))
    return list(dict.fromkeys(path.resolve() for path in candidates if path.is_file()))


@contextmanager
def _external_environment(*, probe=False):
    """Avoid passing this app's Qt6/PyInstaller libraries to LibreCAD's Qt5."""
    environment = dict(os.environ)
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment.pop(key, None)
    if probe and sys.platform != "win32" and not environment.get("DISPLAY"):
        environment["QT_QPA_PLATFORM"] = "offscreen"
        # Official Linux AppImages may only bundle xcb. A host-provided Qt5
        # offscreen platform can serve the non-GUI version probe, without
        # substituting any Qt runtime library or changing a GUI launch.
        if sys.platform.startswith("linux"):
            for plugins in Path("/usr/lib").glob("*/qt5/plugins/platforms"):
                if (plugins / "libqoffscreen.so").is_file():
                    environment["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins)
                    break
    if "LD_LIBRARY_PATH_ORIG" in environment:
        environment["LD_LIBRARY_PATH"] = environment["LD_LIBRARY_PATH_ORIG"]
    elif getattr(sys, "frozen", False):
        environment.pop("LD_LIBRARY_PATH", None)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        environment["PATH"] = os.pathsep.join(
            value for value in environment.get("PATH", "").split(os.pathsep)
            if value and not str(Path(value).resolve()).casefold().startswith(str(Path(bundle).resolve()).casefold() + os.sep)
            and str(Path(value).resolve()).casefold() != str(Path(bundle).resolve()).casefold()
        )
    with _LAUNCH_LOCK:
        kernel = None
        if sys.platform == "win32" and bundle:
            import ctypes

            kernel = ctypes.windll.kernel32
            kernel.SetDllDirectoryW(None)
        try:
            yield environment
        finally:
            if kernel is not None:
                kernel.SetDllDirectoryW(str(bundle))


def _cad_version(path: Path) -> dict:
    # Ordinary --version is NOT supported by this LibreCAD and would open its
    # GUI. The documented converter's QCommandLineParser exits immediately.
    with _external_environment(probe=True) as environment:
        run = subprocess.run([str(path), "dxf2pdf", "--version"], capture_output=True,
                             timeout=15, env=environment, creationflags=0x08000000 if sys.platform == "win32" else 0)
    output = (run.stdout + run.stderr).decode("utf-8", errors="replace")
    match = re.search(r"LibreCAD\s+(?:version\s+|v)?(\d+\.\d+\.\d+(?:\.\d+)?)", output, re.I)
    return {"version": match[1] if match else None, "exit_code": run.returncode, "output": output[-4000:]}


def _resolve_cad(selected=None) -> tuple[Path | None, dict]:
    candidates = [Path(selected).expanduser().resolve()] if selected else _candidate_cads()
    diagnostics = []
    for path in candidates:
        if not path.is_file():
            diagnostics.append({"path": str(path), "error": "not_found"})
            continue
        try:
            checked = _cad_version(path)
            diagnostics.append({"path": str(path), **checked})
            if checked["exit_code"] == 0 and checked["version"] == LIBRECAD_VERSION:
                return path, {"version": LIBRECAD_VERSION, "candidates": diagnostics}
        except (OSError, subprocess.SubprocessError) as exc:
            diagnostics.append({"path": str(path), "error": str(exc)})
    return None, {"candidates": diagnostics}


def _cad_processes() -> list[dict]:
    import psutil

    answer = []
    for process in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        try:
            info = process.info
            if not str(info.get("name", "")).casefold().startswith("librecad"):
                continue
            answer.append({key: info.get(key) for key in ("pid", "name", "exe", "create_time")})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return answer


def _destinations(resources: list[dict], directory: Path) -> list[dict]:
    if directory.is_symlink():
        raise PreparationError("FONT_DIRECTORY_LINK", "字体目录指向其他位置，为保留已有配置，本次未写入。", path=str(directory))
    existing = {path.name.casefold(): path for path in directory.iterdir()} if directory.is_dir() else {}
    output = []
    for item in resources:
        name = item["font"]
        # LibreCAD may load CXF and LFF with the same basename. Do not rely on
        # enumeration order when another same-name resource could win.
        cxf = existing.get(Path(name).with_suffix(".cxf").name.casefold())
        if cxf is not None:
            raise PreparationError("FONT_NAME_CONFLICT", "已有同名 CAD 字体与配套资源冲突，原文件已保留。", path=str(cxf))
        target = existing.get(name.casefold(), directory / name)
        output.append({"source": item.get("path"), "target": str(target), "role": "font",
                       "style": item["style"], "bytes": item["bytes"], "sha256": item["sha256"]})
        license_data = item["license"]
        license_target = directory / "ImageToCAD-licenses" / item["profile"] / license_data["file"]
        output.append({"source": license_data.get("path"), "target": str(license_target), "role": "license",
                       "style": item["style"], "bytes": license_data["bytes"], "sha256": license_data["sha256"]})
    for record in output:
        target = Path(record["target"])
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not _matches(target, record):
                raise PreparationError("FONT_NAME_CONFLICT", "已有同名字体或许可与配套资源不同；原文件未被覆盖。",
                                       path=str(target), expected=record)
            record["state"] = "unchanged"
        else:
            record["state"] = "missing"
    return output


def _copy_new(record: dict) -> None:
    target, source = Path(record["target"]), Path(record["source"])
    data = source.read_bytes()
    if {"bytes": len(data), "sha256": sha256(data).hexdigest()} != {key: record[key] for key in ("bytes", "sha256")}:
        raise PreparationError("RESOURCE_CHANGED", "准备过程中配套资源发生变化，请重新检查。", path=str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with target.open("xb") as handle:
            created = True
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if not _matches(target, record):
            raise PreparationError("FONT_NAME_CONFLICT", "准备时发现已有同名文件，原文件保持不变。", path=str(target)) from None
    except OSError:
        if created:
            target.unlink(missing_ok=True)
        raise


def _persist_report(report: dict) -> None:
    """Keep diagnostics in a bounded private log, including windowed EXEs."""
    try:
        log = _cache_dir().parent / "logs" / "cad-fonts.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            if not any(isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(log)
                       for handler in LOGGER.handlers):
                handler = RotatingFileHandler(log, maxBytes=4 * 1024 * 1024, backupCount=2, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                LOGGER.addHandler(handler)
                LOGGER.setLevel(logging.INFO)
            report["details"]["log_path"] = str(log)
            LOGGER.info("CAD delivery: %s", json.dumps(report, ensure_ascii=False))
    except OSError as exc:
        report["details"]["log_error"] = str(exc)
        report["message"] += " 诊断日志无法写入。"


def _report(path, selected, *, prepare=False) -> dict:
    report = {"schema": "cad-delivery-fonts-v1", "status": "FAILED", "message": "字体准备尚未完成。",
              "cad_executable": None, "can_prepare": False, "can_launch": False, "launch_requested": False,
              "cad_loaded_verified": False, "required_fonts": [], "installed_files": [], "unchanged_files": [],
              "processes": [], "details": {}}
    try:
        result = Path(path).expanduser().resolve()
        required = _drawing_fonts(result)
        report["details"]["result"] = {"path": str(result), **_identity(result)}
        resources = _resources(required, result.parent)
        report["required_fonts"] = resources
        cad, checked = _resolve_cad(selected)
        report["details"]["cad_detection"] = checked
        if cad is None:
            report.update(status="NOT_PREPARED", message=f"未找到可核验的 LibreCAD {LIBRECAD_VERSION}。请点击“选择 LibreCAD”选择程序。")
            return report
        report["cad_executable"] = str(cad)
        directory = _font_directory()
        destinations = _destinations(resources, directory)
        report["details"]["font_directory"] = str(directory)
        if prepare and any(item["state"] == "missing" for item in destinations):
            resources = _resources(required, result.parent, create=True)
            report["required_fonts"] = resources
            destinations = _destinations(resources, directory)
            # All identities and all conflicts are checked before the first
            # user-directory write. Only exclusively created files are added.
            for item in destinations:
                if item["state"] == "missing":
                    _copy_new(item)
                    report["installed_files"].append(dict(item, state="installed"))
            destinations = _destinations(resources, directory)
        report["unchanged_files"] = [item for item in destinations if item["state"] == "unchanged"
                                     and item["target"] not in {new["target"] for new in report["installed_files"]}]
        report["details"]["destinations"] = destinations
        processes = _cad_processes()
        report["processes"] = processes
        if any(item["state"] == "missing" for item in destinations):
            report.update(status="NOT_PREPARED", message="此图的 CAD 字体尚未准备，请点击“准备 CAD 字体”。", can_prepare=True)
        else:
            newest_font = max((Path(item["target"]).stat().st_mtime for item in destinations if item["role"] == "font"), default=0)
            stale = [item for item in processes if not item.get("create_time") or item["create_time"] <= newest_font]
            report["details"]["stale_processes"] = stale
            if stale:
                report.update(status="REOPEN_REQUIRED", message="字体文件已准备。请保存图纸并完全退出 LibreCAD，然后点击“重新检查”。", can_prepare=True)
            else:
                report.update(status="PREPARED", message="所需字体已准备，可以打开图纸。", can_prepare=True, can_launch=True)
        if _identity(result) != {key: report["details"]["result"][key] for key in ("bytes", "sha256")}:
            raise PreparationError("RESULT_CHANGED", "图纸在检查期间发生变化，请重新检查。")
    except PreparationError as exc:
        report.update(status="FAILED", message=exc.message, can_prepare=False, can_launch=False)
        report["details"]["failure"] = {"code": exc.code, **exc.details}
    except Exception as exc:
        LOGGER.exception("CAD font preparation failed")
        report.update(status="FAILED", message="无法完成字体检查或准备，请确认结果包完整并且当前用户有写入权限。", can_prepare=False, can_launch=False)
        report["details"]["failure"] = {"code": type(exc).__name__, "error": str(exc)}
    finally:
        _persist_report(report)
    return report


def inspect_result_fonts(dxf_path, cad_executable=None) -> dict:
    return _report(dxf_path, cad_executable)


def prepare_result_fonts(dxf_path, cad_executable=None) -> dict:
    return _report(dxf_path, cad_executable, prepare=True)


def launch_result_in_cad(dxf_path, cad_executable=None) -> dict:
    report = inspect_result_fonts(dxf_path, cad_executable)
    if not report["can_launch"]:
        return report
    try:
        with _external_environment() as environment:
            process = subprocess.Popen([report["cad_executable"], str(Path(dxf_path).resolve())],
                                       cwd=str(Path(dxf_path).resolve().parent), env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        report.update(launch_requested=True, message="已请求 LibreCAD 打开图纸。字体文件已准备；请在 CAD 中查看实际显示。")
        report["details"]["launched_pid"] = process.pid
    except OSError as exc:
        report.update(status="FAILED", can_launch=False, message="LibreCAD 未能启动，请重新选择可以运行的程序。")
        report["details"]["launch_error"] = str(exc)
    _persist_report(report)
    return report


def run_cad_fonts_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare result-bound LibreCAD fonts, without recognition")
    parser.add_argument("action", choices=("inspect", "prepare", "open"))
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--cad-executable", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    function = {"inspect": inspect_result_fonts, "prepare": prepare_result_fonts, "open": launch_result_in_cad}[args.action]
    report = function(args.result, cad_executable=args.cad_executable)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _CODES[report["status"]]
