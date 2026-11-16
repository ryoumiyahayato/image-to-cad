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
    add_source_filled_marks,
    add_straight_line_entities,
)
from app.export.trace_dxf_entities import add_arc_entities
from app.export.engineering_symbol_entities import bind_symbol_member


def semantic_paths(mask: np.ndarray | None) -> tuple[TracePath, ...]:
    """Serialize a committed semantic mask as contours; never reconcile lines."""
    if mask is None or not np.any(mask > 0):
        return ()
    return tuple(trace_binary(np.where(mask > 0, 0, 255).astype(np.uint8)))


def _is_source_region_record(record):
    version = record.get("version")
    return (
        "native_source_region_partition" in record
        or record.get("kind") == "explicit_native_source_region"
        or (isinstance(version, str) and version.startswith("explicit-native-source-region-"))
    )


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
    center_transform=None,
    arcs=(),
    native_fills=(),
    native_paths=(),
    protected_graphics_mode="legacy",
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
    source_structure=None,
    cancellation_token=None,
    progress_callback=None,
):
    """The shared DXF entity serializer. Coordinates/identities are read-only."""
    names = layer_names or {name: name for name in TRACE_LAYER_STYLES}
    center_transform = center_transform or transform
    # This preflight must precede both contour suppression and any DXF mutation.
    # An explicit source selection is an atomic replacement, never a best-effort
    # partial record that can fall through to another enclosure serializer.
    region_plans = {}
    region_records = [record for record in enclosure_records if _is_source_region_record(record)]
    if region_records:
        from app.export.source_region_entities import (
            preflight_source_region, preflight_source_region_document,
        )

        if len(region_records) != 1:
            raise ValueError("Source region trial supports exactly one explicit selection per page")
        if contour_source_refs or (
            source_structure is not None
            and source_structure.provenance.get("draftsman_output_v1") is not None
        ):
            raise ValueError("Source region selection cannot rewrite frozen contour bindings")
        for record in region_records:
            index = record.get("contour_index")
            if type(index) is not int or not 0 <= index < len(trace_paths):
                raise ValueError("Source region requires a valid contour index")
            if sum(other.get("contour_index") == index for other in enclosure_records) != 1:
                raise ValueError("Source region contour index conflicts with another enclosure")
            if resolved_output is not None and index not in resolved_output.emitted_indices("contours"):
                raise ValueError("Source region replacement cannot be partially suppressed")
            region_plans[index] = preflight_source_region(record, edge_transform=transform)
        preflight_source_region_document(doc, tuple(region_plans.values()))
    coordinates = []
    from app.export.native_pdf_path_entities import add_native_path_entities
    coordinates.extend(add_native_path_entities(doc, modelspace, native_paths, transform))
    from app.export.native_fill_entities import add_native_fill_entities

    coordinates.extend(
        add_native_fill_entities(doc, modelspace, native_fills, transform, names)
    )
    coordinates.extend(add_source_filled_marks(
        modelspace, (stroke_presentation or {}).get("local_filled_marks", ()),
        transform=transform, layer=names["ENGINEERING_SYMBOL"],
    ))
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
    # Native signature ink precedes structure in the actual entity stream too;
    # readers that ignore SORTENTSTABLE must not paint over cell rules.
    provenance = source_structure.provenance if source_structure is not None else {}
    signing = provenance.get("raster_signing", {})
    signing_boxes = tuple(tuple(box) for box in signing.get("signature_boxes", ()))
    fixed_boxes = signing.get("fixed_member_boxes")
    if fixed_boxes is None and signing and any(r.visual_kind == "shared_signing_ink" for r in logos):
        # Older structures have shared paint but no per-object completeness record.
        fixed_boxes = (*signing_boxes, *(r.bbox for r in logos if r.visual_kind == "stamp"))
    fixed_boxes = tuple(tuple(box) for box in (fixed_boxes or ()))
    fixed_layer = names["SIGNING_SHARED_INK"]
    source_origin = tuple(provenance.get("scan_classification", {}).get("source_crop", (0, 0)))[:2]
    signature_paths, signature_entities, signature_bounds = add_signature_images(
        doc, modelspace, signatures, transform=transform, output_path=output_path,
        layer_name=names["SIGNATURE_OVERLAY"], name_prefix=signature_prefix,
        presentation=protected_graphics_mode,
        signing_boxes=signing_boxes,
        source_origin=source_origin,
        fixed_member_boxes=fixed_boxes, fixed_layer_name=fixed_layer,
    )
    coordinates.extend(signature_bounds)
    independent_signatures = sum(e.dxf.layer != fixed_layer for e in signature_entities)
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
        transform=center_transform,
        pixel_edge_transform=transform,
        layer_name=names["TRACE_STRAIGHT"],
        color=selected_palette.straight,
        line_records=line_records,
        line_source_refs=line_source_refs,
    )
    if any(line_records):
        doc.header["$LWDISPLAY"] = True
    for entity, record in zip(_line_entities, line_records):
        aliases = (record or {}).get("pdf_path_aliases", ())
        if aliases:
            for appid in ("PDF_PATH_SOURCE", "PDF_PATH_ALIASES"):
                if appid not in doc.appids:
                    doc.appids.new(appid)
            ref = aliases[0]
            entity.set_xdata("PDF_PATH_SOURCE", [(1000,ref["id"]),(1000,"stroke"),
                (1071,ref["object_index"]),(1071,ref["subpath"]),(1071,ref["edge"]),
                (1071,ref["edge"])])
            entity.set_xdata("PDF_PATH_ALIASES", [tag for a in aliases for tag in (
                (1000,a["id"]),(1000,a["role"]),(1071,a["object_index"]),
                (1071,a["subpath"]),(1071,a["edge"]))])
    coordinates.extend(line_bounds)
    contour_expectations = []
    trace_path_count, trace_vertex_count, _trace_entities, trace_bounds = (
        add_exact_trace_entities(
            modelspace,
            trace_paths,
            transform=center_transform,
            pixel_edge_transform=transform,
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
            excluded_indices=tuple(int(r["contour_index"]) for r in enclosure_records if "contour_index" in r),
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
    native_scan_symbols = []
    for record in enclosure_records:
        index = record.get("contour_index")
        if _is_source_region_record(record):
            from app.export.source_region_entities import emit_source_region_plan

            member, residual, _backup, bounds = emit_source_region_plan(
                doc, modelspace, region_plans[index],
            )
            coordinates.extend(bounds)
            trace_path_count += 2
            trace_vertex_count += sum(
                len(boundary.vertices)
                for entity in (member, residual)
                for boundary in entity.paths
            )
            continue
        if index is not None and contour_members is not None and int(index) not in resolved_output.emitted_indices(
            "contours"
        ):
            continue
        attributes = {"layer": names["ENGINEERING_SYMBOL"]}
        if record.get("native_source_compound_strokes"):
            from app.export.compound_stroke_entities import add_compound_stroke_entities

            native, _residual, bounds = add_compound_stroke_entities(
                doc, modelspace, record, center_transform=center_transform,
            )
            coordinates.extend(bounds)
            for entity in native:
                if entity.dxftype() == "LINE":
                    line_count += 1
                else:
                    trace_path_count += 1
                    trace_vertex_count += len(entity)
            continue
        if record.get("native_source_open_stroke"):
            from app.export.observed_open_stroke_entities import add_observed_open_stroke

            entity, bounds = add_observed_open_stroke(doc, modelspace, record,
                                                     center_transform=center_transform)
            coordinates.extend(bounds)
            if entity.dxftype() == "LINE":
                line_count += 1
            else:
                trace_path_count += 1
                trace_vertex_count += len(entity)
            continue
        if record.get("native_source_frame"):
            from app.export.observed_frame_entities import add_observed_frame

            entity, bounds = add_observed_frame(doc, modelspace, record,
                center_transform=center_transform, layer=names["ENGINEERING_SYMBOL"])
            coordinates.extend(bounds)
            trace_path_count += 1
            trace_vertex_count += len(entity)
            continue
        if record.get("native_scan"):
            if "glyph_box" in record:
                native_scan_symbols.append(record)
            for branch in record["branches"]:
                start = center_transform(*branch["start_px"])
                end = center_transform(*branch["end_px"])
                entity = modelspace.add_line(start, end, dxfattribs=attributes)
                bind_symbol_member(entity, record, "BRANCH", branch["width_px"])
                coordinates.extend((start, end))
                line_count += 1
        if index is None:
            continue
        points = [center_transform(x, y) for x, y in trace_paths[int(index)].points]
        if record["kind"] == "circle":
            center = np.mean(points, axis=0)
            radii = np.linalg.norm(np.asarray(points) - center, axis=1)
            # An anisotropic page transform requires an ellipse-equivalent
            # polyline; uniform page calibration emits a true native CIRCLE.
            if np.ptp(radii) < max(1e-8, np.mean(radii) * 1e-6):
                circle = modelspace.add_circle(
                    tuple(center), float(np.mean(radii)), dxfattribs=attributes
                )
            else:
                circle = modelspace.add_lwpolyline(points, close=True, dxfattribs=attributes)
            if record.get("native_scan"):
                bind_symbol_member(circle, record, "RING", record["width_px"])
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
        transform=center_transform,
        pixel_edge_transform=transform,
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
        transform=center_transform,
        pixel_edge_transform=transform,
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
    if native_scan_symbols:
        exported = accepted_ocr_texts(exportable_texts)
        symbol_glyphs = {(r["glyph_box"], r["glyph_text"]): r for r in native_scan_symbols}
        for candidate, entity in zip(exported, text_entities, strict=True):
            record = symbol_glyphs.get((candidate.bbox, candidate.text))
            if record is not None:
                bind_symbol_member(entity, record, "GLYPH", record["glyph_width_px"])
    coordinates.extend(text_bounds)
    if text_review is not None:
        from app.core.manual_text_recovery import emit as emit_manual_text

        manual_entities, manual_bounds = emit_manual_text(
            text_review, doc, modelspace, transform, names, text_consistency,
            source_transform=center_transform,
        )
        text_entities.extend(manual_entities)
        text_count += len(manual_entities)
        coordinates.extend(manual_bounds)
    engineering = tuple(r for r in logos if r.visual_kind == "engineering_graphic")
    signing_objects = {
        kind: tuple(r for r in logos if r.visual_kind == kind)
        for kind in ("stamp", "shared_signing_ink")
    }
    logos = tuple(r for r in logos if r.visual_kind != "engineering_graphic"
                  and r.visual_kind not in signing_objects)
    graphic_paths, graphic_entities, graphic_bounds = add_signature_images(
        doc,
        modelspace,
        logos,
        transform=transform,
        output_path=output_path,
        layer_name=names["LOGO_GRAPHIC"],
        name_prefix=signature_prefix + "_LOGO",
        asset_kind="logo",
        presentation=protected_graphics_mode,
    )
    coordinates.extend(graphic_bounds)
    from app.ocr.engineering_symbols import observed_graphic_attachments

    presentations = tuple(observed_graphic_attachments(r, source_structure) for r in engineering)
    from app.export.engineering_residual_images import has_native_recovery, residual_image_tiles

    engineering_parts = []
    engineering_bindings = []
    for original, (presentation, attachments) in zip(engineering, presentations, strict=True):
        eligible = has_native_recovery(original.bbox, enclosure_records)
        for part in residual_image_tiles(presentation, eligible=eligible):
            engineering_parts.append(part)
            engineering_bindings.append((original, attachments, part, eligible))
    engineering_paths, engineering_entities, engineering_bounds = add_signature_images(
        doc, modelspace, tuple(engineering_parts),
        transform=transform, output_path=output_path,
        layer_name=names["ENGINEERING_SYMBOL"],
        name_prefix=signature_prefix + "_ENGINEERING",
        asset_kind="engineering",
    )
    if engineering_entities and source_structure is not None:
        appid = "ENGINEERING_GRAPHIC_SOURCE"
        if appid not in doc.appids:
            doc.appids.add(appid)
        for entity, (original, attachments, part, eligible) in zip(
            engineering_entities, engineering_bindings, strict=True
        ):
            tile_tags = ([(1000, "RESIDUAL_ALPHA_TILE_V1" if np.all(part.mask > 0)
                          else "RESIDUAL_ALPHA_TILE_BUDGET_FALLBACK"),
                          (1000, ",".join(map(str, part.bbox)))] if eligible else [])
            entity.set_xdata(appid, [
                (1000, "OBSERVED_SOURCE_INK"),
                (1000, "ELECTRICAL_CONNECTIVITY_UNRESOLVED"),
                (1000, ",".join(map(str, original.bbox))),
                *((1000, ",".join(map(str, record))) for record in attachments),
                *tile_tags,
            ])
    coordinates.extend(engineering_bounds)
    signing_paths, signing_entities = [], []
    shared_entities = []
    for kind, layer, asset in (("stamp", "STAMP_OVERLAY", "stamp"),
                               ("shared_signing_ink", "SIGNING_SHARED_INK", "signing-shared")):
        caption = signing.get("shared_caption")
        paths, entities, bounds = add_signature_images(
            doc, modelspace, signing_objects[kind], transform=transform,
            output_path=output_path, layer_name=names[layer],
            name_prefix=signature_prefix+"_"+layer, asset_kind=asset,
            presentation="adaptive-source-image", source_origin=source_origin,
            shared_caption=caption if kind == "shared_signing_ink" else None,
            fixed_member_boxes=fixed_boxes if kind == "stamp" else (),
            fixed_layer_name=fixed_layer,
        )
        signing_paths.extend(paths)
        signing_entities.extend(entities)
        if kind == "shared_signing_ink":
            shared_entities.extend(entities)
        coordinates.extend(bounds)
    if shared_entities:
        from app.export.source_component import attach_fixed_signing_fragments

        fragments = [e for e in (*signature_entities, *signing_entities)
                     if e.dxf.layer == fixed_layer and e not in shared_entities]
        if fragments:
            signature_entities = [e for e in signature_entities if e not in fragments]
            signing_entities = [e for e in signing_entities if e not in fragments]
            attach_fixed_signing_fragments(doc, modelspace, shared_entities[0], fragments)
    set_foreground_draw_order(
        modelspace,
        [*text_entities, *signature_entities, *graphic_entities, *engineering_entities,
         *signing_entities],
    )
    return (
        line_count,
        trace_path_count,
        trace_vertex_count,
        text_count,
        signature_paths,
        coordinates,
        text_summary,
        independent_signatures,
        (*graphic_paths, *engineering_paths, *signing_paths),
    )
