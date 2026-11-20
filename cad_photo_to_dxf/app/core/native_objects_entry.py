"""Validated native-object dispatch for the existing production service.

This adapter never calls the legacy trace/export path. It preserves the source
file and records an entry trace even if the selected native pipeline fails.
"""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
import traceback
from typing import Callable, Sequence

from app.core.cancellation import CancellationToken, ProcessingCancelled, checkpoint


def validate_native_request(
    input_path,
    output_path,
    roi,
    dpi,
    *,
    page_number=None,
    frame_number=None,
    orientation=0,
):
    """Metadata-only preflight; never uses a GUI preview as recognition input."""
    from app.native_objects.job import make_job
    from app.native_objects.source_import import inspect_source, validate_roi

    job = make_job(
        input_path,
        output_path,
        roi,
        dpi=dpi,
        page_number=page_number,
        frame_number=frame_number,
        orientation=orientation,
    )
    info = inspect_source(
        job.input_path,
        dpi=job.dpi,
        page_number=job.page_number,
        frame_number=job.frame_number,
    )
    validate_roi(job.roi, info["source_size_px"])
    return job.input_path, job.output_path, job.roi, float(job.dpi)


def dispatch_native_objects(
    input_path: str | Path,
    output_path: str | Path,
    roi: Sequence[int],
    *,
    dpi: float = 200.0,
    progress_callback: Callable[[str, float], None] | None = None,
    evidence_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    page_number: int | None = None,
    frame_number: int | None = None,
    orientation: int = 0,
    job_id: str | None = None,
    temp_dir: str | Path | None = None,
    resource_report_path: str | Path | None = None,
    cancellation_token: CancellationToken | None = None,
    entrypoint: str = "ProductionProcessingService.process_native_objects",
) -> dict:
    from app.core.processing import file_content_sha256
    from app.native_objects.job import make_job
    from app.native_objects.source_import import (
        inspect_source,
        validate_roi,
        prepare_source,
        assert_fresh_evidence,
    )
    from app.native_objects.platform_stats import sample, elapsed
    from app.native_objects.contracts import save_json
    from app.native_objects.execution import check_cancel

    job = make_job(
        input_path,
        output_path,
        roi,
        dpi=dpi,
        page_number=page_number,
        frame_number=frame_number,
        orientation=orientation,
        job_id=job_id,
        evidence_dir=evidence_dir,
        temp_dir=temp_dir,
        resource_report_path=resource_report_path,
        cache_dir=cache_dir,
    )
    info = inspect_source(
        job.input_path,
        dpi=job.dpi,
        page_number=job.page_number,
        frame_number=job.frame_number,
    )
    validate_roi(job.roi, info["source_size_px"])
    source, target, bounds, dpi, cache = (
        job.input_path,
        job.output_path,
        job.roi,
        float(job.dpi),
        job.cache_dir,
    )
    if target.exists():
        raise FileExistsError(
            f"Native-object output already exists; select a new path: {target}"
        )
    trace_path = target.with_suffix(".entry_trace.json")
    if trace_path.exists():
        raise FileExistsError(
            f"Entry trace already exists; select a new output path: {trace_path}"
        )
    if job.resource_report_path.exists():
        raise FileExistsError(
            f"Resource report already exists; use a fresh job path: {job.resource_report_path}"
        )
    assert_fresh_evidence(job)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_sha = file_content_sha256(source)
    from app.core.native_job_manager import algorithm_fingerprint
    from app.version import product_status_payload

    trace = {
        "algorithm": algorithm_fingerprint(),
        "product_status": product_status_payload(),
        "schema": "native-objects-production-entry-v3",
        "job_id": job.job_id,
        "job_config": job.payload(),
        "mode": "native-objects",
        "entrypoint": str(entrypoint),
        "call_chain": [
            str(entrypoint),
            "ProductionProcessingService.process_native_objects",
            "app.native_objects.source_import.prepare_source",
            "app.native_objects.pipeline.run_native_objects",
        ],
        "input_path": str(source),
        "output_path": str(target),
        "source_sha256": source_sha,
        "roi_original_xyxy_px": list(bounds),
        "dpi": dpi,
        "explicit_native_cache_dir": str(cache) if cache is not None else None,
        "cache_source_hash_and_ROI_validation_owner": "native_objects.pipeline",
        "legacy_processing_called": False,
        "legacy_export_called": False,
        "fallback_to_legacy_permitted": False,
        "status": "DISPATCHING",
    }

    def save_trace():
        save_json(trace_path, trace)

    def progress(stage, fraction):
        checkpoint(cancellation_token)
        check_cancel(str(stage))
        value = float(fraction)
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(
                "Native pipeline progress must be a finite fraction between 0 and 1"
            )
        if progress_callback is not None:
            progress_callback(str(stage), value)

    save_trace()
    resource_start = sample()
    try:
        checkpoint(cancellation_token)
        check_cancel("SOURCE_IMPORT")
        prepared = prepare_source(job)
        trace["import_manifest_path"] = str(job.evidence_dir / "import_manifest.json")
        trace["working_ROI_xyxy_px"] = list(prepared.working_roi)
        trace["source_to_working_to_CAD"] = prepared.manifest["coordinates"]
        save_trace()
        from app.native_objects.pipeline import run_native_objects

        trace["pipeline_module"] = str(
            Path(run_native_objects.__code__.co_filename).resolve()
        )
        result = run_native_objects(
            source,
            target,
            bounds,
            dpi=dpi,
            progress_callback=progress,
            evidence_dir=job.evidence_dir,
            cache_dir=cache,
            job_config=job,
            prepared_source=prepared,
        )
        checkpoint(cancellation_token)
        if not isinstance(result, dict) or not isinstance(result.get("objects"), list):
            raise TypeError(
                "Native pipeline must return a dictionary with an objects list"
            )
        paths = {}
        for key in ("dxf_path", "preview_path", "report_path"):
            value = result.get(key)
            if value is None:
                raise ValueError(f"Native pipeline returned no {key}")
            path = Path(value).resolve()
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(
                    f"Native pipeline did not save a nonempty {key}: {path}"
                )
            paths[key] = path
        if paths["dxf_path"] != target:
            raise ValueError(
                "Native pipeline saved a different DXF than the requested output"
            )
        from PIL import Image

        with Image.open(paths["preview_path"]) as preview:
            if preview.format != "PNG":
                raise ValueError("Native preview must be an actual PNG file")
            preview.verify()
        with paths["report_path"].open(encoding="utf-8") as handle:
            if not isinstance(json.load(handle), dict):
                raise ValueError("Native report must contain a JSON object")
        if (
            result.get("source_sha256") != source_sha
            or file_content_sha256(source) != source_sha
        ):
            raise ValueError(
                "Native pipeline source identity changed or was not returned"
            )
        if not result.get("evidence_dir") or not Path(result["evidence_dir"]).is_dir():
            raise ValueError("Native pipeline evidence directory is missing")
        trace.update(
            status="COMPLETED",
            saved_paths={key: str(path) for key, path in paths.items()},
            output_sha256=file_content_sha256(target),
            objects=len(result["objects"]),
            evidence_dir=str(Path(result["evidence_dir"]).resolve()),
            source_unchanged=True,
            product_or_target_CAD_acceptance_implied=False,
        )
        result = dict(result)
        result["entry_trace_path"] = str(trace_path)
        result["job_id"] = job.job_id
        result["resource_report_path"] = str(job.resource_report_path)
        result["import_manifest_path"] = str(job.evidence_dir / "import_manifest.json")
        return result
    except ProcessingCancelled as exc:
        trace.update(
            status="CANCELLED_NO_PUBLICATION",
            error_type=type(exc).__name__,
            error=str(exc),
            source_unchanged=source.is_file()
            and file_content_sha256(source) == source_sha,
        )
        raise
    except Exception as exc:
        trace.update(
            status="FAILED_NO_LEGACY_FALLBACK",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
            source_unchanged=source.is_file()
            and file_content_sha256(source) == source_sha,
        )
        raise
    finally:
        resource_row = {
            "job_id": job.job_id,
            "status": trace["status"],
            "source_sha256": source_sha,
            "resources": elapsed(resource_start),
            "application_resources_dir": str(job.resources_dir),
            "source_unchanged": source.is_file()
            and file_content_sha256(source) == source_sha,
        }
        job.resource_report_path.parent.mkdir(parents=True, exist_ok=True)
        save_json(job.resource_report_path, resource_row)
        save_trace()
