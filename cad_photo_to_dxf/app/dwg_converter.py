from __future__ import annotations

import os
from pathlib import Path

from ezdxf.addons import odafc


class DwgConversionUnavailable(RuntimeError):
    """Raised when the external ODA File Converter cannot be used."""


def configure_oda_converter(executable: str | Path | None = None) -> bool:
    """Configure a user-selected ODA executable and report availability."""
    if executable is not None:
        path = Path(executable).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.name.lower() != "odafileconverter.exe" and os.name == "nt":
            raise ValueError("请选择 ODAFileConverter.exe")
        if os.name == "nt":
            odafc.win_exec_path = str(path)
        else:
            odafc.unix_exec_path = str(path)
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
            "未找到 ODA File Converter。请安装后选择 ODAFileConverter.exe，"
            "或先导出 DXF。"
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
        raise DwgConversionUnavailable(f"DXF 转 DWG 失败：{exc}") from exc
    if not destination_path.is_file() or destination_path.stat().st_size <= 0:
        raise DwgConversionUnavailable("ODA 未生成有效的 DWG 文件")
    return destination_path
