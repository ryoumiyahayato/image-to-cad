"""Exercise the public product entry with saved mixed-page files."""
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import ezdxf
import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw

from app.core.cancellation import CancellationToken, ProcessingCancelled
from app.core.conversion import convert_document


@pytest.fixture
def mixed_pdf(tmp_path):
    source = tmp_path / "mixed.pdf"
    logo = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
    ImageDraw.Draw(logo).line((3, 16, 15, 3, 27, 16), fill=(0, 0, 0, 255), width=2)
    buffer = BytesIO()
    logo.save(buffer, format="PNG")
    scan = Image.new("RGB", (480, 320), "white")
    pen = ImageDraw.Draw(scan)
    pen.line((35, 55, 410, 55), fill="black", width=5)
    pen.rectangle((40, 120, 290, 265), outline="black", width=5)
    scan_buffer = BytesIO()
    scan.save(scan_buffer, format="PNG")
    with fitz.open() as pdf:
        native = pdf.new_page(width=240, height=160)
        native.draw_line((20, 30), (150, 30), width=1)
        native.insert_text((20, 90), "Editable room A-12", fontsize=12)
        native.insert_image((175, 20, 220, 50), stream=buffer.getvalue())
        scanned = pdf.new_page(width=240, height=160)
        scanned.insert_image(scanned.rect, stream=scan_buffer.getvalue())
        pdf.save(source)
    return source


@pytest.mark.parametrize("all_pages", [False, True])
def test_default_and_explicit_all_pages_route_each_page(mixed_pdf, tmp_path, all_pages):
    result = convert_document(mixed_pdf, tmp_path / "all.dxf", all_pages=all_pages,
                              enable_ocr=False, dpi="72")
    assert result["page_count_total"] == result["page_count_converted"] == 2
    assert [page["route"] for page in result["outputs"]] == ["vector", "scan-pdf"]
    native, scanned = [ezdxf.readfile(page["output"]) for page in result["outputs"]]
    assert native.modelspace().query("TEXT")[0].dxf.text == "Editable room A-12"
    assert scanned.modelspace().query("LINE")
    assert not scanned.modelspace().query("TEXT")
    assert result["outputs"][1]["ocr"]["enabled"] is False
    for page, saved in zip(result["outputs"], (native, scanned)):
        assert not saved.audit().errors
        with Image.open(page["preview"]) as preview:
            assert preview.format == "PNG" and min(preview.size) > 0
    assert json.loads(Path(result["report"]).read_text())["page_count_converted"] == 2


def test_selected_scan_page_and_default_overwrite_protection(mixed_pdf, tmp_path):
    output = tmp_path / "selected.dxf"
    result = convert_document(mixed_pdf, output, page_number=2, enable_ocr=False, dpi=72)
    assert result["page_count_converted"] == 1
    assert result["outputs"][0]["route"] == "scan-pdf"
    assert result["outputs"][0]["page_number"] == 2
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        convert_document(mixed_pdf, output, page_number=2, enable_ocr=False, dpi=72)
    assert output.read_bytes() == before


def test_scale_changes_geometry_text_and_image_together(mixed_pdf, tmp_path):
    drawings = []
    for scale in (1, 100):
        result = convert_document(mixed_pdf, tmp_path / f"scale-{scale}.dxf",
                                  page_number=1, drawing_scale=scale, enable_ocr=False)
        assert result["drawing_scale"] == scale
        drawings.append(ezdxf.readfile(result["outputs"][0]["output"]))
    original, scaled = [document.modelspace() for document in drawings]
    for kind, properties in (
        ("LINE", ("start", "end")),
        ("TEXT", ("insert",)),
        ("IMAGE", ("insert", "u_pixel", "v_pixel")),
    ):
        before, after = original.query(kind)[0], scaled.query(kind)[0]
        for property_name in properties:
            assert tuple(after.dxf.get(property_name)) == pytest.approx(
                tuple(value * 100 for value in before.dxf.get(property_name)))
    before_text, after_text = original.query("TEXT")[0], scaled.query("TEXT")[0]
    assert after_text.dxf.height == pytest.approx(before_text.dxf.height * 100)
    assert after_text.dxf.width == pytest.approx(before_text.dxf.width)
    assert after_text.dxf.text == before_text.dxf.text
    assert tuple(scaled.query("IMAGE")[0].dxf.image_size) == tuple(original.query("IMAGE")[0].dxf.image_size)
    assert not drawings[1].audit().errors


def test_cancellation_before_and_during_conversion_leaves_no_dxf(mixed_pdf, tmp_path):
    for timing in ("before", "during"):
        token = CancellationToken()
        if timing == "before":
            token.cancel()

        def progress(stage, fraction):
            if "PDF 原生对象" in stage:
                token.cancel()

        output = tmp_path / f"cancel-{timing}.dxf"
        with pytest.raises(ProcessingCancelled):
            convert_document(mixed_pdf, output, page_number=1,
                              cancellation_token=token, progress_callback=progress)
        assert not output.exists()
        assert not output.with_suffix(".report.json").exists()


def test_public_parameters_and_artifact_paths_are_validated(mixed_pdf, tmp_path):
    output = tmp_path / "invalid.dxf"
    invalid = [
        {"page_number": 0}, {"page_number": 3}, {"page_number": 1.5},
        {"page_number": True}, {"page_number": 1, "all_pages": True},
        {"dpi": float("nan")}, {"drawing_scale": 0},
        {"drawing_scale": float("inf")}, {"drawing_scale": True},
        {"page_number": 1, "preview_path": mixed_pdf},
        {"page_number": 1, "report_path": mixed_pdf},
        {"page_number": 1, "report_path": output},
        {"page_number": 1, "preview_path": output},
    ]
    before = mixed_pdf.read_bytes()
    with pytest.raises(ValueError):
        convert_document(mixed_pdf, mixed_pdf, enable_ocr=False)
    for options in invalid:
        with pytest.raises(ValueError):
            convert_document(mixed_pdf, output, enable_ocr=False, **options)
        assert not output.exists()
        assert mixed_pdf.read_bytes() == before


def test_custom_report_does_not_overwrite_an_unrequested_sidecar(mixed_pdf, tmp_path):
    output = tmp_path / "custom.dxf"
    unrelated = output.with_suffix(".report.json")
    unrelated.write_text("Existing user report", encoding="utf-8")
    result = convert_document(mixed_pdf, output, page_number=1,
                              report_path=tmp_path / "summary.json", enable_ocr=False)
    assert Path(result["report"]).name == "summary.json"
    assert unrelated.read_text() == "Existing user report"


def test_ordinary_cli_input_needs_no_native_roi_or_job_options(mixed_pdf, tmp_path):
    repo = Path(__file__).resolve().parents[2]
    output = tmp_path / "cli.dxf"
    process = subprocess.run(
        [sys.executable, str(repo / "cad_photo_to_dxf" / "main.py"),
         "--input", str(mixed_pdf), "--output", str(output), "--no-ocr", "--dpi", "72"],
        cwd=repo, capture_output=True, text=True, timeout=60,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(output.with_suffix(".report.json").read_text())
    assert result["page_count_converted"] == 2
    assert [page["route"] for page in result["outputs"]] == ["vector", "scan-pdf"]
    for page in result["outputs"]:
        assert len(ezdxf.readfile(page["output"]).modelspace()) > 0
