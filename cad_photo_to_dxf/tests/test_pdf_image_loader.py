from __future__ import annotations

from PIL import Image, ImageDraw

from app.image_loader import load_image, pdf_page_count, pdf_page_size_mm


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


def test_pdf_page_size_mm_reports_page_dimensions(tmp_path) -> None:
    pdf_path = tmp_path / "scan-size.pdf"
    page = Image.new("RGB", (720, 360), "white")
    page.save(pdf_path, "PDF", resolution=72.0)

    width_mm, height_mm = pdf_page_size_mm(pdf_path, 0)

    assert 250.0 < width_mm < 260.0
    assert 125.0 < height_mm < 130.0
