from __future__ import annotations
import numpy as np
from app.core.trace_types import TracePath
from app.geometry.raster_trace import trace_binary
from app.export.ocr_outline_export import accepted_ocr_texts, add_ocr_outline_blocks
from app.ocr.signature_overlay import add_signature_images, set_foreground_draw_order
from app.ocr.text_output_contract import (
    TextOutputState,
    suppressible_ocr_texts,
    text_output_decisions,
    text_output_summary,
)
from app.export.trace_dxf_entities import (
    TRACE_LAYER_STYLES,
    TracePalette,
    add_exact_trace_entities,
    add_straight_line_entities,
)
from app.export.trace_dxf_entities import add_arc_entities


def semantic_paths(mask: np.ndarray | None) -> tuple[TracePath, ...]:
    """Serialize a committed semantic mask as contours; never reconcile lines."""
    if mask is None or not np.any(mask > 0):
        return ()
    return tuple(trace_binary(np.where(mask > 0, 0, 255).astype(np.uint8)))


def write_page_entities(
    doc,
    modelspace,
    *,
    trace_paths,
    straight_lines,
    texts,
    signatures,
    transform,
    output_path,
    source_size,
    arcs=(),
    native_fills=(),
    logos=(),
    enclosure_records=(),
    stroke_presentation=None,
    text_rule_contours=(),
    source_text_outline_paths=(),
    uncertain_text_outline_paths=(),
    semantic_outlines_prepartitioned=False,
    resolved_output=None,
    trace_color=7,
    palette=None,
    layer_names=None,
    block_prefix="OCR_LINE",
    signature_prefix="SIGNATURE",
    text_review=None,
    text_consistency=None,
    line_source_refs=None,
    contour_source_refs=None,
    contour_consistency=None,
    cancellation_token=None,
    progress_callback=None,
):
    """The shared DXF entity serializer. Coordinates/identities are read-only."""
    names = layer_names or {name: name for name in TRACE_LAYER_STYLES}
    coordinates = []
    from app.export.native_fill_entities import add_native_fill_entities

    coordinates.extend(
        add_native_fill_entities(doc, modelspace, native_fills, transform, names)
    )
    _, _, arc_bounds = add_arc_entities(
        modelspace,
        arcs,
        transform=transform,
        layer_names=names,
        color=(palette or TracePalette()).curve,
    )
    coordinates.extend(arc_bounds)
    line_records = (
        list(stroke_presentation.get("line_records", ())) if stroke_presentation else []
    )
    if line_records and len(line_records) != len(straight_lines):
        raise ValueError("Stroke presentation must bind every source line index")
    if line_source_refs is not None and len(line_source_refs) != len(straight_lines):
        raise ValueError("LINE source refs must bind every source line index")
    if resolved_output is not None:
        contour_members = {
            item.index: item
            for item in resolved_output.members
            if item.collection == "contours"
        }
        allowed_line_indices = set(resolved_output.emitted_indices("straight_lines"))
        if line_source_refs is not None:
            line_source_refs = tuple(
                r for i, r in enumerate(line_source_refs) if i in allowed_line_indices
            )
        allowed_text_indices = set(resolved_output.emitted_indices("texts"))
        straight_lines = tuple(
            item
            for index, item in enumerate(straight_lines)
            if index in allowed_line_indices
        )
        texts = tuple(
            item for index, item in enumerate(texts) if index in allowed_text_indices
        )
        allowed_signature_indices = set(resolved_output.emitted_indices("signatures"))
        signatures = tuple(
            item
            for index, item in enumerate(signatures)
            if index in allowed_signature_indices
        )
        line_records = [
            r for i, r in enumerate(line_records) if i in allowed_line_indices
        ]
        allowed_logos = set(resolved_output.emitted_indices("logos"))
        logos = tuple(
            item for index, item in enumerate(logos) if index in allowed_logos
        )
    else:
        contour_members = None
    text_decisions = text_output_decisions(texts)
    text_summary = text_output_summary(texts)
    exportable_texts = accepted_ocr_texts(texts)
    if text_consistency is not None:
        text_consistency.expect_page(
            exportable_texts,
            names["OCR_TEXT"],
            transform=transform,
            doc=doc,
            review=text_review,
        )
    suppressible_texts = suppressible_ocr_texts(texts)
    source_outline_texts = tuple(
        decision.candidate
        for decision in text_decisions
        if (decision.text_emit_eligible and not decision.source_outline_suppressible)
    )
    fallback_texts = tuple(
        decision.candidate
        for decision in text_decisions
        if decision.state is TextOutputState.TEXT_FALLBACK_OUTLINE
    )
    residual_texts = tuple(
        decision.candidate
        for decision in text_decisions
        if decision.state is TextOutputState.RESIDUAL_GRAPHIC
    )
    selected_palette = palette or TracePalette()
    if int(trace_color) != 7:
        selected_palette = TracePalette(
            int(trace_color),
            int(trace_color),
            int(trace_color),
        )
    line_count, _line_entities, line_bounds = add_straight_line_entities(
        modelspace,
        straight_lines,
        transform=transform,
        layer_name=names["TRACE_STRAIGHT"],
        color=selected_palette.straight,
        line_records=line_records,
        line_source_refs=line_source_refs,
    )
    if any(line_records):
        doc.header["$LWDISPLAY"] = True
    coordinates.extend(line_bounds)
    contour_expectations = []
    trace_path_count, trace_vertex_count, _trace_entities, trace_bounds = (
        add_exact_trace_entities(
            modelspace,
            trace_paths,
            transform=transform,
            color=trace_color,
            source_size=source_size,
            palette=palette,
            # Source masks already removed the owned glyphs. Reapplying a
            # text-box test can suppress nearby independent rule contours.
            ocr_texts=(() if semantic_outlines_prepartitioned else suppressible_texts),
            text_rule_contours=text_rule_contours,
            source_outline_ocr_texts=(
                () if semantic_outlines_prepartitioned else source_outline_texts
            ),
            fallback_ocr_texts=(
                () if semantic_outlines_prepartitioned else fallback_texts
            ),
            residual_ocr_texts=residual_texts,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
            layer_names=names,
            bound_members=contour_members,
            excluded_indices=tuple(int(r["contour_index"]) for r in enclosure_records),
            fill_records=stroke_presentation.get("fill_records", {})
            if stroke_presentation
            else {},
            closed_curve_records=stroke_presentation.get(
                "closed_scan_curve_records", ()
            )
            if stroke_presentation
            else (),
            contour_source_refs=contour_source_refs,
            contour_source_expectations=contour_expectations,
        )
    )
    if contour_source_refs:
        if len(contour_expectations) != len(contour_source_refs):
            raise ValueError(
                "Source-bound contour was suppressed or emitted as another entity type"
            )
        contour_consistency.capture(doc, contour_expectations)
    coordinates.extend(trace_bounds)
    for record in enclosure_records:
        index = int(record["contour_index"])
        if contour_members is not None and index not in resolved_output.emitted_indices(
            "contours"
        ):
            continue
        points = [transform(x, y) for x, y in trace_paths[index].points]
        attributes = {"layer": names["ENGINEERING_SYMBOL"]}
        if record["kind"] == "circle":
            center = np.mean(points, axis=0)
            radii = np.linalg.norm(np.asarray(points) - center, axis=1)
            # An anisotropic page transform requires an ellipse-equivalent
            # polyline; uniform page calibration emits a true native CIRCLE.
            if np.ptp(radii) < max(1e-8, np.mean(radii) * 1e-6):
                modelspace.add_circle(
                    tuple(center), float(np.mean(radii)), dxfattribs=attributes
                )
            else:
                modelspace.add_lwpolyline(points, close=True, dxfattribs=attributes)
        else:
            modelspace.add_lwpolyline(points, close=True, dxfattribs=attributes)
        coordinates.extend(points)
        trace_path_count += 1
        trace_vertex_count += len(points)
    (
        source_path_count,
        source_vertex_count,
        _source_entities,
        source_bounds,
    ) = add_exact_trace_entities(
        modelspace,
        source_text_outline_paths,
        transform=transform,
        color=trace_color,
        source_size=source_size,
        palette=palette,
        forced_layer_name="SOURCE_TEXT_OUTLINE",
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
        layer_names=names,
    )
    coordinates.extend(source_bounds)
    (
        uncertain_path_count,
        uncertain_vertex_count,
        _uncertain_entities,
        uncertain_bounds,
    ) = add_exact_trace_entities(
        modelspace,
        uncertain_text_outline_paths,
        transform=transform,
        color=trace_color,
        source_size=source_size,
        palette=palette,
        forced_layer_name="TEXT_FALLBACK_OUTLINE",
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
        layer_names=names,
    )
    coordinates.extend(uncertain_bounds)
    trace_path_count += source_path_count + uncertain_path_count
    trace_vertex_count += source_vertex_count + uncertain_vertex_count
    text_count, text_entities, text_bounds = add_ocr_outline_blocks(
        doc,
        modelspace,
        exportable_texts,
        transform=transform,
        layer_name=names["OCR_TEXT"],
        block_prefix=block_prefix,
        text_review=text_review,
    )
    coordinates.extend(text_bounds)
    if text_review is not None:
        from app.core.manual_text_recovery import emit as emit_manual_text

        manual_entities, manual_bounds = emit_manual_text(
            text_review, doc, modelspace, transform, names, text_consistency
        )
        text_entities.extend(manual_entities)
        text_count += len(manual_entities)
        coordinates.extend(manual_bounds)
    signature_paths, signature_entities, signature_bounds = add_signature_images(
        doc,
        modelspace,
        signatures,
        transform=transform,
        output_path=output_path,
        layer_name=names["SIGNATURE_OVERLAY"],
        name_prefix=signature_prefix,
    )
    coordinates.extend(signature_bounds)
    graphic_paths, graphic_entities, graphic_bounds = add_signature_images(
        doc,
        modelspace,
        logos,
        transform=transform,
        output_path=output_path,
        layer_name=names["LOGO_GRAPHIC"],
        name_prefix=signature_prefix + "_LOGO",
        asset_kind="logo",
    )
    coordinates.extend(graphic_bounds)
    set_foreground_draw_order(
        modelspace,
        [*text_entities, *signature_entities, *graphic_entities],
    )
    return (
        line_count,
        trace_path_count,
        trace_vertex_count,
        text_count,
        signature_paths,
        coordinates,
        text_summary,
        len(signature_entities),
        graphic_paths,
    )
