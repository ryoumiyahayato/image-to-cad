from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .cancellation import CancellationToken, ProgressCallback
from .connectivity_safety import (
    CONNECTION_CONFIDENCE_THRESHOLD,
    DEFAULT_CONNECTION_DPI,
    MAX_DIRECTION_ERROR_DEGREES,
    MAX_LINE_WIDTH_DIFFERENCE_MM,
)
from .final_structure import (
    FINAL_STRUCTURE_SCHEMA_VERSION,
    build_final_structure,
    final_structure_from_trace_result,
)
from .ocr_recognition import MAX_OCR_CANDIDATES, MIN_OCR_CONFIDENCE
from .optimized_trace import trace_image_optimized
from .raster_trace import RasterTraceResult
from .straight_line_reconstruction import (
    MAX_CONNECTION_DISTANCE_MM,
    PROTECTION_EXPANSION_MM,
)
from .text_output_contract import DEFAULT_MINIMUM_TEXT_CONFIDENCE


PRODUCTION_ALGORITHM_VERSION = "optimized-trace-phase11-v1"
PRODUCTION_MODEL_VERSION = "rapidocr-runtime-and-geometry-rules-v1"
DISABLED_LAYOUT_PROFILE = "disabled"


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

    def __post_init__(self) -> None:
        if not isfinite(float(self.source_dpi)) or float(self.source_dpi) <= 0:
            raise ValueError("Processing DPI must be a positive finite number")
        if self.foreground_threshold is not None and not (
            0 <= int(self.foreground_threshold) <= 255
        ):
            raise ValueError("Foreground threshold must be between 0 and 255")
        if not self.algorithm_version.strip():
            raise ValueError("Algorithm version must not be empty")
        if not self.model_version.strip():
            raise ValueError("Model version must not be empty")

    def threshold_summary(self) -> dict[str, object]:
        return {
            "foreground_threshold": self.foreground_threshold,
            "minimum_ocr_confidence": MIN_OCR_CONFIDENCE,
            "maximum_ocr_candidates": MAX_OCR_CANDIDATES,
            "minimum_text_output_confidence": (
                DEFAULT_MINIMUM_TEXT_CONFIDENCE
            ),
            "connection_confidence_threshold": (
                CONNECTION_CONFIDENCE_THRESHOLD
            ),
            "maximum_direction_error_degrees": (
                MAX_DIRECTION_ERROR_DEGREES
            ),
            "maximum_line_width_difference_mm": (
                MAX_LINE_WIDTH_DIFFERENCE_MM
            ),
            "maximum_connection_distance_mm": (
                MAX_CONNECTION_DISTANCE_MM
            ),
            "protection_expansion_mm": PROTECTION_EXPANSION_MM,
        }

    def payload(self) -> dict[str, object]:
        return {
            "source_dpi": float(self.source_dpi),
            "enable_ocr": bool(self.enable_ocr),
            "foreground_threshold": self.foreground_threshold,
            "layout_profile": self.layout_profile.payload(),
            "algorithm_version": self.algorithm_version,
            "model_version": self.model_version,
            "final_structure_schema_version": (
                FINAL_STRUCTURE_SCHEMA_VERSION
            ),
            "critical_thresholds": self.threshold_summary(),
        }


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
            "final_structure_schema_version": int(
                self.final_structure_schema_version
            ),
            "critical_threshold_summary": json.loads(
                self.threshold_summary_json
            ),
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
            config_summary_json=_canonical_json(
                payload["config_summary"]
            ),
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
) -> ProcessingCacheKey:
    content_hash = input_content_sha256.strip().lower()
    if len(content_hash) != 64 or any(
        character not in "0123456789abcdef"
        for character in content_hash
    ):
        raise ValueError("Input content hash must be a SHA-256 hex digest")
    page_number = 1 if page_index is None else int(page_index) + 1
    if page_number <= 0:
        raise ValueError("Page number must be positive")
    config_payload = config.payload()
    return ProcessingCacheKey(
        input_content_sha256=content_hash,
        page_number=page_number,
        dpi=float(config.source_dpi),
        enable_ocr=bool(config.enable_ocr),
        algorithm_version=config.algorithm_version,
        model_version=config.model_version,
        config_summary_json=_canonical_json(config_payload),
        layout_profile=config.layout_profile.name,
        final_structure_schema_version=(
            FINAL_STRUCTURE_SCHEMA_VERSION
        ),
        threshold_summary_json=_canonical_json(
            config.threshold_summary()
        ),
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
        )
        structure = final_structure_from_trace_result(result)
        provenance: dict[str, Any] = dict(structure.provenance)
        provenance["processing_contract"] = config.payload()
        contracted = build_final_structure(
            source_size_px=structure.source_size_px,
            contour_binary=structure.contour_binary,
            contours=structure.contours,
            straight_lines=structure.straight_lines,
            texts=structure.texts,
            logos=structure.logos,
            signatures=structure.signatures,
            preview_binary=structure.preview_binary,
            threshold=structure.threshold,
            warnings=structure.warnings,
            provenance=provenance,
            observations=structure.observations,
        )
        if contracted.structure_id != structure.structure_id:
            raise AssertionError(
                "Processing metadata changed FinalStructure content"
            )
        return replace(result, final_structure=contracted)
