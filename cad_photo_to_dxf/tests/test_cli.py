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
        '--headless', '--allow-uncorrected', '--input', str(source),
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
    assert report['structure_id'] == structure.structure_id
    assert report['source_size_px'] == list(structure.source_size_px)
    document = ezdxf.readfile(args.output)
    assert not document.audit().errors
    assert len(document.modelspace().query('LINE')) == len(structure.straight_lines)
    assert cv2.imread(str(args.preview)) is not None
