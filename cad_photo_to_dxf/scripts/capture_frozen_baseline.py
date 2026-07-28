from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter
from typing import Any
import xml.etree.ElementTree as ET


PACKAGE_NAMES = (
    "numpy",
    "scipy",
    "opencv-python",
    "ezdxf",
    "PySide6",
    "pypdfium2",
    "Pillow",
    "rapidocr",
    "onnxruntime",
    "pytest",
    "ruff",
    "mypy",
)
CORE_SOURCE_FILES = (
    "app/optimized_trace.py",
    "app/raster_trace.py",
    "app/scan_cleanup.py",
    "app/ocr_recognition.py",
    "app/ocr_pipeline.py",
    "app/trace_single_export.py",
    "app/straight_line_reconstruction.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a reproducible test, configuration and three-page DXF "
            "snapshot from one frozen image-to-CAD Git worktree."
        )
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--junit-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--enable-ocr",
        action="store_true",
        help="Opt in to OCR. The frozen production default is OCR disabled.",
    )
    return parser


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _git_commit(project_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def _source_hashes(project_root: Path) -> dict[str, str | None]:
    return {
        relative: (
            _file_sha256(project_root / relative)
            if (project_root / relative).is_file()
            else None
        )
        for relative in CORE_SOURCE_FILES
    }


def _junit_summary(path: Path) -> dict[str, int | float | str]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    top_level = [
        suite
        for suite in suites
        if suite is root or suite not in list(root.iter("testsuite/testsuite"))
    ]
    selected = top_level or suites
    return {
        "tests": sum(int(float(suite.attrib.get("tests", 0))) for suite in selected),
        "failures": sum(
            int(float(suite.attrib.get("failures", 0))) for suite in selected
        ),
        "errors": sum(
            int(float(suite.attrib.get("errors", 0))) for suite in selected
        ),
        "skipped": sum(
            int(float(suite.attrib.get("skipped", 0))) for suite in selected
        ),
        "time_seconds": round(
            sum(float(suite.attrib.get("time", 0.0)) for suite in selected),
            3,
        ),
        "junit_sha256": _file_sha256(path),
    }


def _callable_defaults(value: Any) -> dict[str, str]:
    signature = inspect.signature(value)
    return {
        name: repr(parameter.default)
        for name, parameter in signature.parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }


def _configuration_snapshot(
    *,
    project_root: Path,
    label: str,
    commit: str,
    test_summary: dict[str, Any],
    enable_ocr: bool,
) -> dict[str, Any]:
    from app import __version__
    from app.line_detect import LineDetectionParams
    from app.ocr_recognition import MAX_OCR_CANDIDATES, MIN_OCR_CONFIDENCE
    from app.optimized_trace import trace_image_optimized

    geometry_defaults = None
    try:
        from app.geometry_cleaner import GeometryCleanParams

        geometry_defaults = asdict(GeometryCleanParams())
    except (ImportError, TypeError):
        geometry_defaults = None

    final_structure_schema = None
    try:
        from app.final_structure import FINAL_STRUCTURE_SCHEMA_VERSION

        final_structure_schema = FINAL_STRUCTURE_SCHEMA_VERSION
    except ImportError:
        final_structure_schema = None

    return {
        "label": label,
        "git_commit": commit,
        "application_version": __version__,
        "final_structure_schema_version": final_structure_schema,
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "dependencies": _package_versions(),
        "default_configuration": {
            "trace_image_optimized": _callable_defaults(trace_image_optimized),
            "line_detection": asdict(LineDetectionParams()),
            "geometry_cleaning": geometry_defaults,
        },
        "ocr_configuration": {
            "enabled_for_baseline": enable_ocr,
            "production_default_enabled": False,
            "minimum_confidence": MIN_OCR_CONFIDENCE,
            "maximum_candidates": MAX_OCR_CANDIDATES,
            "rapidocr_parameters": {
                "Global.text_score": MIN_OCR_CONFIDENCE,
                "Global.max_side_len": 4096,
                "Global.log_level": "warning",
            },
        },
        "core_source_sha256": _source_hashes(project_root),
        "test_result": test_summary,
    }


def _output_metrics(
    *,
    input_path: Path,
    image: Any,
    trace_result: Any,
    export_result: Any,
    dxf_path: Path,
    trace_seconds: float,
    export_seconds: float,
) -> dict[str, Any]:
    import ezdxf

    structure = getattr(trace_result, "final_structure", None)
    dxf_document = ezdxf.readfile(dxf_path)
    audit = dxf_document.audit()
    return {
        "input_path": str(input_path),
        "input_sha256": _file_sha256(input_path),
        "source_size_px": [int(image.shape[1]), int(image.shape[0])],
        "trace_seconds": round(trace_seconds, 3),
        "export_seconds": round(export_seconds, 3),
        "threshold": int(trace_result.threshold),
        "foreground_pixels": int(trace_result.foreground_pixels),
        "contour_count": len(trace_result.paths),
        "contour_vertex_count": int(trace_result.vertex_count),
        "straight_line_count": len(getattr(trace_result, "straight_lines", ())),
        "text_count": len(getattr(trace_result, "texts", ())),
        "logo_count": len(getattr(trace_result, "logos", ())),
        "signature_count": len(getattr(trace_result, "signatures", ())),
        "structure_id": (
            getattr(structure, "structure_id", None)
            if structure is not None
            else None
        ),
        "dxf_path": str(dxf_path),
        "dxf_sha256": _file_sha256(dxf_path),
        "dxf_entity_count": len(dxf_document.modelspace()),
        "dxf_line_count": int(export_result.line_count),
        "dxf_text_count": int(export_result.text_count),
        "dxf_trace_path_count": int(export_result.trace_path_count),
        "dxf_trace_vertex_count": int(export_result.trace_vertex_count),
        "dxf_audit_error_count": len(audit.errors),
    }


def _capture_outputs(
    inputs: list[Path],
    output_dir: Path,
    *,
    enable_ocr: bool,
) -> list[dict[str, Any]]:
    import cv2

    from app.optimized_trace import trace_image_optimized
    from app.trace_single_export import export_exact_trace_dxf

    try:
        from app.trace_single_export import export_final_structure_dxf
    except ImportError:
        export_final_structure_dxf = None

    outputs_dir = output_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for input_path in inputs:
        image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError(f"Could not load baseline input: {input_path}")
        trace_started = perf_counter()
        trace_result = trace_image_optimized(image, enable_ocr=enable_ocr)
        trace_seconds = perf_counter() - trace_started
        dxf_path = outputs_dir / f"{input_path.stem}.dxf"
        export_started = perf_counter()
        structure = getattr(trace_result, "final_structure", None)
        if structure is not None and export_final_structure_dxf is not None:
            export_result = export_final_structure_dxf(structure, dxf_path)
        else:
            export_result = export_exact_trace_dxf(
                trace_result.paths,
                dxf_path,
                image.shape[0],
                image_width=image.shape[1],
                texts=tuple(getattr(trace_result, "texts", ())),
            )
        export_seconds = perf_counter() - export_started
        records.append(
            _output_metrics(
                input_path=input_path,
                image=image,
                trace_result=trace_result,
                export_result=export_result,
                dxf_path=dxf_path,
                trace_seconds=trace_seconds,
                export_seconds=export_seconds,
            )
        )
    return records


def main() -> int:
    args = _parser().parse_args()
    project_root = args.project_root.resolve()
    output_dir = args.output_dir.resolve()
    junit_source = args.junit_source.resolve()
    inputs = [path.resolve() for path in args.input]
    if not (project_root / "app").is_dir():
        raise ValueError(f"Not an application project root: {project_root}")
    sys.path.insert(0, str(project_root))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Baseline output directory is not empty: {output_dir}")
    if not junit_source.is_file():
        raise FileNotFoundError(junit_source)
    for input_path in inputs:
        if not input_path.is_file():
            raise FileNotFoundError(input_path)

    commit = _git_commit(project_root)
    expected = args.expected_commit.lower()
    if commit.lower() != expected:
        raise ValueError(f"Expected commit {expected}, observed {commit}")

    output_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = output_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    junit_target = tests_dir / "pytest-junit.xml"
    shutil.copy2(junit_source, junit_target)
    test_summary = _junit_summary(junit_target)

    original_cwd = Path.cwd()
    os.chdir(project_root)
    try:
        _write_json(
            output_dir / "config-snapshot.json",
            _configuration_snapshot(
                project_root=project_root,
                label=args.label,
                commit=commit,
                test_summary=test_summary,
                enable_ocr=bool(args.enable_ocr),
            ),
        )
        records = _capture_outputs(
            inputs,
            output_dir,
            enable_ocr=bool(args.enable_ocr),
        )
    finally:
        os.chdir(original_cwd)

    passed = (
        test_summary["failures"] == 0
        and test_summary["errors"] == 0
        and all(record["dxf_audit_error_count"] == 0 for record in records)
    )
    _write_json(
        output_dir / "baseline-result.json",
        {
            "label": args.label,
            "git_commit": commit,
            "passed": passed,
            "test_result": test_summary,
            "outputs": records,
        },
    )
    print(
        json.dumps(
            {
                "label": args.label,
                "git_commit": commit,
                "passed": passed,
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
