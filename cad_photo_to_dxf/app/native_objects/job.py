"""Per-request native import contract. No drawing or mutable job is global."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral
from pathlib import Path
import re
import sys
import uuid


def application_resources() -> Path:
    """Installed/frozen application resources, independent of the caller cwd."""
    bundle = getattr(sys, "_MEIPASS", None)
    return (
        Path(bundle) if bundle else Path(__file__).resolve().parents[2]
    ) / "resources"


@dataclass(frozen=True)
class NativeJobConfig:
    input_path: Path
    output_path: Path
    roi: tuple[int, int, int, int]
    dpi: int
    job_id: str
    page_number: int | None
    frame_number: int | None
    orientation_cw: int
    evidence_dir: Path
    temp_dir: Path
    resource_report_path: Path
    resources_dir: Path
    cache_dir: Path | None
    preview_max_dimension: int = 1600
    mode: str = "native-objects"

    def payload(self) -> dict:
        return {
            "schema": "native-job-v3",
            "job_id": self.job_id,
            "mode": self.mode,
            "input_path": str(self.input_path),
            "output_path": str(self.output_path),
            "page_number_1based": self.page_number,
            "frame_number_1based": self.frame_number,
            "roi_source_xyxy_px": list(self.roi),
            "ROI_frame": "decoded selected raster/page before explicit orientation; half-open",
            "recognition_dpi": self.dpi,
            "orientation_clockwise_degrees": self.orientation_cw,
            "evidence_dir": str(self.evidence_dir),
            "temp_dir": str(self.temp_dir),
            "resource_report_path": str(self.resource_report_path),
            "application_resources_dir": str(self.resources_dir),
            "cache_dir": str(self.cache_dir) if self.cache_dir else None,
            "preview_max_dimension": self.preview_max_dimension,
            "unit": "paper_mm",
            "paper_mm_per_recognition_pixel": 25.4 / self.dpi,
            "scale_evidence": {
                "basis": "explicit job recognition DPI; raster samples are not rescaled",
                "engineering_scale": "UNVERIFIED",
                "engineering_scale_denominator": None,
                "metadata_DPI_overrides_explicit_DPI": False,
            },
        }


def make_job(
    input_path,
    output_path,
    roi,
    *,
    dpi=200.0,
    page_number=None,
    frame_number=None,
    orientation=0,
    job_id=None,
    evidence_dir=None,
    temp_dir=None,
    resource_report_path=None,
    cache_dir=None,
    preview_max_dimension=1600,
) -> NativeJobConfig:
    source, target = (
        Path(input_path).expanduser().resolve(),
        Path(output_path).expanduser().resolve(),
    )
    if not source.is_file():
        raise FileNotFoundError(f"Native-object input does not exist: {source}")
    if target.suffix.lower() != ".dxf":
        raise ValueError(
            "Native-object output must be a .dxf file; DWG is not verified"
        )
    if source == target:
        raise ValueError("Input and output must be different files")
    if not isinstance(roi, (tuple, list)) or len(roi) != 4:
        raise ValueError(
            "Native-object mode requires four original-pixel ROI coordinates"
        )
    if any(isinstance(v, bool) or not isinstance(v, Integral) for v in roi):
        raise ValueError(
            "ROI coordinates must be integers in the original selected source frame"
        )
    bounds = tuple(int(v) for v in roi)
    if not (0 <= bounds[0] < bounds[2] and 0 <= bounds[1] < bounds[3]):
        raise ValueError(f"Invalid half-open source ROI: {bounds}")
    if isinstance(dpi, bool) or not isfinite(float(dpi)) or float(dpi) <= 0:
        raise ValueError("Native-object DPI must be positive and finite")
    if not float(dpi).is_integer():
        raise ValueError(
            "Native-object mode currently supports integer rendering DPI only; fractional source DPI is not silently rounded"
        )
    for name, value in (("page", page_number), ("frame", frame_number)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, Integral) or value < 1
        ):
            raise ValueError(f"Native {name} must be a 1-based positive integer")
    if (
        isinstance(orientation, bool)
        or not isinstance(orientation, Integral)
        or orientation not in (0, 90, 180, 270)
    ):
        raise ValueError(
            "Native orientation must be 0, 90, 180 or 270 degrees clockwise"
        )
    if (
        isinstance(preview_max_dimension, bool)
        or not isinstance(preview_max_dimension, Integral)
        or preview_max_dimension < 64
    ):
        raise ValueError("Preview maximum dimension must be an integer >= 64")
    jid = job_id or ("job-" + uuid.uuid4().hex)
    if not isinstance(jid, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", jid
    ):
        raise ValueError("job_id must be 1-80 filename-safe ASCII characters")
    evidence = (
        Path(evidence_dir).expanduser().resolve()
        if evidence_dir
        else target.parent / (target.stem + "_evidence")
    )
    temporary = (
        Path(temp_dir).expanduser().resolve() if temp_dir else evidence / "temporary"
    )
    resource_report = (
        Path(resource_report_path).expanduser().resolve()
        if resource_report_path
        else evidence / "job_resources.json"
    )
    cache = Path(cache_dir).expanduser().resolve() if cache_dir else None
    if cache is not None and not cache.is_dir():
        raise ValueError(f"Explicit native cache directory is missing: {cache}")
    if source in (resource_report, evidence, temporary):
        raise ValueError(
            "Native evidence/temp/resource paths cannot overwrite the input"
        )
    reserved_files = {
        target,
        target.with_suffix(".entry_trace.json"),
        target.with_suffix(".report.json"),
        target.with_suffix(".objects.json"),
        target.with_suffix(".png"),
        target.with_suffix(".pdf"),
    }
    if resource_report in reserved_files or resource_report.suffix.lower() != ".json":
        raise ValueError(
            "Resource report must be a separate .json file, not an output artifact"
        )
    if evidence in reserved_files or temporary in reserved_files:
        raise ValueError("Evidence/temp directories cannot be output artifact paths")
    for directory in (evidence, temporary):
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"Native task directory is an existing file: {directory}")
    if cache is not None and any(
        path == cache or cache in path.parents
        for path in (target, evidence, temporary, resource_report)
    ):
        raise ValueError(
            "Native outputs/evidence/temp must not write inside the explicit read-only cache"
        )
    return NativeJobConfig(
        source,
        target,
        bounds,
        int(dpi),
        jid,
        int(page_number) if page_number is not None else None,
        int(frame_number) if frame_number is not None else None,
        int(orientation),
        evidence,
        temporary,
        resource_report,
        application_resources().resolve(),
        cache,
        int(preview_max_dimension),
    )
