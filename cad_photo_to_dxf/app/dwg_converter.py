from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Iterable

from ezdxf.addons import odafc


class DwgConversionUnavailable(RuntimeError):
    """Raised when the external ODA File Converter cannot be used."""


_CONFIGURED_CONVERTER_PATH: Path | None = None
_SETTINGS_FILENAME = "oda-file-converter-path.txt"


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
        # Conversion can still proceed for the current session when settings
        # cannot be written, for example in a locked-down corporate profile.
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
            # Current ODA installers commonly use a versioned directory such as
            # "ODAFileConverter 27.11.0" below Program Files/ODA.
            matches = sorted(
                oda_root.glob("**/ODAFileConverter.exe"),
                key=lambda path: str(path).casefold(),
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
    """Configure ODA and remember a user-selected executable across exports."""

    global _CONFIGURED_CONVERTER_PATH

    path = find_oda_converter(executable)
    if path is not None:
        if os.name == "nt":
            odafc.win_exec_path = str(path)
        else:
            odafc.unix_exec_path = str(path)
        _CONFIGURED_CONVERTER_PATH = path
        if executable is not None:
            _persist_converter_path(path)
        # The executable exists and has been assigned explicitly. Let the real
        # conversion call report any runtime or installation problem in detail.
        return True
    return bool(odafc.is_installed())


def convert_dxf_to_dwg(
    source: str | Path,
    destination: str | Path,
    *,
    version: str = "R2018",
    converter_executable: str | Path | None = None,
) -> Path:
    """Convert one generated DXF to DWG with an installed ODA File Converter."""

    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path.suffix.lower() != ".dxf" or not source_path.is_file():
        raise FileNotFoundError(source_path)
    if destination_path.suffix.lower() != ".dwg":
        destination_path = destination_path.with_suffix(".dwg")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        available = configure_oda_converter(converter_executable)
    except Exception as exc:
        raise DwgConversionUnavailable(str(exc)) from exc
    if not available:
        raise DwgConversionUnavailable(
            "未找到 ODA File Converter。可选择 ODAFileConverter.exe，"
            "或将整个 ODAFileConverter 文件夹放到本程序安装目录旁边。"
        )

    try:
        odafc.convert(
            source_path,
            destination_path,
            version=version,
            audit=True,
            replace=True,
        )
    except Exception as exc:
        configured = find_oda_converter()
        location = f"（当前使用：{configured}）" if configured is not None else ""
        raise DwgConversionUnavailable(f"DXF 转 DWG 失败{location}：{exc}") from exc
    if not destination_path.is_file() or destination_path.stat().st_size <= 0:
        raise DwgConversionUnavailable("ODA 未生成有效的 DWG 文件")
    return destination_path
