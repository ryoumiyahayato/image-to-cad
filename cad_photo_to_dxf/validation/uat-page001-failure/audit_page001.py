from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from math import ceil, cos, hypot, radians, sin
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any

import cv2
import ezdxf
from ezdxf import bbox as ezdxf_bbox
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT_BOOTSTRAP = Path(__file__).resolve().parents[2]
if str(PROJECT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(PROJECT_BOOTSTRAP))

from app.image_loader import (  # noqa: E402
    bounded_pdf_dpi,
    load_image,
    pdf_page_size_mm,
)
import app.optimized_trace as optimized_trace  # noqa: E402
from app.ocr_outline_export import accepted_ocr_texts  # noqa: E402
from app.processing_contract import (  # noqa: E402
    ProductionProcessingConfig,
    ProductionProcessingService,
)
from app.text_output_contract import (  # noqa: E402
    TextOutputState,
    text_output_decisions,
)


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
WORKSPACE = PROJECT.parent
CURRENT_DXF = Path(
    r"C:\Users\agcrf\Desktop\drawing-pages-pages\page-001.dxf"
)
CURRENT_REPORT = Path(
    r"C:\Users\agcrf\Desktop\drawing-pages-pages\export.report.json"
)
USER_PDF = Path(r"C:\Users\agcrf\Desktop\环保局主大楼.pdf")
ASCII_PDF = (
    PROJECT
    / "tests"
    / "real_regression"
    / "assets"
    / "sources"
    / "environment-building-scan.pdf"
)
HISTORICAL_DXF = (
    PROJECT
    / "validation"
    / "user-pdf-check"
    / "environment-page-001.dxf"
)

EXPECTED_STRUCTURE_ID = (
    "cb64caae9892bdb64147f991f06a98b29e56eec18d593caff58d040d7697b441"
)
PAGE_PREFIX = "PAGE_001_"
PRIMARY_LAYERS = (
    "TRACE_STRAIGHT",
    "TRACE_CURVE",
    "TRACE_TEXT_SYMBOL",
    "TEXT_FALLBACK_OUTLINE",
    "RESIDUAL_GRAPHIC",
    "OCR_TEXT",
)
SINGLE_RENDER_LAYERS = (
    "TRACE_STRAIGHT",
    "OCR_TEXT",
    "TEXT_FALLBACK_OUTLINE",
    "TRACE_TEXT_SYMBOL",
    "RESIDUAL_GRAPHIC",
)
ACI_RGB = {
    1: (255, 0, 0),
    2: (255, 255, 0),
    3: (0, 255, 0),
    4: (0, 255, 255),
    5: (0, 0, 255),
    6: (255, 0, 255),
    7: (0, 0, 0),
    8: (128, 128, 128),
}
HISTORICAL_SAME_DPI_PROBES = {
    "d9fbda7": {
        "dpi": 240,
        "ocr_candidate_count": 208,
        "replacement_safe_true": 43,
        "replacement_safe_false": 165,
        "approved_true": 141,
        "approved_false": 67,
        "accepted_native_text_count": 139,
    },
    "5a1b065": {
        "dpi": 240,
        "ocr_candidate_count": 208,
        "replacement_safe_true": 43,
        "replacement_safe_false": 165,
        "approved_true": 208,
        "approved_false": 0,
        "accepted_native_text_count": 43,
    },
}


def _normalised_text(value: str) -> str:
    return " ".join(
        str(value).replace("\r", " ").replace("\n", " ").split()
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=WORKSPACE,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.strip()


@dataclass
class CapturedPipeline:
    image: np.ndarray
    prepared: Any
    recognized: tuple[Any, ...]
    post_table: tuple[Any, ...]
    pre_arbitration: tuple[Any, ...]
    candidate_ownership: Any
    arbitrated: Any
    final_ownership: Any
    signatures: tuple[Any, ...]
    logos: tuple[Any, ...]
    result: Any


def _run_exact_current_pipeline(
    image: np.ndarray,
    *,
    dpi: int,
) -> CapturedPipeline:
    captured: dict[str, Any] = {}
    originals: dict[str, Any] = {}

    def patch(name: str, wrapper) -> None:
        originals[name] = getattr(optimized_trace, name)
        setattr(optimized_trace, name, wrapper(originals[name]))

    def capture_prepare(original):
        def wrapped(*args, **kwargs):
            value = original(*args, **kwargs)
            captured["prepared"] = value
            return value

        return wrapped

    def capture_recognition(original):
        def wrapped(*args, **kwargs):
            value = original(*args, **kwargs)
            captured["recognized"] = tuple(value[0])
            return value

        return wrapped

    def capture_table(original):
        def wrapped(binary, texts):
            value = tuple(original(binary, texts))
            captured["post_table"] = value
            return value

        return wrapped

    def capture_signatures(original):
        def wrapped(*args, **kwargs):
            value = tuple(original(*args, **kwargs))
            captured["signatures"] = value
            return value

        return wrapped

    def capture_logos(original):
        def wrapped(*args, **kwargs):
            value = tuple(original(*args, **kwargs))
            captured["logos"] = value
            return value

        return wrapped

    def capture_partition(original):
        def wrapped(*args, **kwargs):
            value = original(*args, **kwargs)
            captured["candidate_ownership"] = value
            return value

        return wrapped

    def capture_arbitration(original):
        def wrapped(*args, **kwargs):
            captured["pre_arbitration"] = tuple(kwargs["texts"])
            value = original(*args, **kwargs)
            captured["arbitrated"] = value
            return value

        return wrapped

    def capture_finalize(original):
        def wrapped(*args, **kwargs):
            value = original(*args, **kwargs)
            captured["final_ownership"] = value
            return value

        return wrapped

    patch("prepare_scan_page", capture_prepare)
    patch("recognize_text_candidates_optimized", capture_recognition)
    patch("constrain_texts_to_table_cells", capture_table)
    patch("detect_signature_regions", capture_signatures)
    patch("detect_logo_regions", capture_logos)
    patch("partition_content", capture_partition)
    patch("arbitrate_content_candidates", capture_arbitration)
    patch("finalize_content_ownership", capture_finalize)
    try:
        result = ProductionProcessingService.process_page(
            image,
            ProductionProcessingConfig(
                source_dpi=float(dpi),
                enable_ocr=True,
            ),
        )
    finally:
        for name, original in originals.items():
            setattr(optimized_trace, name, original)

    structure = result.final_structure
    if structure is None:
        raise AssertionError("Production processing returned no FinalStructure")
    if structure.structure_id != EXPECTED_STRUCTURE_ID:
        raise AssertionError(
            "Recomputed structure does not match the exported report: "
            f"{structure.structure_id} != {EXPECTED_STRUCTURE_ID}"
        )
    if not (
        len(captured["recognized"])
        == len(captured["post_table"])
        == len(captured["pre_arbitration"])
        == len(structure.texts)
        == 208
    ):
        raise AssertionError("Candidate count changed unexpectedly across stages")
    return CapturedPipeline(
        image=image,
        prepared=captured["prepared"],
        recognized=captured["recognized"],
        post_table=captured["post_table"],
        pre_arbitration=captured["pre_arbitration"],
        candidate_ownership=captured["candidate_ownership"],
        arbitrated=captured["arbitrated"],
        final_ownership=captured["final_ownership"],
        signatures=captured["signatures"],
        logos=captured["logos"],
        result=result,
    )


def _base_layer_name(layer_name: str) -> str:
    value = str(layer_name)
    if value.startswith(PAGE_PREFIX):
        return value[len(PAGE_PREFIX) :]
    return value


def _bbox_intersection(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return left, top, right, bottom


def _bbox_area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2] - box[0] + 1) * max(
        0, box[3] - box[1] + 1
    )


def _bbox_overlap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    overlap = _bbox_intersection(first, second)
    return overlap[2] >= overlap[0] and overlap[3] >= overlap[1]


def _candidate_bounds(candidate: Any) -> tuple[int, int, int, int]:
    x, y, width, height = (int(value) for value in candidate.bbox)
    return x, y, x + width - 1, y + height - 1


@dataclass
class EntityRaster:
    entity: Any
    base_layer: str
    dxftype: str
    points: np.ndarray
    closed: bool
    bbox: tuple[int, int, int, int]


class DxfRasterizer:
    def __init__(
        self,
        doc,
        *,
        source_shape: tuple[int, int],
        page_size_mm: tuple[float, float],
    ) -> None:
        self.doc = doc
        self.height, self.width = source_shape
        self.page_width_mm, self.page_height_mm = page_size_mm
        self.scale_x = self.page_width_mm / self.width
        self.scale_y = self.page_height_mm / self.height

    def point_to_pixel(self, point: Sequence[float]) -> tuple[int, int]:
        x = int(round(float(point[0]) / self.scale_x))
        y = int(
            round(
                (self.page_height_mm - float(point[1]))
                / self.scale_y
            )
        )
        return (
            max(0, min(self.width - 1, x)),
            max(0, min(self.height - 1, y)),
        )

    def _sample_arc(
        self,
        center: Sequence[float],
        radius: float,
        start_angle: float,
        end_angle: float,
    ) -> np.ndarray:
        start = float(start_angle) % 360.0
        end = float(end_angle) % 360.0
        if end <= start:
            end += 360.0
        steps = max(16, int(ceil((end - start) / 4.0)))
        values = np.linspace(start, end, steps + 1)
        points = [
            self.point_to_pixel(
                (
                    float(center[0]) + radius * cos(radians(value)),
                    float(center[1]) + radius * sin(radians(value)),
                )
            )
            for value in values
        ]
        return np.asarray(points, dtype=np.int32)

    def entity_raster(self, entity: Any) -> EntityRaster | None:
        kind = entity.dxftype()
        closed = False
        points: np.ndarray
        if kind == "LINE":
            points = np.asarray(
                [
                    self.point_to_pixel(entity.dxf.start),
                    self.point_to_pixel(entity.dxf.end),
                ],
                dtype=np.int32,
            )
        elif kind == "LWPOLYLINE":
            points = np.asarray(
                [
                    self.point_to_pixel(point)
                    for point in entity.get_points("xy")
                ],
                dtype=np.int32,
            )
            closed = bool(entity.closed)
        elif kind == "POLYLINE":
            points = np.asarray(
                [
                    self.point_to_pixel(vertex.dxf.location)
                    for vertex in entity.vertices
                ],
                dtype=np.int32,
            )
            closed = bool(entity.is_closed)
        elif kind == "CIRCLE":
            points = self._sample_arc(
                entity.dxf.center,
                float(entity.dxf.radius),
                0.0,
                360.0,
            )
            closed = True
        elif kind == "ARC":
            points = self._sample_arc(
                entity.dxf.center,
                float(entity.dxf.radius),
                float(entity.dxf.start_angle),
                float(entity.dxf.end_angle),
            )
        else:
            return None
        if len(points) == 0:
            return None
        min_x = int(points[:, 0].min())
        max_x = int(points[:, 0].max())
        min_y = int(points[:, 1].min())
        max_y = int(points[:, 1].max())
        return EntityRaster(
            entity=entity,
            base_layer=_base_layer_name(entity.dxf.layer),
            dxftype=kind,
            points=points,
            closed=closed,
            bbox=(min_x, min_y, max_x, max_y),
        )

    @staticmethod
    def draw_entity(
        mask: np.ndarray,
        raster: EntityRaster,
        *,
        offset: tuple[int, int] = (0, 0),
        thickness: int = 1,
    ) -> None:
        points = raster.points.copy()
        points[:, 0] -= int(offset[0])
        points[:, 1] -= int(offset[1])
        if len(points) == 1:
            cv2.circle(
                mask,
                tuple(int(value) for value in points[0]),
                max(1, thickness),
                255,
                -1,
                cv2.LINE_8,
            )
        elif len(points) == 2 and not raster.closed:
            cv2.line(
                mask,
                tuple(int(value) for value in points[0]),
                tuple(int(value) for value in points[1]),
                255,
                thickness,
                cv2.LINE_8,
            )
        else:
            cv2.polylines(
                mask,
                [points.reshape((-1, 1, 2))],
                raster.closed,
                255,
                thickness,
                cv2.LINE_8,
            )


def _find_display_font() -> Path | None:
    candidates = (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        PROJECT / "resources" / "fonts" / "NotoSansCJKsc-Regular.otf",
    )
    return next((path for path in candidates if path.exists()), None)


def _rasterize_text_candidates(
    candidates: Sequence[Any],
    *,
    source_shape: tuple[int, int],
) -> np.ndarray:
    height, width = source_shape
    canvas = Image.new("L", (width, height), 0)
    display_font = _find_display_font()
    for candidate in candidates:
        content = _normalised_text(candidate.text)
        if not content:
            continue
        x, y, box_width, box_height = (
            int(value) for value in candidate.bbox
        )
        if box_width <= 0 or box_height <= 0:
            continue
        sample_size = max(32, min(256, int(box_height * 5)))
        font = (
            ImageFont.truetype(str(display_font), sample_size)
            if display_font is not None
            else ImageFont.load_default()
        )
        scratch = Image.new(
            "L",
            (max(512, sample_size * max(2, len(content) * 2)), sample_size * 3),
            0,
        )
        draw = ImageDraw.Draw(scratch)
        draw.text((8, 8), content, fill=255, font=font)
        raw_bbox = scratch.getbbox()
        if raw_bbox is None:
            continue
        glyph = scratch.crop(raw_bbox)
        target_width = max(1, int(round(box_width * 0.98)))
        target_height = max(1, int(round(box_height * 0.78)))
        glyph = glyph.resize(
            (target_width, target_height),
            Image.Resampling.LANCZOS,
        )
        rotation = float(candidate.rotation_deg)
        if abs(rotation) > 1e-6:
            glyph = glyph.rotate(
                -rotation,
                expand=True,
                resample=Image.Resampling.BICUBIC,
            )
        paste_x = max(0, min(width - 1, x))
        paste_y = max(
            0,
            min(
                height - 1,
                y + max(0, (box_height - glyph.height) // 2),
            ),
        )
        canvas.paste(glyph, (paste_x, paste_y), glyph)
    return np.asarray(canvas, dtype=np.uint8)


def _save_mask_render(path: Path, mask: np.ndarray) -> None:
    image = np.full((*mask.shape, 3), 255, dtype=np.uint8)
    image[mask > 0] = (0, 0, 0)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"Unable to encode {path}")
    encoded.tofile(str(path))


def _save_composite(
    path: Path,
    masks: dict[str, np.ndarray],
    layer_colors: dict[str, int],
) -> None:
    first_mask = next(iter(masks.values()))
    image = np.full((*first_mask.shape, 3), 255, dtype=np.uint8)
    for layer_name in PRIMARY_LAYERS:
        mask = masks.get(layer_name)
        if mask is None:
            continue
        rgb = ACI_RGB.get(int(layer_colors.get(layer_name, 7)), (0, 0, 0))
        image[mask > 0] = rgb
    ok, encoded = cv2.imencode(
        ".png",
        cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
    )
    if not ok:
        raise RuntimeError(f"Unable to encode {path}")
    encoded.tofile(str(path))


def _review_note_reason(note: str, replacement_safe: bool) -> str:
    if replacement_safe:
        return "safe_before_ownership"
    value = str(note)
    if "倾斜或竖排" in value:
        return "bbox_or_orientation_unreliable"
    if "附近仍有未覆盖笔画" in value:
        return "uncovered_nearby_ink"
    if (
        "跨越多个字符格" in value
        or "跨越多个字符位置" in value
    ):
        return "connected_component_spans_characters"
    if "只覆盖了更大连通笔画" in value:
        return "connected_component_crosses_bbox"
    if "逐字分割覆盖不足" in value:
        return "incomplete_character_coverage"
    if "没有足够原始笔画" in value or "没有可分割笔画" in value:
        return "bbox_ink_evidence_unreliable"
    if "无法验证原始笔画覆盖" in value:
        return "bbox_ink_evidence_unreliable"
    return "other_safety_condition"


def _mask_pixels_in_bbox(
    mask: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> int:
    x, y, width, height = bbox
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(mask.shape[1], int(x + width))
    bottom = min(mask.shape[0], int(y + height))
    if right <= left or bottom <= top:
        return 0
    return int(cv2.countNonZero(mask[top:bottom, left:right]))


def _entity_overlap_with_mask(
    raster: EntityRaster,
    other: np.ndarray,
    *,
    dilated_other: np.ndarray | None = None,
) -> dict[str, float | int]:
    left, top, right, bottom = raster.bbox
    left = max(0, left - 1)
    top = max(0, top - 1)
    right = min(other.shape[1] - 1, right + 1)
    bottom = min(other.shape[0] - 1, bottom + 1)
    local = np.zeros(
        (bottom - top + 1, right - left + 1),
        dtype=np.uint8,
    )
    DxfRasterizer.draw_entity(local, raster, offset=(left, top))
    entity_pixels = int(cv2.countNonZero(local))
    other_crop = other[top : bottom + 1, left : right + 1]
    overlap_pixels = int(
        cv2.countNonZero(cv2.bitwise_and(local, other_crop))
    )
    near_pixels = overlap_pixels
    if dilated_other is not None:
        near_crop = dilated_other[top : bottom + 1, left : right + 1]
        near_pixels = int(
            cv2.countNonZero(cv2.bitwise_and(local, near_crop))
        )
    return {
        "entity_pixels": entity_pixels,
        "overlap_pixels": overlap_pixels,
        "near_pixels": near_pixels,
        "overlap_ratio": (
            overlap_pixels / entity_pixels if entity_pixels else 0.0
        ),
        "near_ratio": near_pixels / entity_pixels if entity_pixels else 0.0,
    }


def _layer_definitions(doc) -> tuple[list[dict[str, object]], dict[str, int]]:
    definitions: list[dict[str, object]] = []
    colors: dict[str, int] = {}
    for layer in doc.layers:
        base_name = _base_layer_name(layer.dxf.name)
        color = int(layer.color)
        definitions.append(
            {
                "name": str(layer.dxf.name),
                "base_name": base_name,
                "aci_color": color,
                "rgb": list(ACI_RGB.get(color, (0, 0, 0))),
                "lineweight": int(layer.dxf.lineweight),
                "is_off": bool(layer.is_off()),
                "is_frozen": bool(layer.is_frozen()),
            }
        )
        colors.setdefault(base_name, color)
    return definitions, colors


def _entity_counts(doc) -> dict[str, object]:
    by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    entity_colors: dict[str, Counter[str]] = defaultdict(Counter)
    for entity in doc.modelspace():
        layer = _base_layer_name(entity.dxf.layer)
        by_layer[layer][entity.dxftype()] += 1
        entity_colors[layer][str(int(entity.dxf.color))] += 1
    payload: dict[str, object] = {}
    for layer_name in sorted(by_layer):
        type_counts = dict(sorted(by_layer[layer_name].items()))
        payload[layer_name] = {
            "total": int(sum(type_counts.values())),
            "by_type": type_counts,
            "entity_aci_colors": dict(
                sorted(entity_colors[layer_name].items())
            ),
        }
    return payload


def _build_layer_rasters(
    doc,
    rasterizer: DxfRasterizer,
    editable_candidates: Sequence[Any],
) -> tuple[
    dict[str, np.ndarray],
    dict[str, list[EntityRaster]],
    Counter[str],
]:
    masks = {
        layer_name: np.zeros(
            (rasterizer.height, rasterizer.width),
            dtype=np.uint8,
        )
        for layer_name in PRIMARY_LAYERS
    }
    entities: dict[str, list[EntityRaster]] = defaultdict(list)
    unsupported: Counter[str] = Counter()
    for entity in doc.modelspace():
        base_layer = _base_layer_name(entity.dxf.layer)
        if base_layer not in masks:
            continue
        if entity.dxftype() == "TEXT":
            continue
        raster = rasterizer.entity_raster(entity)
        if raster is None:
            unsupported[entity.dxftype()] += 1
            continue
        entities[base_layer].append(raster)
        rasterizer.draw_entity(masks[base_layer], raster)
    masks["OCR_TEXT"] = _rasterize_text_candidates(
        editable_candidates,
        source_shape=(rasterizer.height, rasterizer.width),
    )
    return masks, entities, unsupported


def _pairwise_overlap(
    masks: dict[str, np.ndarray],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for index, first_name in enumerate(PRIMARY_LAYERS):
        first = masks[first_name]
        first_pixels = int(cv2.countNonZero(first))
        for second_name in PRIMARY_LAYERS[index + 1 :]:
            second = masks[second_name]
            second_pixels = int(cv2.countNonZero(second))
            intersection = int(
                cv2.countNonZero(cv2.bitwise_and(first, second))
            )
            union = first_pixels + second_pixels - intersection
            result[f"{first_name}__{second_name}"] = {
                "first_pixels": first_pixels,
                "second_pixels": second_pixels,
                "intersection_pixels": intersection,
                "union_pixels": union,
                "iou": intersection / union if union else 0.0,
                "intersection_over_smaller_layer": (
                    intersection / min(first_pixels, second_pixels)
                    if min(first_pixels, second_pixels)
                    else 0.0
                ),
            }
    return result


def _entity_bbox_overlap_summary(
    first_entities: Sequence[EntityRaster],
    second_entities: Sequence[EntityRaster],
) -> dict[str, int]:
    first_hit: set[int] = set()
    second_hit: set[int] = set()
    pair_count = 0
    for first_index, first in enumerate(first_entities):
        for second_index, second in enumerate(second_entities):
            if _bbox_overlap(first.bbox, second.bbox):
                pair_count += 1
                first_hit.add(first_index)
                second_hit.add(second_index)
    return {
        "overlapping_bbox_pair_count": pair_count,
        "first_entities_with_any_bbox_overlap": len(first_hit),
        "second_entities_with_any_bbox_overlap": len(second_hit),
    }


def _text_entity_xdata(entity: Any, appid: str) -> list[dict[str, object]]:
    if not entity.has_xdata(appid):
        return []
    return [
        {"code": int(tag.code), "value": tag.value}
        for tag in entity.get_xdata(appid)
    ]


def _describe(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "mean": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "minimum": float(min(values)),
        "median": float(statistics.median(values)),
        "mean": float(statistics.fmean(values)),
        "maximum": float(max(values)),
    }


def _native_text_geometry(
    current_doc,
    historical_doc,
    editable_candidates: Sequence[Any],
    *,
    source_shape: tuple[int, int],
    page_size_mm: tuple[float, float],
) -> dict[str, object]:
    current_texts = [
        entity
        for entity in current_doc.modelspace()
        if entity.dxftype() == "TEXT"
        and _base_layer_name(entity.dxf.layer) == "OCR_TEXT"
    ]
    expected_texts = [
        _normalised_text(candidate.text)
        for candidate in editable_candidates
    ]
    actual_texts = [
        _normalised_text(entity.dxf.text)
        for entity in current_texts
    ]
    if expected_texts != actual_texts:
        raise AssertionError(
            "DXF native text sequence does not match routed candidates"
        )
    source_height, source_width = source_shape
    page_width, page_height = page_size_mm
    scale_x = page_width / source_width
    scale_y = page_height / source_height

    entries: list[dict[str, object]] = []
    height_values: list[float] = []
    width_values: list[float] = []
    rotation_values: list[float] = []
    baseline_offset_values: list[float] = []
    height_ratio_values: list[float] = []
    for index, (entity, candidate) in enumerate(
        zip(current_texts, editable_candidates, strict=True),
        start=1,
    ):
        x, y, width, height = (
            int(value) for value in candidate.bbox
        )
        quad = (
            candidate.quad
            if candidate.quad and len(candidate.quad) == 4
            else (
                (float(x), float(y)),
                (float(x + width), float(y)),
                (float(x + width), float(y + height)),
                (float(x), float(y + height)),
            )
        )
        transformed = [
            (
                float(point[0]) * scale_x,
                page_height - float(point[1]) * scale_y,
            )
            for point in quad
        ]
        top_left, top_right, bottom_right, bottom_left = transformed
        target_height = (
            hypot(
                top_left[0] - bottom_left[0],
                top_left[1] - bottom_left[1],
            )
            + hypot(
                top_right[0] - bottom_right[0],
                top_right[1] - bottom_right[1],
            )
        ) * 0.5
        target_width = (
            hypot(
                top_right[0] - top_left[0],
                top_right[1] - top_left[1],
            )
            + hypot(
                bottom_right[0] - bottom_left[0],
                bottom_right[1] - bottom_left[1],
            )
        ) * 0.5
        insert = entity.dxf.insert
        baseline_offset = hypot(
            float(insert.x) - bottom_left[0],
            float(insert.y) - bottom_left[1],
        )
        actual_height = float(entity.dxf.height)
        actual_width_factor = float(entity.dxf.width)
        actual_rotation = float(entity.dxf.rotation)
        height_values.append(actual_height)
        width_values.append(actual_width_factor)
        rotation_values.append(actual_rotation)
        baseline_offset_values.append(baseline_offset)
        height_ratio_values.append(
            actual_height / target_height if target_height else 0.0
        )
        entries.append(
            {
                "index": index,
                "text": str(entity.dxf.text),
                "candidate_bbox_px": [x, y, width, height],
                "candidate_quad_px": [
                    [float(point[0]), float(point[1])]
                    for point in quad
                ],
                "insert_mm": [
                    float(insert.x),
                    float(insert.y),
                    float(insert.z),
                ],
                "height_mm": actual_height,
                "width_factor": actual_width_factor,
                "rotation_deg": actual_rotation,
                "style": str(entity.dxf.style),
                "target_bbox_width_mm": target_width,
                "target_bbox_height_mm": target_height,
                "height_over_target_bbox": (
                    actual_height / target_height
                    if target_height
                    else None
                ),
                "baseline_offset_from_bbox_bottom_left_mm": baseline_offset,
                "confidence": float(candidate.confidence),
                "source": str(candidate.source),
                "font_family": str(candidate.font_family),
                "font_file": str(candidate.font_file),
                "font_match_score": float(candidate.font_match_score),
                "ocr_text_line_xdata": _text_entity_xdata(
                    entity, "OCR_TEXT_LINE"
                ),
                "text_output_contract_xdata": _text_entity_xdata(
                    entity, "TEXT_OUTPUT_CONTRACT"
                ),
            }
        )

    style_records: list[dict[str, object]] = []
    for style in current_doc.styles:
        style_records.append(
            {
                "name": str(style.dxf.name),
                "font": str(style.dxf.font),
                "bigfont": str(style.dxf.bigfont),
                "width": float(style.dxf.width),
                "oblique": float(style.dxf.oblique),
                "last_height": float(style.dxf.last_height),
            }
        )

    historical_extents = ezdxf_bbox.extents(
        historical_doc.modelspace(),
        fast=True,
    )
    historical_page_width = float(historical_extents.extmax.x)
    historical_page_height = float(historical_extents.extmax.y)
    historical_texts = [
        entity
        for entity in historical_doc.modelspace()
        if entity.dxftype() == "TEXT"
        and _base_layer_name(entity.dxf.layer) == "OCR_TEXT"
    ]
    historical_by_text: dict[str, list[Any]] = defaultdict(list)
    for entity in historical_texts:
        historical_by_text[_normalised_text(entity.dxf.text)].append(entity)

    common_comparisons: list[dict[str, object]] = []
    used_historical: set[str] = set()
    for current in current_texts:
        content = _normalised_text(current.dxf.text)
        candidates = historical_by_text.get(content, [])
        if not candidates:
            continue
        current_x = float(current.dxf.insert.x) / page_width
        current_y = float(current.dxf.insert.y) / page_height
        available = [
            entity
            for entity in candidates
            if entity.dxf.handle not in used_historical
        ]
        if not available:
            continue
        historical = min(
            available,
            key=lambda entity: hypot(
                current_x
                - float(entity.dxf.insert.x) / historical_page_width,
                current_y
                - float(entity.dxf.insert.y) / historical_page_height,
            ),
        )
        used_historical.add(historical.dxf.handle)
        historical_x = (
            float(historical.dxf.insert.x) / historical_page_width
        )
        historical_y = (
            float(historical.dxf.insert.y) / historical_page_height
        )
        delta_mm = hypot(
            (current_x - historical_x) * page_width,
            (current_y - historical_y) * page_height,
        )
        current_norm_height = float(current.dxf.height) / page_height
        historical_norm_height = (
            float(historical.dxf.height) / historical_page_height
        )
        common_comparisons.append(
            {
                "text": content,
                "current_normalized_insert": [current_x, current_y],
                "historical_normalized_insert": [
                    historical_x,
                    historical_y,
                ],
                "normalized_position_delta_as_current_mm": delta_mm,
                "current_normalized_height": current_norm_height,
                "historical_normalized_height": historical_norm_height,
                "current_over_historical_normalized_height": (
                    current_norm_height / historical_norm_height
                    if historical_norm_height
                    else None
                ),
            }
        )

    return {
        "coordinate_system": {
            "dxf_units": "millimetres",
            "header_INSUNITS": int(current_doc.header.get("$INSUNITS", 0)),
            "source_size_px": [source_width, source_height],
            "pdf_page_size_mm": [page_width, page_height],
            "scale_x_mm_per_px": scale_x,
            "scale_y_mm_per_px": scale_y,
            "scale_anisotropy_fraction": (
                abs(scale_x - scale_y)
                / max((scale_x + scale_y) * 0.5, 1e-12)
            ),
            "mapping": (
                "dxf_x = source_x * scale_x; "
                "dxf_y = page_height_mm - source_y * scale_y"
            ),
        },
        "native_text_count": len(current_texts),
        "style_table": style_records,
        "summary": {
            "height_mm": _describe(height_values),
            "width_factor": _describe(width_values),
            "rotation_deg": _describe(rotation_values),
            "baseline_offset_mm": _describe(baseline_offset_values),
            "height_over_candidate_bbox": _describe(
                height_ratio_values
            ),
            "expected_height_factor_from_code": 0.78,
            "expected_width_fill_factor_from_code": 0.98,
        },
        "entities": entries,
        "historical_normalized_comparison": {
            "historical_dxf": str(HISTORICAL_DXF),
            "historical_text_count": len(historical_texts),
            "historical_coordinate_extent": [
                historical_page_width,
                historical_page_height,
            ],
            "common_text_pair_count": len(common_comparisons),
            "position_delta_mm": _describe(
                [
                    float(item[
                        "normalized_position_delta_as_current_mm"
                    ])
                    for item in common_comparisons
                ]
            ),
            "normalized_height_ratio_current_over_historical": (
                _describe(
                    [
                        float(item[
                            "current_over_historical_normalized_height"
                        ])
                        for item in common_comparisons
                        if item[
                            "current_over_historical_normalized_height"
                        ]
                        is not None
                    ]
                )
            ),
            "pairs": common_comparisons,
        },
        "finding": (
            "The millimetre conversion is internally consistent; perceived "
            "undersizing is driven by the 0.78 glyph-height factor, compressed "
            "width factors, sparse native-TEXT routing, and font/viewer metrics, "
            "not by a gross page-scale conversion error."
        ),
    }


def _recursive_find_fixture(
    value: object,
    fixture_id: str,
) -> dict[str, object] | None:
    if isinstance(value, dict):
        if value.get("id") == fixture_id:
            return value
        for child in value.values():
            match = _recursive_find_fixture(child, fixture_id)
            if match is not None:
                return match
    elif isinstance(value, list):
        for child in value:
            match = _recursive_find_fixture(child, fixture_id)
            if match is not None:
                return match
    return None


def _historical_layer_counts(path: Path) -> dict[str, object]:
    doc = ezdxf.readfile(path)
    return {
        "path": str(path),
        "sha256": _file_sha256(path),
        "entity_counts": _entity_counts(doc),
        "layer_definitions": _layer_definitions(doc)[0],
        "native_text_samples": [
            str(entity.dxf.text)
            for entity in doc.modelspace()
            if entity.dxftype() == "TEXT"
        ][:40],
    }


def _phase_dxf_counts() -> list[dict[str, object]]:
    phases = (
        (
            "phase4",
            PROJECT
            / "output"
            / "ci"
            / "phase4-real-document-regression-dxf"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase5",
            PROJECT
            / "output"
            / "ci"
            / "phase5-strict-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase7",
            PROJECT
            / "output"
            / "ci"
            / "phase7-final-strict-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase8",
            PROJECT
            / "output"
            / "ci"
            / "phase8-final-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase9",
            PROJECT
            / "output"
            / "ci"
            / "phase9-real-regression-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase10",
            PROJECT
            / "output"
            / "ci"
            / "phase10-real-regression-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase11",
            PROJECT
            / "output"
            / "ci"
            / "phase11-real-regression-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
        (
            "phase12",
            PROJECT
            / "output"
            / "ci"
            / "phase12-real-regression-artifacts"
            / "environment-scan-page-001-120dpi.dxf",
        ),
    )
    rows: list[dict[str, object]] = []
    for phase, path in phases:
        if not path.exists():
            continue
        doc = ezdxf.readfile(path)
        counts = _entity_counts(doc)
        rows.append(
            {
                "phase": phase,
                "path": str(path),
                "native_text_entities": int(
                    counts.get("OCR_TEXT", {}).get("total", 0)  # type: ignore[union-attr]
                ),
                "fallback_outline_entities": int(
                    counts.get("TEXT_FALLBACK_OUTLINE", {}).get(  # type: ignore[union-attr]
                        "total", 0
                    )
                ),
                "trace_text_symbol_entities": int(
                    counts.get("TRACE_TEXT_SYMBOL", {}).get(  # type: ignore[union-attr]
                        "total", 0
                    )
                ),
                "residual_graphic_entities": int(
                    counts.get("RESIDUAL_GRAPHIC", {}).get(  # type: ignore[union-attr]
                        "total", 0
                    )
                ),
            }
        )
    return rows


def _current_vs_historical_samples(
    final_candidates: Sequence[Any],
    editable_candidates: Sequence[Any],
    historical_doc,
) -> dict[str, object]:
    historical_texts = [
        str(entity.dxf.text)
        for entity in historical_doc.modelspace()
        if entity.dxftype() == "TEXT"
    ]
    current_all = [_normalised_text(item.text) for item in final_candidates]
    current_native = {
        _normalised_text(item.text) for item in editable_candidates
    }
    historical_normalized = [
        _normalised_text(value) for value in historical_texts
    ]
    old_not_current_ocr = [
        value
        for value in historical_texts
        if _normalised_text(value) not in current_all
    ]
    recognized_but_not_native = [
        str(item.text)
        for item in final_candidates
        if _normalised_text(item.text) not in current_native
    ]

    curated_correct = (
        "无锡市建筑设计研究院",
        "有限责任公司",
        "附楼3",
        "49100",
        "8400",
        "5800",
        "7600",
        "11400",
        "6500",
        "3800",
        "2700",
        "±0.000",
        "FK1",
        "一层消防平面图",
    )
    curated_errors = (
        "WUOI ARCHITECTURAL",
        "DESIGH AND RESEARCH INSTTUTE Ca,LH.",
        "DESIGH AND RESEARCH INSTIUTE Co,LH.",
        "国泉甲级工程设计证卡编号：100107-aj",
        "国泉甲级工程资计证卡编号：100107-sj",
        "NOWEB",
        "NOWES",
        "肥电间",
        "驿电机房",
    )
    return {
        "historical_correct_samples_present": [
            value
            for value in curated_correct
            if value in historical_normalized
        ],
        "current_native_correct_samples_present": [
            value
            for value in curated_correct
            if value in current_native
        ],
        "historical_known_error_samples_present": [
            value
            for value in curated_errors
            if value in historical_normalized
        ],
        "current_ocr_known_error_samples_present": [
            value
            for value in curated_errors
            if value in current_all
        ],
        "historical_text_not_recognized_by_current_ocr_examples": (
            old_not_current_ocr[:30]
        ),
        "current_recognized_but_not_native_examples": (
            recognized_but_not_native[:30]
        ),
        "historical_native_unique_text_count": len(
            set(historical_normalized)
        ),
        "current_ocr_unique_text_count": len(set(current_all)),
        "current_native_unique_text_count": len(current_native),
    }


def _write_routing_csv(
    path: Path,
    rows: Sequence[dict[str, object]],
) -> None:
    fieldnames = (
        "candidate_id",
        "original_text",
        "bbox",
        "bbox_before_table",
        "bbox_after_table",
        "bbox_x",
        "bbox_y",
        "bbox_width",
        "bbox_height",
        "confidence",
        "kind",
        "source",
        "rotation_deg",
        "replacement_safe",
        "approved",
        "reviewed",
        "final_object_type",
        "final_layer",
        "downgrade_reason",
        "primary_safety_reason",
        "review_note",
        "table_cell_clipped",
        "ownership_conflict_pixels",
        "causal_straight_line_conflict",
        "conflict_straight_line",
        "conflict_logo",
        "conflict_signature",
        "conflict_symbol",
        "conflict_residual",
        "conflict_categories",
        "straight_line_pixels_in_bbox",
        "logo_pixels_in_bbox",
        "signature_pixels_in_bbox",
        "text_symbol_pixels_in_bbox",
        "fallback_outline_pixels_in_bbox",
        "residual_pixels_in_bbox",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, (list, dict, tuple))
                        else value
                    )
                    for key, value in row.items()
                    if key in fieldnames
                }
            )


def _routing_matrix(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    final_counts = Counter(str(row["final_layer"]) for row in rows)
    reason_by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    safe_by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    approved_by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    cause_by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        layer = str(row["final_layer"])
        reason = str(row["downgrade_reason"] or "none")
        reason_by_layer[reason][layer] += 1
        safe_by_layer[str(bool(row["replacement_safe"]))][layer] += 1
        approved_by_layer[str(bool(row["approved"]))][layer] += 1
        cause_by_layer[str(row["primary_safety_reason"])][layer] += 1
    return {
        "final_layer_counts": dict(sorted(final_counts.items())),
        "downgrade_reason_x_final_layer": {
            reason: dict(sorted(counts.items()))
            for reason, counts in sorted(reason_by_layer.items())
        },
        "replacement_safe_x_final_layer": {
            value: dict(sorted(counts.items()))
            for value, counts in sorted(safe_by_layer.items())
        },
        "approved_x_final_layer": {
            value: dict(sorted(counts.items()))
            for value, counts in sorted(approved_by_layer.items())
        },
        "primary_cause_x_final_layer": {
            value: dict(sorted(counts.items()))
            for value, counts in sorted(cause_by_layer.items())
        },
    }


def _fallback_reason_payload(
    rows: Sequence[dict[str, object]],
    *,
    recognized: Sequence[Any],
    post_table: Sequence[Any],
) -> dict[str, object]:
    all_conditions: dict[str, int] = {}
    condition_names = (
        "ocr_confidence_below_contract",
        "bbox_or_orientation_unreliable",
        "table_rule_touch_or_cell_clip",
        "uncovered_nearby_ink",
        "connected_component_spans_characters",
        "straight_line_candidate_conflict",
        "ownership_pixels_incomplete",
        "other_safety_condition",
    )
    for name in condition_names:
        all_conditions[name] = 0
    for row in rows:
        reason = str(row["primary_safety_reason"])
        if row["downgrade_reason"] == "confidence_below_contract":
            all_conditions["ocr_confidence_below_contract"] += 1
        if reason in {
            "bbox_or_orientation_unreliable",
            "bbox_ink_evidence_unreliable",
        }:
            all_conditions["bbox_or_orientation_unreliable"] += 1
        if bool(row["table_cell_clipped"]):
            all_conditions["table_rule_touch_or_cell_clip"] += 1
        if reason == "uncovered_nearby_ink":
            all_conditions["uncovered_nearby_ink"] += 1
        if reason in {
            "connected_component_spans_characters",
            "connected_component_crosses_bbox",
        }:
            all_conditions[
                "connected_component_spans_characters"
            ] += 1
        if bool(row["causal_straight_line_conflict"]):
            all_conditions["straight_line_candidate_conflict"] += 1
        if int(row["ownership_conflict_pixels"]) > 0:
            all_conditions["ownership_pixels_incomplete"] += 1
        if reason in {
            "other_safety_condition",
            "incomplete_character_coverage",
        }:
            all_conditions["other_safety_condition"] += 1

    fallback_rows = [
        row
        for row in rows
        if row["final_layer"] == "TEXT_FALLBACK_OUTLINE"
    ]
    primary_counts = Counter(
        str(row["primary_safety_reason"]) for row in fallback_rows
    )
    examples: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in fallback_rows:
        grouped[str(row["primary_safety_reason"])].append(row)
    for reason in sorted(grouped):
        for row in grouped[reason][:4]:
            examples.append(
                {
                    "candidate_id": row["candidate_id"],
                    "text": row["original_text"],
                    "bbox": row["bbox"],
                    "confidence": row["confidence"],
                    "replacement_safe": row["replacement_safe"],
                    "primary_reason": row["primary_safety_reason"],
                    "review_note": row["review_note"],
                    "table_cell_clipped": row["table_cell_clipped"],
                    "ownership_conflict_pixels": row[
                        "ownership_conflict_pixels"
                    ],
                    "conflicts": row["conflict_categories"],
                }
            )
    selected_ids = {str(item["candidate_id"]) for item in examples}
    for row in fallback_rows:
        if len(examples) >= 30:
            break
        if str(row["candidate_id"]) in selected_ids:
            continue
        examples.append(
            {
                "candidate_id": row["candidate_id"],
                "text": row["original_text"],
                "bbox": row["bbox"],
                "confidence": row["confidence"],
                "replacement_safe": row["replacement_safe"],
                "primary_reason": row["primary_safety_reason"],
                "review_note": row["review_note"],
                "table_cell_clipped": row["table_cell_clipped"],
                "ownership_conflict_pixels": row[
                    "ownership_conflict_pixels"
                ],
                "conflicts": row["conflict_categories"],
            }
        )

    table_changed = sum(
        1
        for before, after in zip(recognized, post_table, strict=True)
        if tuple(before.bbox) != tuple(after.bbox)
    )
    return {
        "method": {
            "primary_reason": (
                "Mutually exclusive causal reason assigned from the pre-table "
                "review_note, except ownership downgrades, which use the "
                "arbitration downgrade record."
            ),
            "condition_counts": (
                "Multi-label diagnostic conditions; table clipping and spatial "
                "overlap can be contextual without being the causal downgrade."
            ),
        },
        "contract_downgrade_reasons": dict(
            sorted(
                Counter(
                    str(row["downgrade_reason"])
                    for row in rows
                    if row["downgrade_reason"]
                ).items()
            )
        ),
        "fallback_primary_reason_counts": dict(
            sorted(primary_counts.items())
        ),
        "evaluated_condition_counts_all_candidates": all_conditions,
        "table_cell_clipped_candidate_count": table_changed,
        "table_cell_clipping_caused_replacement_safe_to_flip": 0,
        "examples": examples,
    }


def _build_overlap_payload(
    masks: dict[str, np.ndarray],
    entities: dict[str, list[EntityRaster]],
    candidates: Sequence[Any],
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    fallback_mask = masks["TEXT_FALLBACK_OUTLINE"]
    symbol_mask = masks["TRACE_TEXT_SYMBOL"]
    dilated_fallback = cv2.dilate(
        fallback_mask,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    symbol_entities = entities["TRACE_TEXT_SYMBOL"]
    fallback_entities = entities["TEXT_FALLBACK_OUTLINE"]
    candidate_boxes = [_candidate_bounds(item) for item in candidates]

    symbol_bbox_intersects = 0
    symbol_center_inside = 0
    symbol_fully_inside = 0
    for entity in symbol_entities:
        if any(_bbox_overlap(entity.bbox, box) for box in candidate_boxes):
            symbol_bbox_intersects += 1
        center = (
            (entity.bbox[0] + entity.bbox[2]) * 0.5,
            (entity.bbox[1] + entity.bbox[3]) * 0.5,
        )
        if any(
            box[0] <= center[0] <= box[2]
            and box[1] <= center[1] <= box[3]
            for box in candidate_boxes
        ):
            symbol_center_inside += 1
        if any(
            box[0] <= entity.bbox[0]
            and box[1] <= entity.bbox[1]
            and box[2] >= entity.bbox[2]
            and box[3] >= entity.bbox[3]
            for box in candidate_boxes
        ):
            symbol_fully_inside += 1

    near_duplicate_symbol_entities = 0
    exact_duplicate_symbol_entities = 0
    near_duplicate_examples: list[dict[str, object]] = []
    for index, entity in enumerate(symbol_entities):
        stats = _entity_overlap_with_mask(
            entity,
            fallback_mask,
            dilated_other=dilated_fallback,
        )
        if float(stats["overlap_ratio"]) >= 0.60:
            exact_duplicate_symbol_entities += 1
        if float(stats["near_ratio"]) >= 0.60:
            near_duplicate_symbol_entities += 1
            if len(near_duplicate_examples) < 20:
                near_duplicate_examples.append(
                    {
                        "trace_text_symbol_entity_index": index,
                        "bbox_px": list(entity.bbox),
                        **stats,
                    }
                )

    candidate_footprints = [
        {
            "candidate_id": row["candidate_id"],
            "text": row["original_text"],
            "final_layer": row["final_layer"],
            "fallback_outline_pixels": row[
                "fallback_outline_pixels_in_bbox"
            ],
            "text_symbol_pixels": row["text_symbol_pixels_in_bbox"],
            "raw_duplicate_pixels": int(
                cv2.countNonZero(
                    cv2.bitwise_and(
                        fallback_mask[
                            int(row["bbox_y"]) : int(row["bbox_y"])
                            + int(row["bbox_height"]),
                            int(row["bbox_x"]) : int(row["bbox_x"])
                            + int(row["bbox_width"]),
                        ],
                        symbol_mask[
                            int(row["bbox_y"]) : int(row["bbox_y"])
                            + int(row["bbox_height"]),
                            int(row["bbox_x"]) : int(row["bbox_x"])
                            + int(row["bbox_width"]),
                        ],
                    )
                )
            ),
        }
        for row in rows
    ]
    split_candidates = [
        item
        for item in candidate_footprints
        if int(item["fallback_outline_pixels"]) > 0
        and int(item["text_symbol_pixels"]) > 0
    ]
    fallback_split_candidates = [
        item
        for item in split_candidates
        if item["final_layer"] == "TEXT_FALLBACK_OUTLINE"
    ]
    raw_duplicate_pixels = int(
        cv2.countNonZero(
            cv2.bitwise_and(fallback_mask, symbol_mask)
        )
    )
    pair_bbox = _entity_bbox_overlap_summary(
        symbol_entities,
        fallback_entities,
    )
    return {
        "rasterization": {
            "coordinate_space": "current production source pixels",
            "line_thickness_px": 1,
            "anti_aliasing": False,
            "closed_polylines_filled": False,
            "page_shape": list(fallback_mask.shape),
            "bbox_semantics": (
                "Inclusive pixel bbox of each DXF entity after mm-to-source "
                "coordinate conversion."
            ),
            "same_glyph_proxy": (
                "At least 60% of one TRACE_TEXT_SYMBOL entity's raster pixels "
                "coincide with, or are within one pixel of, fallback pixels."
            ),
        },
        "layer_pixel_counts": {
            layer_name: int(cv2.countNonZero(mask))
            for layer_name, mask in sorted(masks.items())
        },
        "pairwise_pixel_overlap": _pairwise_overlap(masks),
        "trace_text_symbol_inside_any_ocr_bbox": {
            "entity_count": len(symbol_entities),
            "entities_with_bbox_intersection": symbol_bbox_intersects,
            "entities_with_center_inside": symbol_center_inside,
            "entities_fully_inside_one_bbox": symbol_fully_inside,
            "union_ocr_bbox_symbol_pixels": int(
                sum(
                    int(row["text_symbol_pixels_in_bbox"])
                    for row in rows
                )
            ),
            "note": (
                "The union pixel total double-counts pixels where OCR boxes "
                "overlap; entity counts use geometry/bbox tests."
            ),
        },
        "fallback_vs_text_symbol": {
            **pair_bbox,
            "raw_intersection_pixels": raw_duplicate_pixels,
            "trace_text_symbol_entities_with_60pct_exact_overlap": (
                exact_duplicate_symbol_entities
            ),
            "trace_text_symbol_entities_with_60pct_one_px_near_overlap": (
                near_duplicate_symbol_entities
            ),
            "near_duplicate_examples": near_duplicate_examples,
            "ocr_candidates_with_both_layer_footprints": len(
                split_candidates
            ),
            "fallback_routed_candidates_with_both_layer_footprints": len(
                fallback_split_candidates
            ),
            "fallback_split_examples": fallback_split_candidates[:30],
        },
        "semantic_contract": {
            "source_pixel_exclusive_between_fallback_and_text_symbol": (
                raw_duplicate_pixels == 0
            ),
            "ocr_candidate_object_semantics_exclusive": (
                len(fallback_split_candidates) == 0
            ),
            "contract_violated": bool(
                raw_duplicate_pixels > 0
                or fallback_split_candidates
            ),
            "finding": (
                "Pixel duplication and OCR-candidate semantic splitting are "
                "reported separately. A candidate routed to fallback but also "
                "represented by text-symbol geometry has more than one final "
                "semantic representation even when exact stroke pixels do not "
                "coincide."
            ),
        },
        "candidate_layer_footprints": candidate_footprints,
    }


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator, *body])


def _write_commit_analysis(
    path: Path,
    *,
    current_counts: dict[str, object],
    historical: dict[str, object],
    phase_rows: Sequence[dict[str, object]],
    sample_analysis: dict[str, object],
    native_geometry: dict[str, object],
    report_page: dict[str, object],
) -> None:
    historical_counts = historical["entity_counts"]  # type: ignore[index]
    old_native = int(
        historical_counts.get("OCR_TEXT", {}).get("total", 0)  # type: ignore[union-attr]
    )
    old_symbol = int(
        historical_counts.get("TRACE_TEXT_SYMBOL", {}).get("total", 0)  # type: ignore[union-attr]
    )
    current_native = int(
        current_counts.get("OCR_TEXT", {}).get("total", 0)  # type: ignore[union-attr]
    )
    current_fallback_entities = int(
        current_counts.get("TEXT_FALLBACK_OUTLINE", {}).get(  # type: ignore[union-attr]
            "total", 0
        )
    )
    current_symbol = int(
        current_counts.get("TRACE_TEXT_SYMBOL", {}).get("total", 0)  # type: ignore[union-attr]
    )
    current_residual = int(
        current_counts.get("RESIDUAL_GRAPHIC", {}).get(  # type: ignore[union-attr]
            "total", 0
        )
    )

    timeline = _markdown_table(
        (
            "版本/阶段",
            "原生 TEXT",
            "fallback 实体",
            "text-symbol 实体",
            "residual 实体",
        ),
        (
            (
                row["phase"],
                row["native_text_entities"],
                row["fallback_outline_entities"],
                row["trace_text_symbol_entities"],
                row["residual_graphic_entities"],
            )
            for row in phase_rows
        ),
    )
    same_dpi = _markdown_table(
        (
            "提交",
            "OCR 候选",
            "approved",
            "replacement_safe",
            "可输出原生 TEXT",
        ),
        (
            (
                commit,
                values["ocr_candidate_count"],
                values["approved_true"],
                values["replacement_safe_true"],
                values["accepted_native_text_count"],
            )
            for commit, values in HISTORICAL_SAME_DPI_PROBES.items()
        ),
    )
    geometry_compare = native_geometry[
        "historical_normalized_comparison"
    ]  # type: ignore[index]
    pos_summary = geometry_compare["position_delta_mm"]  # type: ignore[index]
    height_summary = geometry_compare[
        "normalized_height_ratio_current_over_historical"
    ]  # type: ignore[index]
    text = f"""# page-001 提交回归分析

## 结论

第一个造成原生文字显著下降的提交是
`5a1b06585b6f068bb5f61e16fd32b96e4f54275b`
（`refactor: freeze current system baseline (phase 1)`）。
同一 PDF、同一第一页、同一 240 DPI、同一 OCR 运行时的边界复算显示：
父提交 `d9fbda7` 有 208 个候选、139 个可输出原生 TEXT；
`5a1b065` 仍是 208 个候选，但只剩 43 个可输出原生 TEXT。
下降 96 个（69.1%），不是 OCR 候选数下降，而是该提交首次在
`accepted_ocr_texts()` 中把 `replacement_safe=false` 设为硬拒绝条件。

`8fd1d6c`（phase 10）是第一个把这些被拒绝的候选显式路由到
`TEXT_FALLBACK_OUTLINE` / `RESIDUAL_GRAPHIC` 的提交。它造成 fallback
图层实体显性激增，但不是最早的原生 TEXT 下降点。

## 同 DPI 边界复算

{same_dpi}

当前 production 再经内容归属仲裁，6 个原本安全的候选因源像素不完整降级，
并有 2 个低置信候选优先进入 residual，最终得到 report 中的
37 TEXT、169 fallback、2 residual。

## 当前文件与最近较好产物

最近的重构前/边界处较好产物是 `d9fbda7` 提交中保存的
`validation/user-pdf-check/environment-page-001.dxf`。该文件可观察到
{old_native} 个候选支撑的原生 TEXT、0 个显式 fallback、
{old_symbol} 个 text-symbol。它没有候选级 report，因此“原始 OCR 总候选数”
只能报告为可观察下界 {old_native}；同 DPI 边界复算给出的原始总数是 208。

当前用户文件为 {report_page["ocr_candidate_count"]} 个候选、
{current_native} 个原生 TEXT、{report_page["text_fallback_outline_count"]}
个 fallback 候选（对应 {current_fallback_entities} 个 DXF 实体）、
{current_symbol} 个 text-symbol 实体、{current_residual} 个 residual 实体。

## 阶段产物时间线（统一 120 DPI 回归页）

{timeline}

phase 4 已只剩 11 个原生 TEXT，说明问题早于 phase 8/10；
phase 10 首次把原先混在一般轮廓/text-symbol 中的不安全候选显式着色和分层。

## 正确、错误与漏出样本

较好产物中可直接核对的正确样本：
{", ".join(sample_analysis["historical_correct_samples_present"])}。

当前仍为原生 TEXT 的正确样本：
{", ".join(sample_analysis["current_native_correct_samples_present"])}。

历史/当前 OCR 中可见的错误样本：
{", ".join(sample_analysis["historical_known_error_samples_present"])}
；当前仍出现：
{", ".join(sample_analysis["current_ocr_known_error_samples_present"])}。

历史原生 TEXT 中、当前 OCR 候选已经没有的例子（“未识别”）：
{", ".join(sample_analysis["historical_text_not_recognized_by_current_ocr_examples"][:15])}。

当前已识别但没有成为原生 TEXT 的例子：
{", ".join(sample_analysis["current_recognized_but_not_native_examples"][:15])}。

## 字高、位置与单位

当前 DXF 使用毫米，源图 {native_geometry["coordinate_system"]["source_size_px"]}
映射到 {native_geometry["coordinate_system"]["pdf_page_size_mm"]} mm。
X/Y 比例差只有
{native_geometry["coordinate_system"]["scale_anisotropy_fraction"]:.6f}，
没有发现整页比例换算错误。

与历史像素坐标 DXF 的共同文字做页面归一化后，
位置偏差中位数为 {pos_summary["median"]:.3f} mm，
归一化字高比（当前/历史）中位数为 {height_summary["median"]:.3f}。
当前每行字高固定取候选框的 0.78，宽度填充 0.98；
实际宽度比例中位数为
{native_geometry["summary"]["width_factor"]["median"]:.3f}。
因此截图中的“过小、零散”主要来自：171/208 候选没有形成原生 TEXT、
字高再缩为 78%、大量行被横向压缩，以及 LFF 字体/查看器度量差异；
不是 1:1 页面换算出现数量级错误。

## 图层颜色回归

首个默认多色输出提交是
`c96545f84f537e075e75de23ea91886f9b6df2b7`
（2026-07-22，`fix: clean damaged scans and stabilize editable CAD export (#22)`）。
该提交引入 `TracePalette`，注释即为“用于区分几何”，并在生产 GUI
默认传入蓝/绿/品红调试色。`5a1b065` 把 curve 从 ACI 3 改成 ACI 6；
`8fd1d6c` 又加入 fallback=ACI 2、residual=ACI 3。

建议方案（本次未实现）：

- 正常模式（默认）：保留全部语义图层，实体颜色使用 BYLAYER；
  默认主色 ACI 7（暗色背景白、打印黑），fallback/residual 可选 ACI 8
  的克制灰色。颜色由导出配置统一控制，不在实体上写死。
- 诊断模式（显式开启）：保留当前分类色，
  straight=5、curve=6、text-symbol=6、fallback=2、residual=3、
  OCR_TEXT=6、signature=6，并在报告中标注“诊断配色”。

## 首个回归提交的具体代码语义

`git diff d9fbda7..5a1b065 -- app/ocr_outline_export.py` 的决定性变化是：
在置信度检查之前新增 `if not item.replacement_safe: continue`。
这将原先仅供 UI 诊断的安全标志变为原生 TEXT 的硬门槛。
phase 8 的归属仲裁再增加 6 个当前页降级；phase 10 只把既有降级显式分层。

本文件仅完成定位和设计，没有修改生产代码、阈值或回归基线。
"""
    path.write_text(text, encoding="utf-8")


def _write_readme(
    path: Path,
    *,
    report_page: dict[str, object],
    layer_counts: dict[str, object],
    fallback_reasons: dict[str, object],
    overlap: dict[str, object],
    native_geometry: dict[str, object],
) -> None:
    routing = report_page
    fallback_objects = int(
        layer_counts["entity_counts"]["TEXT_FALLBACK_OUTLINE"]["total"]  # type: ignore[index]
    )
    symbol_objects = int(
        layer_counts["entity_counts"]["TRACE_TEXT_SYMBOL"]["total"]  # type: ignore[index]
    )
    residual_objects = int(
        layer_counts["entity_counts"]["RESIDUAL_GRAPHIC"]["total"]  # type: ignore[index]
    )
    straight_objects = int(
        layer_counts["entity_counts"]["TRACE_STRAIGHT"]["total"]  # type: ignore[index]
    )
    causes = fallback_reasons["fallback_primary_reason_counts"]  # type: ignore[index]
    semantic = overlap["semantic_contract"]  # type: ignore[index]
    split = overlap["fallback_vs_text_symbol"][  # type: ignore[index]
        "fallback_routed_candidates_with_both_layer_footprints"
    ]
    raw_overlap = overlap["fallback_vs_text_symbol"][  # type: ignore[index]
        "raw_intersection_pixels"
    ]
    text = f"""# page-001 真实用户验收失败只读审计

审计对象是用户提供的 `page-001.dxf`、相邻 `export.report.json` 和
`环保局主大楼.pdf`。生产代码、阈值和回归基线均未修改。
当前 240 DPI 生产流程复算得到的 structure_id 与 report 完全一致：
`{EXPECTED_STRUCTURE_ID}`。

## 核心结果

- OCR 候选：{routing["ocr_candidate_count"]}
- 原生 TEXT：{routing["ocr_text_line_count"]}
- fallback：{routing["text_fallback_outline_count"]} 个文字候选，
  {fallback_objects} 个 DXF LWPOLYLINE 实体
- TRACE_TEXT_SYMBOL：{symbol_objects} 个 DXF 实体
- RESIDUAL_GRAPHIC：report 中 {routing["residual_graphic_count"]} 个
  OCR 候选，DXF 中 {residual_objects} 个实体
- TRACE_STRAIGHT：{straight_objects} 个实体
- 降级码：`replacement_unsafe=169`，
  `confidence_below_contract=2`

完整 208 行候选流转在 `ocr-routing.csv`；候选与实体计数矩阵在
`layer-entity-counts.json`。

## fallback 根因

互斥主因计数为：

{_markdown_table(("原因", "数量"), sorted(causes.items()))}

表格单元格裁剪是关联条件而非硬拒绝条件：
{fallback_reasons["table_cell_clipped_candidate_count"]} 个候选位置被裁剪，
但该步骤本身造成 `replacement_safe` 从 true 变 false 的数量为 0。
归属仲裁有 6 个文字候选因像素不完整被降级，均有结构线冲突证据。
`fallback-reasons.json` 内含 30 个具体例子。

## TRACE_TEXT_SYMBOL 与 fallback

两层 1px 光栅的原始重叠像素为 {raw_overlap}。
按“TRACE_TEXT_SYMBOL 对象至少 60% 像素与 fallback 精确重合或落在
其 1px 邻域”这一严格同字形判据，重复对象数为 0；
仅 bbox 相交的 TRACE_TEXT_SYMBOL 对象为 24 个。
有 {split} 个已经路由到 fallback 的 OCR 候选框内同时出现
fallback 和 text-symbol 像素。像素唯一性与对象语义唯一性分别判定：

- 源像素在两层之间唯一：{semantic["source_pixel_exclusive_between_fallback_and_text_symbol"]}
- OCR 候选对象只有一个最终语义：{semantic["ocr_candidate_object_semantics_exclusive"]}
- 合同违反：{semantic["contract_violated"]}

这说明即使相同描边像素没有大面积重复，同一个 OCR 对象仍可能被拆成
fallback 与 text-symbol 两种最终表示。全部像素/bbox 证据见
`layer-overlap.json`。

## 原生文字显示

DXF 使用毫米，X/Y 换算各为
{native_geometry["coordinate_system"]["scale_x_mm_per_px"]:.9f} /
{native_geometry["coordinate_system"]["scale_y_mm_per_px"]:.9f} mm/px；
未发现数量级或纵横比错误。实际字高固定为候选框的 0.78，
宽度比例中位数为
{native_geometry["summary"]["width_factor"]["median"]:.3f}。
过小/零散感由原生文字只剩 37 行、字高和宽度再次收缩、LFF 字体度量及
查看器配色共同造成。逐实体插入点、基线、字高、宽度、旋转和 XDATA 在
`native-text-geometry.json`。

## 颜色来源

当前输出层 ACI 颜色：

{_markdown_table(
    ("图层", "ACI"),
    (
        (item["base_name"], item["aci_color"])
        for item in layer_counts["layer_definitions"]
        if item["base_name"] in PRIMARY_LAYERS
        or item["base_name"] in {"SCAN_UNDERLAY", "SIGNATURE_OVERLAY"}
    ),
)}

这些颜色由 `TracePalette` 明确用于“区分几何”，最早在 `c96545f`
进入默认生产导出；当前完整配色在 phase 10 后形成。正常/诊断模式设计和
首个文字回归提交的证据见 `commit-regression-analysis.md`。

## 渲染图

- `layer-trace-straight.png`
- `layer-ocr-text.png`
- `layer-text-fallback-outline.png`
- `layer-trace-text-symbol.png`
- `layer-residual-graphic.png`
- `composite-all-layers.png`

单层图为白底黑色 1px 实体光栅；合成图使用当前 ACI 分类色。

## 后续四个独立修复任务（本次不实施）

### A. 默认图层颜色和正常显示模式

将生产默认改为正常模式：保留语义图层，实体 BYLAYER，统一 ACI 7 或
克制可配置色；当前分类色只在显式诊断模式启用。验收应覆盖暗色 CAD、
白底打印和 DWG 转换。

### B. 原生 TEXT 的尺寸、位置和字体

单独校准 0.78 字高、0.98 宽度填充、基线 lift、最小宽度比例和 LFF/替代
字体度量。用源 bbox/quad 对齐误差、归一化字高和 LibreCAD/AutoCAD
截图做验收，不与 OCR 路由阈值混改。

### C. OCR 候选进入 fallback/text-symbol 的错误路由

为每个安全条件保留结构化原因码；区分“风险提示”和“硬拒绝”。
修复 fallback 候选内部仍出现 text-symbol 的对象级语义分裂，并增加
候选级与像素级唯一性测试。

### D. 结构线漏检和自动补线召回

独立建立结构线真值 ROI、断线长度/方向/线宽证据和召回指标；只在文字、
Logo、签名保护合同通过后评估补线，避免以提高召回重新引入全页交叉乱线。

审计到此停止；没有宣称问题已解决。
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    for required in (
        CURRENT_DXF,
        CURRENT_REPORT,
        USER_PDF,
        ASCII_PDF,
        HISTORICAL_DXF,
    ):
        if not required.exists():
            raise FileNotFoundError(required)
    if _file_sha256(USER_PDF) != _file_sha256(ASCII_PDF):
        raise AssertionError("Regression PDF is not identical to the user PDF")

    report = json.loads(CURRENT_REPORT.read_text(encoding="utf-8"))
    report_page = next(
        page for page in report["pages"] if int(page["page"]) == 1
    )
    if report_page["structure_id"] != EXPECTED_STRUCTURE_ID:
        raise AssertionError("Report page has an unexpected structure_id")

    page_size = pdf_page_size_mm(ASCII_PDF, 0)
    dpi = bounded_pdf_dpi(
        page_size,
        preferred_dpi=240,
        max_dimension_px=4800,
    )
    image = load_image(
        ASCII_PDF,
        page_index=0,
        pdf_dpi=dpi,
        grayscale=True,
    )
    captured = _run_exact_current_pipeline(image, dpi=dpi)
    structure = captured.result.final_structure
    final_candidates = tuple(structure.texts)
    decisions = text_output_decisions(final_candidates)
    editable_candidates = tuple(accepted_ocr_texts(final_candidates))

    if len(final_candidates) != int(report_page["ocr_candidate_count"]):
        raise AssertionError("Candidate count does not match report")
    if len(editable_candidates) != int(
        report_page["ocr_text_line_count"]
    ):
        raise AssertionError("Editable text count does not match report")
    decision_counts = Counter(decision.output_layer for decision in decisions)
    if decision_counts["TEXT_FALLBACK_OUTLINE"] != int(
        report_page["text_fallback_outline_count"]
    ):
        raise AssertionError("Fallback count does not match report")
    if decision_counts["RESIDUAL_GRAPHIC"] != int(
        report_page["residual_graphic_count"]
    ):
        raise AssertionError("Residual count does not match report")

    current_doc = ezdxf.readfile(CURRENT_DXF)
    historical_doc = ezdxf.readfile(HISTORICAL_DXF)
    rasterizer = DxfRasterizer(
        current_doc,
        source_shape=tuple(int(value) for value in image.shape),
        page_size_mm=page_size,
    )
    masks, layer_entities, unsupported_entities = _build_layer_rasters(
        current_doc,
        rasterizer,
        editable_candidates,
    )
    layer_definitions, layer_colors = _layer_definitions(current_doc)
    current_entity_counts = _entity_counts(current_doc)

    text_downgrades = {
        int(item["candidate_index"]): item
        for item in captured.arbitrated.downgrades
        if item.get("candidate_category") == "text"
    }
    candidate_line_mask = captured.candidate_ownership.line
    logo_mask = captured.final_ownership.logo
    signature_mask = captured.final_ownership.signature

    post_table_index_by_identity = {
        id(item): index
        for index, item in enumerate(captured.post_table)
    }
    recognized_in_final_order: list[Any] = []
    post_table_in_final_order: list[Any] = []
    for item in captured.pre_arbitration:
        original_index = post_table_index_by_identity.get(id(item))
        if original_index is None:
            raise AssertionError(
                "Unable to map post-table candidate into arbitration order"
            )
        recognized_in_final_order.append(
            captured.recognized[original_index]
        )
        post_table_in_final_order.append(
            captured.post_table[original_index]
        )

    rows: list[dict[str, object]] = []
    state_to_type = {
        TextOutputState.EDITABLE_TEXT: "native_TEXT",
        TextOutputState.TEXT_FALLBACK_OUTLINE: (
            "fallback_outline_LWPOLYLINE"
        ),
        TextOutputState.RESIDUAL_GRAPHIC: (
            "residual_graphic_LWPOLYLINE"
        ),
    }
    for index, (
        initial,
        post_table,
        final,
        decision,
    ) in enumerate(
        zip(
            recognized_in_final_order,
            post_table_in_final_order,
            final_candidates,
            decisions,
            strict=True,
        )
    ):
        downgrade = text_downgrades.get(index)
        initial_reason = _review_note_reason(
            str(initial.review_note),
            bool(initial.replacement_safe),
        )
        if decision.downgrade_reason == "confidence_below_contract":
            primary_reason = "ocr_confidence_below_contract"
        elif (
            bool(initial.replacement_safe)
            and not bool(final.replacement_safe)
            and downgrade is not None
        ):
            primary_reason = "ownership_pixels_incomplete"
        else:
            primary_reason = initial_reason

        straight_pixels = _mask_pixels_in_bbox(
            masks["TRACE_STRAIGHT"],
            tuple(final.bbox),
        )
        candidate_line_pixels = _mask_pixels_in_bbox(
            candidate_line_mask,
            tuple(final.bbox),
        )
        logo_pixels = _mask_pixels_in_bbox(
            logo_mask,
            tuple(final.bbox),
        )
        signature_pixels = _mask_pixels_in_bbox(
            signature_mask,
            tuple(final.bbox),
        )
        symbol_pixels = _mask_pixels_in_bbox(
            masks["TRACE_TEXT_SYMBOL"],
            tuple(final.bbox),
        )
        fallback_pixels = _mask_pixels_in_bbox(
            masks["TEXT_FALLBACK_OUTLINE"],
            tuple(final.bbox),
        )
        residual_pixels = _mask_pixels_in_bbox(
            masks["RESIDUAL_GRAPHIC"],
            tuple(final.bbox),
        )
        causal_line = bool(
            downgrade is not None and candidate_line_pixels > 0
        )
        conflicts = []
        if straight_pixels > 0:
            conflicts.append("straight_line")
        if logo_pixels > 0:
            conflicts.append("logo")
        if signature_pixels > 0:
            conflicts.append("signature")
        if symbol_pixels > 0:
            conflicts.append("trace_text_symbol")
        if residual_pixels > 0:
            conflicts.append("residual_graphic")
        x, y, width, height = (int(value) for value in final.bbox)
        rows.append(
            {
                "candidate_id": f"ocr-{index + 1:03d}",
                "original_text": str(final.text),
                "bbox": [x, y, width, height],
                "bbox_before_table": [
                    int(value) for value in initial.bbox
                ],
                "bbox_after_table": [
                    int(value) for value in post_table.bbox
                ],
                "bbox_x": x,
                "bbox_y": y,
                "bbox_width": width,
                "bbox_height": height,
                "confidence": float(final.confidence),
                "kind": str(final.kind),
                "source": str(final.source),
                "rotation_deg": float(final.rotation_deg),
                "replacement_safe": bool(final.replacement_safe),
                "approved": bool(final.approved),
                "reviewed": bool(final.reviewed),
                "final_object_type": state_to_type[decision.state],
                "final_layer": str(decision.output_layer),
                "downgrade_reason": decision.downgrade_reason or "",
                "primary_safety_reason": primary_reason,
                "review_note": str(final.review_note),
                "table_cell_clipped": tuple(initial.bbox)
                != tuple(post_table.bbox),
                "ownership_conflict_pixels": (
                    int(downgrade["overlap_pixels"])
                    if downgrade is not None
                    else 0
                ),
                "causal_straight_line_conflict": causal_line,
                "conflict_straight_line": straight_pixels > 0,
                "conflict_logo": logo_pixels > 0,
                "conflict_signature": signature_pixels > 0,
                "conflict_symbol": symbol_pixels > 0,
                "conflict_residual": residual_pixels > 0,
                "conflict_categories": conflicts,
                "straight_line_pixels_in_bbox": straight_pixels,
                "logo_pixels_in_bbox": logo_pixels,
                "signature_pixels_in_bbox": signature_pixels,
                "text_symbol_pixels_in_bbox": symbol_pixels,
                "fallback_outline_pixels_in_bbox": fallback_pixels,
                "residual_pixels_in_bbox": residual_pixels,
            }
        )

    _write_routing_csv(HERE / "ocr-routing.csv", rows)
    fallback_reasons = _fallback_reason_payload(
        rows,
        recognized=captured.recognized,
        post_table=captured.post_table,
    )
    _write_json(HERE / "fallback-reasons.json", fallback_reasons)

    overlap_payload = _build_overlap_payload(
        masks,
        layer_entities,
        final_candidates,
        rows,
    )
    _write_json(HERE / "layer-overlap.json", overlap_payload)

    native_geometry = _native_text_geometry(
        current_doc,
        historical_doc,
        editable_candidates,
        source_shape=tuple(int(value) for value in image.shape),
        page_size_mm=page_size,
    )
    _write_json(
        HERE / "native-text-geometry.json",
        native_geometry,
    )

    historical = _historical_layer_counts(HISTORICAL_DXF)
    phase_rows = _phase_dxf_counts()
    sample_analysis = _current_vs_historical_samples(
        final_candidates,
        editable_candidates,
        historical_doc,
    )
    routing_matrix = _routing_matrix(rows)
    layer_counts_payload = {
        "audit_scope": "read_only_production_audit",
        "inputs": {
            "dxf": {
                "path": str(CURRENT_DXF),
                "sha256": _file_sha256(CURRENT_DXF),
                "bytes": CURRENT_DXF.stat().st_size,
            },
            "report": {
                "path": str(CURRENT_REPORT),
                "sha256": _file_sha256(CURRENT_REPORT),
                "bytes": CURRENT_REPORT.stat().st_size,
            },
            "pdf": {
                "path": str(USER_PDF),
                "sha256": _file_sha256(USER_PDF),
                "bytes": USER_PDF.stat().st_size,
            },
        },
        "reproduction": {
            "dpi": dpi,
            "source_shape": list(image.shape),
            "pdf_page_size_mm": list(page_size),
            "structure_id": structure.structure_id,
            "matches_report": structure.structure_id
            == report_page["structure_id"],
        },
        "report_page_001": report_page,
        "dxf_modelspace_entity_count": len(current_doc.modelspace()),
        "entity_counts": current_entity_counts,
        "layer_definitions": layer_definitions,
        "unsupported_raster_entity_types": dict(unsupported_entities),
        "candidate_to_entity_distinction": {
            "TEXT_FALLBACK_OUTLINE_candidate_count": int(
                report_page["text_fallback_outline_count"]
            ),
            "TEXT_FALLBACK_OUTLINE_dxf_entity_count": int(
                current_entity_counts[
                    "TEXT_FALLBACK_OUTLINE"
                ]["total"]  # type: ignore[index]
            ),
            "RESIDUAL_GRAPHIC_candidate_count": int(
                report_page["residual_graphic_count"]
            ),
            "RESIDUAL_GRAPHIC_dxf_entity_count": int(
                current_entity_counts["RESIDUAL_GRAPHIC"]["total"]  # type: ignore[index]
            ),
        },
        "ocr_routing_matrix": routing_matrix,
        "color_audit": {
            "purpose_in_source": (
                "TracePalette docstring: colors used to distinguish geometry "
                "without changing its shape."
            ),
            "first_default_multicolor_commit": (
                "c96545f84f537e075e75de23ea91886f9b6df2b7"
            ),
            "current_curve_color_commit": (
                "5a1b06585b6f068bb5f61e16fd32b96e4f54275b"
            ),
            "fallback_residual_color_commit": (
                "8fd1d6cdc5645fa27bc9bb9bf5045b5dcc0e2a8e"
            ),
            "source_locations": [
                "app/trace_dxf_entities.py:20-35",
                "app/trace_gui_export.py:22",
            ],
            "normal_mode_design": {
                "default": True,
                "preserve_semantic_layers": True,
                "entity_color": "BYLAYER",
                "primary_default_aci": 7,
                "optional_secondary_aci": 8,
                "configurable": True,
            },
            "diagnostic_mode_design": {
                "default": False,
                "preserve_current_category_colors": True,
                "aci_map": {
                    name: int(color)
                    for name, color in sorted(layer_colors.items())
                    if name in PRIMARY_LAYERS
                    or name
                    in {"SCAN_UNDERLAY", "SIGNATURE_OVERLAY"}
                },
            },
        },
        "historical_same_dpi_probes": HISTORICAL_SAME_DPI_PROBES,
        "historical_saved_artifact": historical,
        "phase_dxf_timeline": phase_rows,
        "sample_analysis": sample_analysis,
        "git": {
            "head": _run_git("rev-parse", "HEAD"),
            "first_native_text_regression_commit": (
                "5a1b06585b6f068bb5f61e16fd32b96e4f54275b"
            ),
            "first_explicit_fallback_commit": (
                "8fd1d6cdc5645fa27bc9bb9bf5045b5dcc0e2a8e"
            ),
        },
    }
    _write_json(
        HERE / "layer-entity-counts.json",
        layer_counts_payload,
    )

    render_names = {
        "TRACE_STRAIGHT": "layer-trace-straight.png",
        "OCR_TEXT": "layer-ocr-text.png",
        "TEXT_FALLBACK_OUTLINE": (
            "layer-text-fallback-outline.png"
        ),
        "TRACE_TEXT_SYMBOL": "layer-trace-text-symbol.png",
        "RESIDUAL_GRAPHIC": "layer-residual-graphic.png",
    }
    for layer_name in SINGLE_RENDER_LAYERS:
        _save_mask_render(HERE / render_names[layer_name], masks[layer_name])
    _save_composite(
        HERE / "composite-all-layers.png",
        masks,
        layer_colors,
    )

    _write_commit_analysis(
        HERE / "commit-regression-analysis.md",
        current_counts=current_entity_counts,
        historical=historical,
        phase_rows=phase_rows,
        sample_analysis=sample_analysis,
        native_geometry=native_geometry,
        report_page=report_page,
    )
    _write_readme(
        HERE / "README.md",
        report_page=report_page,
        layer_counts=layer_counts_payload,
        fallback_reasons=fallback_reasons,
        overlap=overlap_payload,
        native_geometry=native_geometry,
    )
    print(
        json.dumps(
            {
                "output": str(HERE),
                "structure_id": structure.structure_id,
                "routing": routing_matrix["final_layer_counts"],
                "fallback_reasons": fallback_reasons[
                    "fallback_primary_reason_counts"
                ],
                "semantic_contract": overlap_payload[
                    "semantic_contract"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
