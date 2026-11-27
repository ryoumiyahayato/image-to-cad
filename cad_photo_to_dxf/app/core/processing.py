from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.diagnostics.observability import ObservationSink
    from app.geometry.raster_trace import RasterTraceResult

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from pathlib import Path

import numpy as np

from app.core.cancellation import CancellationToken, ProgressCallback
from app.geometry.connectivity_safety import (
    CONNECTION_CONFIDENCE_THRESHOLD,
    DEFAULT_CONNECTION_DPI,
    MAX_DIRECTION_ERROR_DEGREES,
    MAX_LINE_WIDTH_DIFFERENCE_MM,
)
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION
from app.geometry.junction_v2_consumer import (
    JunctionContract,
    validate_junction_contract_authority,
)
from app.diagnostics.performance_observability import PerformanceCallback
from app.geometry.straight_line_reconstruction import (
    MAX_CONNECTION_DISTANCE_MM,
    PROTECTION_EXPANSION_MM,
)
from app.ocr.text_output_contract import DEFAULT_MINIMUM_TEXT_CONFIDENCE

PRODUCTION_ALGORITHM_VERSION = "optimized-trace-phase11-p2b-representation-v2-upright-digits-v1-source-text-bounds-v1-cell-rows-v1-text-carriers-v1-source-raster-alias-v1-reading-basis-v1-printed-rows-v1-isolated-scan-stroke-v1-text-rule-source-scope-v1-single-glyph-display-v1-native-pdf-review-suggestions-v1-isolated-scan-curve-source-v1-long-line-orientation-v1-disjoint-window-reading-v2-text-backup-source-scope-v2-artifact-component-scope-v1-artifact-local-damage-scope-v1-source-row-target-only-v1-source-row-ink-display-v1-native-text-group-backup-v1-native-pdf-fill-v1-native-source-group-v1-native-simple-polygon-fill-v2"
PRODUCTION_ALGORITHM_VERSION += "-verified-paper-boundary-v1"
PRODUCTION_ALGORITHM_VERSION += "-signing-field-source-protection-v1"
PRODUCTION_ALGORITHM_VERSION += "-pixel-domain-rule-bounds-v1-signing-rules-v1"
PRODUCTION_ALGORITHM_VERSION += "-ruled-cell-row-display-v1"
PRODUCTION_ALGORITHM_VERSION += "-verified-row-source-member-retirement-v1"
PRODUCTION_ALGORITHM_VERSION += "-complete-row-group-display-v1"
PRODUCTION_ALGORITHM_VERSION += "-pdf-parent-fill-ownership-v1"
PRODUCTION_ALGORITHM_VERSION += "-cell-reading-basis-v1"
PRODUCTION_ALGORITHM_VERSION += "-pre-cell-observation-v1"
PRODUCTION_ALGORITHM_VERSION += "-scan-content-classification-v1"
PRODUCTION_ALGORITHM_VERSION += "-scan-speckle-source-ink-v1"
PRODUCTION_ALGORITHM_VERSION += "-scan-noise-review-v1"
PRODUCTION_ALGORITHM_VERSION += "-original-scan-dust-v1"
PRODUCTION_ALGORITHM_VERSION += "-source-raster-runs-v1"
PRODUCTION_ALGORITHM_VERSION += "-source-filled-marks-v1"
PRODUCTION_ALGORITHM_VERSION += "-signing-ink-ownership-v1"
PRODUCTION_ALGORITHM_VERSION += "-scanned-title-row-layout-v1"
PRODUCTION_ALGORITHM_VERSION += "-compact-printed-cell-rows-v1"
PRODUCTION_ALGORITHM_VERSION += "-observed-scan-circle-symbols-v1"
PRODUCTION_ALGORITHM_VERSION += "-isolated-pdf-dimension-omission-v1"
PRODUCTION_ALGORITHM_VERSION += "-native-pdf-text-omissions-v1"
PRODUCTION_ALGORITHM_VERSION += "-shared-signing-members-fixed-v1"
PRODUCTION_ALGORITHM_VERSION += "-aligned-original-glyph-review-v1-online-fullpage-r2-enclosure-recheck-r3"
PRODUCTION_ALGORITHM_VERSION += "-signing-source-domain-v1"
PRODUCTION_ALGORITHM_VERSION += "-source-token-glyph-review-v1"
PRODUCTION_ALGORITHM_VERSION += "-dimension-chain-disjoint-members-v2"
PRODUCTION_MODEL_VERSION = "rapidocr-runtime-and-geometry-rules-v1"
DISABLED_LAYOUT_PROFILE = "disabled"
DEFAULT_IMAGE_DPI = 240.0
PRODUCTION_ALGORITHM_VERSION += "-observed-boxed-label-members-v1"
PRODUCTION_ALGORITHM_VERSION += "-observed-label-frame-geometry-v2-paper-pen"
PRODUCTION_ALGORITHM_VERSION += "-observed-isolated-open-strokes-v1"


def trace_image_optimized(*args, **kwargs):
    """Load the preserved legacy recognizer only when legacy mode is selected."""
    from app.geometry.optimized_trace import trace_image_optimized as implementation

    return implementation(*args, **kwargs)


def _sha256_hex(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(x not in "0123456789abcdef" for x in normalized):
        raise ValueError(f"{label} must be a SHA-256 hex digest")
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
    paper_boundary_verified: bool = False
    layout_profile: LayoutProfileSelection = LayoutProfileSelection()
    algorithm_version: str = PRODUCTION_ALGORITHM_VERSION
    model_version: str = PRODUCTION_MODEL_VERSION
    junction_contract: JunctionContract | None = None
    draftsman_behavior_manifest_digest: str | None = None
    experimental_observed_text_display: bool = False
    experimental_native_source_row: bool = False
    experimental_pdf_native_text: str = "off"
    experimental_pdf_native_geometry: bool = False
    experimental_protected_graphics: str = "legacy"
    recover_pdf_native_text_omissions: bool = True

    def __post_init__(self) -> None:
        if self.experimental_protected_graphics not in (
            "legacy", "source-image", "native-alpha", "adaptive-source-image"
        ):
            raise ValueError('Unknown protected graphic representation')
        if not isinstance(self.experimental_pdf_native_geometry, bool):
            raise ValueError("Native PDF geometry flag must be boolean")
        if self.experimental_pdf_native_text not in ("off", "matched", "independent"):
            raise ValueError("Unknown experimental PDF native text route")
        if self.experimental_pdf_native_text != "off" and self.experimental_observed_text_display:
            raise ValueError("Native text entry and G35 display trials are separate")
        if not isinstance(self.paper_boundary_verified, (bool, np.bool_)):
            raise ValueError("Paper boundary verification must be boolean")
        if not isinstance(self.experimental_observed_text_display, (bool, np.bool_)):
            raise ValueError("Experimental observed display must be boolean")
        if not isinstance(self.experimental_native_source_row, (bool, np.bool_)):
            raise ValueError("Experimental native source row must be boolean")
        if self.experimental_native_source_row and self.experimental_observed_text_display:
            raise ValueError("Experimental source-row and G35 display runs are separate")
        if (
            isinstance(self.source_dpi, (bool, np.bool_))
            or not isfinite(float(self.source_dpi))
            or float(self.source_dpi) <= 0
        ):
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
            object.__setattr__(
                self,
                "draftsman_behavior_manifest_digest",
                _sha256_hex(
                    self.draftsman_behavior_manifest_digest,
                    "Draftsman behavior manifest",
                ),
            )

    def threshold_summary(self) -> dict[str, object]:
        from app.ocr.ocr_recognition import MAX_OCR_CANDIDATES, MIN_OCR_CONFIDENCE

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
            "paper_boundary_verified": bool(self.paper_boundary_verified),
            "layout_profile": self.layout_profile.payload(),
            "algorithm_version": self.algorithm_version,
            "model_version": self.model_version,
            "final_structure_schema_version": (FINAL_STRUCTURE_SCHEMA_VERSION),
            "critical_thresholds": self.threshold_summary(),
            "recover_pdf_native_text_omissions": self.recover_pdf_native_text_omissions,
        }
        if self.junction_contract is not None:
            authority = validate_junction_contract_authority(self.junction_contract)
            payload["junction_contract_digest"] = authority.trusted_contract_digest
            payload["junction_trusted_authority"] = authority.cache_identity
        if self.draftsman_behavior_manifest_digest is not None:
            payload["draftsman_behavior_manifest_digest"] = (
                self.draftsman_behavior_manifest_digest.strip().lower()
            )
        if self.experimental_observed_text_display:
            payload["experimental_observed_text_display"] = True
            payload["observed_display_version"] = "observed-source-components-display-v2"
        if self.experimental_native_source_row:
            payload["experimental_native_source_row"] = True
            payload["native_source_row_version"] = "native-row-before-ownership-v4"
        if self.experimental_pdf_native_text != "off":
            payload["experimental_pdf_native_text"] = self.experimental_pdf_native_text
            payload["pdf_native_text_version"] = "embedded-cmap-visible-native-text-v7-stable-cell-source"
        if self.experimental_pdf_native_text == "independent":
            from app.ocr.observed_text_display import PDF_LABEL_DISPLAY_VERSION

            payload["pdf_path_digit_review_version"] = "isolated-vertical-digits-v2"
            payload["pdf_path_callout_review_version"] = "isolated-leader-full-label-bounds-v2"
            payload["pdf_label_display_version"] = PDF_LABEL_DISPLAY_VERSION
        if self.experimental_pdf_native_geometry:
            from app.geometry.native_pdf_paths import POLICY

            payload["experimental_pdf_native_geometry"] = POLICY
        if self.experimental_protected_graphics != 'legacy':
            payload['experimental_protected_graphics']=self.experimental_protected_graphics
        if self.experimental_protected_graphics == 'adaptive-source-image':
            payload['protected_graphics_version'] = 'source-logo-lockup-signature-crossings-v4'
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
        object.__setattr__(
            self,
            "input_content_sha256",
            _sha256_hex(self.input_content_sha256, "Input content hash"),
        )
        if isinstance(self.page_number, bool) or self.page_number <= 0:
            raise ValueError("Page number must be positive")
        if isinstance(self.dpi, bool) or not isfinite(self.dpi) or self.dpi <= 0:
            raise ValueError("Cache DPI must be positive and finite")

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
        config_payload["pdf_geometry_binding"] = dict(pdf_geometry_binding)
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
    """Shared native entry plus the explicitly selected legacy page service."""

    @staticmethod
    def process_native_objects(
        input_path: str | Path,
        output_path: str | Path,
        roi,
        *,
        dpi: float = 200.0,
        progress_callback: ProgressCallback | None = None,
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
        connection_checkpoint: dict | None = None,
        source_stage_checkpoint: dict | None = None,
    ) -> dict:
        """Explicit native-object mode; failures never enter the legacy trace."""
        from app.core.native_objects_entry import dispatch_native_objects

        checkpoint_options = {}
        if connection_checkpoint is not None:
            checkpoint_options["connection_checkpoint"] = connection_checkpoint
        if source_stage_checkpoint is not None:
            checkpoint_options["source_stage_checkpoint"] = source_stage_checkpoint
        return dispatch_native_objects(
            input_path, output_path, roi, dpi=dpi,
            progress_callback=progress_callback, evidence_dir=evidence_dir,
            cache_dir=cache_dir, page_number=page_number, frame_number=frame_number,
            orientation=orientation, job_id=job_id, temp_dir=temp_dir,
            resource_report_path=resource_report_path,
            cancellation_token=cancellation_token, entrypoint=entrypoint,
            **checkpoint_options,
        )


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
        pdf_text_suggestions=None,
        before_arc_replacement=None,
        confirmed_noise: np.ndarray | None = None,
        source_crop: tuple[int, int, int, int] | None = None,
        original_scan_features: Mapping[str, object] | None = None,
        registered_original_scan=None,
        original_scan_requested: bool = False,
        unreviewed_dust: np.ndarray | None = None,
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
            paper_boundary_verified=config.paper_boundary_verified,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
            performance_callback=performance_callback,
            observation_sink=observation_sink,
            junction_contract=config.junction_contract,
            processing_contract=config.payload(),
            pdf_geometry=pdf_geometry,
            pdf_text_suggestions=pdf_text_suggestions,
            before_arc_replacement=before_arc_replacement,
            confirmed_noise=confirmed_noise,
            source_crop=source_crop,
            original_scan_features=original_scan_features,
            registered_original_scan=registered_original_scan,
            original_scan_requested=original_scan_requested,
            unreviewed_dust=unreviewed_dust,
        )
        if pdf_text_suggestions is not None and result.final_structure is not None:
            from app.geometry.pdf_text_suggestions import SUGGESTION_KEY

            # Metadata only. The original OCR and final source ownership stay
            # unchanged until explicit review of a saved snapshot.
            structure = replace(
                result.final_structure,
                provenance={
                    **result.final_structure.provenance,
                    SUGGESTION_KEY: pdf_text_suggestions,
                },
            )
            from app.ocr.source_row_display import normalize_source_row_displays

            structure = normalize_source_row_displays(
                structure,
                source_binding=(
                    pdf_geometry.binding if pdf_geometry is not None else None
                ),
            )
            result = replace(result, final_structure=structure, texts=structure.texts)
        if config.enable_ocr and result.final_structure is not None:
            from app.geometry.scan_cleanup import _to_gray
            from app.ocr.proven_row_group_display import refine_proven_row_group_displays

            # Late display-only consumer: all source ownership/retirement and
            # structural geometry are already final and cannot be modified here.
            display_source = image
            if source_crop is not None:
                left, top, right, bottom = source_crop
                display_source = image[top:bottom, left:right]
            structure = refine_proven_row_group_displays(_to_gray(display_source), result.final_structure)
            result = replace(result, final_structure=structure, texts=structure.texts)
        if config.enable_ocr and result.final_structure is not None:
            from app.ocr.observed_text_display import refine_source_supported_scan_displays
            from app.geometry.scan_cleanup import _to_gray
            display_source = image
            if source_crop is not None:
                left, top, right, bottom = source_crop
                display_source = image[top:bottom, left:right]
            structure = refine_source_supported_scan_displays(_to_gray(display_source), result.final_structure)
            result = replace(result, final_structure=structure, texts=structure.texts)
        if config.enable_ocr and config.experimental_observed_text_display and result.final_structure is not None:
            from app.geometry.scan_cleanup import _to_gray
            from app.ocr.observed_text_display import refine_observed_text_displays

            # Last operation: no ownership, fill, retirement or structural
            # consumer sees this experimental display suggestion.
            structure = refine_observed_text_displays(_to_gray(image), result.final_structure)
            result = replace(result, final_structure=structure, texts=structure.texts)
        if config.experimental_pdf_native_geometry and result.final_structure is not None:
            from app.geometry.native_pdf_paths import apply_native_pdf_paths
            from app.geometry.scan_cleanup import _to_gray
            structure = apply_native_pdf_paths(result.final_structure, _to_gray(image), pdf_geometry, config.source_dpi)
            result = replace(result, final_structure=structure, paths=structure.contours,
                             binary=structure.contour_binary, straight_lines=structure.straight_lines,
                             arcs=structure.arcs, native_fills=structure.native_fills,
                             vertex_count=sum(len(p.points) for p in structure.contours),
                             foreground_pixels=int(np.count_nonzero(structure.contour_binary == 0)))
        if result.final_structure is not None and config.experimental_protected_graphics != 'legacy':
            structure=replace(result.final_structure,provenance={**result.final_structure.provenance,
                'protected_graphic_presentation':config.experimental_protected_graphics})
            result=replace(result,final_structure=structure)
        structure = result.final_structure
        if (
            config.enable_ocr
            and config.experimental_pdf_native_text == "independent"
            and pdf_geometry is not None
            and structure is not None
            and structure.provenance.get("clean_digital")
        ):
            from app.diagnostics.observability import rasterize_lines
            from app.geometry.content_ownership import graphic_source_mask, signature_source_mask
            from app.geometry.scan_cleanup import _to_gray
            from app.ocr.observed_text_display import refine_unfitted_pdf_labels

            gray = _to_gray(image)
            if gray.shape[::-1] != structure.source_size_px:
                return result
            protected = (
                rasterize_lines(structure.straight_lines, gray.shape),
                graphic_source_mask(gray, structure.logos),
                signature_source_mask(gray, structure.signatures),
                structure.uncertain_text_outline_mask,
            )
            texts = refine_unfitted_pdf_labels(
                gray, structure.texts, protected_source_masks=protected
            )
            if texts != structure.texts:
                structure = replace(structure, texts=texts)
                result = replace(result, final_structure=structure, texts=texts)
        return result
