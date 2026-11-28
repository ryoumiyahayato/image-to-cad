"""Ordinary scan conversion: cleanup, finite geometry, text and source graphics."""
from __future__ import annotations

from collections import Counter
from math import atan2, degrees, isfinite
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from PIL import Image, ImageOps
from ezdxf.tools.text_size import text_size

from app.core.cancellation import checkpoint, report_progress, ProcessingCancelled
from app.core.perspective import auto_correct, warp_perspective
from app.core.scan_drafting import (
    REPAIR_LAYER, resolve_page, save_drafting_evidence, save_repair_evidence,
    save_text_repair_evidence, suggest_repairs,
)
from app.core.scan_quality import measure_saved_scan, source_reference
from app.core.scan_residuals import save_geometry_residuals, scan_residual_path
from app.export.product_fonts import install_text_style, text_width_factor
from app.geometry.scan_cell_layout import place_cell_text
from app.geometry.scan_cleanup import paper_ink_alpha, prepare_scan_page
from app.geometry.scan_geometry import extract_scan_geometry
from app.geometry.scan_ownership import emblem_ink, glyph_ink, protected_ink
from app.ocr.line_recognition import recognize_lines, reread_source_lines


def _load(source, page_index):
    with Image.open(source) as original:
        original.seek(page_index)
        upright = ImageOps.exif_transpose(original)
        if upright.mode in ("RGBA", "LA") or "transparency" in upright.info:
            rgba = upright.convert("RGBA")
            upright = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
        rgb = np.asarray(upright.convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _ocr_view(image, binary, protected, dpi):
    """Remove long table rules from the recognition view, preserving glyph crossings."""
    ink = cv2.bitwise_not(binary)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    boxes = stats[1:]
    heights = boxes[(boxes[:, 4] > 4) & (boxes[:, 2] < 3*boxes[:, 3])
                    & (boxes[:, 3] < 4*boxes[:, 2]), 3]
    # On a sparse page the only text may already be attached to the ruling.
    # Use paper text height as a fallback so a tall digit stem survives.
    height = np.quantile(heights, 0.75) if heights.size else 2.5 * dpi / 25.4
    span = max(31, round(2.5 * height)) | 1
    rules = np.zeros_like(ink)
    for size in ((span, 1), (1, span)):
        rules |= cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, size))
    view = image.copy()
    view[protected > 0] = 255
    if rules.any():
        view = cv2.inpaint(view, rules, 2, cv2.INPAINT_TELEA)
        view[protected > 0] = 255
    return view


def _add_source_image(doc, msp, image, mask, output, suffix, layer, scale):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    x0, x1 = int(xs.min()), int(xs.max())+1
    y0, y1 = int(ys.min()), int(ys.max())+1
    gray = cv2.cvtColor(image[y0:y1,x0:x1], cv2.COLOR_BGR2GRAY)
    opacity = (paper_ink_alpha(image, (x0,y0,x1,y1))
               if layer == "PROTECTED_GRAPHICS" else 255-gray)
    alpha = np.where(mask[y0:y1,x0:x1] > 0, opacity, 0).astype(np.uint8)
    rgba = np.zeros((y1-y0,x1-x0,4), np.uint8)
    if layer == "PROTECTED_GRAPHICS":
        rgb = image[y0:y1, x0:x1, ::-1]
        colored = (np.ptp(rgb, axis=2) > 12) & (mask[y0:y1,x0:x1] > 0)
        # Unmix coloured ink from white paper so antialiased edges stay transparent.
        pigment = 255 - rgb.min(axis=2)
        alpha[colored] = pigment[colored]
        rgba[colored, :3] = np.rint(255 - (255-rgb[colored]).astype(float) * 255
                                    / np.maximum(1, pigment[colored, None])).clip(0, 255)
    if not alpha.any():
        return None
    rgba[:,:,3] = alpha
    folder = output.parent / (output.stem + "_assets")
    folder.mkdir(parents=True, exist_ok=True)
    asset = folder / (suffix + ".png")
    Image.fromarray(rgba).save(asset)
    definition = doc.add_image_def(asset.relative_to(output.parent).as_posix(), (x1-x0,y1-y0))
    msp.add_image(definition, insert=(x0*scale,(image.shape[0]-y1)*scale),
                  size_in_units=((x1-x0)*scale,(y1-y0)*scale),
                  dxfattribs={"layer":layer,"flags":11})
    return str(asset)


def _literal_text(text):
    # Keep OCR punctuation literal when DXF readers decode TEXT control sequences.
    return text.replace("%", r"\U+0025").replace("^", r"\U+005E")


def _add_native_text(modelspace, line, style, point, scale, *, layer):
    q = np.asarray(line.quad)
    height = max(1.0, 0.80 * float(np.linalg.norm(q[3] - q[0]))) * scale
    width = float(np.linalg.norm(q[1] - q[0])) * scale
    baseline = q[3] + 0.12 * (q[0] - q[3])
    rotation = degrees(atan2(-(q[1, 1] - q[0, 1]), q[1, 0] - q[0, 0]))
    entity = modelspace.add_text(_literal_text(line.text), dxfattribs={
        "layer": layer, "style": style["style"], "height": height,
        "width": text_width_factor(line.text, style["font_path"], height, width),
        "insert": point(baseline), "rotation": rotation, "color": 256,
    })
    if not style["font_path"] and width > 0:
        measured = text_size(entity).width
        if measured > 0:
            entity.dxf.width = width / measured
    return entity


def convert_scan(source_path, output_path, *, dpi=300.0, page_index=0, image=None,
                 enable_ocr=True, perspective=False, corners=None,
                 preserve_regions=(), min_text_confidence=0.70, preview_path=None, drawing_scale=1.0,
                 cancellation_token=None, progress_callback=None):
    """Save a single raster page as an ordinary editable R2013 DXF.

    ``image`` is an optional BGR/gray array supplied by the scanned-PDF router.
    ``preserve_regions`` contains source-image (x0,y0,x1,y1) rectangles. All
    paper dimensions and pen widths use ``dpi``. Model coordinates also use
    the supplied paper-to-model ``drawing_scale``.
    """
    if isinstance(dpi, bool) or not isfinite(float(dpi)) or dpi <= 0:
        raise ValueError("DPI must be a positive finite number")
    if not 0 <= min_text_confidence <= 1:
        raise ValueError("Text confidence must be between zero and one")
    output = Path(output_path).resolve()
    source = Path(source_path)
    residual_output = scan_residual_path(output).resolve()
    if residual_output == source.resolve() or (
        preview_path is not None and residual_output == Path(preview_path).resolve()
    ):
        raise ValueError("输入和预览路径不能与扫描几何残差图重名")
    output.parent.mkdir(parents=True, exist_ok=True)
    if image is None:
        image = _load(source, page_index)
    else:
        image = np.asarray(image).copy()
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        alpha = image[:,:,3:4].astype(float)/255
        image = np.uint8(image[:,:,:3]*alpha + 255*(1-alpha))
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8 or not image.size:
        raise ValueError("Scan input must be a nonempty 8-bit image")
    if image.shape[0]*image.shape[1] > 60000000:
        raise ValueError("Scan exceeds 60 megapixels; select a smaller page or lower render DPI")
    warnings = []
    manual = np.zeros(image.shape[:2], np.uint8)
    for region in preserve_regions:
        x0,y0,x1,y1 = map(int, region)
        if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
            raise ValueError("Protected region must be inside the input image")
        manual[y0:y1,x0:x1] = 255
    corrected = False
    if corners is not None:
        image = warp_perspective(image, corners)
        manual = warp_perspective(manual, corners)
        corrected = True
    elif perspective:
        result = auto_correct(image)
        if result is not None and result.confidence >= 0.60:
            image = result.image
            manual = warp_perspective(manual, result.corners)
            corrected = True
            warnings.extend(result.warnings)
        else:
            warnings.append("未找到可靠纸张边界，保留原图范围。")
    checkpoint(cancellation_token)
    report_progress(progress_callback,"cleanup",0.05)
    prepared = prepare_scan_page(image, protected_mask=manual)
    protected = protected_ink(image, prepared.binary, manual)
    lines, ocr_error = [], None
    if enable_ocr:
        try:
            view = _ocr_view(image, prepared.binary, protected, dpi)
            recovery = None
            if not prepared.clean_digital and max(image.shape[:2]) > 2560:
                recovery_ink = cv2.bitwise_not(prepared.binary | protected)
                recovery_image = prepared.normalized.copy()
                recovery_image[protected > 0] = 255
                recovery = recovery_image, recovery_ink
            lines = recognize_lines(view, recovery=recovery, min_text_confidence=min_text_confidence,
                                    cancellation_token=cancellation_token,
                                    progress_callback=progress_callback)
            if lines and max(image.shape[:2]) > 2560:
                original_gray = prepared.gray.copy()
                original_gray[protected > 0] = 255
                lines = reread_source_lines(lines, original_gray, cancellation_token=cancellation_token)
        except ProcessingCancelled:
            raise
        except Exception as exc:
            ocr_error = f"OCR_UNAVAILABLE: {type(exc).__name__}: {exc}"
            warnings.append(ocr_error)
    accepted = [line for line in lines if line.confidence >= min_text_confidence]
    uncertain = [line for line in lines if line.confidence < min_text_confidence]
    source_ink = cv2.bitwise_or(prepared.binary, protected)
    glyphs = glyph_ink(source_ink, lines)
    emblems = emblem_ink(image, prepared.binary, glyphs)
    protected |= emblems
    geometry_input = source_ink | glyphs | emblems
    report_progress(progress_callback,"geometry",0.50)
    candidates, _, geometry_warnings = extract_scan_geometry(
        geometry_input, cancellation_token=cancellation_token)
    warnings.extend(geometry_warnings)
    report_progress(progress_callback,"drafting",0.70)
    geometry, symbols, drafting = resolve_page(candidates, geometry_input, accepted, dpi=dpi,
                                               source_binary=source_ink,
                                               cancellation_token=cancellation_token)
    repairs = suggest_repairs(candidates, prepared.binary, cancellation_token=cancellation_token)
    drafting["repair_suggestions"] = len(repairs) + len(uncertain)
    if drafting["repair_suggestions"]:
        warnings.append(f"{drafting['repair_suggestions']}处补绘建议写入默认关闭的 {REPAIR_LAYER} 图层。")
    doc = ezdxf.new("R2013", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LWDISPLAY"] = True
    doc.set_raster_variables(frame=0, quality=1, units="mm")
    for layer in ("GEOMETRY","TEXT","PROTECTED_GRAPHICS","REVIEW_SOURCE", REPAIR_LAYER):
        doc.layers.new(layer,dxfattribs={"color":7})
    # A frozen layer stays hidden in CAD editors that discard the DXF off flag.
    doc.layers.get("REVIEW_SOURCE").freeze()
    doc.layers.get(REPAIR_LAYER).freeze()
    style = install_text_style(doc, output, (line.text for line in lines))
    warnings.extend(style["warnings"])
    resources = list(style["resources"])
    msp = doc.modelspace()
    paper_mm_per_px = 25.4 / float(dpi)
    scale = paper_mm_per_px * drawing_scale
    height,width = image.shape[:2]
    def point(p):
        return float(p[0])*scale, (height-float(p[1]))*scale
    geometry_entities, text_entities = [], []
    for shape in geometry:
        attrs = {"layer":"GEOMETRY","color":256,"lineweight":shape["lineweight"]}
        kind = shape["type"]
        if kind == "LINE":
            native = msp.add_line(point(shape["points"][0]),point(shape["points"][1]),dxfattribs=attrs)
        elif kind == "CIRCLE":
            native = msp.add_circle(point(shape["center"]),shape["radius"]*scale,dxfattribs=attrs)
        elif kind == "ARC":
            native = msp.add_arc(point(shape["center"]),shape["radius"]*scale,
                                 shape["start_angle"],shape["end_angle"],dxfattribs=attrs)
        else:
            if "const_width_px" in shape:
                attrs.update(const_width=shape["const_width_px"]*scale, lineweight=0)
            native = msp.add_lwpolyline([point(p) for p in shape["points"]],
                                       close=shape.get("closed",False),dxfattribs=attrs)
        geometry_entities.append(native)
    for line in accepted:
        text_entities.append(_add_native_text(msp, line, style, point, scale, layer="TEXT"))
    if text_entities:
        place_cell_text(geometry_input, geometry, accepted, symbols, text_entities, style["font_path"],
                        dpi=dpi, scale=scale,
                        cancellation_token=cancellation_token)
    save_drafting_evidence(doc, candidates, geometry, accepted, symbols,
                           geometry_entities, text_entities, source=source, page_index=page_index,
                           image_size=(width, height), dpi=dpi, drawing_scale=drawing_scale,
                           perspective_corrected=corrected, cancellation_token=cancellation_token)
    save_repair_evidence(msp, repairs, point, page_index, cancellation_token=cancellation_token)
    for line in uncertain:
        checkpoint(cancellation_token)
        entity = _add_native_text(msp, line, style, point, scale, layer=REPAIR_LAYER)
        save_text_repair_evidence(entity, line, page_index)
    # Separate connected graphic groups remain independently movable IMAGEs.
    groups = cv2.dilate(protected,np.ones((7,7),np.uint8))
    # A seal's lettering need not touch its ring. Overlapping component bounds
    # describe one graphic, while disjoint signatures remain independent.
    _, _, bounds, _ = cv2.connectedComponentsWithStats(groups,connectivity=8)
    for x, y, w, h, area in bounds[1:]:
        if area >= 3:
            groups[y:y+h,x:x+w] = 255
    count,labels,stats,_ = cv2.connectedComponentsWithStats(groups,connectivity=8)
    protected_count = 0
    for index in range(1,count):
        if stats[index,cv2.CC_STAT_AREA] < 3:
            continue
        mask = np.uint8((labels == index)&(protected > 0))*255
        asset = _add_source_image(doc,msp,image,mask,output,f"graphic-{protected_count+1}",
                                  "PROTECTED_GRAPHICS",scale)
        if asset:
            resources.append(asset)
            protected_count += 1
    checkpoint(cancellation_token)
    report_progress(progress_callback,"save",0.90)
    doc.saveas(output)
    reference, pending = source_reference(image, manual, accepted, uncertain)
    quality, missing, extra = measure_saved_scan(output, reference, accepted, dpi=dpi,
                                                 drawing_scale=drawing_scale)
    residual = missing | pending
    asset = _add_source_image(doc,msp,image,residual,output,"unresolved-ink","REVIEW_SOURCE",scale)
    if asset:
        resources.append(asset)
        warnings.append("未转换的墨迹保留在默认关闭的 REVIEW_SOURCE 图层。")
        doc.saveas(output)
        del missing, extra, residual
        quality, missing, extra = measure_saved_scan(output, reference, accepted, dpi=dpi,
                                                     drawing_scale=drawing_scale)
        residual = missing | pending
    residual_pixels = cv2.countNonZero(residual)
    if uncertain:
        warnings.append(f"{len(uncertain)}行低置信度文字保留原图，未用猜测文字替换。")
    if quality["geometry"]["extra_pixels"] or quality["geometry"]["outside_page_entities"]:
        warnings.append("保存后的 DXF 含有超出来源支持范围的几何。")
    if any(quality["text"][k] for k in ("missing_or_changed", "outside_box", "unexpected_lines")):
        warnings.append("保存后的 DXF 存在文字内容或框内排版偏差。")
    # Reopen the actual saved file; resources remain relative and portable.
    saved = ezdxf.readfile(output)
    audit = saved.audit()
    if audit.errors:
        raise ValueError(f"Saved DXF contains {len(audit.errors)} structural errors")
    save_geometry_residuals(output, image, missing, extra)
    if preview_path is not None:
        from app.core.dxf_preview import render_dxf
        render_dxf(output,preview_path)
    report_progress(progress_callback,"complete",1.0)
    return {"route":"scan", "output":str(output),
            "preview":str(preview_path) if preview_path else None,
            "counts":dict(Counter(entity.dxftype() for entity in saved.modelspace())),
            "source":str(source),"page_index":page_index,"source_size_px":[width,height],
            "page_size_mm":[width*paper_mm_per_px,height*paper_mm_per_px],"dpi":float(dpi),
            "engineering_scale":"UNVERIFIED","perspective_corrected":corrected,
            "ocr":{"enabled":bool(enable_ocr),"error":ocr_error,
                   "editable_lines":[{"text":x.text,"confidence":x.confidence,"quad":x.quad} for x in accepted],
                   "uncertain_lines":[{"text":x.text,"confidence":x.confidence,"quad":x.quad} for x in uncertain]},
            "protected_graphics":protected_count,"unresolved_ink_pixels":residual_pixels,
            "quality":quality,"drafting":drafting,"resources":resources,"warnings":warnings,
            "status":"COMPLETED_WITH_REVIEW" if warnings or residual_pixels else "COMPLETED"}
