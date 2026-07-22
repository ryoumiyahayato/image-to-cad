from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
DEFAULT_PDF_DPI = 300
MAX_PDF_RENDER_PIXELS = 80_000_000


def pdf_page_count(path: str | Path) -> int:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if file_path.suffix.lower() != ".pdf":
        return 1
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 读取组件 pypdfium2") from exc
    document = pdfium.PdfDocument(str(file_path))
    try:
        count = len(document)
    finally:
        document.close()
    if count <= 0:
        raise ValueError("PDF 不包含可读取页面")
    return count


def pdf_page_size_mm(path: str | Path, page_index: int) -> tuple[float, float]:
    """Return one PDF page size in millimetres without rendering the page."""

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if file_path.suffix.lower() != ".pdf":
        raise ValueError("Page dimensions are available only for PDF input")
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 读取组件 pypdfium2") from exc
    document = pdfium.PdfDocument(str(file_path))
    try:
        if not 0 <= page_index < len(document):
            raise IndexError(f"PDF 页码超出范围：{page_index + 1}/{len(document)}")
        page = document[page_index]
        try:
            width_points, height_points = page.get_size()
        finally:
            page.close()
    finally:
        document.close()
    factor = 25.4 / 72.0
    return float(width_points) * factor, float(height_points) * factor


def _load_pdf_page(
    file_path: Path,
    page_index: int,
    pdf_dpi: int,
    *,
    grayscale: bool = False,
) -> np.ndarray:
    if pdf_dpi < 72 or pdf_dpi > 1200:
        raise ValueError("PDF 渲染 DPI 必须在 72 到 1200 之间")
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 读取组件 pypdfium2") from exc

    document = pdfium.PdfDocument(str(file_path))
    try:
        page_count = len(document)
        if not 0 <= page_index < page_count:
            raise IndexError(
                f"PDF 页码超出范围：{page_index + 1}/{page_count}"
            )
        page = document[page_index]
        try:
            width_points, height_points = page.get_size()
            scale = float(pdf_dpi) / 72.0
            estimated_pixels = width_points * height_points * scale * scale
            if estimated_pixels > MAX_PDF_RENDER_PIXELS:
                scale *= math.sqrt(MAX_PDF_RENDER_PIXELS / estimated_pixels)
            bitmap = page.render(scale=scale, grayscale=grayscale)
            try:
                pil_image = bitmap.to_pil().convert("L" if grayscale else "RGB")
                rendered = np.asarray(pil_image, dtype=np.uint8)
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()

    if rendered.size == 0:
        raise ValueError(f"无法渲染 PDF 页面：{file_path}")
    if grayscale:
        return np.ascontiguousarray(rendered)
    return cv2.cvtColor(np.ascontiguousarray(rendered), cv2.COLOR_RGB2BGR)


def load_image(
    path: str | Path,
    *,
    page_index: int = 0,
    pdf_dpi: int = DEFAULT_PDF_DPI,
    grayscale: bool = False,
) -> np.ndarray:
    """Load a raster image or render one page of a scanned PDF.

    ``grayscale=True`` avoids allocating a three-channel 300-DPI page for OCR and
    exact tracing. The normal preview path remains colour by default.
    """

    file_path = Path(path)
    extension = file_path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image type: {file_path.suffix}")
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if extension == ".pdf":
        return _load_pdf_page(
            file_path,
            page_index,
            pdf_dpi,
            grayscale=grayscale,
        )

    data = np.fromfile(str(file_path), dtype=np.uint8)
    image = cv2.imdecode(
        data,
        cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR,
    )
    if image is None:
        raise ValueError(f"Unable to decode image: {file_path}")
    return np.ascontiguousarray(image)


def save_image(path: str | Path, image: np.ndarray) -> None:
    """Save an image to a path, including paths containing non-ASCII text."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    extension = file_path.suffix.lower() or ".png"
    ok, encoded = cv2.imencode(extension, image)
    if not ok:
        raise ValueError(f"Unable to encode image as {extension}")
    encoded.tofile(str(file_path))
