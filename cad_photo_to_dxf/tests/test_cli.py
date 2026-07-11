from __future__ import annotations

import pytest

from main import build_parser


def test_cli_accepts_positive_finite_dimensions() -> None:
    args = build_parser().parse_args(
        [
            "--headless",
            "--input",
            "drawing.png",
            "--min-line-length",
            "25",
            "--paper-width-mm",
            "297",
            "--paper-height-mm",
            "210",
        ]
    )
    assert args.min_line_length == 25
    assert args.paper_width_mm == 297.0
    assert args.paper_height_mm == 210.0


@pytest.mark.parametrize(
    "arguments",
    [
        ["--min-line-length", "0"],
        ["--min-line-length", "-5"],
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
