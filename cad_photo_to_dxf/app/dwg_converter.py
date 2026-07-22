from __future__ import annotations

import locale
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Iterable

import ezdxf


class DwgConversionUnavailable(RuntimeError):
    """Raised when the external ODA File Converter cannot be used."""


_CONFIGURED_CONVERTER_PATH: Path | None = None
_SETTINGS_FILENAME = "oda-file-converter-path.txt"
_VERSION_MAP = {
    "R12": "ACAD12",
    "R13": "ACAD13",
    "R14": "ACAD14",
    "R2000": "ACAD2000",
    "R2004": "ACAD2004",
    "R2007": "ACAD2007",
    "R2010": "ACAD2010",
    "R2013": "ACAD2013",
    "R2018": "ACAD2018",
    "AC1009": "ACAD12",
    "AC1012": "ACAD13",
    "AC1014": "ACAD14",
    "AC1015": "ACAD2000",
    "AC1018": "ACAD2004",
    "AC1021": "ACAD2007",
    "AC1024": "ACAD2010",
    "AC1027": "ACAD2013",
    "AC1032": "ACAD2018",
}
_VALID_VERSIONS = set(_VERSION_MAP.values())


def _settings_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if root:
        return Path(root) / "CADPhotoToDXF" / _SETTINGS_FILENAME
    return Path.home() / ".cad-photo-to-dxf" / _SETTINGS_FILENAME


def _read_saved_converter_path() -> Path | None:
    try:
        value = _settings_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(value) if value else None


def _persist_converter_path(path: Path) -> None:
    try:
        target = _settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(str(path), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        pass


def _candidate_executable(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        for name in ("ODAFileConverter.exe", "ODAFileConverter"):
            nested = candidate / name
            if nested.is_file():
                candidate = nested
                break
        else:
            return None
    if not candidate.is_file():
        return None
    candidate = candidate.resolve()
    if os.name == "nt" and candidate.name.lower() != "odafileconverter.exe":
        return None
    return candidate


def _application_local_candidates() -> Iterable[Path]:
    executable_dir = Path(sys.executable).resolve().parent
    package_root = Path(__file__).resolve().parents[1]
    for root in (executable_dir, package_root, Path.cwd()):
        yield root / "ODAFileConverter.exe"
        yield root / "ODAFileConverter" / "ODAFileConverter.exe"
        yield root / "ODA File Converter" / "ODAFileConverter.exe"
        yield root / "ODA" / "ODAFileConverter.exe"


def _installed_oda_candidates() -> Iterable[Path]:
    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    roots.append(Path("C:/Program Files"))

    seen_roots: set[str] = set()
    for root in roots:
        root_key = str(root).casefold()
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        oda_root = root / "ODA"
        yield oda_root / "ODAFileConverter.exe"
        if not oda_root.is_dir():
            continue
        try:
            matches = sorted(
                oda_root.glob("**/ODAFileConverter.exe"),
                key=lambda item: str(item).casefold(),
                reverse=True,
            )
        except OSError:
            continue
        yield from matches


def find_oda_converter(executable: str | Path | None = None) -> Path | None:
    """Resolve an explicit, remembered, app-local, or installed converter path."""

    if executable is not None:
        explicit = _candidate_executable(executable)
        if explicit is None:
            path = Path(executable).expanduser()
            if path.is_dir():
                raise FileNotFoundError(path / "ODAFileConverter.exe")
            if os.name == "nt" and path.name.lower() != "odafileconverter.exe":
                raise ValueError("请选择 ODAFileConverter.exe")
            raise FileNotFoundError(path)
        return explicit

    candidates: list[str | Path | None] = [
        _CONFIGURED_CONVERTER_PATH,
        _read_saved_converter_path(),
        os.environ.get("ODA_FILE_CONVERTER"),
    ]
    candidates.extend(_application_local_candidates())
    candidates.extend(_installed_oda_candidates())

    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        resolved = _candidate_executable(candidate)
        if resolved is not None:
            return resolved
    return None


def configure_oda_converter(executable: str | Path | None = None) -> bool:
    """Remember the converter and configure ezdxf's ODA option correctly."""

    global _CONFIGURED_CONVERTER_PATH
    path = find_oda_converter(executable)
    if path is None:
        return False
    _CONFIGURED_CONVERTER_PATH = path
    if os.name == "nt":
        ezdxf.options.set("odafc-addon", "win_exec_path", str(path))
    else:
        ezdxf.options.set("odafc-addon", "unix_exec_path", str(path))
    if executable is not None:
        _persist_converter_path(path)
    return True


def _mapped_version(version: str) -> str:
    normalized = str(version or "R2018").upper()
    mapped = _VERSION_MAP.get(normalized, normalized)
    if mapped not in _VALID_VERSIONS:
        raise DwgConversionUnavailable(f"不支持的 DWG 目标版本：{version}")
    return mapped


def _run_converter(
    executable: Path,
    source_path: Path,
    output_dir: Path,
    version: str,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        str(executable),
        str(source_path.parent),
        str(output_dir),
        _mapped_version(version),
        "DWG",
        "0",
        "1",
        source_path.name,
    ]
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "encoding": locale.getpreferredencoding(False) or "utf-8",
        "errors": "replace",
        "timeout": 1800,
        "check": False,
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(arguments, **kwargs)  # type: ignore[arg-type]


def convert_dxf_to_dwg(
    source: str | Path,
    destination: str | Path,
    *,
    version: str = "R2018",
    converter_executable: str | Path | None = None,
) -> Path:
    """Convert one DXF to DWG without showing ODA's folder-selection window."""

    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path.suffix.lower() != ".dxf" or not source_path.is_file():
        raise FileNotFoundError(source_path)
    if destination_path.suffix.lower() != ".dwg":
        destination_path = destination_path.with_suffix(".dwg")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        executable = find_oda_converter(converter_executable)
    except Exception as exc:
        raise DwgConversionUnavailable(str(exc)) from exc
    if executable is None:
        raise DwgConversionUnavailable(
            "未找到 ODA File Converter。安装后程序会自动调用；"
            "也可以只选择一次 ODAFileConverter.exe。"
        )
    configure_oda_converter(executable)

    try:
        with TemporaryDirectory(prefix="cadphoto_oda_") as temp_dir:
            output_dir = Path(temp_dir)
            completed = _run_converter(executable, source_path, output_dir, version)
            candidates = sorted(output_dir.glob("*.dwg"))
            expected = output_dir / source_path.with_suffix(".dwg").name
            generated = expected if expected.is_file() else (candidates[0] if candidates else None)
            if generated is None or generated.stat().st_size <= 0:
                detail = (completed.stderr or completed.stdout or "ODA 未生成输出文件").strip()
                raise DwgConversionUnavailable(
                    f"DXF 转 DWG 失败（当前使用：{executable}）：{detail}"
                )
            if destination_path.exists():
                destination_path.unlink()
            try:
                shutil.move(str(generated), str(destination_path))
            except OSError:
                shutil.copy2(generated, destination_path)
    except subprocess.TimeoutExpired as exc:
        raise DwgConversionUnavailable("ODA 转换超过 30 分钟，已终止。") from exc
    except DwgConversionUnavailable:
        raise
    except Exception as exc:
        raise DwgConversionUnavailable(
            f"DXF 转 DWG 失败（当前使用：{executable}）：{exc}"
        ) from exc

    if not destination_path.is_file() or destination_path.stat().st_size <= 0:
        raise DwgConversionUnavailable("ODA 未生成有效的 DWG 文件")
    return destination_path
