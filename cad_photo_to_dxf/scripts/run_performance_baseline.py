from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import fmean, pstdev
import subprocess
import sys
from time import perf_counter
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTIONS = {
    "small": "perspective-sample-plan",
    "medium": "environment-plan-page-003-150dpi",
    "large": "warehouse-plan-page-003-72dpi",
}
CORE_STAGES = (
    "background_normalization",
    "binarization",
    "ocr",
    "structural_line_detection",
    "roi_generation",
    "connectivity",
    "ownership",
    "contour_tracing",
    "final_structure_generation",
)
REQUIRED_STAGES = (
    "page_load",
    *CORE_STAGES,
    "gui_preview",
    "dxf_export",
    "cache_miss",
    "cache_hit",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure the production pipeline on small, medium and large real "
            "pages in isolated worker processes."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/real_regression/manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("validation/final-acceptance/phase12-performance.json"),
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("output/ci/phase12-performance"),
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--worker-document-id")
    parser.add_argument("--worker-size")
    parser.add_argument("--worker-run", type=int)
    parser.add_argument("--worker-output", type=Path)
    return parser


def _read_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("documents"), list):
        raise ValueError("Regression manifest must contain a documents list")
    return value


def _document_by_id(
    manifest: dict[str, Any],
    document_id: str,
) -> dict[str, Any]:
    for document in manifest["documents"]:
        if document.get("id") == document_id:
            return document
    raise ValueError(f"Manifest document not found: {document_id}")


def _peak_working_set_bytes() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCountersEx),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        if not ok:
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.PeakWorkingSetSize)

    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except (ImportError, AttributeError):
        return 0


def _worker(args: argparse.Namespace) -> int:
    if not all(
        (
            args.worker_document_id,
            args.worker_size,
            args.worker_run,
            args.worker_output,
        )
    ):
        raise ValueError("Worker arguments are incomplete")

    import ezdxf

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from app.image_loader import load_image
    from app.preview_renderer import render_final_structure_preview
    from app.processing_contract import (
        ProductionProcessingConfig,
        ProductionProcessingService,
        build_processing_cache_key,
        cache_key_matches,
        file_content_sha256,
    )
    from app.text_output_contract import text_output_summary
    from app.trace_single_export import export_final_structure_dxf
    from app.trace_storage import load_trace_cache, save_trace_cache

    manifest_path = args.manifest.resolve()
    manifest = _read_manifest(manifest_path)
    document = _document_by_id(manifest, args.worker_document_id)
    source = (PROJECT_ROOT / str(document["source_path"])).resolve()
    page = document["page"]
    page_index = int(page["number"]) - 1
    dpi = float(page["dpi"])

    load_started = perf_counter()
    image = load_image(
        source,
        page_index=page_index,
        pdf_dpi=int(round(dpi)),
    )
    page_load_seconds = perf_counter() - load_started

    config = ProductionProcessingConfig(
        source_dpi=dpi,
        enable_ocr=bool(document.get("enable_ocr", True)),
    )
    cache_key = build_processing_cache_key(
        input_content_sha256=file_content_sha256(source),
        page_index=page_index,
        config=config,
    )
    durations: dict[str, float] = defaultdict(float)

    def collect(stage: str, seconds: float) -> None:
        durations[stage] += float(seconds)

    run_directory = args.worker_output.resolve().parent
    run_directory.mkdir(parents=True, exist_ok=True)
    cache_path = run_directory / f"{args.worker_size}-run-{args.worker_run}.npz"
    dxf_path = run_directory / f"{args.worker_size}-run-{args.worker_run}.dxf"

    miss_started = perf_counter()
    result = ProductionProcessingService.process_page(
        image,
        config,
        performance_callback=collect,
    )
    save_trace_cache(cache_path, result, cache_key=cache_key.payload())
    cache_miss_seconds = perf_counter() - miss_started

    hit_started = perf_counter()
    stored = load_trace_cache(cache_path)
    cache_hit_seconds = perf_counter() - hit_started
    if not cache_key_matches(stored.cache_key, cache_key):
        raise AssertionError("Fresh cache entry did not match its processing key")
    structure = stored.final_structure
    if structure is None or result.final_structure is None:
        raise AssertionError("Production result and cache must contain FinalStructure")
    if structure.structure_id != result.final_structure.structure_id:
        raise AssertionError("Cache restore changed FinalStructure content")

    preview_started = perf_counter()
    preview = render_final_structure_preview(structure)
    gui_preview_seconds = perf_counter() - preview_started

    export_started = perf_counter()
    export_result = export_final_structure_dxf(structure, dxf_path)
    dxf_export_seconds = perf_counter() - export_started
    if export_result.structure_id != structure.structure_id:
        raise AssertionError("DXF export did not consume the preview structure")

    dxf_document = ezdxf.readfile(dxf_path)
    auditor = dxf_document.audit()
    modelspace = dxf_document.modelspace()
    entities = list(modelspace)
    text_summary = text_output_summary(structure.texts)
    contour_vertices = sum(len(item.points) for item in structure.contours)
    object_counts = {
        "contours": len(structure.contours),
        "contour_vertices": contour_vertices,
        "straight_lines": len(structure.straight_lines),
        "ocr_candidates": len(structure.texts),
        "editable_text": text_summary.editable_text_count,
        "fallback_text": text_summary.fallback_outline_count,
        "residual_graphic": text_summary.residual_graphic_count,
        "logos": len(structure.logos),
        "signatures": len(structure.signatures),
        "dxf_entities": len(entities),
        "dxf_lines": len(list(modelspace.query("LINE"))),
        "dxf_text": len(list(modelspace.query("TEXT"))),
    }
    stage_seconds = {
        "page_load": page_load_seconds,
        **{stage: durations.get(stage, 0.0) for stage in CORE_STAGES},
        "gui_preview": gui_preview_seconds,
        "dxf_export": dxf_export_seconds,
        "cache_miss": cache_miss_seconds,
        "cache_hit": cache_hit_seconds,
    }
    missing = set(REQUIRED_STAGES).difference(stage_seconds)
    if missing:
        raise AssertionError(f"Missing performance stages: {sorted(missing)}")
    peak_working_set_bytes = _peak_working_set_bytes()
    payload = {
        "size_class": args.worker_size,
        "run": int(args.worker_run),
        "document_id": str(document["id"]),
        "source_path": str(source.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "page_number": page_index + 1,
        "dpi": dpi,
        "pixel_size": [int(image.shape[1]), int(image.shape[0])],
        "pixel_count": int(image.shape[0] * image.shape[1]),
        "stage_seconds": stage_seconds,
        "peak_working_set_bytes": peak_working_set_bytes,
        "peak_working_set_mib": peak_working_set_bytes / (1024.0 * 1024.0),
        "object_counts": object_counts,
        "structure_id": structure.structure_id,
        "cache_key_digest": cache_key.digest,
        "cache_key_match": True,
        "preview_shape": [int(value) for value in preview.shape],
        "dxf_audit_error_count": len(auditor.errors),
        "dxf_audit_fix_count": len(auditor.fixes),
        "dxf_path": str(dxf_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "cache_path": str(cache_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }
    args.worker_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def _stats(values: list[float]) -> dict[str, float | int]:
    mean = fmean(values)
    deviation = pstdev(values) if len(values) > 1 else 0.0
    return {
        "samples": len(values),
        "mean": mean,
        "minimum": min(values),
        "maximum": max(values),
        "range": max(values) - min(values),
        "population_stdev": deviation,
        "coefficient_of_variation_percent": (
            0.0 if mean == 0.0 else deviation / mean * 100.0
        ),
    }


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_size: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_size[str(run["size_class"])].append(run)
    summaries: dict[str, Any] = {}
    for size, size_runs in sorted(by_size.items()):
        stage_stats = {
            stage: _stats(
                [float(run["stage_seconds"][stage]) for run in size_runs]
            )
            for stage in REQUIRED_STAGES
        }
        object_keys = sorted(size_runs[0]["object_counts"])
        object_stats = {
            key: _stats(
                [float(run["object_counts"][key]) for run in size_runs]
            )
            for key in object_keys
        }
        structure_ids = sorted({str(run["structure_id"]) for run in size_runs})
        summaries[size] = {
            "document_id": size_runs[0]["document_id"],
            "pixel_size": size_runs[0]["pixel_size"],
            "pixel_count": size_runs[0]["pixel_count"],
            "runs": len(size_runs),
            "stage_seconds": stage_stats,
            "peak_working_set_mib": _stats(
                [float(run["peak_working_set_mib"]) for run in size_runs]
            ),
            "object_counts": object_stats,
            "structure_ids": structure_ids,
            "deterministic_structure": len(structure_ids) == 1,
            "dxf_audit_errors": sum(
                int(run["dxf_audit_error_count"]) for run in size_runs
            ),
        }
    return summaries


def _parent(args: argparse.Namespace) -> int:
    if args.runs < 3:
        raise ValueError("Performance baseline requires at least three runs per size")
    manifest_path = args.manifest.resolve()
    manifest = _read_manifest(manifest_path)
    for document_id in DEFAULT_SELECTIONS.values():
        _document_by_id(manifest, document_id)

    output_path = args.output.resolve()
    artifacts = args.artifacts.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for size, document_id in DEFAULT_SELECTIONS.items():
        for run_index in range(1, args.runs + 1):
            worker_output = artifacts / f"{size}-run-{run_index}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--manifest",
                str(manifest_path),
                "--worker-document-id",
                document_id,
                "--worker-size",
                size,
                "--worker-run",
                str(run_index),
                "--worker-output",
                str(worker_output),
            ]
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                check=False,
                text=True,
                capture_output=True,
            )
            if completed.returncode:
                raise RuntimeError(
                    f"Performance worker failed for {size} run {run_index}:\n"
                    f"{completed.stdout}\n{completed.stderr}"
                )
            runs.append(json.loads(worker_output.read_text(encoding="utf-8")))

    summaries = _aggregate(runs)
    checks = {
        "three_size_classes": set(summaries) == set(DEFAULT_SELECTIONS),
        "minimum_three_runs_each": all(
            int(summary["runs"]) >= 3 for summary in summaries.values()
        ),
        "all_required_stages_recorded": all(
            set(run["stage_seconds"]) == set(REQUIRED_STAGES) for run in runs
        ),
        "deterministic_structure_ids": all(
            bool(summary["deterministic_structure"])
            for summary in summaries.values()
        ),
        "zero_dxf_audit_errors": all(
            int(summary["dxf_audit_errors"]) == 0
            for summary in summaries.values()
        ),
        "cache_keys_match": all(bool(run["cache_key_match"]) for run in runs),
        "positive_peak_memory": all(
            int(run["peak_working_set_bytes"]) > 0 for run in runs
        ),
    }
    payload = {
        "schema_version": 1,
        "phase": 12,
        "manifest": str(manifest_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "measurement_contract": {
            "isolated_process_per_run": True,
            "runs_per_size": args.runs,
            "size_selection": DEFAULT_SELECTIONS,
            "required_stage_order": list(REQUIRED_STAGES),
            "variation_fields": [
                "range",
                "population_stdev",
                "coefficient_of_variation_percent",
            ],
            "peak_memory_metric": "process PeakWorkingSetSize",
            "cache_miss_scope": "processing plus cache save",
            "cache_hit_scope": "cache load and reconstruction",
        },
        "summaries": summaries,
        "runs": runs,
        "checks": checks,
        "passed": all(checks.values()),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "runs": len(runs),
                "checks": checks,
                "passed": payload["passed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


def main() -> int:
    args = _parser().parse_args()
    return _worker(args) if args.worker else _parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
