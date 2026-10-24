"""Bounded, read-only inspection of saved CAD output in its recorded page frame.

Pixels generate review candidates, never engineering correction authority.
The production DXF renderer and LFF metrics remain the rendering authority.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
import zipfile

import cv2
import ezdxf
from ezdxf import bbox
from ezdxf.math import Matrix44
import numpy as np
import pypdfium2 as pdfium
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from app.core.cache import _deserialize_lines, _deserialize_texts, _unpack_binary
from app.core.image_loader import load_image, save_image
from app.core.preview import render_emitted_dxf_preview
from app.export.ocr_outline_export import native_text_placement
from app.ocr.librecad_lff import librecad_text_metrics, librecad_text_path

ALGORITHM = "saved-page-fidelity-inspection-v1"
SUPPORTED = {"LINE", "LWPOLYLINE", "TEXT", "ARC", "CIRCLE", "HATCH", "IMAGE"}
_QT = None


@dataclass(frozen=True)
class Limits:
    max_pixels: int = 12_000_000
    max_entities: int = 20_000
    max_components: int = 30_000
    max_candidates: int = 64
    max_region_entities: int = 32
    max_details: int = 8
    source_seconds: float = 12.0
    seconds: float = 120.0
    source_cut: int = 160
    cad_cut: int = 200
    tolerance_px: int = 1
    tile_px: int = 96

    def __post_init__(self):
        for key, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid inspection limit: {key}")
        if not 1 <= self.source_cut <= 254 or not 1 <= self.cad_cut <= 254:
            raise ValueError("Threshold outside 1..254")
        if self.tolerance_px > 2 or self.max_details > 16:
            raise ValueError("Tolerance/details exceeds inspection policy")


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [plain(v) for v in value]
    except TypeError:
        return str(value)


def write_json(path, value):
    Path(path).write_text(
        json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def file_identity(path):
    """Input versions explicitly requested by the P15-A inspection contract."""
    path = Path(path).resolve()
    start = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    end = path.stat()
    if (start.st_size, start.st_mtime_ns) != (end.st_size, end.st_mtime_ns):
        raise ValueError(f"Input changed while reading: {path}")
    return dict(
        path=str(path),
        bytes=end.st_size,
        mtime_ns=end.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def checkpoint(start, limits):
    if perf_counter() - start > limits.seconds:
        raise TimeoutError("Inspection deadline exceeded; no input was written")


def page_metadata(path, physical_page, dpi, limits):
    if not 1 <= physical_page or not 72 <= dpi <= 1200:
        raise ValueError("Physical page is 1-based; DPI must be 72..1200")
    with pdfium.PdfDocument(str(path)) as document:
        if physical_page > len(document):
            raise ValueError("Physical page outside document")
        page = document[physical_page - 1]
        try:
            w, h = page.get_size()
            result = dict(
                media_box=list(page.get_mediabox()),
                crop_box=list(page.get_cropbox()),
                rotation=page.get_rotation(),
                rendered_page_points=[w, h],
                dpi=dpi,
                physical_page=physical_page,
            )
            if math.ceil(w * dpi / 72) * math.ceil(h * dpi / 72) > limits.max_pixels:
                raise ValueError(
                    "Page pixel budget exceeded; no implicit resampling permitted"
                )
            return result
        finally:
            page.close()


def coordinate_contract(contract, meta, shape, units):
    """Validate a recorded calibration, never infer scale from CAD extents."""
    if not contract or contract.get("scope") != "FULL_PAGE":
        return dict(
            status="COORDINATE_CONTRACT_INCOMPLETE",
            reason="FULL_PAGE contract required",
        )
    h, w = shape
    ref = Path(contract.get("reference", ""))
    if not ref.is_file() or list(contract.get("size_px") or []) != [w, h] or units != 4:
        return dict(
            status="COORDINATE_CONTRACT_INCOMPLETE",
            reason="Reference/size/DXF millimetres mismatch",
        )
    reference = json.loads(ref.read_text(encoding="utf-8"))
    scale = float(reference.get("mm_per_pixel", 0))
    expected = meta["rendered_page_points"][0] * 25.4 / 72 / (w - 1)
    if not math.isfinite(scale) or not math.isclose(
        scale, expected, rel_tol=1e-8, abs_tol=1e-10
    ):
        return dict(
            status="COORDINATE_CONTRACT_INCOMPLETE",
            reason="Recorded calibration differs from PDF paper width",
        )
    if reference.get("physical_page", meta["physical_page"]) != meta["physical_page"]:
        return dict(
            status="COORDINATE_CONTRACT_INCOMPLETE", reason="Reference page mismatch"
        )
    return dict(
        status="VERIFIED",
        kind="RECORDED_PDF_PAPER_WIDTH",
        mm_per_pixel=scale,
        reference=file_identity(ref),
        forward="(x*s, (height-y)*s)",
        inverse="(X/s, height-Y/s)",
        model_dimensions_verified=False,
    )


def read_trace(path, shape, physical_page, dpi, limits, *, source_identity=None):
    if path is None:
        return (
            dict(status="SOURCE_ASSOCIATION_NOT_AVAILABLE", reason="No trace supplied"),
            {},
            None,
        )
    started = perf_counter()
    names = [
        "cache_version",
        "final_structure_schema_version",
        "preview_shape",
        "preview_packed",
        "cache_key_json",
        "structure_id",
        "lines_json",
        "texts_json",
        "provenance_json",
    ]
    try:
        # Avoid observations_json: it is not needed and can exceed 170 MB.
        with zipfile.ZipFile(path) as archive:
            if sum(archive.getinfo(k + ".npy").file_size for k in names) > 32_000_000:
                raise ValueError("Selected trace fields exceed byte budget")
        with np.load(path, allow_pickle=False) as fields:
            if (
                int(fields["cache_version"][0]) != 11
                or int(fields["final_structure_schema_version"][0]) != 4
            ):
                raise ValueError("Unsupported trace/schema version")
            if tuple(fields["preview_shape"].reshape(-1)) != shape:
                raise ValueError("Trace page dimensions mismatch")
            key = json.loads(str(fields["cache_key_json"].reshape(-1)[0]))
            if key and (
                key.get("page_number") != physical_page or key.get("dpi") != dpi
            ):
                raise ValueError("Trace page/DPI mismatch")
            source_digest = key.get("input_content_sha256")
            if (
                source_identity
                and source_digest
                and source_digest != source_identity["sha256"]
            ):
                raise ValueError("Trace source document version mismatch")
            source = _unpack_binary(fields["preview_packed"], fields["preview_shape"])
            lines = _deserialize_lines(str(fields["lines_json"].reshape(-1)[0]))
            texts = _deserialize_texts(str(fields["texts_json"].reshape(-1)[0]))
            provenance = json.loads(str(fields["provenance_json"].reshape(-1)[0]))
            structure_id = str(fields["structure_id"].reshape(-1)[0])
        if perf_counter() - started > limits.source_seconds:
            raise TimeoutError("Source field time budget exceeded")
        lookup = defaultdict(list)
        presentations = provenance.get("stroke_presentation", {}).get(
            "line_records", []
        )
        for index, line in enumerate(lines):
            if perf_counter() - started > limits.source_seconds:
                raise TimeoutError("Source association time budget exceeded")
            lookup[
                geometry_key(
                    "LINE", [line.x1, shape[0] - line.y1, line.x2, shape[0] - line.y2]
                )
            ].append(
                dict(
                    kind="LINE",
                    index=index,
                    source_ids=list(line.source_ids),
                    history=list(line.history),
                    saved_width_px=line.width,
                    saved_presentation=presentations[index]
                    if index < len(presentations)
                    else None,
                )
            )
        for index, text in enumerate(texts):
            if perf_counter() - started > limits.source_seconds:
                raise TimeoutError("Source association time budget exceeded")
            placement = native_text_placement(
                text, transform=lambda x, y: (x, shape[0] - y)
            )
            if placement:
                g = placement.geometry
                values = [
                    *g.insert,
                    g.character_height,
                    g.width_factor,
                    g.rotation,
                    placement.content,
                ]
                lookup[geometry_key("TEXT", values)].append(
                    dict(
                        kind="TEXT",
                        index=index,
                        original_candidate_text=text.text,
                        bbox=list(text.bbox),
                        replacement_safe=text.replacement_safe,
                        reviewed=text.reviewed,
                        source=text.source,
                    )
                )
        return (
            dict(
                status="PARTIAL",
                structure_id=structure_id,
                cache_version=11,
                schema=4,
                scope="Selected immutable saved fields; full observations/owner ledger NOT loaded or validated",
                key_present=bool(key),
                algorithm_version=key.get("algorithm_version"),
                source_identity="FILE_VERSION_RECORDED; full cache identity not revalidated",
                source_file_version_matches_cache_key=bool(
                    source_identity and source_digest
                ),
                provenance_sections=sorted(provenance),
                seconds=perf_counter() - started,
            ),
            lookup,
            source,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TimeoutError,
        MemoryError,
        zipfile.BadZipFile,
    ) as exc:
        return (
            dict(status="SOURCE_ASSOCIATION_NOT_AVAILABLE", reason=str(exc)),
            {},
            None,
        )


def geometry_key(kind, values):
    return kind, tuple(
        round(float(v), 5) if isinstance(v, (float, int)) else v for v in values
    )


def visible(entity, doc):
    layer = doc.layers.get(entity.dxf.layer)
    return (
        not layer.is_off()
        and not layer.is_frozen()
        and not entity.dxf.get("invisible", 0)
    )


def geometry(entity):
    kind = entity.dxftype()
    if kind == "LINE":
        return [*list(entity.dxf.start)[:2], *list(entity.dxf.end)[:2]]
    if kind == "TEXT":
        return [
            *list(entity.dxf.insert)[:2],
            entity.dxf.height,
            entity.dxf.width,
            entity.dxf.rotation,
            entity.dxf.text,
        ]
    if kind in {"ARC", "CIRCLE"}:
        return [*list(entity.dxf.center)[:2], entity.dxf.radius] + (
            [entity.dxf.start_angle, entity.dxf.end_angle] if kind == "ARC" else []
        )
    if kind == "LWPOLYLINE":
        return [bool(entity.closed), plain(entity.get_points("xyseb"))]
    if kind == "IMAGE":
        return [
            plain(entity.dxf.insert),
            plain(entity.dxf.u_pixel),
            plain(entity.dxf.v_pixel),
            plain(entity.dxf.image_size),
            entity.image_def.dxf.filename,
        ]
    return {
        k: plain(v)
        for k, v in entity.dxfattribs().items()
        if k not in {"handle", "owner"}
    } | {"boundaries": [plain(p.vertices) for p in entity.paths]}


def bounds_source(entity, height):
    if entity.dxftype() == "TEXT":
        m = librecad_text_metrics(entity.dxf.text)
        tr = QTransform()
        tr.translate(entity.dxf.insert.x, entity.dxf.insert.y)
        tr.rotate(entity.dxf.rotation)
        tr.scale(
            entity.dxf.height / m.em_height * entity.dxf.width,
            -entity.dxf.height / m.em_height,
        )
        r = tr.map(librecad_text_path(entity.dxf.text)).boundingRect()
        return [r.left(), height - r.bottom(), r.right(), height - r.top()]
    box = bbox.extents([entity])
    if not box.has_data:
        return None
    return [box.extmin.x, height - box.extmax.y, box.extmax.x, height - box.extmin.y]


def read_dxf(path, scale, size, lookup, limits):
    doc = ezdxf.readfile(path)
    if len(doc.modelspace()) > limits.max_entities:
        raise ValueError("DXF entity budget exceeded")
    rows, clones = [], []
    for original in doc.modelspace():
        kind = original.dxftype()
        shown = visible(original, doc)
        if kind not in SUPPORTED and shown:
            raise ValueError(f"Official preview does not support {kind}")
        e = original.copy()
        e.transform(Matrix44.scale(1 / scale))
        shape = geometry(e) if kind in SUPPORTED else []
        matches = (
            lookup.get(geometry_key(kind, shape), [])
            if kind in {"LINE", "TEXT"}
            else []
        )
        xdata = {
            k: [(t.code, plain(t.value)) for t in tags]
            for k, tags in (original.xdata.data.items() if original.xdata else [])
        }
        row = dict(
            type=kind,
            layer=original.dxf.layer,
            visible=shown,
            current_file_handle=original.dxf.handle,
            geometry_source_CAD_axes=shape,
            bounds_source_px=bounds_source(e, size[1]) if kind in SUPPORTED else None,
            attributes=plain(original.dxfattribs()),
            xdata=xdata,
            source_association="SAVED_FS_GEOMETRY_MATCH"
            if len(matches) == 1
            else "AMBIGUOUS"
            if matches
            else "SOURCE_UNDETERMINED",
            saved_members=matches,
            source_record_present=bool(xdata),
            ownership="NOT_RECONSTRUCTED; source records do not grant pixel deletion",
            engineering_verdict="NOT_AUTOMATICALLY_VERIFIED",
            modification_authorized=False,
        )
        row["structural_observations"] = []
        if (
            kind == "LINE"
            and len(matches) == 1
            and matches[0].get("saved_presentation") is None
        ):
            row["structural_observations"].append(
                "SAVED_LINE_WITHOUT_PRESENTATION_RECORD; reason not inferred"
            )
        row["_sort"] = json.dumps(
            [kind, row["layer"], shape], sort_keys=True, ensure_ascii=False
        )
        rows.append(row)
        if shown:
            clones.append(e)
    # Stable geometry groups, not persistent source UUIDs or handle identities.
    rows.sort(key=lambda r: (r["_sort"], json.dumps(r["xdata"], sort_keys=True)))
    grouped = Counter(r["_sort"] for r in rows)
    member_uses = Counter(
        (m["kind"], m["index"])
        for r in rows
        for m in r["saved_members"]
        if len(r["saved_members"]) == 1
    )
    keys = {key: f"G{i + 1:05d}" for i, key in enumerate(sorted(grouped))}
    for row in rows:
        key = row.pop("_sort")
        row["geometry_group"] = keys[key]
        row["geometry_group_members"] = grouped[key]
        if grouped[key] > 1:
            row["object_identity"] = "AMBIGUOUS_EQUAL_GEOMETRY; not deletion authority"
        else:
            row["object_identity"] = (
                "UNIQUE_IN_THIS_INPUT_VERSION; not cross-conversion UUID"
            )
        if len(row["saved_members"]) == 1:
            m = row["saved_members"][0]
            if member_uses[m["kind"], m["index"]] > 1:
                row["source_association"] = "AMBIGUOUS_MULTIPLE_CAD_FOR_SAVED_MEMBER"
    proxy = SimpleNamespace(modelspace=lambda: clones, layers=doc.layers)
    rendered = render_emitted_dxf_preview(proxy, Path(path).parent, size)
    audit = doc.audit()  # In-memory diagnostic only; never save the document.
    return (
        rendered,
        rows,
        dict(errors=len(audit.errors), fixes=len(audit.fixes)),
        int(doc.units),
    )


def difference_masks(source, cad, source_cut=160, cad_cut=200, tolerance=1):
    a, b = source < source_cut, cad < cad_cut
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * tolerance + 1, 2 * tolerance + 1)
    )
    near_b = cv2.dilate(b.astype(np.uint8), kernel) > 0
    near_a = cv2.dilate(a.astype(np.uint8), kernel) > 0
    return a & ~near_b, b & ~near_a


def metrics(source, cad, source_cut, tolerance):
    missing, extra = difference_masks(source, cad, source_cut, 200, tolerance)
    return dict(
        source_pixels=int((source < source_cut).sum()),
        CAD_pixels=int((cad < 200).sum()),
        missing_candidate_pixels=int(missing.sum()),
        extra_candidate_pixels=int(extra.sum()),
        source_cut=source_cut,
        CAD_cut=200,
        tolerance_px=tolerance,
        interpretation="Measured visual difference; not engineering error or source-coverage certificate",
    )


def regions(missing, extra, limits, *, apply_limit=True):
    buckets = Counter()
    truncated = False
    for mask in [missing, extra]:
        count, _labels, stats, _centers = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), 8
        )
        parts = sorted(
            stats[1:].tolist(), key=lambda s: (-s[4], s[1], s[0], s[2], s[3])
        )
        truncated |= count - 1 > limits.max_components
        for x, y, w, h, area in parts[: limits.max_components]:
            if area < 3:
                continue
            # Tile aggregation is for reporting only. No source mask is modified.
            buckets[
                (int((x + w / 2) // limits.tile_px), int((y + h / 2) // limits.tile_px))
            ] += area
    h, w = missing.shape
    results = []
    for (tx, ty), area in buckets.items():
        if area < 12:
            continue
        x0, y0 = tx * limits.tile_px, ty * limits.tile_px
        x1, y1 = min(w, x0 + limits.tile_px), min(h, y0 + limits.tile_px)
        m, e = int(missing[y0:y1, x0:x1].sum()), int(extra[y0:y1, x0:x1].sum())
        results.append(
            dict(
                id=f"R-{x0:05d}-{y0:05d}-{x1 - x0:03d}-{y1 - y0:03d}",
                bbox=[x0, y0, x1, y1],
                missing_pixels=m,
                extra_pixels=e,
                visual_state="VISUAL_DIFFERENCE_ONLY",
                engineering_state="INSUFFICIENT_EVIDENCE",
                modification_authorized=False,
            )
        )
    results.sort(
        key=lambda r: (
            -(r["missing_pixels"] + r["extra_pixels"]),
            r["bbox"][1],
            r["bbox"][0],
        )
    )
    return (results[: limits.max_candidates] if apply_limit else results), dict(
        component_budget_truncated=truncated,
        candidate_budget_truncated=len(results) > limits.max_candidates,
        candidate_tiles_before_limit=len(results),
    )


def intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


class SpatialIndex:
    def __init__(self, records):
        self.bins = defaultdict(list)
        self.wide = []
        for record in records:
            b = record["bounds_source_px"]
            if b is None or not record["visible"]:
                continue
            xs, ys = (
                range(math.floor(b[0] / 128), math.floor(b[2] / 128) + 1),
                range(math.floor(b[1] / 128), math.floor(b[3] / 128) + 1),
            )
            if len(xs) * len(ys) > 64:
                self.wide.append(record)
            else:
                for x in xs:
                    for y in ys:
                        self.bins[x, y].append(record)

    def query(self, box, maximum):
        found = {id(r): r for r in self.wide}
        for x in range(box[0] // 128, box[2] // 128 + 1):
            for y in range(box[1] // 128, box[3] // 128 + 1):
                found.update({id(r): r for r in self.bins[x, y]})
        rows = [r for r in found.values() if intersects(r["bounds_source_px"], box)]
        rows.sort(
            key=lambda r: (r["type"] not in {"TEXT", "IMAGE"}, r["geometry_group"])
        )
        return rows[:maximum], len(rows) > maximum


def context(region, index, limits):
    rows, clipped = index.query(region["bbox"], limits.max_region_entities)
    types = Counter(r["type"] for r in rows)
    region.update(
        entity_groups=[r["geometry_group"] for r in rows],
        entity_types=dict(types),
        association_truncated=clipped,
        source_state="MULTIPLE_NEARBY_CAD_MEMBERS"
        if len(rows) > 1
        else "SPATIAL_CONTEXT_ONLY"
        if rows
        else "NO_MATCHING_NEARBY_CAD_MEMBER",
        saved_source_matches=sum(
            r["source_association"] == "SAVED_FS_GEOMETRY_MATCH" for r in rows
        ),
        owner_state="UNKNOWN_PER_PIXEL; nearby bounding boxes are not source ownership",
    )
    guards = []
    if types["TEXT"]:
        guards.append(
            "TEXT_FONT_OR_LAYOUT_DIFFERENCE; content correctness is not inferred from pixels"
        )
    if types["IMAGE"]:
        guards.append("IMAGE_RENDERED_FROM_ACTUAL_ASSET; no LINE-per-pixel requirement")
    if types["ARC"] or types["CIRCLE"]:
        guards.append("CURVE_OPENING_AND_MEMBERS_PROTECTED; no automatic closure")
    if len(rows) > 1:
        guards.append("INDEPENDENT_MEMBERS_POSSIBLE; overlap is not duplication proof")
    region["guards"] = guards
    region["structural_observations"] = sorted(
        {s for r in rows for s in r.get("structural_observations", [])}
    )
    region["review_priority"] = (
        "TEXT_IMAGE_DISPLAY_REVIEW"
        if types["TEXT"] or types["IMAGE"]
        else "GEOMETRY_SOURCE_REVIEW"
    )


def rank_regions(candidates, prepared, missing, source, limits):
    """Preserve geometry candidates before filling the budget with font differences."""
    for region in candidates:
        x0, y0, x1, y1 = region["bbox"]
        if prepared is not None:
            ink = prepared[y0:y1, x0:x1] < 128
            missing_ink = missing[y0:y1, x0:x1]
            region["prepared_source_pixels"] = int(ink.sum())
            region["missing_on_prepared_source_pixels"] = int((missing_ink & ink).sum())
            if (
                region["missing_pixels"] >= 24
                and region["missing_pixels"] > region["extra_pixels"] * 2
                and (
                    region["missing_on_prepared_source_pixels"]
                    / region["missing_pixels"]
                    < 0.20
                )
            ):
                region["guards"].append(
                    "TONAL_OR_PREPROCESS_DIFFERENCE; raw tone is not confirmed structural ink"
                )
                region["review_priority"] = "TONAL_BACKGROUND_REVIEW"
        region["raw_dark_fraction"] = float(
            (source[y0:y1, x0:x1] < limits.source_cut).mean()
        )
    priority = {
        "GEOMETRY_SOURCE_REVIEW": 0,
        "TEXT_IMAGE_DISPLAY_REVIEW": 1,
        "TONAL_BACKGROUND_REVIEW": 2,
    }
    candidates.sort(
        key=lambda r: (
            priority[r["review_priority"]],
            -(r["missing_pixels"] + r["extra_pixels"]),
            r["id"],
        )
    )
    # All page tiles are bounded by max_pixels/tile_px²; the retained output is capped.
    selected = candidates[: limits.max_candidates]
    # At most six geometry thumbnails plus two display/tone examples in the overview.
    first = [r for r in selected if r["review_priority"] == "GEOMETRY_SOURCE_REVIEW"][
        : max(1, limits.max_details - 2)
    ]
    other = [r for r in candidates if r["review_priority"] != "GEOMETRY_SOURCE_REVIEW"][
        :2
    ]
    overview = first + other
    for r in selected:
        if len(overview) >= limits.max_details:
            break
        if r not in overview:
            overview.append(r)
    retained = overview + [r for r in candidates if r not in overview]
    return retained[: limits.max_candidates]


def inspect_case(case, output, limits=Limits()):
    global _QT
    _QT = QApplication.instance() or QApplication([])
    started = perf_counter()
    output = Path(output).resolve()
    pdf, dxf = Path(case["pdf"]), Path(case["dxf"])
    paths = [pdf, dxf] + ([Path(case["trace"])] if case.get("trace") else [])
    if case.get("coordinate"):
        paths.append(Path(case["coordinate"]["reference"]))
    for label in case.get("labels", []):
        paths.append(Path(label["evidence"]))
        if label.get("before_dxf") and Path(label["before_dxf"]).is_file():
            paths.append(Path(label["before_dxf"]))
    paths = list(dict.fromkeys(paths))
    if any(p.resolve().is_relative_to(output) for p in paths):
        raise ValueError("Output must not contain any inspection input")
    output.mkdir(parents=True, exist_ok=True)
    identities = [file_identity(p) for p in paths]
    dpi, physical_page = int(case.get("dpi", 240)), int(case["page"])
    meta = page_metadata(pdf, physical_page, dpi, limits)
    source = load_image(pdf, page_index=physical_page - 1, pdf_dpi=dpi, grayscale=True)
    h, w = source.shape
    if h * w > limits.max_pixels:
        raise ValueError("Rendered page exceeds budget")
    doc_units = int(ezdxf.readfile(dxf).units)
    contract = coordinate_contract(
        case.get("coordinate"), meta, source.shape, doc_units
    )
    result = dict(
        format="cad-fidelity-report-v1",
        algorithm=ALGORITHM,
        name=case["id"],
        generated_utc=datetime.now(timezone.utc).isoformat(),
        inputs=identities,
        page=meta | {"size_px": [w, h]},
        coordinate=contract,
        limits=asdict(limits),
        production_CAD_change="NONE",
        automatic_verified_defects=0,
        modification_authorized=False,
    )
    save_image(output / "source.png", source)
    checkpoint(started, limits)
    if contract["status"] != "VERIFIED":
        result.update(
            status="COORDINATE_CONTRACT_INCOMPLETE",
            candidates=[],
            historical=[],
            metrics=None,
            source_association="NOT_AVAILABLE",
            seconds=perf_counter() - started,
        )
        write_json(output / "report.json", result)
        return result
    trace, lookup, prepared = read_trace(
        case.get("trace"),
        source.shape,
        physical_page,
        dpi,
        limits,
        source_identity=identities[0],
    )
    cad, entities, audit, _units = read_dxf(
        dxf, contract["mm_per_pixel"], (w, h), lookup, limits
    )
    save_image(output / "cad.png", cad)
    index = SpatialIndex(entities)
    missing, extra = difference_masks(
        source, cad, limits.source_cut, limits.cad_cut, limits.tolerance_px
    )
    candidates, budgets = regions(missing, extra, limits, apply_limit=False)
    for candidate in candidates:
        context(candidate, index, limits)
    candidates = rank_regions(candidates, prepared, missing, source, limits)
    for candidate in candidates:
        candidate["historical_context"] = [
            label["id"]
            for label in case.get("labels", [])
            if intersects(candidate["bbox"], label["bbox"])
        ]
    historical = []
    for label in case.get("labels", [])[:16]:
        checkpoint(started, limits)
        b = list(map(int, label["bbox"]))
        if not (0 <= b[0] < b[2] <= w and 0 <= b[1] < b[3] <= h):
            raise ValueError("Historical label outside page")
        evidence = Path(label["evidence"])
        if not evidence.is_file():
            raise ValueError(f"Historical evidence missing: {evidence}")
        item = dict(
            id=label["id"],
            bbox=b,
            declared_class=label["classification"],
            basis="REFERENCED_HISTORICAL_EVIDENCE; not inferred/reauthorized by pixel metrics",
            evidence=file_identity(evidence),
            note=label["note"],
            modification_authorized=False,
            automatic_candidate_intersections=[
                r["id"] for r in candidates if intersects(b, r["bbox"])
            ],
        )
        context(item, index, limits)
        x0, y0, x1, y1 = b
        item["current"] = [
            metrics(source[y0:y1, x0:x1], cad[y0:y1, x0:x1], cut, tolerance)
            for cut in (128, 160, 192)
            for tolerance in (0, 1)
        ]
        previous = label.get("before_dxf")
        if previous and Path(previous).is_file():
            old, old_rows, old_audit, old_units = read_dxf(
                previous, contract["mm_per_pixel"], (w, h), {}, limits
            )
            if old_units != 4:
                raise ValueError("Historical comparison units mismatch")
            item["before"] = [
                metrics(source[y0:y1, x0:x1], old[y0:y1, x0:x1], cut, tolerance)
                for cut in (128, 160, 192)
                for tolerance in (0, 1)
            ]
            item["before_input"], item["before_audit"] = (
                file_identity(previous),
                old_audit,
            )
            item["before_nearby_TEXT_geometry"] = [
                dict(
                    group=r["geometry_group"],
                    geometry=r["geometry_source_CAD_axes"],
                    bounds=r["bounds_source_px"],
                )
                for r in old_rows
                if r["visible"]
                and r["type"] == "TEXT"
                and intersects(r["bounds_source_px"], b)
            ][: limits.max_region_entities]
            item["current_nearby_TEXT_geometry"] = [
                dict(
                    group=r["geometry_group"],
                    geometry=r["geometry_source_CAD_axes"],
                    bounds=r["bounds_source_px"],
                )
                for r in entities
                if r["visible"]
                and r["type"] == "TEXT"
                and intersects(r["bounds_source_px"], b)
            ][: limits.max_region_entities]
            save_image(output / (label["id"] + "-before.png"), old[y0:y1, x0:x1])
        elif previous:
            item["before_status"] = "NOT_AVAILABLE; no fake old version generated"
        if prepared is not None:
            ink = prepared[y0:y1, x0:x1] < 128
            item["prepared_source_pixels"] = int(ink.sum())
            item["current_literal_CAD_coverage"] = int(
                (ink & (cad[y0:y1, x0:x1] < 200)).sum()
            )
            if "before" in item:
                item["before_literal_CAD_coverage"] = int(
                    (ink & (old[y0:y1, x0:x1] < 200)).sum()
                )
        historical.append(item)
    details = candidates[: limits.max_details] + historical
    overlay = cv2.cvtColor(source, cv2.COLOR_GRAY2BGR)
    for i, region in enumerate(candidates[: limits.max_details]):
        x0, y0, x1, y1 = region["bbox"]
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 80, 230), 2)
        cv2.putText(
            overlay,
            str(i + 1),
            (x0 + 2, y0 + 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 40, 230),
            1,
        )
    save_image(output / "overview.png", overlay)
    for region in details:
        x0, y0, x1, y1 = region["bbox"]
        save_image(output / (region["id"] + "-source.png"), source[y0:y1, x0:x1])
        save_image(output / (region["id"] + "-cad.png"), cad[y0:y1, x0:x1])
        highlight = cv2.cvtColor(source[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
        highlight[missing[y0:y1, x0:x1]] = (40, 40, 230)
        highlight[extra[y0:y1, x0:x1]] = (220, 150, 0)
        save_image(output / (region["id"] + "-diff.png"), highlight)
    checkpoint(started, limits)
    matched = sum(
        r["visible"] and r["source_association"] == "SAVED_FS_GEOMETRY_MATCH"
        for r in entities
    )
    visible_count = sum(r["visible"] for r in entities)
    for before, path in zip(identities, paths):
        if before != file_identity(path):
            raise ValueError(f"Input changed during inspection: {path}")
    result.update(
        status="COMPLETED",
        source_association=trace,
        audit=audit,
        budgets=budgets,
        metrics=[
            metrics(source, cad, cut, t) for cut in (128, 160, 192) for t in (0, 1)
        ],
        entity_counts=dict(Counter(r["type"] for r in entities)),
        visible_entities=visible_count,
        visible_entity_types=dict(Counter(r["type"] for r in entities if r["visible"])),
        hidden_entities=len(entities) - visible_count,
        source_geometry_matched=matched,
        source_geometry_matched_denominator=visible_count,
        entities_with_source_records=sum(
            r["visible"] and r["source_record_present"] for r in entities
        ),
        source_geometry_unmatched=visible_count - matched,
        candidates=candidates,
        historical=historical,
        input_bytes_unchanged=True,
        seconds=perf_counter() - started,
    )
    write_json(output / "entities.json", entities)
    write_json(output / "report.json", result)
    return result
