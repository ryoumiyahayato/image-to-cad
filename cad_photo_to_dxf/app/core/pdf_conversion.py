"""Native PDF pages to editable DXF, shared by the desktop and command line.

PDF points are converted directly to paper millimetres. Paths never pass through
raster detection. Text remains whole Unicode runs; image pixels stay images.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile

import ezdxf
import numpy as np
from PIL import Image
import pymupdf as fitz

from app.core.cancellation import checkpoint, report_progress
from app.export.product_fonts import cap_height_ratio, install_text_style, text_width_factor
from app.geometry.native_pdf_paths import PT_MM, add_native_pdf_path
from app.geometry.pdf_text_suggestions import extract_visible_pdf_text


def _open_page(source, page_number):
    try:
        selected = int(page_number)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("PDF_PAGE_INVALID: page numbers must be integers") from error
    if isinstance(page_number, bool) or selected != page_number:
        raise ValueError("PDF_PAGE_INVALID: page numbers must be integers")
    pdf = fitz.open(source)
    if pdf.needs_pass:
        pdf.close()
        raise ValueError("PDF_ENCRYPTED: provide a decrypted PDF")
    if not 1 <= selected <= len(pdf):
        pdf.close()
        raise ValueError("PDF_PAGE_OUT_OF_RANGE: page numbers start at 1")
    return pdf, pdf[selected - 1]


def inspect_pdf_page(source, page_number=1):
    pdf, page = _open_page(source, page_number)
    try:
        # get_cdrawings avoids creating a Point/Rect Python object per vertex.
        paths = page.get_cdrawings()
        texts = extract_visible_pdf_text(page)
        image_count = len(page.get_image_info())
        vector_count = sum(p["type"] in {"s", "f", "fs"} for p in paths)
        return {"route": "vector" if vector_count or texts else "scan",
                "page_number": page_number, "page_count": len(pdf),
                "page_size_mm": [page.rect.width * PT_MM, page.rect.height * PT_MM],
                "vector_paths": vector_count, "text_runs": len(texts),
                "text_characters": sum(len(t["text"]) for t in texts), "images": image_count,
                "rotation": page.rotation, "warnings": []}
    finally:
        pdf.close()


def _image_entity(doc, msp, image_path, pixels, matrix, world, output):
    relative = image_path.relative_to(output.parent).as_posix()
    definition = doc.add_image_def(relative, size_in_pixel=pixels)
    p0, pu, pv = [world(fitz.Point(*p) * matrix) for p in ((0, 1), (1, 1), (0, 0))]
    width, height = pixels
    image = msp.add_image(definition, p0, size_in_units=(1, 1), dxfattribs={"layer": "PDF_IMAGES"})
    image.dxf.u_pixel = ((pu[0]-p0[0])/width, (pu[1]-p0[1])/width, 0)
    image.dxf.v_pixel = ((pv[0]-p0[0])/height, (pv[1]-p0[1])/height, 0)
    image.dxf.flags = 3 | 8  # Display and honor the original image alpha.
    return image


def convert_pdf_page(source, output, page_number=1, *, monochrome=True, font_directory=None,
                     overwrite=False, preview_path=None, write_report=True,
                     cancellation_token=None, progress_callback=None):
    """Write one native page. Raster-only pages are returned to the scan route."""
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source == output:
        raise ValueError("PDF_INPUT_OUTPUT_COLLISION: input and output must be different")
    if output.suffix.lower() != ".dxf":
        raise ValueError("PDF_OUTPUT_EXTENSION: output must use .dxf")
    if preview_path is not None:
        preview_path = Path(preview_path).expanduser().resolve()
    report_path = output.with_suffix(".report.json") if write_report else None
    artifacts = [output, *([preview_path] if preview_path is not None else []),
                 *([report_path] if report_path is not None else [])]
    if len(set(artifacts)) != len(artifacts) or source in artifacts:
        raise ValueError("PDF_ARTIFACT_COLLISION: input, DXF, preview and report must be different")
    for path in artifacts:
        if path.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {path}")
    checkpoint(cancellation_token)
    pdf, page = _open_page(source, page_number)
    try:
        drawings = page.get_drawings(extended=True)
        texts = extract_visible_pdf_text(page)
        image_blocks = [b for b in page.get_text("dict", flags=fitz.TEXT_PRESERVE_IMAGES)["blocks"] if b["type"] == 1]
        paths = [d for d in drawings if d["type"] in {"s", "f", "fs"}]
        size = [page.rect.width * PT_MM, page.rect.height * PT_MM]
        if not paths and not texts:
            return {"route": "scan", "output": None, "counts": {}, "warnings": [], "resources": [],
                    "page_number": page_number, "page_size_mm": size}
        output.parent.mkdir(parents=True, exist_ok=True)
        doc = ezdxf.new("R2013")
        doc.units = ezdxf.units.MM
        for layer in ("PDF_GEOMETRY", "PDF_TEXT", "PDF_IMAGES"):
            doc.layers.new(layer, dxfattribs={"color": 7})
        doc.header["$INSUNITS"] = ezdxf.units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$LWDISPLAY"] = True
        doc.set_raster_variables(frame=0, quality=1, units="mm")
        msp = doc.modelspace()
        rotation, height = page.rotation_matrix, page.rect.height
        def world(point):
            p = fitz.Point(float(point[0]), float(point[1])) * rotation
            return p.x * PT_MM, (height - p.y) * PT_MM
        resources, warnings = [], []
        font = install_text_style(doc, output, [t["text"] for t in texts], font_directory=font_directory) if texts else None
        if font:
            resources.extend(font["resources"])
            warnings.extend(font["warnings"])
        if paths and not texts:
            warnings.append("NO_NATIVE_TEXT: outlined letters remain editable vector shapes; OCR is needed to recover Unicode")
        if any(d["type"] == "clip" or (d["type"] == "group" and (d.get("blendmode") != "Normal" or d.get("opacity", 1) != 1 or d.get("knockout"))) for d in drawings):
            warnings.append("PDF_CLIPPING_OR_GROUP_REQUIRES_REVIEW: native paths are retained; inspect clip boundaries")
        if list(page.annots() or ()) or list(page.widgets() or ()):
            warnings.append("PDF_ANNOTATIONS_NOT_EDITABLE: annotation appearances are separate from page content")
        operations = [(int(p["seqno"]), "path", p) for p in paths]
        operations.extend((int(t["seqno"]), "text", t) for t in texts)
        bboxlog = page.get_bboxlog()
        image_paints = [(i, fitz.Rect(box)) for i, (kind, box, *_) in enumerate(bboxlog) if kind == "fill-image"]
        for image_index, block in enumerate(image_blocks):
            box = fitz.Rect(block["bbox"])
            seqno = next((i for i, b in image_paints if max(abs(a-c) for a, c in zip(b, box)) < 0.001), len(bboxlog)+image_index)
            image_paints = [(i, b) for i, b in image_paints if i != seqno]
            operations.append((seqno, "image", block))
        images_dir = output.parent / (output.stem + "_images")
        for index, (_, kind, item) in enumerate(sorted(operations, key=lambda op: op[0])):
            if index % 100 == 0:
                checkpoint(cancellation_token)
                report_progress(progress_callback, "PDF 原生对象", index/max(1, len(operations)))
            if kind == "path":
                add_native_pdf_path(doc, msp, item, world, monochrome)
            elif kind == "text":
                origin = item["origin"]
                direction = np.asarray(item["dir"], float)
                p0, p1 = world(origin), world(np.asarray(origin)+direction)
                angle = math.degrees(math.atan2(p1[1]-p0[1], p1[0]-p0[0]))
                box = fitz.Rect(item["bbox"])
                projections = [float(np.dot(np.asarray(tuple(p))-np.asarray(origin), direction)) for p in (box.tl, box.tr, box.bl, box.br)]
                target_width = (max(projections)-min(projections))*PT_MM
                h = float(item["size"])*PT_MM*cap_height_ratio(font["font_path"])
                attrs = {"layer": "PDF_TEXT", "color": 256, "style": font["style"], "height": h,
                         "insert": p0, "rotation": angle,
                         "width": text_width_factor(item["text"], font["font_path"], h, target_width)}
                if not monochrome:
                    rgb = item.get("color", (0, 0, 0))
                    if len(rgb) == 1:
                        rgb = rgb*3
                    if len(rgb) == 3:
                        attrs["true_color"] = ezdxf.colors.rgb2int(tuple(round(c*255) for c in rgb))
                msp.add_text(item["text"], dxfattribs=attrs)
            else:
                images_dir.mkdir(parents=True, exist_ok=True)
                im = Image.open(BytesIO(item["image"])).convert("RGBA")
                if item.get("mask"):
                    mask = Image.open(BytesIO(item["mask"])).convert("L")
                    if mask.size == im.size:
                        im.putalpha(mask)
                image_path = images_dir / f"image-{len(resources):04d}.png"
                im.save(image_path)
                resources.append(str(image_path))
                _image_entity(doc, msp, image_path, im.size, fitz.Matrix(item["transform"]), world, output)
        doc.set_modelspace_vport(height=size[1], center=(size[0]/2, size[1]/2))
        checkpoint(cancellation_token)
        with tempfile.TemporaryDirectory(prefix="pdf-dxf-", dir=output.parent) as temporary:
            staged = Path(temporary)/output.name
            doc.saveas(staged)
            reopened = ezdxf.readfile(staged)
            audit = reopened.audit()
            if audit.errors:
                raise ValueError(f"SAVED_DXF_INVALID:{len(audit.errors)}")
            counts = dict(Counter(e.dxftype() for e in reopened.modelspace()))
            if sum(counts.values()) == 0:
                raise ValueError("PDF_CONVERSION_EMPTY")
            if output.exists() and not overwrite:
                raise FileExistsError(output)
            staged.replace(output)
        if preview_path:
            preview = Path(preview_path)
            preview.parent.mkdir(parents=True, exist_ok=True)
            from app.core.dxf_preview import render_dxf
            render_dxf(output, preview)
        report = {"route": "vector", "output": str(output), "page_number": page_number,
                  "page_size_mm": size, "counts": counts, "warnings": warnings,
                  "resources": resources, "native_text_runs": len(texts),
                  "native_text_characters": sum(len(t["text"]) for t in texts),
                  "native_paint_paths": len(paths), "ocr_calls": 0,
                  "preview": str(preview_path) if preview_path else None,
                  "units": "paper_mm", "engineering_scale": "UNVERIFIED"}
        if report_path is not None:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        report_progress(progress_callback, "PDF 已保存", 1.0)
        return report
    finally:
        pdf.close()
