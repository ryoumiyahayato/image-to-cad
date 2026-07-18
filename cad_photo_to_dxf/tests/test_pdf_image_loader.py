from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
import pypdfium2 as pdfium
import pytest

from app.image_loader import load_image, pdf_page_count


def test_load_image_renders_image_only_pdf(tmp_path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    page = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(page)
    draw.line((10, 20, 150, 20), fill="black", width=3)
    page.save(pdf_path, "PDF", resolution=144.0)

    assert pdf_page_count(pdf_path) == 1
    image = load_image(pdf_path, page_index=0, pdf_dpi=144)

    assert image.ndim == 3
    assert image.shape[0] > 0
    assert image.shape[1] > 0
    assert int(image.min()) < 100


def test_pdf_page_size_mm_matches_page_aspect(tmp_path: Path) -> None:
    from app.image_loader import pdf_page_size_mm

    pdf_path = tmp_path / "sized.pdf"
    document = pdfium.PdfDocument.new()
    document.new_page(width=720, height=360, index=0)
    document.save(str(pdf_path), version=17)
    document.close()

    width_mm, height_mm = pdf_page_size_mm(pdf_path, 0)
    assert width_mm == pytest.approx(254.0, rel=1e-6)
    assert height_mm == pytest.approx(127.0, rel=1e-6)
