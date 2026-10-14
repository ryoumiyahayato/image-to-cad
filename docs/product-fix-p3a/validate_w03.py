"""Reproduce P3A W03 evidence from frozen P2B OCR and the real source PDF.

Run from cad_photo_to_dxf; large artifacts remain outside Git.
"""

from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import time
import sys

sys.path.insert(0, str(Path.cwd()))

import cv2
import ezdxf
from ezdxf import bbox
import numpy as np

from app.core.cache import _deserialize_texts, save_trace_cache, load_trace_cache
from app.core.image_loader import load_image
from app.core.preview import render_final_structure_preview, render_emitted_dxf_preview
from app.core.scale_calibrator import ScaleCalibration
from app.core.structure import metadata_to_jsonable
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.optimized_trace import trace_image_optimized
from app.geometry.source_presentation import stroke_presentation
from app.geometry.reconciliation_geometry import _line_from_payload
from app.geometry.source_stroke_reconciliation import _lines_digest


ROOT = Path.cwd().parent
OUT = ROOT / "local-artifacts/product-fix-p3a"
OUT.mkdir(parents=True, exist_ok=True)
BEFORE = ROOT / "local-artifacts/product-fix-p2b/W03"
FROZEN = json.loads(
    Path("tests/fixtures/product-p2b-ocr-observations.json").read_text(encoding="utf-8")
)
info = FROZEN["W03"]["input"]
source = load_image(
    Path("tests/real_regression/assets/sources") / info["SOURCE_FILE"],
    page_index=info["SOURCE_PAGE"] - 1,
    pdf_dpi=info["DPI"],
    grayscale=True,
)
if len(sys.argv) < 2:
    raise SystemExit(
        "Supply the retained complete W03 UAT texts.json; the test fixture is only a subset."
    )
ocr_path = Path(sys.argv[1])
ocr_bytes = ocr_path.read_bytes()
ocr_sha256 = hashlib.sha256(ocr_bytes).hexdigest()
candidates = _deserialize_texts(ocr_bytes.decode("utf-8"))
assert len(candidates) > 100, "Incomplete W03 OCR observation set"
print("W03 production trace, frozen OCR", len(candidates), ocr_sha256, flush=True)
start = time.perf_counter()
last_stage = None


def progress(stage, fraction):
    global last_stage
    if stage != last_stage:
        print(stage, round(fraction, 3), flush=True)
        last_stage = stage


cache = OUT / "W03-processing-result.npz"
receipt_path = OUT / "W03-processing-result-input.json"
if "--resume" in sys.argv:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["ocr_sha256"] == ocr_sha256
    result = load_trace_cache(cache)
    elapsed = receipt["processing_seconds"]
else:
    with patch(
        "app.geometry.optimized_trace.recognize_text_candidates_optimized",
        return_value=(candidates, ()),
    ):
        result = trace_image_optimized(
            source,
            enable_ocr=True,
            source_dpi=info["DPI"],
            progress_callback=progress,
            performance_callback=lambda name, seconds: print(
                "PERF", name, round(seconds, 3), flush=True
            ),
        )
    elapsed = time.perf_counter() - start
    save_trace_cache(cache, result)
    receipt_path.write_text(
        json.dumps(
            {
                "ocr_path": str(ocr_path),
                "ocr_sha256": ocr_sha256,
                "ocr_count": len(candidates),
                "processing_seconds": elapsed,
            }
        ),
        encoding="utf-8",
    )
if "--refresh-strokes" in sys.argv:
    seed = result.final_structure
    old_presentation = metadata_to_jsonable(seed.provenance["stroke_presentation"])
    assert not old_presentation["false_parallel_decisions"]
    ledger = next(
        o for o in seed.observations if o["event"] == "source_stroke_reconciliation"
    )["ledger"]
    assert hashlib.sha256(source.tobytes()).hexdigest() == ledger["source_image_sha256"]
    route = next(
        e
        for e in ledger["evidence"]
        if e["artifact"] == "runtime-route-ledger-snapshot"
    )
    inputs = tuple(_line_from_payload(p) for p in route["measurements"]["input_lines"])
    assert _lines_digest(inputs) == ledger["input_set_digest"]
    main_count = sum(r["route_origin"] == "MAIN" for r in ledger["representations"])
    assert len(inputs) == len(ledger["representations"])
    main = inputs[:main_count]
    # The captured input snapshot concatenates MAIN then RESTORATION. Check
    # population identity independently before replaying the current source
    # rule. No protection mask is supplied: zero proposals without a veto
    # proves that a protection veto cannot change this population either.
    main_keys = Counter(
        (line.x1, line.y1, line.x2, line.y2, line.width, line.source_ids)
        for line in main
    )
    representation_keys = Counter(
        (
            *r["geometry_px"]["start"],
            *r["geometry_px"]["end"],
            r["geometry_px"]["width"],
            tuple(r["source_ids"]),
        )
        for r in ledger["representations"]
        if r["route_origin"] == "MAIN"
    )
    assert main_keys == representation_keys
    same_main, replay = stroke_presentation(source, main, float(info["DPI"]))
    assert same_main == main and not replay["false_parallel_decisions"]
    _, fresh = stroke_presentation(
        source, seed.straight_lines, float(info["DPI"]), allow_merge=False
    )
    fresh.update(
        {key: old_presentation[key] for key in ("graphic_ownership", "fill_records")}
    )
    refreshed = replace(
        seed, provenance={**seed.provenance, "stroke_presentation": fresh}
    )
    result = replace(result, final_structure=refreshed)
    save_trace_cache(cache, result)
    proof = {
        "main_inputs_replayed": main_count,
        "all_input_digest_verified": ledger["input_set_digest"],
        "source_sha256_verified": ledger["source_image_sha256"],
        "protection_mask": "NONE; stronger no-proposal check",
        "new_merge_decisions": 0,
        "all_main_geometry_unchanged": True,
        "lineweight_changes_in_this_refresh": sum(
            bool(a and b and a["cad_lineweight"] != b["cad_lineweight"])
            for a, b in zip(old_presentation["line_records"], fresh["line_records"])
        ),
    }
    (OUT / "stroke-replay-proof.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8"
    )
    print("Current stroke rule verified on captured full MAIN input", proof, flush=True)
structure = result.final_structure
assert load_trace_cache(cache).final_structure.structure_id == structure.structure_id
print(
    "W03 traced",
    elapsed,
    len(structure.straight_lines),
    "lines",
    len(structure.contours),
    "contours",
    flush=True,
)
target = OUT / "W03"
target.mkdir(exist_ok=True)
cv2.imwrite(str(target / "source.png"), source)
scale = info["PAGE_SIZE_MM"][0] / source.shape[1]
exported = export_final_structure_dxf(
    structure, target / "drawing.dxf", ScaleCalibration((0, 0), (1, 0), scale)
)
before_doc = ezdxf.readfile(BEFORE / "drawing.dxf")
after_doc = ezdxf.readfile(exported.path)
assert not after_doc.audit().has_errors
presentation = metadata_to_jsonable(structure.provenance["stroke_presentation"])
graphics = presentation["graphic_ownership"]


def in_graphic(entity):
    px = entity.dxf.insert.x / scale
    py = source.shape[0] - entity.dxf.insert.y / scale
    return any(
        x <= px <= x + w and y <= py <= y + h
        for x, y, w, h in (g["bbox"] for g in graphics)
    )


before_text = [
    (e.dxf.text, tuple(e.dxf.insert), e.dxf.height, e.dxf.width)
    for e in before_doc.modelspace().query("TEXT")
    if not in_graphic(e)
]
after_text = [
    (e.dxf.text, tuple(e.dxf.insert), e.dxf.height, e.dxf.width)
    for e in after_doc.modelspace().query("TEXT")
]
assert before_text == after_text, (
    "Native TEXT outside source-owned graphics changed: investigate, never fix OCR here"
)
assert len(after_doc.modelspace().query("IMAGE")) == 9
assert len(structure.signatures) == 7
asset_records = []
for e in after_doc.modelspace().query("IMAGE"):
    filename = e.image_def.dxf.filename
    assert ":" not in filename and not Path(filename).is_absolute()
    asset = target / filename
    assert asset.is_file()
    asset_records.append(
        {
            "file": filename,
            "class": e.get_xdata("IMAGE_TO_CAD")[0].value,
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        }
    )
old_assets = {
    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in BEFORE.glob("drawing.*.png")
}
for a in asset_records:
    if a["class"] in ("LOGO", "SIGNATURE"):
        assert old_assets[a["file"]] == a["sha256"], "Existing P2B asset changed"
print("TEXT and 8 P2B assets byte/attribute preserved", flush=True)

editable = ezdxf.readfile(exported.path)
arrow = [
    e
    for e in editable.modelspace().query("IMAGE")
    if e.get_xdata("IMAGE_TO_CAD")[0].value == "GRAPHIC"
]
assert len(arrow) == 1
arrow[0].translate(2, 3, 0)
arrow[0].scale_uniform(1.25)
expected_insert = tuple(arrow[0].dxf.insert)
editable.saveas(target / "move-scale-save-reopen.dxf")
reopened = ezdxf.readfile(target / "move-scale-save-reopen.dxf")
reopened_arrow = [
    e
    for e in reopened.modelspace().query("IMAGE")
    if e.get_xdata("IMAGE_TO_CAD")[0].value == "GRAPHIC"
][0]
assert tuple(reopened_arrow.dxf.insert) == expected_insert
assert not reopened.audit().has_errors
assert len(reopened.modelspace().query("IMAGE")) == 9
reopened.modelspace().delete_entity(reopened_arrow)
reopened.saveas(target / "delete-save-reopen.dxf")
assert (
    len(ezdxf.readfile(target / "delete-save-reopen.dxf").modelspace().query("IMAGE"))
    == 8
)

# Verify the calibrated package against the actual source-unit DXF from the
# same writer. CAD inverse transforms normalize equivalent TEXT angles and
# introduce floating-point noise at integer pixel coordinates; QPainter can
# quantize those infinitesimal changes differently. Never edit the final DXF
# or hide differences with a source overlay.
for e in after_doc.modelspace():
    e.scale_uniform(1 / scale)
source_unit = export_final_structure_dxf(structure, target / "source-unit.dxf")
pixel_doc = ezdxf.readfile(source_unit.path)


def geometry(entity):
    kind = entity.dxftype()
    if kind == "LINE":
        return [*entity.dxf.start, *entity.dxf.end]
    if kind == "LWPOLYLINE":
        return np.asarray(entity.get_points("xyseb")).ravel().tolist()
    if kind == "CIRCLE":
        return [*entity.dxf.center, entity.dxf.radius]
    if kind == "TEXT":
        return [
            *entity.dxf.insert,
            entity.dxf.height,
            entity.dxf.width,
            entity.dxf.rotation % 360,
        ]
    if kind == "IMAGE":
        return [*entity.dxf.insert, *entity.dxf.u_pixel, *entity.dxf.v_pixel]
    if kind == "HATCH":
        return (
            np.asarray([p for boundary in entity.paths for p in boundary.vertices])
            .ravel()
            .tolist()
        )
    raise ValueError(kind)


assert len(after_doc.modelspace()) == len(pixel_doc.modelspace())
geometry_error = 0.0
for calibrated, pixel in zip(after_doc.modelspace(), pixel_doc.modelspace()):
    assert calibrated.dxftype() == pixel.dxftype()
    for attr in ("layer", "color", "lineweight"):
        assert calibrated.dxf.get(attr) == pixel.dxf.get(attr)
    if calibrated.dxftype() == "TEXT":
        assert (
            calibrated.dxf.text == pixel.dxf.text
            and calibrated.dxf.style == pixel.dxf.style
        )
    if calibrated.has_xdata("P3A_STROKE"):
        assert calibrated.get_xdata("P3A_STROKE") == pixel.get_xdata("P3A_STROKE")
    if calibrated.dxftype() == "IMAGE":
        assert (
            hashlib.sha256(
                (target / calibrated.image_def.dxf.filename).read_bytes()
            ).digest()
            == hashlib.sha256(
                (target / pixel.image_def.dxf.filename).read_bytes()
            ).digest()
        )
    error = np.abs(np.asarray(geometry(calibrated)) - np.asarray(geometry(pixel))).max()
    geometry_error = max(geometry_error, float(error))
assert geometry_error < 1e-9, "Calibrated/source-unit entity geometry mismatch"
after = render_emitted_dxf_preview(pixel_doc, target, source.shape[::-1])
assert np.array_equal(after, render_final_structure_preview(structure)), (
    "Preview/final parity failure"
)
inverse_preview = render_emitted_dxf_preview(after_doc, target, source.shape[::-1])
inverse_difference = np.abs(inverse_preview.astype(int) - after.astype(int))
before = cv2.imread(str(BEFORE / "final-preview.png"), cv2.IMREAD_GRAYSCALE)
cv2.imwrite(str(target / "final-preview.png"), after)
(OUT / "stroke-presentation.json").write_text(
    json.dumps(presentation, indent=2), encoding="utf-8"
)

assert len(graphics) == 1
x, y, w, h = graphics[0]["bbox"]
records = presentation["line_records"]
thick_index = max(
    (
        i
        for i, r in enumerate(records)
        if r and structure.straight_lines[i].length > 300
    ),
    key=lambda i: records[i]["source_width_px"],
)
thin_index = next(
    i
    for i, r in enumerate(records)
    if r
    and r["source_width_px"] == 1
    and structure.straight_lines[i].length > 70
    and structure.straight_lines[i].x1 > 4200
    and 800 < structure.straight_lines[i].y1 < 2500
    and abs(structure.straight_lines[i].y1 - structure.straight_lines[i].y2) < 1
)


def line_roi(index, padding=24):
    line = structure.straight_lines[index]
    w = min(320, max(160, int(abs(line.x2 - line.x1)) + 2 * padding + 1))
    h = min(320, max(120, int(abs(line.y2 - line.y1)) + 2 * padding + 1))
    return (
        int((line.x1 + line.x2) / 2) - w // 2,
        int((line.y1 + line.y2) / 2) - h // 2,
        w,
        h,
    )


rois = {
    "full-sheet": (0, 0, source.shape[1], source.shape[0]),
    "north-arrow": (x - 12, y - 12, w + 24, h + 24),
    "title-block": (4260, 770, 370, 1840),
    "thick-rule": line_roi(thick_index),
    "thin-table-rule": line_roi(thin_index),
    "true-double-wall": (1300, 350, 340, 62),
}


def entity_count(doc, rect):
    x, y, w, h = rect
    count = Counter()
    for e in doc.modelspace():
        layer = doc.layers.get(e.dxf.layer)
        if layer.is_off() or layer.is_frozen():
            continue
        extent = bbox.extents([e], fast=True)
        if not extent.has_data:
            continue
        # Original CAD units are paper mm; map bbox back into source pixels.
        left, right = extent.extmin.x / scale, extent.extmax.x / scale
        top, bottom = (
            source.shape[0] - extent.extmax.y / scale,
            source.shape[0] - extent.extmin.y / scale,
        )
        if right >= x and left <= x + w and bottom >= y and top <= y + h:
            count[e.dxftype()] += 1
    return dict(count)


fresh_after = ezdxf.readfile(exported.path)
evidence = {}
for name, rect in rois.items():
    x, y, w, h = rect
    x = max(0, x)
    y = max(0, y)
    w = min(w, source.shape[1] - x)
    h = min(h, source.shape[0] - y)
    crops = [im[y : y + h, x : x + w] for im in (source, before, after)]
    # Same physical crop/scale in all three columns. Tall title blocks remain
    # tall; no aspect distortion is introduced to make the result look better.
    view_scale = min(1, 1000 / max(w, h))
    cw, ch = max(1, round(w * view_scale)), max(1, round(h * view_scale))
    panel = np.full((ch + 38, 3 * cw + 32, 3), 255, np.uint8)
    for i, (im, label) in enumerate(zip(crops, ("SOURCE", "BEFORE CAD", "AFTER CAD"))):
        pos = i * (cw + 16)
        tile = cv2.resize(im, (cw, ch), interpolation=cv2.INTER_AREA)
        panel[38 : 38 + ch, pos : pos + cw] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
        cv2.putText(
            panel,
            label,
            (pos + 5, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(OUT / (name + "-source-before-after.png")), panel)
    evidence[name] = {
        "roi_source_px": [x, y, w, h],
        "geometry_count_before": entity_count(before_doc, (x, y, w, h)),
        "geometry_count_after": entity_count(fresh_after, (x, y, w, h)),
        "count_scope": "visible emitted entities intersecting the source crop; an extending entity counts once",
        "ownership_class": "GRAPHIC OBJECT"
        if name == "north-arrow"
        else "STRUCTURAL GEOMETRY / mixed sheet"
        if name == "full-sheet"
        else "STRUCTURAL GEOMETRY",
        "source_support": graphics[0]["reason"]
        if name == "north-arrow"
        else "original source rules and normal cross-section records",
        "entity_type": "IMAGE"
        if name == "north-arrow"
        else "native LINE/LWPOLYLINE/TEXT and local IMAGE as applicable",
        "source_stroke_width": records[thick_index]
        if name == "thick-rule"
        else records[thin_index]
        if name == "thin-table-rule"
        else "see intersecting line records; graphic retains source pixels",
        "cad_lineweight": records[thick_index]["cad_lineweight"]
        if name == "thick-rule"
        else records[thin_index]["cad_lineweight"]
        if name == "thin-table-rule"
        else "bounded 13/25/50/100 for measured native LINE; IMAGE not applicable",
    }
    intersecting = [
        r
        for line, r in zip(structure.straight_lines, records)
        if max(line.x1, line.x2) >= x
        and min(line.x1, line.x2) <= x + w
        and max(line.y1, line.y2) >= y
        and min(line.y1, line.y2) <= y + h
    ]
    evidence[name]["source_stroke_width_px_counts"] = dict(
        Counter(str(r["source_width_px"]) if r else "UNMEASURED" for r in intersecting)
    )
    evidence[name]["cad_lineweight_counts"] = dict(
        Counter(str(r["cad_lineweight"]) if r else "UNCHANGED" for r in intersecting)
    )


def line_tuple(e):
    return tuple(e.dxf.start), tuple(e.dxf.end)


before_lines = [line_tuple(e) for e in before_doc.modelspace().query("LINE")]
after_lines = [line_tuple(e) for e in fresh_after.modelspace().query("LINE")]
assert before_lines == after_lines, "W03 committed P1 LINE coordinates/order changed"
assert [
    (tuple(e.dxf.center), e.dxf.radius) for e in before_doc.modelspace().query("CIRCLE")
] == [
    (tuple(e.dxf.center), e.dxf.radius)
    for e in fresh_after.modelspace().query("CIRCLE")
]
assert evidence["north-arrow"]["geometry_count_after"] == {"IMAGE": 1}
summary = {
    "source": info,
    "processing_seconds": elapsed,
    "structure_id": structure.structure_id,
    "entities_before": dict(Counter(e.dxftype() for e in before_doc.modelspace())),
    "entities_after": dict(Counter(e.dxftype() for e in fresh_after.modelspace())),
    "native_text_outside_graphic_attributes_exactly_unchanged": True,
    "graphic_owned_native_text_before": [
        e.dxf.text for e in before_doc.modelspace().query("TEXT") if in_graphic(e)
    ],
    "ocr_observations_path": str(ocr_path),
    "ocr_observations_sha256": ocr_sha256,
    "ocr_observations_count": len(candidates),
    "p2b_eight_asset_hashes_unchanged": True,
    "straight_line_tuples_exactly_unchanged": before_lines == after_lines,
    "before_lines_not_in_after": sum(line not in after_lines for line in before_lines),
    "lineweight_counts": dict(
        Counter(r["category"] if r else "UNMEASURED" for r in records)
    ),
    "source_width_px_counts": dict(
        Counter(str(r["source_width_px"]) if r else "UNMEASURED" for r in records)
    ),
    "source_supported_fill_count": len(presentation.get("fill_records", {})),
    "graphic_move_scale_save_reopen_delete": "PASS",
    "false_parallel_decisions": presentation["false_parallel_decisions"],
    "graphics": graphics,
    "assets": asset_records,
    "audit_errors": 0,
    "preview_final_parity": True,
    "preview_parity_scope": "exact pixels against actual source-unit DXF; calibrated DXF entity geometry/weights verified equivalent",
    "calibrated_source_unit_geometry_max_error": geometry_error,
    "inverse_scale_raster_different_pixels": int(np.count_nonzero(inverse_difference)),
    "inverse_scale_raster_max_intensity_delta": int(inverse_difference.max()),
    "evidence": evidence,
}
(OUT / "acceptance.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            k: v
            for k, v in summary.items()
            if k not in ("evidence", "assets", "graphics")
        },
        indent=2,
    ),
    flush=True,
)
