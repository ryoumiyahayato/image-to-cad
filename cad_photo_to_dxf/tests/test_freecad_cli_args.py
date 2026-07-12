from __future__ import annotations

from pathlib import Path

from validation.freecad_import_check import _parse_args


def test_freecad_checker_accepts_normal_python_arguments(tmp_path: Path) -> None:
    source = tmp_path / "input.dxf"
    output = tmp_path / "evidence.json"
    args = _parse_args(["--input", str(source), "--output", str(output)])
    assert args.input == source
    assert args.output == output


def test_freecad_checker_ignores_its_script_path_from_freecadcmd(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.dxf"
    output = tmp_path / "evidence.json"
    script = Path(__file__).resolve().parents[1] / "validation" / "freecad_import_check.py"
    args = _parse_args(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            str(script),
        ]
    )
    assert args.input == source
    assert args.output == output
