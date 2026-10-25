from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.diagnostics.observability import ObservationSink
    from app.diagnostics.source_support_lifecycle import SourceSupportLifecycle

from dataclasses import replace

import cv2
import numpy as np

from app.core.cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from app.geometry.connectivity_safety import DEFAULT_CONNECTION_DPI
from app.geometry.content_ownership import (
    arbitrate_content_candidates,
    binary_from_foreground,
    build_connection_protection,
    build_text_semantic_ownership,
    complete_verified_text_ownership,
    finalize_content_ownership,
    graphic_source_mask,
    partition_content,
    preserve_verified_text_members,
    retain_layout_rule_ownership,
    retained_rule_contours,
    signature_source_mask,
    text_candidate_source_mask,
)
from app.core.structure_build import build_final_structure
from app.geometry.junction_v2_consumer import (
    JunctionConsumptionResult,
    JunctionContract,
    consume_junction_contract,
)
from app.geometry.line_detect import LineSegment
from app.ocr.logo_detection import detect_logo_regions, source_logo_objects
from app.ocr.engineering_symbols import resolve_enclosure_relations
from app.ocr.ocr_layout import (
    constrain_texts_to_table_cells,
    verified_layout_rule_sources,
)
from app.ocr.single_glyph_display import refine_single_glyph_displays
from app.ocr.ocr_overlap import collapse_overlapping_candidates
from app.ocr.ocr_pipeline import recognize_text_candidates_optimized
from app.diagnostics.performance_observability import (
    PerformanceCallback,
    emit_performance,
    performance_clock,
    record_performance,
)
from app.geometry.raster_trace import RasterTraceResult, trace_binary
from app.core.resolution import image_resolution_scale
from app.geometry.scan_artifact_filter import suppress_scan_artifact_traces
from app.geometry.scan_cleanup import prepare_scan_page
from app.ocr.signature_overlay import (
    detect_signature_regions,
    signature_field_regions,
    source_ink_region,
)
from app.geometry.source_stroke_reconciliation import ReconciliationLedger
from app.geometry.straight_line_reconstruction import reconstruct_straight_lines
from app.geometry.source_presentation import (
    source_orientation_graphics,
    stroke_presentation,
    source_fill_records,
)
from app.ocr.text_output_contract import text_output_decisions, text_output_summary


def _stable_audit_union(*groups):
    """Preserve first-pass audit records while appending scoped new evidence."""

    output = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            payload = item.payload() if hasattr(item, "payload") else item
            key = repr(payload)
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
    return tuple(output)


def _graphic_owns_text(candidate, source_binary, graphic_ink):
    x, y, w, h = candidate.bbox
    roi = graphic_ink[y : y + h, x : x + w]
    source = source_binary[y : y + h, x : x + w] < 128
    return bool(
        roi.size
        and np.count_nonzero((roi > 0) & source)
        > max(4, np.count_nonzero(source) * 0.55)
    )


def _prefer_source_regions(existing, source_regions):
    """Replace overlapping provisional crops, retaining unrelated objects."""

    def overlaps(first, second):
        x, y, w, h = first.bbox
        a, b, c, d = second.bbox
        intersection = max(0, min(x + w, a + c) - max(x, a)) * max(
            0, min(y + h, b + d) - max(y, b)
        )
        return intersection > min(w * h, c * d) * 0.5

    return (
        *source_regions,
        *(r for r in existing if not any(overlaps(r, s) for s in source_regions)),
    )


def commit_source_objects(
    *,
    source_gray,
    contour_binary,
    source_candidates,
    texts,
    logos,
    signatures,
    text_semantics,
    orientation_graphics=None,
):
    """Commit representation from source evidence, without touching LINE authority.

    The production path and committed-model evidence replay use this one stage.
    Callers own the writable contour raster; FinalStructure stays immutable.
    """
    # Representation is committed AFTER line reconciliation. This stage never
    # supplies candidates to, removes, or rewrites structural LINE geometry.
    source_binary = np.where(source_gray < 128, 0, 255).astype(np.uint8)
    if orientation_graphics is None:
        orientation_graphics = source_orientation_graphics(source_gray)
    source_logos = (*source_logo_objects(source_binary), *orientation_graphics)
    source_signatures = signature_field_regions(source_binary, source_candidates)
    logos = _prefer_source_regions(logos, source_logos)
    signatures = _prefer_source_regions(signatures, source_signatures)
    graphic_ink = cv2.max(
        graphic_source_mask(source_binary, logos),
        signature_source_mask(source_binary, signatures),
    )

    def graphic_owned(candidate):
        return _graphic_owns_text(candidate, source_binary, graphic_ink)

    candidates = tuple(c for c in source_candidates if not graphic_owned(c))
    related = set()
    (
        related_texts,
        enclosure_paths,
        enclosure_records,
        fallback_graphics,
        enclosure_ink,
    ) = resolve_enclosure_relations(
        source_binary, candidates, claimed_candidates=related
    )
    graphic_ink = cv2.max(
        graphic_ink, graphic_source_mask(source_binary, fallback_graphics)
    )
    # Restore only source-supported enclosure text rejected by old ownership;
    # ordinary OCR arbitration and ordinary native TEXT stay unchanged.
    replaced_boxes = {candidates[i].bbox for i in related}
    texts = tuple(
        c for c in texts if not graphic_owned(c) and c.bbox not in replaced_boxes
    )
    texts += tuple(c for c in related_texts if c.source.endswith(":enclosure-relation"))
    logos = (*logos, *fallback_graphics)
    logos = tuple(source_ink_region(region, source_gray) for region in logos)
    signatures = tuple(source_ink_region(region, source_gray) for region in signatures)
    replacement_ink = cv2.max(graphic_ink, enclosure_ink)
    footprint = cv2.dilate(replacement_ink, np.ones((3, 3), np.uint8)) > 0
    contour_binary[footprint] = 255
    text_semantics = replace(
        text_semantics,
        **{
            name: np.where(footprint, 0, getattr(text_semantics, name)).astype(np.uint8)
            for name in ("editable_source", "source_outline", "uncertain_outline")
        },
    )
    return (
        contour_binary,
        texts,
        logos,
        signatures,
        text_semantics,
        enclosure_paths,
        enclosure_records,
    )


def _preserve_ownership_continuity(
    initial,
    updated,
    *,
    initial_downgrades,
):
    """Carry first-pass conflicts/residual evidence across scoped line deltas."""

    result = replace(
        updated,
        ambiguous=cv2.max(initial.ambiguous, updated.ambiguous),
        candidate_classes=_stable_audit_union(
            initial.candidate_classes,
            updated.candidate_classes,
        ),
        conflicts=_stable_audit_union(initial.conflicts, updated.conflicts),
        downgrades=_stable_audit_union(
            initial_downgrades,
            updated.downgrades,
        ),
    )
    result.assert_valid()
    return result


def _assign_and_reconcile(
    binary,
    *,
    line_candidates,
    texts,
    logos,
    signatures,
    graphic_mask,
    signature_mask,
    reconciliation_ledger,
    late_restorations,
    performance_callback,
    verified_text_sources=(),
):
    """Arbitrate proposals, reconcile source identity, then enforce ownership veto.

    The second raster pass represents the changed committed set. It never
    reconstructs endpoints or treats pixels as line identity.
    """
    # Geometry preparation and stroke presentation must finish first. Removing
    # a detector observation earlier can change their representative selection.
    line_candidates = reconciliation_ledger.consolidate_detector_aliases(
        line_candidates
    )
    ownership_started = performance_clock()
    candidate_ownership = partition_content(
        binary,
        lines=line_candidates,
        texts=texts,
        signatures=signatures,
        logos=logos,
        graphic_mask=graphic_mask,
        signature_mask=signature_mask,
    )
    arbitrated = arbitrate_content_candidates(
        binary,
        lines=line_candidates,
        texts=texts,
        logos=logos,
        signatures=signatures,
        ownership=candidate_ownership,
    )
    ownership = finalize_content_ownership(
        binary,
        candidates=candidate_ownership,
        arbitrated=arbitrated,
    )
    initial_ownership = ownership
    initial_downgrades = tuple(arbitrated.downgrades)
    record_performance(
        performance_callback,
        "ownership",
        ownership_started,
    )
    texts = arbitrated.texts
    logos = arbitrated.logos
    signatures = arbitrated.signatures
    reconciliation_result = reconciliation_ledger.reconcile(
        main_candidates=line_candidates,
        accepted_main=arbitrated.lines,
        restoration_candidates=late_restorations,
        ownership_masks={
            "line": ownership.line,
            "text": ownership.text,
            "logo": ownership.logo,
            "signature": ownership.signature,
            "graphic": ownership.graphic,
            "residual": ownership.residual,
        },
        ownership_downgrades=arbitrated.downgrades,
    )
    straight_lines = reconciliation_result.lines

    # Repartition only after the single mandatory reconciliation commit so
    # newly admitted safe restoration pieces are represented in the existing
    # ownership masks used by fallback and observations.  Ownership remains a
    # veto authority: an unexpected rejection fails closed instead of silently
    # changing the committed line set.
    reconciled_candidates = partition_content(
        binary,
        lines=straight_lines,
        texts=texts,
        signatures=signatures,
        logos=logos,
        graphic_mask=graphic_mask,
        signature_mask=signature_mask,
        forced_residual=initial_ownership.residual,
    )
    reconciled_arbitrated = arbitrate_content_candidates(
        binary,
        lines=straight_lines,
        texts=texts,
        logos=logos,
        signatures=signatures,
        ownership=reconciled_candidates,
    )
    if tuple(reconciled_arbitrated.lines) != tuple(straight_lines):
        raise AssertionError(
            "Ownership rejected a committed reconciliation piece; "
            "no partial reconciliation was applied"
        )
    texts = reconciled_arbitrated.texts
    logos = reconciled_arbitrated.logos
    signatures = reconciled_arbitrated.signatures
    ownership = finalize_content_ownership(
        binary,
        candidates=reconciled_candidates,
        arbitrated=reconciled_arbitrated,
    )
    ownership = _preserve_ownership_continuity(
        initial_ownership,
        ownership,
        initial_downgrades=initial_downgrades,
    )
    ownership = preserve_verified_text_members(
        binary, texts, verified_text_sources,
        previous=candidate_ownership, ownership=ownership,
    )
    return reconciliation_result, ownership, texts, logos, signatures


def trace_image_optimized(
    image: np.ndarray,
    *,
    foreground_threshold: int | None = None,
    enable_ocr: bool = False,
    source_dpi: float | None = DEFAULT_CONNECTION_DPI,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
    observation_sink: ObservationSink | None = None,
    performance_callback: PerformanceCallback | None = None,
    source_support_lifecycle: SourceSupportLifecycle | None = None,
    junction_contract: JunctionContract | None = None,
    processing_contract: dict[str, object] | None = None,
    pdf_geometry=None,
    pdf_text_suggestions=None,
    before_arc_replacement=None,
) -> RasterTraceResult:
    """Run OCR and tracing without constructing full-resolution UI overlays.

    Digital PDF pages keep literal non-white pixels. Real scans are normalized once
    and the same cleaned page is reused by OCR and tracing, avoiding duplicate work
    while suppressing folds, tape shadows, stains and damaged paper texture.
    """

    if observation_sink is not None:
        from app.diagnostics.observability import (
            observe,
            rasterize_lines,
            rasterize_text_boxes,
            texts_payload,
        )
    checkpoint(cancellation_token)
    if (
        source_support_lifecycle is not None
        and source_support_lifecycle.shape != image.shape[:2]
    ):
        raise ValueError("SourceSupportLifecycle shape must match the source image")
    if observation_sink is not None:
        observe(
            observation_sink,
            "original_page",
            image=image,
            payload={
                "shape": [int(value) for value in image.shape],
                "dtype": str(image.dtype),
            },
        )
    report_progress(progress_callback, "prepare-image", 0.02)
    prepared = prepare_scan_page(
        image,
        foreground_threshold=foreground_threshold,
        performance_callback=performance_callback,
    )
    if observation_sink is not None:
        observe(
            observation_sink,
            "original_gray",
            image=prepared.gray,
            payload={"clean_digital": bool(prepared.clean_digital)},
        )
        observe(
            observation_sink,
            "normalized_background",
            image=prepared.normalized,
            payload={"clean_digital": bool(prepared.clean_digital)},
        )
        observe(
            observation_sink,
            "binary_foreground",
            image=prepared.binary,
            payload={
                "threshold": int(prepared.threshold),
                "foreground_pixels": int(np.count_nonzero(prepared.binary == 0)),
            },
        )
        observe(
            observation_sink,
            "legacy_closing",
            payload={
                "executed": False,
                "reason": (
                    "Whole-page 2x1/1x2 morphological closing is removed from "
                    "the production path; this stage records its absence."
                ),
                "historical_introduction_commit": (
                    "d9fbda763e95c6dd7154934b801b59dbf034e711"
                ),
            },
            status="not_executed",
        )

    texts = ()
    warnings: list[str] = []
    if enable_ocr:
        ocr_started = performance_clock()
        texts, ocr_warnings = recognize_text_candidates_optimized(
            prepared.gray,
            cancellation_token=cancellation_token,
            progress_callback=(
                None
                if progress_callback is None
                else lambda stage, fraction: progress_callback(
                    stage,
                    0.04 + 0.41 * fraction,
                )
            ),
            observation_sink=observation_sink,
        )
        record_performance(performance_callback, "ocr", ocr_started)
        warnings.extend(ocr_warnings)
    else:
        emit_performance(performance_callback, "ocr", 0.0)
    if not enable_ocr and observation_sink is not None:
        for stage_key in (
            "ocr_raw_tiles",
            "ocr_rule_removed_tiles",
            "ocr_text_boxes",
        ):
            observe(
                observation_sink,
                stage_key,
                payload={"reason": "OCR is disabled for this trace."},
                status="not_executed",
            )

    signatures = detect_signature_regions(prepared.binary)
    orientation_graphics = source_orientation_graphics(prepared.gray)
    logos = (*detect_logo_regions(prepared.binary), *orientation_graphics)
    verified_text_sources = []
    display_cells = {}
    if texts:
        # OCR and source-row proofs use the original strong ink. The tracing
        # threshold can also include antialiasing bridges between those rows.
        texts = constrain_texts_to_table_cells(
            prepared.gray,
            texts,
            verified_sources=verified_text_sources,
            display_cells=display_cells,
        )
        texts = collapse_overlapping_candidates(texts)
    source_candidates = tuple(texts)
    if enable_ocr and observation_sink is not None:
        observe(
            observation_sink,
            "ocr_text_boxes",
            image=rasterize_text_boxes(texts, prepared.binary.shape),
            payload={"texts": texts_payload(texts), "count": len(texts)},
        )

    # Classification happens once. Signatures and explicit logos exclude only
    # their actual source ink from structural detection. No OCR rectangle may
    # cut a title-block rule, wall, leader or symbol.
    signature_mask = signature_source_mask(prepared.binary, signatures)
    graphic_mask = graphic_source_mask(prepared.binary, logos)
    if observation_sink is not None:
        text_candidate_mask = text_candidate_source_mask(
            prepared.binary,
            texts,
        )
        observe(
            observation_sink,
            "text_candidate_mask",
            image=text_candidate_mask,
            payload={"role": "candidate", "count": len(texts)},
        )
        observe(
            observation_sink,
            "logo_candidate_mask",
            image=graphic_mask,
            payload={
                "role": "candidate",
                "count": len(logos),
                "regions": [item.payload() for item in logos],
            },
        )
        observe(
            observation_sink,
            "signature_candidate_mask",
            image=signature_mask,
            payload={
                "role": "candidate",
                "count": len(signatures),
                "regions": [item.payload() for item in signatures],
            },
        )
    connection_protection = build_connection_protection(
        prepared.binary,
        texts=texts,
        logos=logos,
        signatures=signatures,
    )
    protected_mask = connection_protection.mask
    reconciliation_ledger = ReconciliationLedger(
        source_gray=prepared.gray,
        source_binary=prepared.binary,
        protected_mask=protected_mask,
        scale=image_resolution_scale(prepared.binary.shape),
    )
    report_progress(
        progress_callback, "line-reconstruction", 0.47 if enable_ocr else 0.08
    )
    late_restorations: list[LineSegment] = []
    scan_stroke_reviews = []
    line_candidates = reconstruct_straight_lines(
        prepared.binary,
        source_dpi=source_dpi,
        scan_support_gray=(None if prepared.clean_digital else prepared.gray),
        protected_mask=protected_mask,
        protection_guards=dict(connection_protection.guards),
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else lambda stage, fraction: progress_callback(
                stage,
                (0.48 if enable_ocr else 0.09) + 0.22 * fraction,
            )
        ),
        observation_sink=observation_sink,
        performance_callback=performance_callback,
        late_restoration_output=late_restorations,
        source_support_lifecycle=source_support_lifecycle,
        reconciliation_ledger=reconciliation_ledger,
        scan_review_output=scan_stroke_reviews,
    )

    line_candidates, stroke_decisions = stroke_presentation(
        prepared.gray,
        line_candidates,
        float(source_dpi or DEFAULT_CONNECTION_DPI),
        protected_mask=protected_mask,
    )
    reconciliation_result, ownership, texts, logos, signatures = _assign_and_reconcile(
        prepared.binary,
        line_candidates=line_candidates,
        texts=texts,
        logos=logos,
        signatures=signatures,
        graphic_mask=graphic_mask,
        signature_mask=signature_mask,
        reconciliation_ledger=reconciliation_ledger,
        late_restorations=late_restorations,
        performance_callback=performance_callback,
        verified_text_sources=verified_text_sources,
    )
    straight_lines = reconciliation_result.lines
    junction_result: JunctionConsumptionResult | None = None
    final_line_authority = reconciliation_result
    if junction_contract is not None:
        junction_result = consume_junction_contract(
            reconciliation_result,
            junction_contract,
        )
        straight_lines = junction_result.lines
        final_line_authority = junction_result
    ownership = complete_verified_text_ownership(
        prepared.binary,
        prepared.gray,
        texts,
        verified_text_sources,
        ownership=ownership,
    )
    rule_started = performance_clock()
    rule_sources = verified_layout_rule_sources(prepared.gray, prepared.binary, texts)
    ownership, retained_rules = retain_layout_rule_ownership(ownership, rule_sources)
    record_performance(performance_callback, "text-rule-source-scope", rule_started)
    curve_review = None
    if not prepared.clean_digital and not getattr(pdf_geometry, "candidates", ()):
        from app.geometry.scan_curve_retention import retain_closed_scan_curves

        curve_started = performance_clock()
        ownership, curve_review = retain_closed_scan_curves(
            prepared.binary,
            prepared.gray,
            ownership,
            straight_lines,
            protected_mask=protected_mask,
        )
        record_performance(
            performance_callback, "isolated-scan-curve-source", curve_started
        )
    if observation_sink is not None:
        observe(
            observation_sink,
            "text_candidate_mask",
            image=retained_rules,
            payload={
                "role": "layout-excluded-rule-sources",
                "rules": [
                    {
                        "text": p.text.text,
                        "bbox": list(p.text.bbox),
                        "source_pixels": int(cv2.countNonZero(p.mask)),
                        "layout_excluded_pixels": p.layout_excluded_pixels,
                        "body_free_columns": p.body_free_columns,
                    }
                    for p in rule_sources
                ],
            },
        )
    text_decisions = text_output_decisions(texts)
    text_contract = text_output_summary(texts)
    text_semantics = build_text_semantic_ownership(
        prepared.binary,
        texts,
        ownership=ownership,
        retained_rule_mask=retained_rules,
    )
    if observation_sink is not None:
        owner_map = np.zeros(prepared.binary.shape, dtype=np.uint8)
        for owner_code, mask in (
            (1, ownership.line),
            (2, ownership.text),
            (3, ownership.logo),
            (4, ownership.signature),
            (5, ownership.graphic),
            (6, ownership.residual),
        ):
            owner_map[mask > 0] = owner_code
        observe(
            observation_sink,
            "text_candidate_mask",
            image=ownership.text,
            payload={"role": "final-owned"},
        )
        observe(
            observation_sink,
            "logo_candidate_mask",
            image=ownership.logo,
            payload={
                "role": "final-owned",
                "count": len(logos),
                "regions": [item.payload() for item in logos],
            },
        )
        observe(
            observation_sink,
            "signature_candidate_mask",
            image=ownership.signature,
            payload={
                "role": "final-owned",
                "count": len(signatures),
                "regions": [item.payload() for item in signatures],
            },
        )
        observe(
            observation_sink,
            "structural_line_candidate_mask",
            image=ownership.line,
            payload={"role": "final-owned"},
        )
        observe(
            observation_sink,
            "conflict_mask",
            image=ownership.ambiguous,
            payload=ownership.payload(),
        )
        observe(
            observation_sink,
            "residual_mask",
            image=ownership.residual,
            payload={
                "role": "residual",
                "residual_pixels": int(cv2.countNonZero(ownership.residual)),
            },
        )
        observe(
            observation_sink,
            "residual_mask",
            image=owner_map,
            payload={
                "role": "pixel-lineage",
                "codebook": {
                    "0": "background",
                    "1": "structural_line",
                    "2": "text",
                    "3": "logo",
                    "4": "signature",
                    "5": "graphic",
                    "6": "residual",
                },
            },
        )
    outline_source = cv2.max(ownership.graphic, ownership.residual)
    primary_outline_source = np.where(
        (outline_source > 0)
        & (text_semantics.source_outline == 0)
        & (text_semantics.uncertain_outline == 0),
        255,
        0,
    ).astype(np.uint8)
    residual_binary = binary_from_foreground(primary_outline_source)
    artifact_removed = 0
    if not prepared.clean_digital and np.any(primary_outline_source):
        contour_started = performance_clock()
        residual_paths = trace_binary(
            residual_binary,
            cancellation_token=cancellation_token,
        )
        if source_support_lifecycle is not None:
            if source_support_lifecycle.auto_register_fallback:
                source_support_lifecycle.register_fallback_roots(
                    residual_binary,
                    residual_paths,
                )
            text_adjacent = cv2.dilate(
                text_candidate_source_mask(prepared.binary, texts),
                np.ones((9, 9), dtype=np.uint8),
            )
            symbol_adjacent = cv2.dilate(
                cv2.max(ownership.logo, ownership.signature),
                np.ones((9, 9), dtype=np.uint8),
            )
            source_support_lifecycle.observe_ownership(
                owner_masks={
                    "LINE": ownership.line,
                    "TEXT": ownership.text,
                    "LOGO": ownership.logo,
                    "SIGNATURE": ownership.signature,
                    "GRAPHIC_FALLBACK": ownership.graphic,
                    "RESIDUAL": ownership.residual,
                },
                downgrades=ownership.downgrades,
                text_adjacent_mask=text_adjacent,
                symbol_adjacent_mask=symbol_adjacent,
            )
            source_support_lifecycle.observe_fallback_start(
                residual_binary,
                residual_paths,
            )
        artifact_result = suppress_scan_artifact_traces(
            prepared.gray,
            residual_binary,
            residual_paths,
            source_support_lifecycle=source_support_lifecycle,
        )
        if artifact_result.removed_root_count:
            residual_binary = artifact_result.binary
            artifact_removed = artifact_result.removed_root_count
        if source_support_lifecycle is not None:
            source_support_lifecycle.observe_fallback_result(
                artifact_result.binary,
            )
        record_performance(
            performance_callback,
            "contour_tracing",
            contour_started,
        )
    elif source_support_lifecycle is not None:
        source_support_lifecycle.observe_ownership(
            owner_masks={
                "LINE": ownership.line,
                "TEXT": ownership.text,
                "LOGO": ownership.logo,
                "SIGNATURE": ownership.signature,
                "GRAPHIC_FALLBACK": ownership.graphic,
                "RESIDUAL": ownership.residual,
            },
            downgrades=ownership.downgrades,
            text_adjacent_mask=cv2.dilate(
                text_candidate_source_mask(prepared.binary, texts),
                np.ones((9, 9), dtype=np.uint8),
            ),
            symbol_adjacent_mask=cv2.dilate(
                cv2.max(ownership.logo, ownership.signature),
                np.ones((9, 9), dtype=np.uint8),
            ),
        )
        source_support_lifecycle.observe_fallback_start(
            residual_binary,
            (),
            executed=False,
        )

    residual_foreground = np.where(residual_binary < 128, 255, 0).astype(np.uint8)
    contour_binary = binary_from_foreground(
        cv2.max(residual_foreground, ownership.logo)
    )
    semantic_texts = tuple(texts)
    (
        contour_binary,
        texts,
        logos,
        signatures,
        text_semantics,
        enclosure_paths,
        enclosure_records,
    ) = commit_source_objects(
        source_gray=prepared.gray,
        contour_binary=contour_binary,
        source_candidates=source_candidates,
        texts=texts,
        logos=logos,
        signatures=signatures,
        text_semantics=text_semantics,
        orientation_graphics=orientation_graphics,
    )
    from app.geometry.content_ownership import (
        native_group_text_backups,
        route_native_group_text_backups,
    )

    native_group_outline, native_group_records = native_group_text_backups(
        prepared.binary,
        prepared.gray,
        texts,
        ownership=replace(
            ownership,
            logo=cv2.max(ownership.logo, graphic_source_mask(prepared.binary, logos)),
            signature=cv2.max(
                ownership.signature, signature_source_mask(prepared.binary, signatures)
            ),
        ),
        retained_rule_mask=retained_rules,
        evidence=pdf_text_suggestions,
        source_binding=(pdf_geometry.binding if pdf_geometry is not None else None),
        clean_digital=prepared.clean_digital,
        threshold=prepared.threshold,
    )
    if native_group_records:
        text_semantics = route_native_group_text_backups(
            text_semantics, native_group_outline, prepared.binary, semantic_texts
        )
        contour_binary = np.where(native_group_outline > 0, 255, contour_binary).astype(
            np.uint8
        )
    text_contract = text_output_summary(texts)
    text_decisions = text_output_decisions(texts)
    if observation_sink is not None:
        final_line_mask = rasterize_lines(
            straight_lines,
            prepared.binary.shape,
        )
        observe(
            observation_sink,
            "final_structural_layer",
            image=final_line_mask,
            payload={
                "lines": len(straight_lines),
                "role": "exported-structural-lines",
            },
        )
        observe(
            observation_sink,
            "final_text_layer",
            image=text_semantics.editable_source,
            payload={
                "texts": texts_payload(texts),
                "count": len(texts),
                "output_contract": text_contract.payload(),
                "semantic_ownership": text_semantics.payload(),
                "decisions": [decision.payload() for decision in text_decisions],
            },
        )
        observe(
            observation_sink,
            "final_text_layer",
            image=text_semantics.source_outline,
            payload={"role": "hidden-source-text-outline"},
        )
        observe(
            observation_sink,
            "final_text_layer",
            image=text_semantics.uncertain_outline,
            payload={"role": "visible-uncertain-text-outline"},
        )
        observe(
            observation_sink,
            "final_outline_layer",
            image=contour_binary,
            payload={"role": "exported-contour-source"},
        )

    report_progress(progress_callback, "prepare-image", 0.71 if enable_ocr else 0.32)
    contour_started = performance_clock()
    paths = trace_binary(
        contour_binary,
        cancellation_token=cancellation_token,
        progress_callback=(
            None
            if progress_callback is None
            else (
                (
                    lambda stage, fraction: progress_callback(
                        stage,
                        0.72 + 0.28 * fraction,
                    )
                )
                if enable_ocr
                else (
                    lambda stage, fraction: progress_callback(
                        stage,
                        0.33 + 0.67 * fraction,
                    )
                )
            )
        ),
    )
    enclosure_records = tuple(
        dict(record, contour_index=len(paths) + i)
        for i, record in enumerate(enclosure_records)
    )
    paths = tuple(paths) + tuple(
        replace(path, root=len(paths) + i) for i, path in enumerate(enclosure_paths)
    )
    record_performance(
        performance_callback,
        "contour_tracing",
        contour_started,
    )
    if artifact_removed:
        warnings.append(
            f"已从最终 CAD 残留轮廓中清除 {artifact_removed} "
            "组折痕、胶带、撕裂或跨空白飞线。"
        )
    foreground_pixels = int(np.count_nonzero(contour_binary == 0))
    vertex_count = sum(len(path.points) for path in paths)
    if not paths and foreground_pixels:
        warnings.append("页面中存在内容，但没有形成可导出的边界。")
    if vertex_count > 1_000_000:
        warnings.append("页面细节较多，生成的 CAD 文件可能较大。")
    if not prepared.clean_digital:
        warnings.append("已自动校正扫描底色并抑制纸张破损、阴影和污渍纹理。")
    if text_contract.ocr_candidate_count:
        warnings.append(
            f"识别到 {text_contract.ocr_candidate_count} 个文字候选，其中 "
            f"{text_contract.editable_text_count} 个导出为可编辑单行文字，"
            f"{text_contract.fallback_outline_count} 个进入 "
            "TEXT_FALLBACK_OUTLINE，"
            f"{text_contract.source_outline_backup_count} 个保留到默认关闭的 "
            "SOURCE_TEXT_OUTLINE，"
            f"{text_contract.residual_graphic_count} 个进入 "
            "RESIDUAL_GRAPHIC。"
        )
    if signatures:
        warnings.append(f"已提取 {len(signatures)} 个完整签名图像并置于前景图层。")
    junction_observations = (
        ()
        if junction_result is None
        else (
            {
                "event": "junction_v2_consumption",
                "schema_version": 1,
                "trusted_authority_id": junction_result.trusted_authority_id,
                "trusted_authority_version": (
                    junction_result.trusted_authority_version
                ),
                "trusted_authority_resource_sha256": (
                    junction_result.trusted_authority_resource_sha256
                ),
                "contract_digest": junction_result.contract_digest,
                "ledger_digest": junction_result.ledger_digest,
                "source_r4_final_set_digest": (
                    junction_result.source_r4_final_set_digest
                ),
                "source_r4_geometry_digest": (
                    junction_result.source_r4_geometry_digest
                ),
                "output_set_digest": junction_result.output_set_digest,
                "consumed_obligation_ids": list(
                    junction_result.consumed_obligation_ids
                ),
                "node_incidence": [
                    dict(item) for item in junction_result.node_incidence
                ],
                "lineage": [item.payload() for item in junction_result.lineage],
            },
        )
    )
    observations = (
        {
            "event": "ownership_partitioned",
            "ambiguous_pixels": int(cv2.countNonZero(ownership.ambiguous)),
            "residual_pixels": int(cv2.countNonZero(ownership.residual)),
            "graphic_fallback_pixels": int(cv2.countNonZero(ownership.graphic)),
            "conflict_objects": len(ownership.conflicts),
            "downgrades": len(ownership.downgrades),
            "source_pixels": int(cv2.countNonZero(ownership.source)),
        },
        {
            "event": "text_output_contract",
            **text_contract.payload(),
            "semantic_ownership": text_semantics.payload(),
            "logo_count": len(logos),
            "signature_count": len(signatures),
        },
        {
            "event": "source_stroke_reconciliation",
            "schema_version": "source-visible-reconciliation-v1",
            "ledger_digest": reconciliation_result.ledger_digest,
            "input_set_digest": reconciliation_result.input_set_digest,
            "final_set_digest": reconciliation_result.final_set_digest,
            "final_piece_ids": list(reconciliation_result.final_piece_ids),
            "ledger": reconciliation_result.ledger_payload(),
        },
        *junction_observations,
    )
    # Mandatory completeness gate: there is no unreviewed restoration append
    # after this assertion and FinalStructure remains the geometry authority.
    final_structure_started = performance_clock()
    final_provenance = {
        "pipeline": "optimized_trace",
        "clean_digital": bool(prepared.clean_digital),
        "source_stroke_reconciliation": {
            "schema_version": "source-visible-reconciliation-v1",
            "ledger_digest": reconciliation_result.ledger_digest,
            "final_set_digest": reconciliation_result.final_set_digest,
        },
    }
    if native_group_records:
        final_provenance["native_text_group_backups"] = native_group_records
    rule_contours = retained_rule_contours(paths, retained_rules)
    if rule_contours:
        final_provenance["text_rule_contours"] = rule_contours
    if enclosure_records:
        final_provenance["engineering_enclosures"] = enclosure_records
    if scan_stroke_reviews:
        accepted_scan_ids = {sid for line in straight_lines for sid in line.source_ids}
        for review in scan_stroke_reviews:
            for decision in review["decisions"]:
                if decision["decision"] == "PROPOSED":
                    decision["final_outcome"] = (
                        "ACCEPTED"
                        if decision["source_id"] in accepted_scan_ids
                        else "NOT_ACCEPTED_BY_RECONCILIATION"
                    )
        final_provenance["scan_stroke_regularization"] = scan_stroke_reviews
    # Annotate the committed geometry; no coordinate edits after reconciliation.
    _, presentation = stroke_presentation(
        prepared.gray,
        straight_lines,
        float(source_dpi or DEFAULT_CONNECTION_DPI),
        allow_merge=False,
    )
    from app.geometry.scan_line_regularization import scan_stroke_line_record

    for index, line in enumerate(straight_lines):
        record = scan_stroke_line_record(
            line, float(source_dpi or DEFAULT_CONNECTION_DPI)
        )
        if record is not None:
            presentation["line_records"][index] = record
    presentation["false_parallel_decisions"] = stroke_decisions[
        "false_parallel_decisions"
    ]
    presentation["fill_records"] = source_fill_records(
        prepared.gray,
        paths,
        source_candidates,
        excluded_indices=tuple(r["contour_index"] for r in enclosure_records),
    )
    if curve_review is not None:
        from app.geometry.scan_curve_retention import (
            bind_closed_curve_contours,
            RECORD_KEY,
        )

        final_provenance["closed_scan_curve_review"] = curve_review
        presentation[RECORD_KEY] = bind_closed_curve_contours(
            paths, contour_binary, prepared.binary, curve_review["proofs"]
        )
    presentation["graphic_ownership"] = [
        dict(
            region.payload(),
            reason="isolated circular perimeter, broad anisotropic filled core, no structural continuation",
        )
        for region in orientation_graphics
    ]
    final_provenance["stroke_presentation"] = presentation
    if processing_contract is not None:
        final_provenance["processing_contract"] = processing_contract
    if junction_result is not None:
        final_provenance["junction_v2_consumption"] = {
            "schema_version": 1,
            "trusted_authority_id": junction_result.trusted_authority_id,
            "trusted_authority_version": junction_result.trusted_authority_version,
            "trusted_authority_resource_sha256": (
                junction_result.trusted_authority_resource_sha256
            ),
            "contract_digest": junction_result.contract_digest,
            "ledger_digest": junction_result.ledger_digest,
            "source_r4_final_set_digest": (junction_result.source_r4_final_set_digest),
            "source_r4_geometry_digest": (junction_result.source_r4_geometry_digest),
            "output_set_digest": junction_result.output_set_digest,
        }
    # Raster ownership, suppression and contours used the original footprints.
    # This fit grants no source authority. ARC protection still uses the
    # unchanged source masks and OCR bbox, independently of the display quad.
    glyph_started = performance_clock()
    texts, glyph_display = refine_single_glyph_displays(
        prepared.gray,
        texts,
        display_cells,
        protected_source_masks=(ownership.line, ownership.logo, ownership.signature),
    )
    if glyph_display:
        final_provenance["single_glyph_display"] = glyph_display
    record_performance(performance_callback, "single-glyph-display", glyph_started)
    final_structure = build_final_structure(
        source_size_px=(contour_binary.shape[1], contour_binary.shape[0]),
        contour_binary=contour_binary,
        contours=tuple(paths),
        straight_lines=final_line_authority.commit(),
        texts=tuple(texts),
        logos=tuple(logos),
        signatures=tuple(signatures),
        editable_text_source_mask=text_semantics.editable_source,
        source_text_outline_mask=text_semantics.source_outline,
        uncertain_text_outline_mask=text_semantics.uncertain_outline,
        preview_binary=prepared.binary,
        threshold=prepared.threshold,
        warnings=tuple(warnings),
        provenance=final_provenance,
        observations=observations,
    )
    if pdf_geometry is not None:
        from app.geometry.native_arc_replacement import apply_pdf_arc_evidence

        if before_arc_replacement is not None:
            before_arc_replacement(final_structure)
        checkpoint(cancellation_token)
        final_structure = apply_pdf_arc_evidence(final_structure, image, pdf_geometry)
        from app.geometry.pdf_fill_evidence import apply_pdf_fill_evidence

        final_structure = apply_pdf_fill_evidence(final_structure, pdf_geometry)
        from app.geometry.native_source_group import apply_native_source_groups

        final_structure = apply_native_source_groups(
            final_structure, image, pdf_geometry
        )
        straight_lines = list(final_structure.straight_lines)
        contour_binary, paths = final_structure.contour_binary, final_structure.contours
        foreground_pixels = int(np.count_nonzero(contour_binary == 0))
        vertex_count = sum(len(p.points) for p in paths)
    if source_support_lifecycle is not None:
        source_support_lifecycle.observe_final(
            contours=tuple(paths),
            straight_lines=tuple(straight_lines),
            contour_binary=contour_binary,
            final_structure_id=final_structure.structure_id,
            arcs=final_structure.arcs,
        )
    record_performance(
        performance_callback,
        "final_structure_generation",
        final_structure_started,
    )
    return RasterTraceResult(
        binary=contour_binary,
        stages={},
        paths=paths,
        threshold=prepared.threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=tuple(warnings),
        texts=tuple(texts),
        signatures=tuple(signatures),
        straight_lines=tuple(straight_lines),
        preview_binary=np.ascontiguousarray(prepared.binary.copy()),
        logos=tuple(logos),
        final_structure=final_structure,
        arcs=final_structure.arcs,
    )
