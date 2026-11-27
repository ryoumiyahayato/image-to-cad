"""Ordinary scan conversion: cleanup, finite geometry, text and source graphics."""
from __future__ import annotations

from collections import Counter
from math import atan2, degrees, isfinite
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from PIL import Image, ImageOps

from app.core.cancellation import checkpoint, report_progress, ProcessingCancelled
from app.core.perspective import auto_correct, warp_perspective
from app.export.product_fonts import install_text_style, text_width_factor
from app.geometry.scan_cleanup import paper_ink_alpha, prepare_scan_page
from app.geometry.scan_geometry import extract_scan_geometry
from app.ocr.line_recognition import recognize_lines
from app.ocr.signature_overlay import detect_signature_regions


def _load(source, page_index):
    with Image.open(source) as original:
        original.seek(page_index)
        upright = ImageOps.exif_transpose(original)
        if upright.mode in ("RGBA", "LA") or "transparency" in upright.info:
            rgba = upright.convert("RGBA")
            upright = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
        rgb = np.asarray(upright.convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _graphic_mask(image, binary):
    """Retain colored marks and handwriting-like groups before OCR/vectorization.

    This is conservative graphic protection, not a signature authenticity or
    semantic classifier. Remaining unmodelled ink is retained separately too.
    """
    mask = np.zeros(binary.shape, np.uint8)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    color = np.uint8((hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 35)) * 255
    grouped = cv2.morphologyEx(color, cv2.MORPH_CLOSE, np.ones((11,11), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 30 or w < 8 or h < 8:
            continue
        # Long ordinary colored labels stay eligible for text recognition.
        if w > 5*h or h > 5*w:
            continue
        selected = labels[y:y+h,x:x+w] == i
        mask[y:y+h,x:x+w][selected] = 255
    for region in detect_signature_regions(binary):
        x, y, w, h = region.bbox
        target = mask[y:y+h,x:x+w]
        target[region.mask > 0] = 255
    return cv2.dilate(mask, np.ones((3,3), np.uint8))


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
    if not alpha.any():
        return None
    rgba = np.zeros((y1-y0,x1-x0,4), np.uint8)
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
    # DXF TEXT percent controls must not reinterpret a literal OCR sequence.
    return text.replace("%", r"\U+0025")


def convert_scan(source_path, output_path, *, dpi=300.0, page_index=0, image=None,
                 enable_ocr=True, perspective=False, corners=None,
                 preserve_regions=(), min_text_confidence=0.70, preview_path=None,
                 cancellation_token=None, progress_callback=None):
    """Save a single raster page as an ordinary editable R2013 DXF.

    ``image`` is an optional BGR/gray array supplied by the scanned-PDF router.
    ``preserve_regions`` contains source-image (x0,y0,x1,y1) rectangles. All
    dimensions are paper millimetres at ``dpi``; no engineering scale is guessed.
    """
    if isinstance(dpi, bool) or not isfinite(float(dpi)) or dpi <= 0:
        raise ValueError("DPI must be a positive finite number")
    if not 0 <= min_text_confidence <= 1:
        raise ValueError("Text confidence must be between zero and one")
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
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
    automatic = _graphic_mask(image, prepared.binary)
    automatic &= np.uint8(prepared.gray < 250)*255
    protected = cv2.max(automatic, manual)
    ocr_image = image.copy()
    ocr_image[protected > 0] = 255
    lines, ocr_error = [], None
    if enable_ocr:
        try:
            lines = recognize_lines(ocr_image, cancellation_token=cancellation_token,
                                    progress_callback=progress_callback)
        except ProcessingCancelled:
            raise
        except Exception as exc:
            ocr_error = f"OCR_UNAVAILABLE: {type(exc).__name__}: {exc}"
            warnings.append(ocr_error)
    accepted = [line for line in lines if line.confidence >= min_text_confidence]
    uncertain = [line for line in lines if line.confidence < min_text_confidence]
    text_mask = np.zeros(prepared.binary.shape,np.uint8)
    uncertain_mask = np.zeros_like(text_mask)
    for line in lines:
        target = text_mask if line.confidence >= min_text_confidence else uncertain_mask
        cv2.fillConvexPoly(target,np.rint(line.quad).astype(np.int32),255)
    text_mask = cv2.dilate(text_mask,np.ones((3,3),np.uint8))
    geometry_input = prepared.binary.copy()
    geometry_input[(protected > 0)|(text_mask > 0)|(uncertain_mask > 0)] = 255
    report_progress(progress_callback,"geometry",0.50)
    geometry, coverage, geometry_warnings = extract_scan_geometry(
        geometry_input, cancellation_token=cancellation_token)
    warnings.extend(geometry_warnings)
    doc = ezdxf.new("R2013", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LWDISPLAY"] = False
    doc.set_raster_variables(frame=0, quality=1, units="mm")
    for layer in ("GEOMETRY","TEXT","PROTECTED_GRAPHICS","REVIEW_SOURCE"):
        doc.layers.new(layer,dxfattribs={"color":7})
    style = install_text_style(doc,output,[line.text for line in accepted])
    warnings.extend(style["warnings"])
    resources = list(style["resources"])
    msp = doc.modelspace()
    scale = 25.4/float(dpi)
    height,width = image.shape[:2]
    def point(p):
        return float(p[0])*scale, (height-float(p[1]))*scale
    for shape in geometry:
        attrs = {"layer":"GEOMETRY","color":256}
        kind = shape["type"]
        if kind == "LINE":
            msp.add_line(point(shape["points"][0]),point(shape["points"][1]),dxfattribs=attrs)
        elif kind == "CIRCLE":
            msp.add_circle(point(shape["center"]),shape["radius"]*scale,dxfattribs=attrs)
        elif kind == "ARC":
            msp.add_arc(point(shape["center"]),shape["radius"]*scale,
                        shape["start_angle"],shape["end_angle"],dxfattribs=attrs)
        else:
            msp.add_lwpolyline([point(p) for p in shape["points"]],
                               close=shape.get("closed",False),dxfattribs=attrs)
    for line in accepted:
        q = np.asarray(line.quad)
        text_height = max(1.0,0.80*float(np.linalg.norm(q[3]-q[0])))*scale
        text_width = float(np.linalg.norm(q[1]-q[0]))*scale
        baseline = q[3]+0.12*(q[0]-q[3])
        rotation = degrees(atan2(-(q[1,1]-q[0,1]),q[1,0]-q[0,0]))
        msp.add_text(_literal_text(line.text),dxfattribs={
            "layer":"TEXT","style":style["style"],"height":text_height,
            "width":text_width_factor(line.text,style["font_path"],text_height,text_width),
            "insert":point(baseline),"rotation":rotation,"color":256})
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
    residual = np.uint8((prepared.binary < 128)&(coverage == 0)&(text_mask == 0)&(protected == 0))*255
    residual_pixels = int(np.count_nonzero(residual))
    asset = _add_source_image(doc,msp,image,residual,output,"unresolved-ink","REVIEW_SOURCE",scale)
    if asset:
        resources.append(asset)
        warnings.append("未转换的墨迹保留在 REVIEW_SOURCE 透明图像层，可对照补字补线。")
    if uncertain:
        warnings.append(f"{len(uncertain)}行低置信度文字保留原图，未用猜测文字替换。")
    checkpoint(cancellation_token)
    report_progress(progress_callback,"save",0.90)
    doc.saveas(output)
    # Reopen the actual saved file; resources remain relative and portable.
    saved = ezdxf.readfile(output)
    audit = saved.audit()
    if audit.errors:
        raise ValueError(f"Saved DXF contains {len(audit.errors)} structural errors")
    if preview_path is not None:
        from app.core.dxf_preview import render_dxf
        render_dxf(output,preview_path)
    report_progress(progress_callback,"complete",1.0)
    return {"route":"scan", "output":str(output),
            "preview":str(preview_path) if preview_path else None,
            "counts":dict(Counter(entity.dxftype() for entity in saved.modelspace())),
            "source":str(source),"page_index":page_index,"source_size_px":[width,height],
            "page_size_mm":[width*scale,height*scale],"dpi":float(dpi),
            "engineering_scale":"UNVERIFIED","perspective_corrected":corrected,
            "ocr":{"enabled":bool(enable_ocr),"error":ocr_error,
                   "editable_lines":[{"text":x.text,"confidence":x.confidence,"quad":x.quad} for x in accepted],
                   "uncertain_lines":[{"text":x.text,"confidence":x.confidence,"quad":x.quad} for x in uncertain]},
            "protected_graphics":protected_count,"unresolved_ink_pixels":residual_pixels,
            "resources":resources,"warnings":warnings,
            "status":"COMPLETED_WITH_REVIEW" if warnings or residual_pixels else "COMPLETED"}
