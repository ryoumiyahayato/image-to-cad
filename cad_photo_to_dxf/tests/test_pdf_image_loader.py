from __future__ import annotations

from PIL import Image, ImageDraw

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
