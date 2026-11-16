from __future__ import annotations

from collections.abc import Mapping
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
from app.diagnostics.observability import rasterize_lines
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
    restore_signature_edge_gray,
    signature_field_sources,
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


def _rejected_enclosure_text_permissions(source_gray, rejected, fallback_source, semantics):
    """Permit source remeasurement, never deletion, for rejected OCR carriers."""
    observed = np.where(source_gray < 255, 0, 255).astype(np.uint8)
    release = np.zeros(source_gray.shape, dtype=bool)
    for item in rejected:
        if item.reviewed or text_output_decisions((item,))[0].text_emit_eligible:
            continue
        carrier = text_candidate_source_mask(observed, (item,)) > 0
        if np.any(carrier & fallback_source):
            release |= carrier
    release &= semantics.uncertain_outline > 0
    release &= (semantics.editable_source == 0) & (semantics.source_outline == 0)
    return release


def _remaining_graphic_members(regions, accepted_ink):
    """Retire only accepted native source members; preserve residual alpha/bbox."""
    from app.geometry.text_residual_retirement import pixel_runs

    output, audit = [], []
    for index, region in enumerate(regions):
        if region.visual_kind != "engineering_graphic":
            output.append(region)
            continue
        x, y, w, h = region.bbox
        if not (0 <= x < x+w <= accepted_ink.shape[1]
                and 0 <= y < y+h <= accepted_ink.shape[0]
                and region.mask.shape == (h, w)):
            output.append(region)
            continue
        retired = (region.mask > 0) & accepted_ink[y:y+h, x:x+w]
        if not retired.any():
            output.append(region)
            continue
        remaining = np.where(retired, 0, region.mask).astype(np.uint8)
        if remaining.any():
            output.append(replace(region, mask=remaining))
        audit.append(dict(
            source_region_index=index, source_bbox=tuple(region.bbox),
            retired_source_pixels=int(retired.sum()),
            remaining_source_pixels=int(np.count_nonzero(remaining)),
            retired_runs_y_x0_x1=pixel_runs(retired, x, y),
            authority="ACCEPTED_NATIVE_MEMBER_SOURCE_ONLY",
        ))
    return tuple(output), tuple(audit)


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
    line_ink=None,
    recover_logo_wordmark=False,
    signature_pdf_binding=None,
    signature_lines=(),
    scan_symbol_dpi=None,
    registered_original_scan=None,
    source_crop=None,
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
    source_logos = (*source_logo_objects(
        source_binary, source_gray=source_gray if recover_logo_wordmark else None, line_ink=line_ink,
        text_candidates=(*source_candidates, *texts),
    ), *orientation_graphics)
    source_signatures, signing_rules = signature_field_sources(source_binary, source_candidates)
    logos = _prefer_source_regions(logos, source_logos)
    signatures = _prefer_source_regions(signatures, source_signatures)
    signatures = tuple(source_ink_region(region, source_gray) for region in signatures)
    logo_ink = graphic_source_mask(source_binary, logos)
    if source_signatures and signature_pdf_binding is not None:
        from app.ocr.pdf_signature_crossings import restore_pdf_signature_crossings

        count = len(source_signatures)
        recovered = restore_pdf_signature_crossings(
            source_gray, signatures[:count], signing_rules, signature_pdf_binding,
            structural_lines=signature_lines,
            protected_masks=(logo_ink, text_semantics.editable_source, text_semantics.uncertain_outline),
        )
        signatures = (*recovered, *signatures[count:])
    graphic_ink = cv2.max(
        logo_ink,
        signature_source_mask(source_binary, signatures),
    )

    def graphic_owned(candidate):
        return _graphic_owns_text(candidate, source_binary, graphic_ink)

    candidates = tuple(c for c in source_candidates if not graphic_owned(c))
    scan_texts, scan_paths, scan_records, scan_replaced = (), (), (), set()
    scan_ink = None
    enclosure_source = source_binary
    if scan_symbol_dpi is not None:
        from app.ocr.scanned_circular_symbols import (
            recover_circular_symbols,
            recover_registered_circular_symbols,
            confirm_input_glyph_on_registered_original,
        )

        protected = (graphic_ink > 0) | (signing_rules > 0)
        if line_ink is not None:
            protected |= line_ink > 0
        text_owned = (text_semantics.editable_source > 0) | (text_semantics.source_outline > 0)
        text_owned |= text_semantics.uncertain_outline > 0
        if registered_original_scan is not None:
            scan_texts, scan_paths, scan_records, scan_ink, scan_replaced = recover_registered_circular_symbols(
                source_gray, source_binary, candidates, protected=protected, text_owned=text_owned,
                dpi=scan_symbol_dpi, scan=registered_original_scan, source_crop=source_crop,
            )
            protected = protected | scan_ink
        direct_candidates = tuple((i, c) for i, c in enumerate(candidates) if i not in scan_replaced)
        direct_texts, direct_paths, direct_records, direct_ink, direct_replaced = recover_circular_symbols(
            source_binary, tuple(c for _, c in direct_candidates),
            protected=protected, text_owned=text_owned, dpi=scan_symbol_dpi,
            skip_boxes={r["input_candidate_bbox"] for r in scan_records},
            glyph_verifier=(
                (lambda candidate: confirm_input_glyph_on_registered_original(
                    candidate, registered_original_scan, source_crop))
                if registered_original_scan is not None else None
            ),
        )
        scan_texts += direct_texts
        scan_paths += direct_paths
        scan_records += tuple(dict(r, sampling_source="input_raster") for r in direct_records)
        scan_ink = direct_ink if scan_ink is None else scan_ink | direct_ink
        scan_replaced.update(direct_candidates[i][0] for i in direct_replaced)
        if scan_records:
            enclosure_source = np.where(scan_ink, 255, source_binary).astype(np.uint8)
    legacy_candidates = tuple((i, item) for i, item in enumerate(candidates) if i not in scan_replaced)
    related = set()
    (
        related_texts,
        enclosure_paths,
        enclosure_records,
        fallback_graphics,
        enclosure_ink,
    ) = resolve_enclosure_relations(
        enclosure_source, tuple(item for _, item in legacy_candidates), claimed_candidates=related
    )
    # Reconsider only source-preserved engineering objects after enclosure
    # arbitration has rejected the OCR carrier. The first pass cannot do this
    # while that carrier still owns uncertain text pixels. Native replacement
    # requires the unchanged source-fit checks; all trusted owners stay protected.
    if scan_symbol_dpi is not None and fallback_graphics:
        fallback_source = graphic_source_mask(source_binary, fallback_graphics) > 0
        retry_protected = (graphic_ink > 0) | (signing_rules > 0)
        retry_protected |= (enclosure_ink > 0) & ~fallback_source
        if line_ink is not None:
            retry_protected |= line_ink > 0
        if scan_ink is not None:
            retry_protected |= scan_ink
        rejected_carriers = tuple(
            item for j, (i, item) in enumerate(legacy_candidates)
            if j in related and not item.reviewed
            and not text_output_decisions((item,))[0].text_emit_eligible
        )
        released_uncertain = _rejected_enclosure_text_permissions(
            source_gray, rejected_carriers, fallback_source, text_semantics,
        )
        retry_owned = text_owned & ~released_uncertain
        retry_candidates = tuple(
            item for j, (i, item) in enumerate(legacy_candidates) if j not in related
        )
        scopes = tuple(region.bbox for region in fallback_graphics
                       if region.visual_kind == "engineering_graphic")
        rt, rp, rr, ri = (), (), (), np.zeros(source_binary.shape, dtype=bool)
        if registered_original_scan is not None:
            rt, rp, rr, ri, _ = recover_registered_circular_symbols(
                source_gray, source_binary, retry_candidates,
                protected=retry_protected, text_owned=retry_owned, dpi=scan_symbol_dpi,
                scan=registered_original_scan, source_crop=source_crop, search_regions=scopes,
            )
        dt, dp, dr, di, _ = recover_circular_symbols(
            source_binary, retry_candidates, protected=retry_protected | ri,
            text_owned=retry_owned, dpi=scan_symbol_dpi, search_regions=scopes,
            skip_boxes={r["input_candidate_bbox"] for r in rr},
            glyph_verifier=(
                (lambda candidate: confirm_input_glyph_on_registered_original(
                    candidate, registered_original_scan, source_crop))
                if registered_original_scan is not None else None
            ),
        )
        rt += dt
        rp += dp
        rr += tuple(dict(r, sampling_source="input_raster") for r in dr)
        ri |= di
        if rr:
            fallback_graphics, release = _remaining_graphic_members(fallback_graphics, ri)
            scan_texts += rt
            scan_paths += rp
            scan_records += tuple(dict(
                r, recovery_stage="source_preserved_enclosure_recheck",
                engineering_graphic_replacements=release,
            ) for r in rr)
            scan_ink = ri if scan_ink is None else scan_ink | ri
    graphic_ink = cv2.max(
        graphic_ink, graphic_source_mask(source_binary, fallback_graphics)
    )
    # Restore only source-supported enclosure text rejected by old ownership;
    # ordinary OCR arbitration and ordinary native TEXT stay unchanged.
    replaced_boxes = {legacy_candidates[i][1].bbox for i in related}
    replaced_boxes.update(candidates[i].bbox for i in scan_replaced)
    texts = tuple(
        c for c in texts if not graphic_owned(c) and c.bbox not in replaced_boxes
    )
    texts += tuple(c for c in related_texts if c.source.endswith(":enclosure-relation"))
    texts += scan_texts
    logos = (*logos, *fallback_graphics)
    logos = tuple(source_ink_region(region, source_gray) for region in logos)
    replacement_ink = cv2.max(graphic_ink, enclosure_ink)
    footprint = cv2.dilate(replacement_ink, np.ones((3, 3), np.uint8)) > 0
    footprint &= signing_rules == 0
    if scan_records:
        footprint |= scan_ink
    contour_binary[footprint] = 255
    # A guessed OCR carrier can already have hidden the cell rule before this
    # late graphic commit rejects the string. Restore measured source ink only,
    # excluding ink already represented by the reconciled LINE owner.
    rule_ink = signing_rules > 0
    restore_rules = rule_ink if line_ink is None else rule_ink & (line_ink == 0)
    contour_binary[restore_rules] = source_binary[restore_rules]
    clear_semantics = footprint | rule_ink
    text_semantics = replace(
        text_semantics,
        **{
            name: np.where(clear_semantics, 0, getattr(text_semantics, name)).astype(np.uint8)
            for name in ("editable_source", "source_outline", "uncertain_outline")
        },
    )
    return (
        contour_binary,
        texts,
        logos,
        signatures,
        text_semantics,
        (*enclosure_paths, *scan_paths),
        (*enclosure_records, *scan_records),
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
    paper_boundary_verified: bool = False,
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
    confirmed_noise: np.ndarray | None = None,
    source_crop: tuple[int, int, int, int] | None = None,
    original_scan_features: Mapping[str, object] | None = None,
    registered_original_scan=None,
    unreviewed_dust: np.ndarray | None = None,
    original_scan_requested: bool = False,
) -> RasterTraceResult:
    """Run OCR and tracing without constructing full-resolution UI overlays.

    Digital PDF pages keep literal non-white pixels. Real scans are normalized once
    and the same cleaned page is reused by OCR and tracing, avoiding duplicate work
    while suppressing folds, tape shadows, stains and damaged paper texture.
    """

    if observation_sink is not None:
        from app.diagnostics.observability import (
            observe,
            rasterize_text_boxes,
            texts_payload,
        )
    checkpoint(cancellation_token)
    report_progress(progress_callback, "prepare-image", 0.02)
    has_pdf_evidence = pdf_geometry is not None
    pdf_content = getattr(pdf_geometry, "page_content", None)
    mixed_vector_gray = getattr(pdf_geometry, "mixed_vector_gray", None)
    prepared = prepare_scan_page(
        image,
        foreground_threshold=foreground_threshold,
        performance_callback=performance_callback,
        pdf_content=pdf_content,
        mixed_vector_gray=mixed_vector_gray,
        confirmed_noise=confirmed_noise,
    )
    if source_crop is not None:
        prepared = prepared.for_crop(source_crop)
        left, top, right, bottom = source_crop
        image = image[top:bottom, left:right]
        if pdf_geometry is not None:
            pdf_geometry = (
                pdf_geometry.for_crop(source_crop)
                if len(pdf_geometry.page_to_pixel) == 6 else None
            )
        mixed_vector_gray = getattr(pdf_geometry, "mixed_vector_gray", None)
    if unreviewed_dust is not None and (
        unreviewed_dust.shape != prepared.binary.shape or unreviewed_dust.dtype != np.bool_
    ):
        raise ValueError("Dust candidates must be a boolean mask in the trace window")
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
    if observation_sink is not None:
        observe(
            observation_sink,
            "original_gray",
            image=prepared.gray,
            payload={
                "clean_digital": bool(prepared.clean_digital),
                "pdf_page_content": pdf_content,
                "classification_reason": prepared.classification_reason,
            },
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

    if prepared.removed_noise_runs:
        # Keep the observed source available above. OCR and geometry recovery
        # use a working copy so confirmed dust cannot reenter from grayscale.
        working_gray = prepared.gray.copy()
        for y, x0, x1 in prepared.removed_noise_runs:
            working_gray[y, x0:x1] = 255
        prepared = replace(prepared, gray=working_gray)

    native_text_plan = None
    native_original_gray = prepared.gray
    original_ocr_superseded = []
    contract = processing_contract or {}
    native_mode = contract.get("experimental_pdf_native_text", "off")
    recover_native_omissions = (
        native_mode == "off"
        and contract.get("recover_pdf_native_text_omissions")
        and not contract.get("experimental_pdf_native_geometry")
        and enable_ocr
        and prepared.clean_digital
        and pdf_geometry is not None
        and source_crop is None
    )
    source_mode = "omissions" if recover_native_omissions else native_mode
    if native_mode == "independent":
        from app.ocr.pdf_native_text import collect_native_text

        protected_signatures = detect_signature_regions(prepared.binary)
        protected_logos = detect_logo_regions(prepared.binary)
        native_text_plan = collect_native_text(
            prepared.gray, pdf_geometry, (), mode=native_mode,
            protected_masks=(
                signature_source_mask(prepared.binary, protected_signatures),
                graphic_source_mask(prepared.binary, protected_logos),
            ),
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

    original_ocr_texts = texts
    if native_mode == "independent" and native_text_plan.texts:
        from app.ocr.pdf_native_text import residual_ocr_partition, mixed_source_rollback_objects

        original_texts=tuple(texts)
        # Reuse the existing source-member separation (including boundary
        # connected circuit strokes). Its clipped display is not the native
        # display, and unaffected business candidates stay exactly original.
        source_carriers=constrain_texts_to_table_cells(prepared.gray,original_texts)
        if len(source_carriers)!=len(original_texts):
            source_carriers=original_texts
        texts,failed,affected,required=residual_ocr_partition(
            prepared.gray,native_text_plan,original_texts,source_carriers=source_carriers)
        fresh=()
        if np.any(required):
            fresh,remaining_warnings=recognize_text_candidates_optimized(
                native_text_plan.background,cancellation_token=cancellation_token,
            )
            warnings.extend(remaining_warnings)
            texts,failed,affected,_=residual_ocr_partition(
                prepared.gray,native_text_plan,original_texts,fresh,source_carriers=source_carriers)
        if failed:
            excluded=mixed_source_rollback_objects(native_text_plan,original_texts,failed)
            native_text_plan=collect_native_text(
                prepared.gray,pdf_geometry,(),mode=native_mode,
                protected_masks=(
                    signature_source_mask(prepared.binary,protected_signatures),
                    graphic_source_mask(prepared.binary,protected_logos),
                ),excluded_object_indices=excluded,
            )
            texts,failed,affected,_=residual_ocr_partition(
                prepared.gray,native_text_plan,original_texts,fresh,source_carriers=source_carriers)
            if failed:
                raise ValueError("Unresolved mixed source after atomic native rollback")
        native_text_plan.suppressed_ocr=list(affected)
        original_ocr_superseded=[dict(
            stage="ORIGINAL_PAGE_OCR_BEFORE_CELL",index=i,
            text=original_texts[i].text,bbox=original_texts[i].bbox,
            quad=original_texts[i].quad,character_boxes=original_texts[i].character_boxes,
            source=original_texts[i].source,
            source_carrier_stage="EXISTING_CELL_SOURCE_MEMBERS_PROBE",
            source_carrier_bbox=source_carriers[i].bbox,
            source_carrier_character_boxes=source_carriers[i].character_boxes,
        ) for i in affected]
        if native_text_plan.texts:
            prepared = prepare_scan_page(
                native_text_plan.background,
                foreground_threshold=foreground_threshold,
                performance_callback=performance_callback,
                pdf_content=pdf_content,
                mixed_vector_gray=mixed_vector_gray,
            )
    if native_mode == "matched":
        from app.ocr.pdf_native_text import collect_native_text

        protected_signatures = detect_signature_regions(prepared.binary)
        protected_logos = detect_logo_regions(prepared.binary)
        native_text_plan = collect_native_text(
            prepared.gray, pdf_geometry, texts, mode=source_mode,
            protected_masks=(
                signature_source_mask(prepared.binary, protected_signatures),
                graphic_source_mask(prepared.binary, protected_logos),
            ),
        )
        if native_text_plan.texts:
            rejected = set(native_text_plan.suppressed_ocr)
            texts = tuple(t for i,t in enumerate(texts) if i not in rejected)
            # Structural extraction sees an actual rendering with only the
            # proved source text objects inactive, including revealed strokes.
            prepared = prepare_scan_page(
                native_text_plan.background,
                foreground_threshold=foreground_threshold,
                performance_callback=performance_callback,
                pdf_content=pdf_content,
                mixed_vector_gray=mixed_vector_gray,
            )
    scanned_glyph_records = ()
    if texts and not has_pdf_evidence and (registered_original_scan is not None or original_scan_requested):
        from app.ocr.scanned_glyph_review import review_scanned_glyphs

        texts, scanned_glyph_records = review_scanned_glyphs(
            texts, registered_original_scan, source_crop=source_crop, input_shape=prepared.gray.shape,
        )
    signatures = detect_signature_regions(prepared.binary)
    orientation_graphics = source_orientation_graphics(prepared.gray)
    logos = (*detect_logo_regions(prepared.binary), *orientation_graphics)
    verified_text_sources = []
    display_cells = {}
    display_row_cells = {}
    native_source_row_records = []
    path_digit_records = []
    boxed_label_records = ()
    if texts and not has_pdf_evidence and not prepared.clean_digital:
        from app.ocr.boxed_label_members import refine_boxed_label_members

        texts, boxed_label_records = refine_boxed_label_members(
            prepared.gray, texts,
            protected_masks=(signature_source_mask(prepared.binary, signatures),
                             graphic_source_mask(prepared.binary, logos)),
            verified_sources=verified_text_sources,
        )
    if texts:
        # OCR and source-row proofs use the original strong ink. The tracing
        # threshold can also include antialiasing bridges between those rows.
        texts = constrain_texts_to_table_cells(
            native_original_gray if native_text_plan is not None and native_text_plan.texts else prepared.gray,
            texts,
            verified_sources=verified_text_sources,
            display_cells=display_cells,
            display_row_cells=display_row_cells,
        )
        texts = collapse_overlapping_candidates(texts)
        if native_mode == "independent" and prepared.clean_digital and pdf_geometry is not None:
            from app.ocr.pdf_path_digits import review_pdf_path_digits

            texts, path_digit_records = review_pdf_path_digits(
                native_original_gray, texts, pdf_geometry.binding,
            )
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
    if processing_contract and processing_contract.get("experimental_native_source_row"):
        from app.ocr.native_source_row import recover_native_source_rows

        # Keep line detector proposals, guards and presentation fixed. Restore
        # only proven text carriers before the first source-ownership commit.
        legacy_count = len(texts)
        fixed_neighbors = native_text_plan.texts if native_text_plan is not None else ()
        recovered = recover_native_source_rows(
            native_original_gray, (*texts,*fixed_neighbors), pdf_geometry, threshold=prepared.threshold,
            records=native_source_row_records,
            protected_source_masks=(graphic_mask,signature_mask),
        )
        # The independent native carriers participate only as fixed display
        # neighbors here. Their source has already been separated and must not
        # enter raster ownership or be appended twice.
        texts = tuple(recovered[:legacy_count])
        source_candidates = tuple(texts)
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
    callout_sources = ()
    if (prepared.clean_digital and pdf_geometry is not None
            and ((native_mode == "independent" and not native_text_plan.texts)
                 or (native_mode == "off" and source_crop is None))):
        from app.ocr.pdf_path_callouts import review_pdf_path_callouts

        callout_sources = review_pdf_path_callouts(
            native_original_gray, texts, pdf_geometry.binding,
            content_changes_only=native_mode == "off",
        )
    ownership, retained_rules = retain_layout_rule_ownership(
        ownership, rule_sources, source_paths=callout_sources,
    )
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
            paper_boundary_verified=paper_boundary_verified,
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
    adaptive_graphics = (
        (processing_contract or {}).get("experimental_protected_graphics")
        == "adaptive-source-image"
    )
    protected_pdf = adaptive_graphics and prepared.clean_digital and pdf_geometry is not None
    scan_symbol_source = pdf_content == "raster" or (
        not has_pdf_evidence and (not prepared.clean_digital or registered_original_scan is not None)
    )
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
        line_ink=ownership.line,
        recover_logo_wordmark=adaptive_graphics,
        signature_pdf_binding=(pdf_geometry.binding
                               if prepared.clean_digital and pdf_geometry is not None else None),
        signature_lines=straight_lines,
        scan_symbol_dpi=source_dpi if enable_ocr and scan_symbol_source else None,
        registered_original_scan=registered_original_scan,
        source_crop=source_crop,
    )
    if (native_mode == "off" and prepared.clean_digital
            and pdf_geometry is not None and source_crop is None):
        from app.ocr.pdf_path_digits import review_pdf_path_digits

        # Correct a proved omission on the committed carrier. The first OCR
        # reading still supplies the observation and reconciled LINE ownership.
        texts, path_digit_records = review_pdf_path_digits(
            native_original_gray, texts, pdf_geometry.binding,
        )
    raster_signing = None
    if enable_ocr and not prepared.clean_digital:
        from app.ocr.raster_signing_ownership import resolve_raster_signing

        signing = resolve_raster_signing(
            prepared.gray, prepared.binary, source_candidates, line_ink=ownership.line,
            excluded=(graphic_source_mask(prepared.binary, logos) > 0)
            | (signature_source_mask(prepared.binary, signatures) > 0),
        )
        if signing is not None:
            (rejected, native, print_ink, new_signatures, signing_graphics,
             caption, fixed_members, unresolved) = signing
            texts = (*[t for t in texts if t.bbox not in rejected], *native, *unresolved)
            logos = (*logos, *signing_graphics)
            signatures = (*signatures, *new_signatures)
            transferred = np.zeros_like(prepared.binary, dtype=bool)
            for region in (*new_signatures, *signing_graphics):
                x, y, w, h = region.bbox
                transferred[y:y+h, x:x+w] |= region.mask > 0
            contour_binary[transferred | print_ink] = 255
            text_semantics = replace(
                text_semantics,
                editable_source=np.where(print_ink, 255, np.where(
                    transferred, 0, text_semantics.editable_source)).astype(np.uint8),
                source_outline=np.where(print_ink, 255, np.where(
                    transferred, 0, text_semantics.source_outline)).astype(np.uint8),
                uncertain_outline=np.where(
                    transferred | print_ink, 0, text_semantics.uncertain_outline).astype(np.uint8),
            )
            raster_signing = {
                "signature_boxes": [r.bbox for r in new_signatures],
                "fixed_member_boxes": fixed_members,
                "printed_readings": [(t.text, t.bbox) for t in native],
                "unresolved_printed_members": [
                    {"text": t.text, "bbox": t.bbox, "status": "UNRESOLVED",
                     "reason": "outside_prepared_foreground"}
                    for t in unresolved
                ],
                "shared_caption": None if caption is None else (caption.text, caption.bbox),
            }
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
    # Compute display once, after source-object routing. Source fields are
    # unchanged; the retirement proof binds to these actual final TEXT layouts.
    glyph_started = performance_clock()
    texts, glyph_display = refine_single_glyph_displays(
        prepared.gray, texts, display_cells,
        protected_source_masks=(ownership.line, ownership.logo, ownership.signature),
    )
    from app.ocr.ruled_cell_display import refine_bilingual_source_bands, refine_ruled_cell_row_displays

    row_source_proofs = []
    texts, row_display = refine_ruled_cell_row_displays(
        prepared.gray, texts, display_row_cells,
        protected_source_masks=(ownership.line, ownership.logo, ownership.signature),
        source_proof_sink=row_source_proofs,
    )
    if protected_pdf and signatures:
        texts, _ = refine_bilingual_source_bands(
            prepared.gray, texts, display_row_cells,
            protected_source_masks=(ownership.line, ownership.logo, ownership.signature,
                                    *((retained_rules,) if retained_rules is not None else ())),
        )
    record_performance(performance_callback, "single-glyph-display", glyph_started)
    if pdf_geometry is not None and getattr(pdf_geometry, "native_fills", ()):
        from app.geometry.pdf_fill_ownership import qualify_pdf_fill_ownership

        # One qualified evidence object feeds both retirement's exclusion and
        # final area/source-group consumers. Rejected OCR candidates still own
        # protection; no text/source deletion right follows from a fill fact.
        pdf_geometry = qualify_pdf_fill_ownership(
            pdf_geometry,
            texts=(*source_candidates, *texts),
            protected_masks=(text_semantics.editable_source,
                             text_semantics.source_outline,
                             text_semantics.uncertain_outline,
                             ownership.logo, ownership.signature),
            protected_regions=(*logos, *signatures),
        )
    from app.geometry.text_residual_retirement import propose_verified_row_retirement

    retirement_protection = (
        ownership.line, ownership.logo, ownership.signature, ownership.ambiguous,
        graphic_source_mask(prepared.binary, logos),
        signature_source_mask(prepared.binary, signatures),
        *((retained_rules,) if retained_rules is not None else ()),
    )
    retired_source, retirement_records = propose_verified_row_retirement(
        prepared.binary, prepared.gray, texts, row_source_proofs,
        visible=contour_binary < 128,
        protected_source_masks=retirement_protection,
        pdf_geometry=pdf_geometry, clean_digital=prepared.clean_digital,
        threshold=prepared.threshold,
    )
    scanned_title_records = ()
    scanned_title_rules = None
    if enable_ocr and not prepared.clean_digital:
        from app.ocr.scanned_title_rows import refine_scanned_title_rows

        texts, scanned_title_ink, scanned_title_rules, scanned_title_records = refine_scanned_title_rows(
            prepared.gray, prepared.binary, texts, display_row_cells,
            visible=contour_binary < 128, protected_masks=retirement_protection,
            line_mask=ownership.line,
        )
        if scanned_title_records:
            retired_source = np.maximum(retired_source, scanned_title_ink)
    if path_digit_records:
        from app.ocr.pdf_path_digits import mark_pdf_digit_retirement

        mark_pdf_digit_retirement(retired_source, path_digit_records, texts,
                                  contour_binary, retirement_protection)
    callout_records = []
    if callout_sources:
        from app.ocr.pdf_path_callouts import apply_callout_texts

        texts, callout_records = apply_callout_texts(
            texts, callout_sources, retired_source, contour_binary, retirement_protection,
            rasterize_lines(straight_lines, prepared.binary.shape),
        )
    if np.any(retired_source):
        # Reuse the formal source-backup partition. Re-trace retained source;
        # never remove a shared DXF PATH or invent a replacement structural line.
        text_semantics = route_native_group_text_backups(
            text_semantics, retired_source, prepared.binary, semantic_texts
        )
        contour_binary = np.where(retired_source > 0, 255, contour_binary).astype(np.uint8)
    if scanned_title_records:
        fixed_rule = scanned_title_rules > 0
        recovered_rule = fixed_rule & (ownership.line == 0)
        # The vector rule's ownership band can cover a contact even when the
        # emitted stroke misses it. Keep the observed rail at those joints.
        for record in scanned_title_records:
            for y, x0, x1 in record.get("contact_rule_runs", ()):
                recovered_rule[y, x0:x1] = True
        contour_binary[recovered_rule] = prepared.binary[recovered_rule]
        retained_rules = scanned_title_rules if retained_rules is None else cv2.max(
            retained_rules, scanned_title_rules
        )
        text_semantics = replace(
            text_semantics,
            **{name: np.where(fixed_rule, 0, getattr(text_semantics, name)).astype(np.uint8)
               for name in ("editable_source", "source_outline", "uncertain_outline")},
        )
    if recover_native_omissions:
        from app.ocr.pdf_native_text import collect_native_text

        # Keep the ordinary OCR, line and callout commits. Only back up ink
        # that disappears when the proved native text object is deactivated.
        native_text_plan = collect_native_text(
            native_original_gray, pdf_geometry, (*original_ocr_texts, *texts),
            mode=source_mode,
            protected_masks=(
                graphic_source_mask(prepared.binary, logos),
                signature_source_mask(prepared.binary, signatures),
            ),
            protected_retirement_masks=(
                *retirement_protection,
                rasterize_lines(straight_lines, prepared.binary.shape),
                text_semantics.source_outline,
                text_semantics.uncertain_outline,
            ),
        )
        contour_binary[native_text_plan.retired > 0] = 255
    if native_text_plan is not None and native_text_plan.texts:
        texts = (*texts, *native_text_plan.texts)
        text_semantics = replace(
            text_semantics,
            editable_source=np.maximum(text_semantics.editable_source, native_text_plan.retired),
            source_outline=np.maximum(text_semantics.source_outline, native_text_plan.retired),
        )
    filled_marks = ()
    if not prepared.clean_digital:
        from app.geometry.source_filled_marks import retain_filled_source_marks

        protected = (
            (text_semantics.editable_source > 0)
            | (text_semantics.source_outline > 0)
            | (text_semantics.uncertain_outline > 0)
            | (graphic_source_mask(prepared.binary, logos) > 0)
            | (signature_source_mask(prepared.binary, signatures) > 0)
        )
        contour_binary, filled_marks = retain_filled_source_marks(
            prepared.gray, prepared.binary, contour_binary,
            dpi=float(source_dpi or DEFAULT_CONNECTION_DPI), protected=protected,
        )
    frame_review = None
    if boxed_label_records and not prepared.clean_digital:
        from app.geometry.observed_label_frames import recover_observed_label_frames

        contour_binary, frame_paths, frame_records, frame_review = recover_observed_label_frames(
            prepared.gray, prepared.binary, contour_binary, boxed_label_records,
            protected_masks=(ownership.line, ownership.logo, ownership.signature,
                text_semantics.editable_source, text_semantics.source_outline,
                text_semantics.uncertain_outline,
                graphic_source_mask(prepared.binary, logos),
                signature_source_mask(prepared.binary, signatures)),
            dpi=float(source_dpi or DEFAULT_CONNECTION_DPI),
            stroke_profile="librecad_paper_pen",
        )
        enclosure_paths = (*enclosure_paths, *frame_paths)
        enclosure_records = (*enclosure_records, *frame_records)
    open_stroke_review = None
    if not prepared.clean_digital and scan_symbol_source:
        from app.geometry.observed_open_strokes import recover_observed_open_strokes

        contour_binary, open_paths, open_records, open_stroke_review = recover_observed_open_strokes(
            prepared.gray, prepared.binary, contour_binary,
            protected_masks=(ownership.line, ownership.logo, ownership.signature,
                text_semantics.editable_source, text_semantics.source_outline,
                text_semantics.uncertain_outline,
                graphic_source_mask(prepared.binary, logos),
                signature_source_mask(prepared.binary, signatures)),
            dpi=float(source_dpi or DEFAULT_CONNECTION_DPI),
        )
        enclosure_paths = (*enclosure_paths, *open_paths)
        enclosure_records = (*enclosure_records, *open_records)
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
    enclosure_indices = iter(range(len(paths), len(paths) + len(enclosure_paths)))
    enclosure_records = tuple(
        dict(record, contour_index=next(enclosure_indices))
        if record.get("ring_replaced", True) else record
        for record in enclosure_records
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
        "scan_classification": {
            "pdf_page_content": pdf_content,
            "reason": prepared.classification_reason,
        },
        "source_stroke_reconciliation": {
            "schema_version": "source-visible-reconciliation-v1",
            "ledger_digest": reconciliation_result.ledger_digest,
            "final_set_digest": reconciliation_result.final_set_digest,
        },
    }
    if prepared.unconfirmed_noise_runs:
        final_provenance["scan_classification"]["unconfirmed_noise_runs_y_x0_x1"] = (
            prepared.unconfirmed_noise_runs
        )
    if prepared.removed_noise_runs:
        final_provenance["scan_classification"]["removed_noise_runs_y_x0_x1"] = (
            prepared.removed_noise_runs
        )
    if source_crop is not None:
        final_provenance["scan_classification"]["source_crop"] = source_crop
    if original_scan_features is not None:
        final_provenance["scan_classification"]["original_scan_features"] = original_scan_features
    if unreviewed_dust is not None:
        from app.geometry.scan_dust import review_dust_candidates

        symbol_ink = cv2.max(
            graphic_source_mask(prepared.binary, logos),
            signature_source_mask(prepared.binary, signatures),
        )
        for record in enclosure_records:
            x, y, w, h = record["bbox"]
            cv2.rectangle(symbol_ink, (x, y), (x + w - 1, y + h - 1), 255, -1)
        for record in filled_marks:
            for polygon in record["fill_paths_px"]:
                cv2.fillPoly(symbol_ink, [np.rint(polygon).astype(np.int32)], 255)
        text_ink = cv2.max(
            ownership.text,
            cv2.max(text_semantics.editable_source, text_semantics.uncertain_outline),
        )
        review = review_dust_candidates(
            unreviewed_dust,
            text_ink=text_ink,
            texts=(*source_candidates, *texts),
            symbol_ink=symbol_ink,
            lines=(*line_candidates, *straight_lines),
            dpi=float(source_dpi or DEFAULT_CONNECTION_DPI),
        )
        final_provenance["scan_classification"]["dust_candidate_review"] = review
    if raster_signing is not None:
        final_provenance["raster_signing"] = raster_signing
    if retirement_records:
        final_provenance["text_residual_retirement"] = retirement_records
    if scanned_title_records:
        final_provenance["scanned_title_rows"] = scanned_title_records
    if scanned_glyph_records:
        final_provenance["scanned_glyph_review"] = scanned_glyph_records
    if frame_review is not None:
        final_provenance["observed_frame_recovery"] = frame_review
    if open_stroke_review is not None:
        final_provenance["observed_open_stroke_recovery"] = open_stroke_review
    if boxed_label_records:
        final_provenance["boxed_label_source_members"] = {
            "version": "observed-boxed-label-members-v1", "decisions": boxed_label_records,
            "text_content_changed": False, "source_deletion_authority": "existing_verified_source_contract",
        }
    if native_source_row_records:
        final_provenance["native_source_row_v1"] = native_source_row_records
    if path_digit_records:
        final_provenance["pdf_path_digit_review"] = path_digit_records
    if callout_records:
        final_provenance["pdf_path_callout_review"] = callout_records
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
        excluded_indices=tuple(r["contour_index"] for r in enclosure_records if "contour_index" in r),
    )
    if filled_marks:
        presentation["local_filled_marks"] = filled_marks
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
    # Display itself still grants no source authority. Only separately proved
    # exact source members above can retire. ARC guards keep original footprints.
    if row_display:
        final_provenance["ruled_cell_row_display"] = row_display
    if glyph_display:
        final_provenance["single_glyph_display"] = glyph_display
    if native_text_plan is not None:
        from app.ocr.pdf_native_text import VERSION as native_text_version

        final_provenance["pdf_native_text"] = dict(
            policy=native_text_version, mode=source_mode,
            records=native_text_plan.records,
            suppressed_ocr_indices=native_text_plan.suppressed_ocr,
            original_ocr_superseded=original_ocr_superseded,
            raster_source_canvas=(
                "ORIGINAL_WITH_EXCLUSIVE_NATIVE_TEXT_INK_BACKED_UP"
                if recover_native_omissions
                else "ACTUAL_PDF_RENDER_WITH_ADOPTED_NATIVE_TEXT_INACTIVE"
            ),
            fallback_reading="ORIGINAL_UNAFFECTED_AND_RETAINED_MIXED_REMAINDER",
            source_binding=dict(pdf_geometry.binding) if pdf_geometry is not None else None,
        )
    if signatures and protected_pdf:
        protected_masks = (
            ownership.line, retained_rules, ownership.logo,
            text_semantics.editable_source, text_semantics.source_outline,
            text_semantics.uncertain_outline,
        )
        # Only field-derived regions have exclusive ink assignment. Leave
        # provisional shape detections at their original opacity.
        signatures = tuple(
            restore_signature_edge_gray(
                region, prepared.gray, contour_binary=contour_binary,
                protected_masks=protected_masks,
            ) if region.visual_evidence is None else region
            for region in signatures
        )
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
