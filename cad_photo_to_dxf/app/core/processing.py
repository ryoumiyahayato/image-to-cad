from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.diagnostics.observability import ObservationSink

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path

import numpy as np

from app.core.cancellation import CancellationToken, ProgressCallback
from app.geometry.connectivity_safety import CONNECTION_CONFIDENCE_THRESHOLD, DEFAULT_CONNECTION_DPI, MAX_DIRECTION_ERROR_DEGREES, MAX_LINE_WIDTH_DIFFERENCE_MM
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION
from app.geometry.junction_v2_consumer import JunctionContract, validate_junction_contract_authority
from app.ocr.ocr_recognition import MAX_OCR_CANDIDATES, MIN_OCR_CONFIDENCE
from app.geometry.optimized_trace import trace_image_optimized
from app.diagnostics.performance_observability import PerformanceCallback
from app.geometry.raster_trace import RasterTraceResult
from app.geometry.straight_line_reconstruction import MAX_CONNECTION_DISTANCE_MM, PROTECTION_EXPANSION_MM
from app.ocr.text_output_contract import DEFAULT_MINIMUM_TEXT_CONFIDENCE

PRODUCTION_ALGORITHM_VERSION = "optimized-trace-phase11-p2b-representation-v2-upright-digits-v1-source-text-bounds-v1-cell-rows-v1-text-carriers-v1-source-raster-alias-v1-reading-basis-v1-printed-rows-v1-isolated-scan-stroke-v1"
PRODUCTION_MODEL_VERSION = "rapidocr-runtime-and-geometry-rules-v1"
DISABLED_LAYOUT_PROFILE = "disabled"
DEFAULT_IMAGE_DPI = 240.0


def _sha256_hex(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(x not in '0123456789abcdef' for x in normalized):
        raise ValueError(f'{label} must be a SHA-256 hex digest')
    return normalized


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_sha256(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def file_content_sha256(path: str | Path) -> str:
    source = Path(path)
    digest = sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_content_sha256(image: np.ndarray) -> str:
    normalized = np.ascontiguousarray(image)
    digest = sha256()
    digest.update(str(normalized.dtype).encode("ascii"))
    digest.update(_canonical_json(list(normalized.shape)).encode("ascii"))
    digest.update(normalized.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class LayoutProfileSelection:
    """Explicit layout specialization state; the generic pipeline keeps it off."""

    enabled: bool = False
    name: str = DISABLED_LAYOUT_PROFILE

    def __post_init__(self) -> None:
        if self.enabled and self.name == DISABLED_LAYOUT_PROFILE:
            raise ValueError("An enabled layout profile must have an explicit name")
        if not self.enabled and self.name != DISABLED_LAYOUT_PROFILE:
            raise ValueError("A named layout profile must be explicitly enabled")

    def payload(self) -> dict[str, object]:
        return {
            "enabled": bool(self.enabled),
            "name": str(self.name),
        }


@dataclass(frozen=True)
class ProductionProcessingConfig:
    """Every setting that can affect the production page-processing result."""

    source_dpi: float = DEFAULT_CONNECTION_DPI
    enable_ocr: bool = True
    foreground_threshold: int | None = None
    layout_profile: LayoutProfileSelection = LayoutProfileSelection()
    algorithm_version: str = PRODUCTION_ALGORITHM_VERSION
    model_version: str = PRODUCTION_MODEL_VERSION
    junction_contract: JunctionContract | None = None
    draftsman_behavior_manifest_digest: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_dpi, (bool, np.bool_)) or not isfinite(float(self.source_dpi)) or float(self.source_dpi) <= 0:
            raise ValueError("Processing DPI must be a positive finite number")
        if self.foreground_threshold is not None and not (
            0 <= int(self.foreground_threshold) <= 255
        ):
            raise ValueError("Foreground threshold must be between 0 and 255")
        if not self.algorithm_version.strip():
            raise ValueError("Algorithm version must not be empty")
        if not self.model_version.strip():
            raise ValueError("Model version must not be empty")
        if self.junction_contract is not None:
            validate_junction_contract_authority(self.junction_contract)
        if self.draftsman_behavior_manifest_digest is not None:
            object.__setattr__(self, 'draftsman_behavior_manifest_digest', _sha256_hex(self.draftsman_behavior_manifest_digest, 'Draftsman behavior manifest'))

    def threshold_summary(self) -> dict[str, object]:
        return {
            "foreground_threshold": self.foreground_threshold,
            "minimum_ocr_confidence": MIN_OCR_CONFIDENCE,
            "maximum_ocr_candidates": MAX_OCR_CANDIDATES,
            "minimum_text_output_confidence": (DEFAULT_MINIMUM_TEXT_CONFIDENCE),
            "connection_confidence_threshold": (CONNECTION_CONFIDENCE_THRESHOLD),
            "maximum_direction_error_degrees": (MAX_DIRECTION_ERROR_DEGREES),
            "maximum_line_width_difference_mm": (MAX_LINE_WIDTH_DIFFERENCE_MM),
            "maximum_connection_distance_mm": (MAX_CONNECTION_DISTANCE_MM),
            "protection_expansion_mm": PROTECTION_EXPANSION_MM,
        }

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_dpi": float(self.source_dpi),
            "enable_ocr": bool(self.enable_ocr),
            "foreground_threshold": self.foreground_threshold,
            "layout_profile": self.layout_profile.payload(),
            "algorithm_version": self.algorithm_version,
            "model_version": self.model_version,
            "final_structure_schema_version": (FINAL_STRUCTURE_SCHEMA_VERSION),
            "critical_thresholds": self.threshold_summary(),
        }
        if self.junction_contract is not None:
            authority = validate_junction_contract_authority(self.junction_contract)
            payload["junction_contract_digest"] = authority.trusted_contract_digest
            payload["junction_trusted_authority"] = authority.cache_identity
        if self.draftsman_behavior_manifest_digest is not None:
            payload["draftsman_behavior_manifest_digest"] = (
                self.draftsman_behavior_manifest_digest.strip().lower()
            )
        return payload


@dataclass(frozen=True)
class ProcessingCacheKey:
    input_content_sha256: str
    page_number: int
    dpi: float
    enable_ocr: bool
    algorithm_version: str
    model_version: str
    config_summary_json: str
    layout_profile: str
    final_structure_schema_version: int
    threshold_summary_json: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'input_content_sha256', _sha256_hex(self.input_content_sha256, 'Input content hash'))
        if isinstance(self.page_number, bool) or self.page_number <= 0:
            raise ValueError('Page number must be positive')
        if isinstance(self.dpi, bool) or not isfinite(self.dpi) or self.dpi <= 0:
            raise ValueError('Cache DPI must be positive and finite')

    @property
    def digest(self) -> str:
        return _json_sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "input_content_sha256": self.input_content_sha256,
            "page_number": int(self.page_number),
            "dpi": float(self.dpi),
            "enable_ocr": bool(self.enable_ocr),
            "algorithm_version": self.algorithm_version,
            "model_version": self.model_version,
            "config_summary": json.loads(self.config_summary_json),
            "layout_profile": self.layout_profile,
            "final_structure_schema_version": int(self.final_structure_schema_version),
            "critical_threshold_summary": json.loads(self.threshold_summary_json),
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
    ) -> ProcessingCacheKey:
        return cls(
            input_content_sha256=str(payload["input_content_sha256"]),
            page_number=int(payload["page_number"]),
            dpi=float(payload["dpi"]),
            enable_ocr=bool(payload["enable_ocr"]),
            algorithm_version=str(payload["algorithm_version"]),
            model_version=str(payload["model_version"]),
            config_summary_json=_canonical_json(payload["config_summary"]),
            layout_profile=str(payload["layout_profile"]),
            final_structure_schema_version=int(
                payload["final_structure_schema_version"]
            ),
            threshold_summary_json=_canonical_json(
                payload["critical_threshold_summary"]
            ),
        )


def build_processing_cache_key(
    *,
    input_content_sha256: str,
    page_index: int | None,
    config: ProductionProcessingConfig,
    pdf_geometry_binding: Mapping[str, object] | None = None,
) -> ProcessingCacheKey:
    page_number = 1 if page_index is None else int(page_index) + 1
    config_payload = config.payload()
    if pdf_geometry_binding is not None:
        config_payload['pdf_geometry_binding'] = dict(pdf_geometry_binding)
    return ProcessingCacheKey(
        input_content_sha256=input_content_sha256,
        page_number=page_number,
        dpi=float(config.source_dpi),
        enable_ocr=bool(config.enable_ocr),
        algorithm_version=config.algorithm_version,
        model_version=config.model_version,
        config_summary_json=_canonical_json(config_payload),
        layout_profile=config.layout_profile.name,
        final_structure_schema_version=(FINAL_STRUCTURE_SCHEMA_VERSION),
        threshold_summary_json=_canonical_json(config.threshold_summary()),
    )


def cache_key_matches(
    stored: Mapping[str, object] | None,
    expected: ProcessingCacheKey,
) -> bool:
    if not stored:
        return False
    try:
        actual = ProcessingCacheKey.from_payload(stored)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return actual == expected and actual.digest == expected.digest


class ProductionProcessingService:
    """The only production trace call used by single-page and batch GUI work."""

    @staticmethod
    def process_page(
        image: np.ndarray,
        config: ProductionProcessingConfig,
        *,
        cancellation_token: CancellationToken | None = None,
        progress_callback: ProgressCallback | None = None,
        performance_callback: PerformanceCallback | None = None,
        observation_sink: ObservationSink | None = None,
        pdf_geometry=None,
        before_arc_replacement=None,
    ) -> RasterTraceResult:
        if config.layout_profile.enabled:
            raise ValueError(
                "No layout profile is installed; the generic profile remains disabled"
            )
        result = trace_image_optimized(
            image,
            foreground_threshold=config.foreground_threshold,
            enable_ocr=config.enable_ocr,
            source_dpi=config.source_dpi,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
            performance_callback=performance_callback,
            observation_sink=observation_sink,
            junction_contract=config.junction_contract,
            processing_contract=config.payload(),
            pdf_geometry=pdf_geometry,
            before_arc_replacement=before_arc_replacement,
        )
        return result
