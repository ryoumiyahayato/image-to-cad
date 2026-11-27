import subprocess
import sys
from io import BytesIO
from pathlib import Path

import ezdxf
import pymupdf as fitz
import pytest
from PIL import Image

from tools.native_first.import_pdf import export_page, inspect_page


def make_pdf(tmp_path, *, rotation=0, scan=False, invisible_text=False):
    path = tmp_path / f"input-{rotation}-{scan}-{invisible_text}.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    if not scan:
        page.draw_line((20, 20), (140, 20), width=1)
        page.draw_circle((170, 90), 25, width=1)
        # A PDF quarter circle is stored as a cubic, but belongs in CAD as ARC.
        k = 20 * 0.5522847498307936
        page.draw_bezier((160, 140), (160, 140+k), (140+k, 160), (140, 160), width=1)
        page.draw_bezier((30, 80), (70, 40), (50, 150), (90, 120), width=1)
        page.insert_text((20, 170), "Editable words 2026", fontsize=11)
    image = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
    for x in range(4, 25):
        image.putpixel((x, 10), (0, 0, 0, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image((200, 30, 260, 70), stream=buffer.getvalue())
    if invisible_text:
        page.insert_text((40, 70), "Hidden OCR must not be painted", render_mode=3)
    page.set_rotation(rotation)
    document.save(path)
    document.close()
    return path


@pytest.mark.parametrize("rotation", [0, 90])
def test_native_mixed_page_retains_editable_objects_and_alpha(tmp_path, rotation):
    source = make_pdf(tmp_path, rotation=rotation)
    output = tmp_path / f"page-{rotation}.dxf"
    report = export_page(source, output)
    drawing = ezdxf.readfile(output)
    assert report["route"] == "vector" and report["ocr_calls"] == 0
    assert report["counts"] == {"LINE": 1, "CIRCLE": 1, "ARC": 1, "SPLINE": 1, "TEXT": 1, "IMAGE": 1}
    assert drawing.modelspace().query("TEXT")[0].dxf.text == "Editable words 2026"
    line = drawing.modelspace().query("LINE")[0]
    expected = (20, 180) if rotation == 0 else (180, 280)
    assert line.dxf.start.x == pytest.approx(expected[0] * 25.4 / 72)
    assert line.dxf.start.y == pytest.approx(expected[1] * 25.4 / 72)
    arc = drawing.modelspace().query("ARC")[0]
    assert arc.dxf.radius == pytest.approx(20 * 25.4 / 72, abs=1e-5)
    assert (arc.dxf.end_angle - arc.dxf.start_angle) % 360 == pytest.approx(90, abs=1e-4)
    image = drawing.modelspace().query("IMAGE")[0]
    pixels = Image.open(output.parent / image.image_def.dxf.filename)
    assert pixels.getextrema()[-1] == (0, 255)
    assert not drawing.audit().errors
    original_line = tuple(line.dxf.start), tuple(line.dxf.end)
    drawing.modelspace().query("TEXT")[0].dxf.text = "Edited whole line"
    edited = tmp_path / "edited.dxf"
    drawing.saveas(edited)
    reopened = ezdxf.readfile(edited)
    assert reopened.modelspace().query("TEXT")[0].dxf.text == "Edited whole line"
    neighbor = reopened.modelspace().query("LINE")[0]
    assert (tuple(neighbor.dxf.start), tuple(neighbor.dxf.end)) == original_line


def test_hidden_ocr_scan_routes_to_scanning(tmp_path):
    source = make_pdf(tmp_path, scan=True, invisible_text=True)
    assert inspect_page(source)["route"] == "scan"
    output = tmp_path / "not-a-native-page.dxf"
    assert export_page(source, output)["route"] == "scan"
    assert not output.exists()


def test_output_not_overwritten_and_page_range_is_explicit(tmp_path):
    source = make_pdf(tmp_path)
    output = tmp_path / "original.dxf"
    output.write_text("Keep user drawing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_page(source, output)
    assert output.read_text() == "Keep user drawing"
    with pytest.raises(ValueError, match="PAGE_OUT_OF_RANGE"):
        inspect_page(source, 0)


def test_direct_pdf_api_protects_reports_previews_and_input(tmp_path):
    source = make_pdf(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "protected.dxf"
    report = output.with_suffix(".report.json")
    report.write_text("Existing user report", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_page(source, output)
    assert report.read_text() == "Existing user report" and not output.exists()
    report.unlink()
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"Existing user preview")
    with pytest.raises(FileExistsError):
        export_page(source, output, preview_path=preview)
    assert preview.read_bytes() == b"Existing user preview" and not output.exists()
    for destination, options in (
        (source, {}), (tmp_path / "wrong.png", {}),
        (output, {"preview_path": source}), (output, {"preview_path": output}),
        (output, {"preview_path": report}),
    ):
        with pytest.raises(ValueError):
            export_page(source, destination, overwrite=True, **options)
    for page in (1.5, True):
        with pytest.raises(ValueError, match="PAGE_INVALID"):
            inspect_page(source, page)
    assert source.read_bytes() == before and not output.exists()


def test_cli_inspection_uses_the_product_converter(tmp_path):
    source = make_pdf(tmp_path)
    repo = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, "-m", "tools.native_first.import_pdf", str(source), "--inspect"],
                            cwd=repo, capture_output=True, text=True, check=True)
    assert '"route": "vector"' in result.stdout
