from __future__ import annotations

import pytest

from main import build_parser


def test_cli_accepts_positive_finite_dimensions() -> None:
    args = build_parser().parse_args(
        [
            "--headless",
            "--input",
            "drawing.png",
            "--paper-width-mm",
            "297",
            "--paper-height-mm",
            "210",
        ]
    )
    assert args.paper_width_mm == 297.0
    assert args.paper_height_mm == 210.0


@pytest.mark.parametrize(
    "arguments",
    [
        ["--paper-width-mm", "nan"],
        ["--paper-width-mm", "inf"],
        ["--paper-height-mm", "0"],
        ["--paper-height-mm", "-1"],
    ],
)
def test_cli_rejects_invalid_numeric_inputs(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(arguments)
    assert exc.value.code == 2


@pytest.mark.parametrize("arguments", [
    ["--no-hatch"], ["--min-line-length", "35"],
    ["--threshold-strength", "12"], ["--auxiliary"],
])
def test_cli_rejects_retired_flags(arguments: list[str]) -> None:
    parser = build_parser()
    assert arguments[0] not in parser.format_help()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(arguments)
    assert exc.value.code == 2


def test_headless_exports_shared_final_structure_with_gui_image_settings(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import cv2
    import ezdxf
    from main import run_headless
    from app.core.processing import ProductionProcessingService
    from app.gui.processing import _processing_config
    from tests.test_processing_contract import _page
    source = tmp_path / 'page.png'
    assert cv2.imwrite(str(source), _page())
    args = build_parser().parse_args([
        '--headless', '--mode', 'legacy', '--allow-uncorrected', '--input', str(source),
        '--output', str(tmp_path / 'page.dxf'),
        '--preview', str(tmp_path / 'preview.png'),
        '--report', str(tmp_path / 'report.json'),
    ])
    original = ProductionProcessingService.process_page
    seen = []
    def capture(image, config, **options):
        result = original(image, config, **options)
        seen.append((config, result.final_structure))
        return result
    monkeypatch.setattr(ProductionProcessingService, 'process_page', capture)
    assert run_headless(args) == 0
    assert len(seen) == 1
    config, structure = seen[0]
    gui_config = _processing_config(SimpleNamespace(_native_pdf_mode=False, _ocr_enabled=lambda: False), None)
    assert config == gui_config
    report = json.loads(args.report.read_text(encoding='utf-8'))
    from app.version import __version__
    assert report['application_version'] == __version__
    assert report['product_status']['status'] == 'LOCAL_NO_GO'
    assert report['product_status']['native_object_reconstruction_verified'] is False
    assert report['structure_id'] == structure.structure_id
    assert report['source_size_px'] == list(structure.source_size_px)
    document = ezdxf.readfile(args.output)
    assert not document.audit().errors
    assert len(document.modelspace().query('LINE')) == len(structure.straight_lines)
    assert cv2.imread(str(args.preview)) is not None


def test_headless_uses_native_tiff_dpi_and_reports_only_reviewed_crop_dust(tmp_path):
    import json
    import cv2
    import ezdxf
    import numpy as np
    from PIL import Image
    from main import run_headless

    high = np.full((512, 512), 255, dtype=np.uint8)
    high[48:290:20, 48:290:20] = 0
    original = tmp_path / "original.tiff"
    Image.fromarray(high).convert("1").save(original, dpi=(200, 200))
    low = cv2.resize(high, (256, 256), interpolation=cv2.INTER_AREA)
    source = tmp_path / "source.png"
    assert cv2.imwrite(str(source), low)
    output = tmp_path / "crop.dxf"
    report = tmp_path / "crop.json"
    args = build_parser().parse_args([
        "--headless", "--mode", "legacy", "--input", str(source), "--source-dpi", "100",
        "--original-scan", str(original), "--blank-paper", "73", "73", "76", "76",
        "--crop", "64", "64", "128", "128", "--allow-empty",
        "--output", str(output), "--preview", str(tmp_path / "crop.png"),
        "--report", str(report),
    ])

    assert run_headless(args) == 0

    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["scan_dust"]["status"] == "VERIFIED_ORIGINAL_GRID"
    assert record["scan_classification"]["source_crop"] == [64, 64, 128, 128]
    assert record["scan_classification"]["removed_noise_runs_y_x0_x1"] == [[10, 10, 11]]
    assert ezdxf.readfile(output).units == 4


def test_rotated_pdf_uses_same_capped_page_grid_in_gui_and_cli(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    import ezdxf
    import numpy as np
    import pypdfium2 as pdfium
    from PySide6.QtWidgets import QApplication

    from app.core import image_loader, preview
    from app.core.arc_types import ArcSegment
    from app.core.processing import ProductionProcessingService
    from app.core.scale_calibrator import ScaleCalibration, raster_to_cad
    from app.core.structure_build import build_final_structure
    from app.core.trace_types import TracePath
    from app.export.trace_single_export import export_final_structure_dxf
    from app.geometry.line_detect import LineSegment, NATIVE_OPEN_STROKE
    from app.gui import MainWindow
    from app.ocr.auxiliary_recognition import TextCandidate
    from main import run_headless

    path = tmp_path / "rotated.pdf"
    with pdfium.PdfDocument.new() as pdf:
        page = pdf.new_page(144, 90)
        page.set_rotation(90)
        page.close()
        pdf.save(path)
    monkeypatch.setattr(image_loader, "MAX_PDF_RENDER_PIXELS", 26_900)
    monkeypatch.setattr(preview, "render_final_structure_preview", lambda s: s.contour_binary)

    def trace(image, config, *, source_crop=None, **kwargs):
        height, width = image.shape[:2]
        left, top, right, bottom = source_crop or (0, 0, width, height)
        size = right - left, bottom - top
        geometry = kwargs["pdf_geometry"]
        assert geometry.source_size_px == (width, height)
        assert geometry.binding["requested_dpi"] == config.source_dpi < 144
        if source_crop is not None:
            assert geometry.for_crop(source_crop).page_to_pixel[4:] == pytest.approx(
                (geometry.page_to_pixel[4] - left, geometry.page_to_pixel[5] - top)
            )
        line = LineSegment(11 - left, 13 - top, 31 - left, 13 - top)
        source_line = LineSegment(
            11 - left, 15 - top, 31 - left, 15 - top, history=(NATIVE_OPEN_STROKE,),
        )
        pixel = TracePath(((16 - left, 20 - top),), None, 0, 0)
        arc = ArcSegment("test-arc", (24 - left, 25 - top), 4., 0., 90.)
        text = TextCandidate("N.T.S.", (12 - left, 30 - top, 22, 9), .99, "text_candidate")
        binary = np.full(size[::-1], 255, np.uint8)
        binary[20 - top, 16 - left] = 0
        structure = build_final_structure(
            source_size_px=size, contour_binary=binary, contours=(pixel,),
            straight_lines=(line, source_line), arcs=(arc,), texts=(text,),
            provenance={"scan_classification": {"source_crop": source_crop}} if source_crop else {},
        )
        return SimpleNamespace(final_structure=structure)

    monkeypatch.setattr(ProductionProcessingService, "process_page", trace)
    _application = QApplication.instance() or QApplication([])
    gui = MainWindow()
    try:
        gui.current_path = path
        gui._native_pdf_mode = True
        gui._current_pdf_page_index = 0
        gui._pdf_page_sizes_mm = {0: image_loader.pdf_page_size_mm(path, 0)}
        assert gui._processing_pdf_dpi(0) == 240
        image = gui._load_trace_source_for_current_page()
        config = gui._processing_config(0, enable_ocr=False)
        geometry = gui._current_pdf_geometry
        w, h = geometry.source_size_px
        assert (w, h) == (129, 207)
        assert gui._pdf_page_sizes_mm[0] == pytest.approx((31.75, 50.8))
        a, b, c, d, tx, ty = geometry.page_to_pixel
        assert (tx, ty) == pytest.approx((0, 0))
        assert (a * 144 + c * 90 + tx, b * 144 + d * 90 + ty) == pytest.approx((w, h))
        structure = trace(image, config, pdf_geometry=geometry).final_structure
        gui._final_structure = structure
        gui.drawing_scale_spin.setValue(50)
        assert gui._export_drawing_multiplier() == 1
        small_preview = image_loader.load_image(path, pdf_dpi=72)
        assert small_preview.shape[:2] != image.shape[:2]
        gui_path = tmp_path / "gui.dxf"
        export_final_structure_dxf(
            structure, gui_path, gui.calibration, raster_image=small_preview,
            drawing_multiplier=gui._export_drawing_multiplier(),
        )
    finally:
        gui.close()

    paths = [gui_path]
    for name, options, requested_dpi in (
        ("full", [], 240),
        ("crop", ["--source-dpi", "144", "--crop", "7", "9", "47", "49"], 144),
    ):
        output = tmp_path / f"{name}.dxf"
        args = build_parser().parse_args([
            "--headless", "--mode", "legacy", "--input", str(path), *options,
            "--output", str(output), "--preview", str(tmp_path / f"{name}.png"),
            "--report", str(tmp_path / f"{name}.json"),
        ])
        assert run_headless(args) == 0
        record = json.loads(args.report.read_text(encoding="utf-8"))
        assert record["pdf_render"]["size_px"] == [w, h]
        assert record["pdf_render"]["rotation"] == 90
        assert record["pdf_render"]["requested_dpi"] == requested_dpi
        assert record["processing_contract"] == config.payload()
        assert record["coordinate_space"] == "paper_mm"
        paths.append(output)

    frame = raster_to_cad((w, h), ScaleCalibration.for_paper((w, h), (31.75, 50.8)))
    assert frame.center(11, 13) == pytest.approx((11.5 * 31.75 / w, 50.8 - 13.5 * 50.8 / h))
    for output in paths:
        document = ezdxf.readfile(output)
        assert document.units == 4
        space = document.modelspace()
        line, source_line = space.query("LINE")
        assert tuple(line.dxf.start)[:2] == pytest.approx(frame.center(11, 13))
        assert tuple(line.dxf.end)[:2] == pytest.approx(frame.center(31, 13))
        assert tuple(source_line.dxf.start)[:2] == pytest.approx(frame.edge(11, 15))
        assert tuple(source_line.dxf.end)[:2] == pytest.approx(frame.edge(31, 15))
        cell = space.query("HATCH")[0].paths[0].vertices
        assert tuple(cell[0])[:2] == pytest.approx(frame.edge(16, 20))
        assert tuple(cell[2])[:2] == pytest.approx(frame.edge(17, 21))
        curve = space.query("ELLIPSE")[0].construction_tool()
        assert tuple(curve.start_point)[:2] == pytest.approx(frame.edge(28, 25))
        assert tuple(curve.end_point)[:2] == pytest.approx(frame.edge(24, 21))

    warped = ScaleCalibration.for_paper((11, 6), (20, 15), corners_at_centers=True)
    warped_frame = raster_to_cad((11, 6), warped)
    assert warped_frame.center(0, 0) == pytest.approx((0, 15))
    assert warped_frame.center(10, 5) == pytest.approx((20, 0))
    assert warped_frame.edge(0, 0) == pytest.approx((-1, 16.5))
