from pathlib import Path
from typing import Any
from PySide6.QtWidgets import QFileDialog
from app.export.dwg_converter import DwgConversionUnavailable, configure_oda_converter

def _choose_oda_converter(window: Any) -> Path:
    configured = getattr(window, "_dwg_converter_path", None)
    if configure_oda_converter(configured):
        return Path(configured) if configured is not None else Path("ODAFileConverter.exe")

    default_location = Path("C:/Program Files/ODA")
    selected, _ = QFileDialog.getOpenFileName(
        window,
        "选择 ODA File Converter",
        str(default_location if default_location.exists() else Path.home()),
        "ODA File Converter (ODAFileConverter.exe)",
    )
    if not selected:
        raise DwgConversionUnavailable(
            "未选择 ODAFileConverter.exe；已保留可直接打开的 DXF。"
        )
    converter_path = Path(selected)
    configure_oda_converter(converter_path)
    window._dwg_converter_path = converter_path
    return converter_path


def _select_output_path(window: Any, *, default_name: str) -> tuple[Path, bool] | None:
    default_dir = Path.cwd() / "output"
    default_dir.mkdir(parents=True, exist_ok=True)
    selected_path, selected_filter = QFileDialog.getSaveFileName(
        window,
        "导出 CAD",
        str(default_dir / default_name),
        "AutoCAD DWG (*.dwg);;Drawing Exchange Format (*.dxf)",
    )
    if not selected_path:
        return None
    requested_path = Path(selected_path)
    if requested_path.suffix.lower() not in {".dwg", ".dxf"}:
        requested_path = requested_path.with_suffix(
            ".dwg" if selected_filter.startswith("AutoCAD DWG") else ".dxf"
        )
    return requested_path, requested_path.suffix.lower() == ".dwg"

