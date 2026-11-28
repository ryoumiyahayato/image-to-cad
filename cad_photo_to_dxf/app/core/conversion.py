"""One ordinary conversion entry shared by the desktop, CLI and build smoke."""
from __future__ import annotations
import json
import math
from pathlib import Path
import time

from app.core.cancellation import checkpoint, report_progress

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
MAX_RENDER_PIXELS = 32_000_000


def inspect_document(source) -> dict:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("支持 PDF、PNG、JPG、TIFF 和 BMP 文件")
    if path.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError("请先解锁受密码保护的 PDF")
            return {"input": str(path), "kind": "pdf", "pages": len(document)}
    from PIL import Image
    with Image.open(path) as image:
        return {"input": str(path), "kind": "image",
                "pages": getattr(image, "n_frames", 1), "size": list(image.size)}


def _render_pdf_page(source: Path, page_number: int, dpi: float):
    import cv2
    import numpy as np
    import pymupdf
    with pymupdf.open(source) as document:
        page = document[page_number - 1]
        area = page.rect.width * page.rect.height
        limit = math.sqrt(MAX_RENDER_PIXELS / max(area, 1.0)) * 72.0
        actual_dpi = min(dpi, limit)
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(actual_dpi / 72, actual_dpi / 72),
            colorspace=pymupdf.csRGB, alpha=False,
        )
        rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), actual_dpi


def convert_document(
    source, output, *, page_number=None, all_pages=False, dpi=300.0,
    enable_ocr=True, perspective=False, overwrite=False, preview_path=None,
    report_path=None, cancellation_token=None, progress_callback=None,
    preserve_regions=(), drawing_scale=1.0,
) -> dict:
    """Convert ordinary input; PDF/TIFF without --page exports all pages."""
    started = time.monotonic()
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    try:
        dpi = float(dpi)
    except (TypeError, ValueError) as error:
        raise ValueError("DPI 必须介于 72 和 1200 之间") from error
    if not math.isfinite(dpi) or not 72 <= dpi <= 1200:
        raise ValueError("DPI 必须介于 72 和 1200 之间")
    if isinstance(drawing_scale, bool):
        raise ValueError("图纸比例必须为正有限数，例如 1:100 输入 100")
    try:
        drawing_scale = float(drawing_scale)
    except (TypeError, ValueError) as error:
        raise ValueError("图纸比例必须为正有限数，例如 1:100 输入 100") from error
    if not math.isfinite(drawing_scale) or drawing_scale <= 0:
        raise ValueError("图纸比例必须为正有限数，例如 1:100 输入 100")
    if output.suffix.lower() != ".dxf":
        raise ValueError("输出文件必须使用 .dxf 扩展名")
    if source == output:
        raise ValueError("输入和输出路径必须不同")
    document = inspect_document(source)
    total = document["pages"]
    if total < 1:
        raise ValueError("输入文件没有可读取页面")
    if page_number is not None and all_pages:
        raise ValueError("请选择指定页或全部页面")
    if page_number is not None:
        try:
            selected_page = int(page_number)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("页码必须为整数，从 1 开始") from error
        if isinstance(page_number, bool) or selected_page != page_number:
            raise ValueError("页码必须为整数，从 1 开始")
        if not 1 <= selected_page <= total:
            raise ValueError(f"页码超出范围：1–{total}")
        selected = [selected_page]
    else:
        selected = list(range(1, total + 1))
    multiple = len(selected) > 1
    if multiple and preview_path is not None:
        raise ValueError("多页转换会为每页保存预览；--preview 仅用于单页")
    if multiple and preserve_regions:
        raise ValueError("保留区域针对单页坐标，请同时指定 --page")
    destinations = [
        output.with_name(f"{output.stem}-p{page:03d}.dxf") if multiple else output
        for page in selected
    ]
    previews = [
        Path(preview_path).expanduser().resolve() if preview_path else path.with_suffix(".preview.png")
        for path in destinations
    ]
    report_file = Path(report_path).expanduser().resolve() if report_path else output.with_suffix(".report.json")
    artifacts = destinations + previews + [report_file]
    if len(set(artifacts)) != len(artifacts) or source in artifacts:
        raise ValueError("DXF、预览和报告必须使用不同路径")
    for path in artifacts:
        if path.exists() and not overwrite:
            raise FileExistsError(f"文件已存在：{path}；请更换输出名称或启用覆盖")
    output.parent.mkdir(parents=True, exist_ok=True)
    results, warnings = [], []
    for index, (number, destination, preview) in enumerate(zip(selected, destinations, previews)):
        checkpoint(cancellation_token)

        def progress(stage, fraction):
            report_progress(progress_callback, f"第 {number}/{total} 页 · {stage}",
                            (index + fraction) / len(selected))

        progress("读取输入", 0.0)
        if document["kind"] == "pdf":
            from app.core.pdf_conversion import convert_pdf_page, inspect_pdf_page
            page = inspect_pdf_page(source, number)
            if page["route"] == "vector":
                result = convert_pdf_page(
                    source, destination, page_number=number, overwrite=overwrite,
                    write_report=False,
                    cancellation_token=cancellation_token, progress_callback=progress,
                )
            else:
                from app.core.scan_conversion import convert_scan
                image, actual_dpi = _render_pdf_page(source, number, float(dpi))
                result = convert_scan(
                    source, destination, image=image, page_index=number - 1,
                    dpi=actual_dpi, enable_ocr=enable_ocr, perspective=False,
                    preserve_regions=preserve_regions, drawing_scale=drawing_scale,
                    cancellation_token=cancellation_token, progress_callback=progress,
                )
                result["route"] = "scan-pdf"
                result["render_dpi"] = actual_dpi
                if actual_dpi < dpi:
                    result.setdefault("warnings", []).append(
                        f"大幅面扫描页按 {actual_dpi:.1f} DPI 处理以控制内存；请求值为 {dpi:g} DPI。"
                    )
                del image
        else:
            from app.core.scan_conversion import convert_scan
            result = convert_scan(
                source, destination, dpi=float(dpi), page_index=number - 1,
                enable_ocr=enable_ocr, perspective=perspective,
                preserve_regions=preserve_regions, drawing_scale=drawing_scale,
                cancellation_token=cancellation_token, progress_callback=progress,
            )
        checkpoint(cancellation_token)
        if drawing_scale != 1 and result["route"] == "vector":
            import ezdxf
            from ezdxf.math import Matrix44
            saved = ezdxf.readfile(destination)
            transform = Matrix44.scale(drawing_scale)
            for entity in saved.modelspace():
                entity.transform(transform)
            saved.saveas(destination)
        result["drawing_scale"] = drawing_scale
        from app.core.dxf_preview import render_dxf
        progress("生成实际 DXF 预览", 0.95)
        try:
            render_dxf(destination, preview)
            result["preview"] = str(preview)
        except Exception as error:
            result.setdefault("warnings", []).append(f"DXF 已保存，预览生成失败：{error}")
            result["preview"] = None
        result["page_number"] = number
        result["output"] = str(destination)
        results.append(result)
        warnings.extend(f"第 {number} 页：{message}" for message in result.get("warnings", []))
        progress("完成", 1.0)
    report = {
        "schema": "image-to-cad-conversion-v1",
        "input": str(source), "outputs": results, "report": str(report_file),
        "page_count_total": total, "page_count_converted": len(results),
        "warnings": warnings, "elapsed_seconds": time.monotonic() - started,
        "coordinate_units": "mm", "drawing_scale": drawing_scale,
        "engineering_scale": "paper_size" if drawing_scale == 1 else "user_supplied_paper_to_model_ratio",
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
