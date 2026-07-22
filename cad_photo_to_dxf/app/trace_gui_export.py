from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox

from . import __version__
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .document_export import DocumentExportResult
from .dwg_converter import DwgConversionUnavailable, convert_dxf_to_dwg
from .dxf_exporter import ExportResult
from .gui_export import _choose_oda_converter, _select_output_path
from .reporting import REPORT_SCHEMA_VERSION, write_json_report
from .trace_document_export import export_trace_document_streaming
from .trace_dxf_entities import MAX_EDITABLE_POLYLINE_VERTICES, TracePalette
from .trace_single_export import export_exact_trace_dxf


DEFAULT_PALETTE = TracePalette(straight=5, curve=3, text_symbol=6)


@dataclass(frozen=True)
class TraceExportCompletion:
    result: DocumentExportResult | ExportResult | None
    report_path: Path
    dwg_path: Path | None
    dwg_error: str | None
    document_mode: bool
    scale_description: str = "1:1"
    output_directory: Path | None = None
    dxf_paths: tuple[Path, ...] = ()
    dwg_paths: tuple[Path, ...] = ()
    page_count: int = 0
    trace_path_count: int = 0
    trace_vertex_count: int = 0
    text_count: int = 0


def _resolve_converter_on_ui(
    window: Any,
    requested_dwg: bool,
) -> tuple[Path | None, str | None]:
    if not requested_dwg:
        return None, None
    try:
        return _choose_oda_converter(window), None
    except DwgConversionUnavailable as exc:
        QMessageBox.information(
            window,
            "将先导出 DXF",
            f"{exc}\n\n本次仍会在后台生成可直接打开的 DXF。",
        )
        return None, str(exc)


def _convert_in_worker(
    dxf_path: Path,
    requested_path: Path,
    requested_dwg: bool,
    converter_path: Path | None,
    target_version: str,
    previous_error: str | None,
    *,
    cancellation_token: CancellationToken | None,
    progress_callback: ProgressCallback | None,
) -> tuple[Path | None, str | None]:
    if not requested_dwg or converter_path is None:
        return None, previous_error
    checkpoint(cancellation_token)
    report_progress(progress_callback, "转换 DWG", 0.97)
    try:
        dwg_path = convert_dxf_to_dwg(
            dxf_path,
            requested_path,
            version=target_version,
            converter_executable=(
                converter_path
                if converter_path.name.lower() != "odafileconverter.exe"
                else None
            ),
        )
        return dwg_path, None
    except DwgConversionUnavailable as exc:
        return None, str(exc)


def _document_missing_pages(window: Any) -> list[int]:
    missing: list[int] = []
    for page_index in range(int(window._pdf_page_count)):
        state = window._pdf_page_states.get(page_index, {})
        cache_value = state.get("trace_cache_path")
        if not cache_value or not Path(str(cache_value)).exists():
            missing.append(page_index + 1)
    return missing


def _multi_page_output_directory(requested_path: Path) -> Path:
    return requested_path.parent / f"{requested_path.stem}-pages"


def _editable_text_strategy() -> dict[str, object]:
    return {
        "ocr_per_character_text_entities": True,
        "one_text_entity_per_non_space_character": True,
        "ocr_line_as_single_vector_block": False,
        "ocr_insert_blocks": False,
        "native_unicode_text_entities": True,
        "absolute_font_path_embedded": False,
        "non_uniform_text_scaling": False,
        "ocr_unicode_preserved_as_character_xdata": True,
    }


def _start_document_export(window: Any) -> None:
    if not bool(getattr(window, "_native_pdf_mode", False)):
        return
    window._save_current_pdf_state()
    missing = _document_missing_pages(window)
    if missing:
        page_text = "、".join(map(str, missing[:12]))
        if len(missing) > 12:
            page_text += "……"
        QMessageBox.warning(
            window,
            "部分页面尚未处理",
            f"尚未处理的页码：{page_text}\n\n"
            "请先点击“处理全部页面”，再导出。",
        )
        return

    selection = _select_output_path(window, default_name="drawing-pages.dwg")
    if selection is None:
        return
    requested_path, requested_dwg = selection
    output_directory = _multi_page_output_directory(requested_path)
    report_path = output_directory / "export.report.json"
    converter_path, converter_error = _resolve_converter_on_ui(window, requested_dwg)
    target_version = str(
        window.dwg_version_combo.currentData()
        if getattr(window, "dwg_version_combo", None) is not None
        else "R2018"
    )
    include_underlay = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
    )
    pages = window.document_pages_for_export()
    total_pages = int(window._pdf_page_count)
    source_path = Path(window.current_path)
    page_scales = tuple(
        float(window._pdf_page_states.get(index, {}).get("drawing_scale", 1.0))
        for index in range(total_pages)
    )
    scale_description = (
        "1:1"
        if all(abs(value - 1.0) < 1e-9 for value in page_scales)
        else "per-page setting"
    )

    def operation(token: CancellationToken, progress: ProgressCallback) -> object:
        output_directory.mkdir(parents=True, exist_ok=True)
        dxf_paths: list[Path] = []
        dwg_paths: list[Path] = []
        page_records: list[dict[str, Any]] = []
        conversion_errors: list[str] = []
        total_trace_paths = 0
        total_trace_vertices = 0
        total_text_characters = 0
        processed_pages = 0

        for page_index, page in enumerate(pages, start=1):
            token.checkpoint()
            processed_pages = page_index
            page_dxf = output_directory / f"page-{page_index:03d}.dxf"
            page_base = (page_index - 1) / max(total_pages, 1)
            page_span = 0.88 / max(total_pages, 1)

            def page_progress(stage: str, fraction: float) -> None:
                progress(
                    f"第 {page_index}/{total_pages} 页：{stage}",
                    page_base + page_span * fraction,
                )

            result = export_trace_document_streaming(
                [page],
                page_dxf,
                include_underlay=include_underlay,
                total_pages=1,
                palette=DEFAULT_PALETTE,
                cancellation_token=token,
                progress_callback=page_progress,
            )
            dxf_paths.append(result.path)
            total_trace_paths += result.trace_path_count
            total_trace_vertices += result.trace_vertex_count
            total_text_characters += result.text_count

            page_dwg: Path | None = None
            page_error: str | None = None
            if requested_dwg and converter_path is not None:
                try:
                    page_dwg = convert_dxf_to_dwg(
                        result.path,
                        output_directory / f"page-{page_index:03d}.dwg",
                        version=target_version,
                        converter_executable=(
                            converter_path
                            if converter_path.name.lower() != "odafileconverter.exe"
                            else None
                        ),
                    )
                    dwg_paths.append(page_dwg)
                except DwgConversionUnavailable as exc:
                    page_error = str(exc)
                    conversion_errors.append(f"第 {page_index} 页：{exc}")
            elif requested_dwg and converter_error:
                page_error = converter_error

            page_records.append(
                {
                    "page": page_index,
                    "dxf": str(result.path),
                    "dwg": str(page_dwg) if page_dwg is not None else None,
                    "trace_path_count": result.trace_path_count,
                    "trace_vertex_count": result.trace_vertex_count,
                    "ocr_text_character_count": result.text_count,
                    "scan_underlays": [str(path) for path in result.underlay_paths],
                    "dwg_error": page_error,
                }
            )

        checkpoint(token)
        report_progress(progress, "写入多页导出清单", 0.97)
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "editable_character_text_one_file_per_pdf_page",
            "input": str(source_path),
            "output_directory": str(output_directory),
            "page_count": processed_pages,
            "pages": page_records,
            "scale": scale_description,
            "editable_entity_strategy": {
                "one_dxf_per_pdf_page": True,
                "combined_modelspace_file": False,
                "paper_space_layouts": False,
                "page_block_wrappers": False,
                **_editable_text_strategy(),
                "max_vertices_per_non_text_polyline_piece": MAX_EDITABLE_POLYLINE_VERTICES,
            },
            "warnings": [
                "为彻底消除第一页固定在第二页左上角的问题，多页 PDF 不再合并到同一个 DXF 模型空间。",
                "每个 PDF 页面生成一个独立 DXF；页面之间不存在坐标或图层叠加。",
                "每个已确认 OCR 非空字符均导出为独立原生 TEXT，可在 CAD 中单独选择、删除和修改。",
                "DXF 不嵌入导出电脑的绝对字体路径；Unicode 内容可保留，但不同 CAD 环境的具体字形可能随可用字体变化。",
                *([converter_error] if requested_dwg and converter_error else []),
                *conversion_errors,
            ],
        }
        write_json_report(report_path, report)
        report_progress(progress, "导出完成", 1.0)
        return TraceExportCompletion(
            result=None,
            report_path=report_path,
            dwg_path=None,
            dwg_error="\n".join(conversion_errors) or converter_error,
            document_mode=True,
            scale_description=scale_description,
            output_directory=output_directory,
            dxf_paths=tuple(dxf_paths),
            dwg_paths=tuple(dwg_paths),
            page_count=processed_pages,
            trace_path_count=total_trace_paths,
            trace_vertex_count=total_trace_vertices,
            text_count=total_text_characters,
        )

    def completed(value: object) -> None:
        completion: TraceExportCompletion = value  # type: ignore[assignment]
        summary = [
            f"输出目录：{completion.output_directory}",
            f"独立页面：{completion.page_count}",
            f"DXF 文件：{len(completion.dxf_paths)}",
            f"DWG 文件：{len(completion.dwg_paths)}",
            f"非文字图形：{completion.trace_path_count}",
            f"可编辑文字：{completion.text_count}",
            f"输出比例：{completion.scale_description}",
            "页面方式：每页一个文件，不再生成 drawing-all-pages.dxf",
            "文字方式：每个非空字符一个原生 TEXT，不生成整行矢量块",
            f"处理报告：{completion.report_path}",
        ]
        if completion.dwg_error:
            summary.append(f"部分或全部 DWG 未生成：{completion.dwg_error}")
            QMessageBox.warning(window, "页面 DXF 已完成", "\n".join(summary))
        else:
            QMessageBox.information(window, "多页 CAD 导出完成", "\n".join(summary))
        window.statusBar().showMessage(
            f"各 PDF 页面已独立导出：{completion.output_directory}"
        )

    window._start_processing(operation, completed, "正在逐页导出独立 CAD 文件…")


def _start_single_export(window: Any) -> None:
    trace_paths = tuple(getattr(window, "_trace_paths", ()))
    if not trace_paths or window.binary_image is None or window.corrected_image is None:
        QMessageBox.warning(window, "尚无处理结果", "请先处理当前页。")
        return
    selection = _select_output_path(window, default_name="drawing-page.dwg")
    if selection is None:
        return
    requested_path, requested_dwg = selection
    dxf_path = requested_path.with_suffix(".dxf") if requested_dwg else requested_path
    report_path = requested_path.with_suffix(".report.json")
    scan_path = dxf_path.with_name(f"{dxf_path.stem}.scan.png")
    converter_path, converter_error = _resolve_converter_on_ui(window, requested_dwg)
    target_version = str(
        window.dwg_version_combo.currentData()
        if getattr(window, "dwg_version_combo", None) is not None
        else "R2018"
    )
    include_underlay = bool(
        getattr(window, "include_underlay_checkbox", None)
        and window.include_underlay_checkbox.isChecked()
    )
    multiplier_getter = getattr(window, "_export_drawing_multiplier", None)
    drawing_multiplier = float(
        multiplier_getter() if callable(multiplier_getter) else window._drawing_scale()
    )
    selected_ratio = float(window._drawing_scale())
    explicit_model_calibration = bool(
        getattr(window, "_has_explicit_model_calibration", lambda: False)()
    )
    binary_shape = tuple(window.binary_image.shape[:2])
    calibration = window.calibration
    raster_image = window.corrected_image.copy() if include_underlay else None
    source_path = Path(window.current_path) if window.current_path is not None else None
    threshold = getattr(window, "_trace_threshold", None)
    foreground_pixels = int(getattr(window, "_trace_foreground_pixels", 0))
    texts = tuple(getattr(window, "_ocr_texts", ()))

    def operation(token: CancellationToken, progress: ProgressCallback) -> object:
        result = export_exact_trace_dxf(
            trace_paths,
            dxf_path,
            binary_shape[0],
            calibration,
            image_width=binary_shape[1],
            drawing_multiplier=drawing_multiplier,
            trace_color=7,
            palette=DEFAULT_PALETTE,
            texts=texts,
            raster_image=raster_image,
            raster_output_path=scan_path if include_underlay else None,
            cancellation_token=token,
            progress_callback=lambda stage, fraction: progress(stage, 0.94 * fraction),
        )
        dwg_path, dwg_error = _convert_in_worker(
            dxf_path,
            requested_path,
            requested_dwg,
            converter_path,
            target_version,
            converter_error,
            cancellation_token=token,
            progress_callback=progress,
        )
        if dwg_path is not None:
            result = replace(result, dwg_path=dwg_path, output_format="DWG")
        scale_description = (
            "已知长度两点标定"
            if explicit_model_calibration
            else f"1:{int(selected_ratio)}"
        )
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "app_version": __version__,
            "mode": "editable_character_text_single_page",
            "input": str(source_path) if source_path is not None else None,
            "trace": {
                "path_count": result.trace_path_count,
                "vertex_count": result.trace_vertex_count,
                "threshold": threshold,
                "foreground_pixels": foreground_pixels,
                "ocr_text_character_count": result.text_count,
            },
            "scale_source": scale_description,
            "drawing_multiplier": drawing_multiplier,
            "model_mm_per_pixel": result.mm_per_pixel,
            "editable_entity_strategy": {
                "page_block_wrappers": False,
                "groups": False,
                "hatches": False,
                **_editable_text_strategy(),
                "max_vertices_per_non_text_polyline_piece": MAX_EDITABLE_POLYLINE_VERTICES,
            },
            "export": {
                **asdict(result),
                "path": str(result.path),
                "underlay_path": str(result.underlay_path) if result.underlay_path else None,
                "dwg_path": str(result.dwg_path) if result.dwg_path else None,
            },
            "warnings": [
                "已确认的文字会作为可编辑 TEXT 导出。",
                "DXF 不写入导出电脑的绝对字体路径；不同 CAD 环境可能使用不同 Unicode 字体显示同一内容。",
                f"超长非文字图形按最多 {MAX_EDITABLE_POLYLINE_VERTICES} 个顶点拆分。",
                *([f"DWG 转换未完成：{dwg_error}"] if dwg_error else []),
            ],
        }
        write_json_report(report_path, report)
        report_progress(progress, "导出完成", 1.0)
        return TraceExportCompletion(
            result=result,
            report_path=report_path,
            dwg_path=dwg_path,
            dwg_error=dwg_error,
            document_mode=False,
            scale_description=scale_description,
        )

    def completed(value: object) -> None:
        completion: TraceExportCompletion = value  # type: ignore[assignment]
        result: ExportResult = completion.result  # type: ignore[assignment]
        summary = [
            *([f"DWG：{completion.dwg_path}"] if completion.dwg_path else []),
            f"DXF：{result.path}",
            f"非文字图形：{result.trace_path_count}",
            f"可编辑文字：{result.text_count}",
            f"图形顶点：{result.trace_vertex_count}",
            f"输出比例：{completion.scale_description}",
            "文字方式：可编辑 TEXT",
            f"处理报告：{completion.report_path}",
        ]
        if completion.dwg_error:
            summary.append(f"DWG 未生成：{completion.dwg_error}")
            QMessageBox.warning(window, "DXF 已完成，DWG 未生成", "\n".join(summary))
        else:
            QMessageBox.information(window, "CAD 导出完成", "\n".join(summary))
        window.statusBar().showMessage(
            f"当前页 CAD 已导出：{completion.dwg_path or result.path}"
        )

    window._start_processing(operation, completed, "正在后台导出当前页 CAD…")


def export_trace_from_window(window: Any) -> None:
    """Start a responsive background export instead of blocking the Qt UI thread."""

    if window._is_processing():
        QMessageBox.information(window, "正在处理", "请等待当前任务完成或取消。")
        return
    if bool(getattr(window, "_native_pdf_mode", False)):
        _start_document_export(window)
    else:
        _start_single_export(window)
