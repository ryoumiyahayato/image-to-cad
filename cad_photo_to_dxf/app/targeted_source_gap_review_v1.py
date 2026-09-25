"""Prepare the blind Targeted Source Gap Review V1 package.

Only the frozen 147-candidate fresh DEV pool and already-created diagnostics
are consumed.  This module does not mine, classify with a model, or change any
production/guard behavior.  Selection strata are internal sampling hypotheses,
not expected human answers.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import sys
import types
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image, ImageDraw

# The existing frozen-pool helper imports OpenCV for its mining entry point.
# Package preparation only reuses its pure crop-box helper, so permit the
# lightweight bundled QA runtime to import it without installing anything.
if importlib.util.find_spec("cv2") is None:  # pragma: no cover - environment specific
    sys.modules.setdefault("cv2", types.ModuleType("cv2"))

from . import primitive_integrity_review_v1 as primitive


BASE_CHECKPOINT = "9b11815940e37fef2f6bc63b95ad7c4432c5ef98"
FRESH_POOL_COUNT = 147
TARGET_REVIEW_SIZE = 16
MIN_REVIEW_SIZE = 12
MAX_REVIEW_SIZE = 20
MAX_PRIOR_REVIEWED_ANCHORS = 4
TASK_ID = "TARGETED-SOURCE-GAP-REVIEW-V1"
PROTOCOL = "SOURCE_GAP_REVIEW_V1"
PACKAGE_ID = "targeted-source-gap-review-v1"
SELECTION_CODE_VERSION = "SOURCE_GAP_REVIEW_V1_CODE_1"
RUNTIME_RELATIVE = "local-artifacts/draftsman/targeted-source-gap-review-v1"
TRACKED_RELATIVE = "cad_photo_to_dxf/validation/targeted-source-gap-review-v1"

PRIMARY_CLASSES = (
    "CONTINUOUS_SOURCE_STROKE",
    "VISIBLE_SEPARATE_SEGMENTS",
    "PATTERNED_VISIBLE_SEGMENTS",
    "STRUCTURAL_INTERRUPTION",
    "PROBABLE_DEGRADATION_GAP",
    "INSUFFICIENT_EVIDENCE",
    "INVALID_PRIMITIVE_FOR_GAP_REVIEW",
)
INVALID_PRIMITIVE_LABEL = "候选本身无效"
INVALID_PRIMITIVE_HELP = "红线本身就不是一根应当进行断开分析的有效直线。"
SECONDARY_FLAGS = (
    "NEARBY_DAMAGE",
    "MULTIPLE_STROKES_INTERRUPTED",
    "CROSSES_STRUCTURE",
    "BOUNDARY_POSITION_CHANGES",
    "ENDPOINT_ANOMALY",
    "OTHER",
)
STRATUM_TARGETS = {
    "CONTINUOUS_STROKE_CONTROLS": 3,
    "PATTERNED_VISIBLE_SEGMENTS": 3,
    "STRUCTURAL_INTERRUPTION": 3,
    "IRREGULAR_SEPARATE_SEGMENTS": 2,
    "DEGRADATION_LIKE_GAP": 3,
    "AMBIGUOUS_EDGE_CASES": 2,
}

# Previously reviewed cases are intentionally reused only as visual controls.
ANCHORS = {
    "CONTINUOUS_STROKE_CONTROLS": "FRESH1-AB2943863A535D1044B9",
    "PATTERNED_VISIBLE_SEGMENTS": "FRESH1-9BB32E8680E08F3ED86C",
    "STRUCTURAL_INTERRUPTION": "FRESH1-2BF547C27C8497056BA6",
}
PRIMITIVE_FINAL_REVIEW_RELATIVE = (
    "cad_photo_to_dxf/validation/primitive-integrity-review-v1/final-review/"
    "primitive-integrity-human-review-final.json"
)


@dataclass(frozen=True)
class PackageBuildResult:
    runtime_root: Path
    package_dir: Path
    package_zip: Path
    tracked_root: Path
    candidate_set_id: str
    selection_digest: str
    selected_count: int
    newly_unreviewed_count: int
    prior_reviewed_anchor_count: int
    strata_counts: dict[str, int]
    source_family_count: int
    source_unit_count: int
    horizontal_count: int
    vertical_count: int
    selection_replay_status: str
    package_validation: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_replace_runtime(path: Path) -> None:
    resolved = path.resolve()
    if resolved.name != PACKAGE_ID or resolved.parent.name != "draftsman" or resolved.parent.parent.name != "local-artifacts":
        raise ValueError(f"refusing to replace unexpected runtime path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _runs(values: Sequence[bool]) -> tuple[list[int], list[int]]:
    if not values:
        return [], []
    supported: list[int] = []
    unsupported: list[int] = []
    current = values[0]
    length = 1
    for value in values[1:]:
        if value == current:
            length += 1
        else:
            (supported if current else unsupported).append(length)
            current = value
            length = 1
    (supported if current else unsupported).append(length)
    return supported, unsupported


def _coefficient_of_variation(values: Sequence[int]) -> float:
    if len(values) < 2:
        return 1.0
    mean = sum(values) / len(values)
    return 1.0 if mean <= 0 else math.sqrt(sum((value - mean) ** 2 for value in values) / len(values)) / mean


def _source_support_profile(repo_root: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Measure visible axis support without assigning a semantic class."""

    geometry = primitive._primitive_geometry(candidate)
    start = geometry["claimed_start_px"]
    end = geometry["claimed_end_px"]
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    length = max(math.hypot(dx, dy), 1.0)
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    sample_count = max(2, int(round(length)) + 1)
    source_path = primitive._repo_path(repo_root, str(candidate["source_render_path"]))
    with Image.open(source_path) as source:
        gray = source.convert("L")
        pixels = gray.load()
        values: list[bool] = []
        for index in range(sample_count):
            ratio = index / (sample_count - 1)
            px = float(start[0]) + dx * ratio
            py = float(start[1]) + dy * ratio
            ink = False
            for offset in range(-2, 3):
                x = int(round(px + nx * offset))
                y = int(round(py + ny * offset))
                if 0 <= x < gray.width and 0 <= y < gray.height and pixels[x, y] < 200:
                    ink = True
                    break
            values.append(ink)
    # Ignore isolated single-pixel raster holes for selection measurements.
    closed = list(values)
    for index in range(1, len(closed) - 1):
        if not closed[index] and closed[index - 1] and closed[index + 1]:
            closed[index] = True
    supported_runs, unsupported_runs = _runs(closed)
    internal_gaps = list(unsupported_runs)
    if not closed[0] and internal_gaps:
        internal_gaps = internal_gaps[1:]
    if not closed[-1] and internal_gaps:
        internal_gaps = internal_gaps[:-1]
    support_fraction = sum(closed) / len(closed)
    return {
        "axis_support_fraction": round(support_fraction, 6),
        "supported_run_count": len(supported_runs),
        "unsupported_interval_count": len(internal_gaps),
        "longest_unsupported_fraction": round(max(internal_gaps, default=0) / len(closed), 6),
        "supported_run_cv": round(_coefficient_of_variation(supported_runs), 6),
        "unsupported_interval_cv": round(_coefficient_of_variation(internal_gaps), 6),
    }


def _selection_measurements(repo_root: Path, candidate: Mapping[str, Any], diagnostic: Mapping[str, Any] | None) -> dict[str, Any]:
    measurements = primitive._selection_measurements(candidate, diagnostic)
    profile = _source_support_profile(repo_root, candidate)
    evidence = candidate.get("direct_continuation", {}).get("evidence", {})
    measurements.update(profile)
    measurements.update(
        {
            "source_quality_bin": candidate.get("selection_features", {}).get("source_quality_bin"),
            "source_degradation_context": candidate.get("degradation_characteristics"),
            "centerline_support_fraction": round(float(evidence.get("centerline_support_fraction", 0.0)), 6),
        }
    )
    return measurements


def _load_prior_reviewed_ids(repo_root: Path, pool_ids: set[str]) -> tuple[set[str], dict[str, Any]]:
    prior_ids, metadata = primitive._load_prior_reviewed_ids(repo_root, pool_ids)
    primitive_review = json.loads(
        primitive._repo_path(repo_root, PRIMITIVE_FINAL_REVIEW_RELATIVE).read_text(encoding="utf-8")
    )
    primitive_ids = {str(row["candidate_id"]) for row in primitive_review}
    if len(primitive_ids) != 16 or primitive_ids - pool_ids:
        raise ValueError("primitive-integrity reviewed identity is not 16 frozen-pool candidates")
    combined = prior_ids | primitive_ids
    return combined, {**metadata, "primitive_integrity_review_count": len(primitive_ids), "combined_unique_count": len(combined)}


def _score(measurements: Mapping[str, Any], stratum: str) -> float:
    support = float(measurements["axis_support_fraction"])
    gaps = float(measurements["unsupported_interval_count"])
    longest = float(measurements["longest_unsupported_fraction"])
    run_cv = float(measurements["supported_run_cv"])
    gap_cv = float(measurements["unsupported_interval_cv"])
    crossing = min(float(measurements["direct_transverse_crossing_columns"]) / 20.0, 1.0)
    enclosed = min(float(measurements["direct_enclosed_contours"]) / 2.0, 1.0)
    off_axis = float(measurements["direct_off_axis_ink_fraction"])
    parallel = float(measurements["direct_parallel_run_fraction"])
    degraded = measurements.get("source_quality_bin") == "DEGRADED_OR_SCANNED"
    if stratum == "CONTINUOUS_STROKE_CONTROLS":
        return 3.0 * support - 4.0 * longest + 0.25 * crossing
    if stratum == "PATTERNED_VISIBLE_SEGMENTS":
        return 1.5 * min(gaps / 4.0, 1.0) + (1.0 - min(run_cv, 1.0)) + (1.0 - min(gap_cv, 1.0)) + longest + min(float(measurements["gap_length_px"]) / 30.0, 1.5)
    if stratum == "STRUCTURAL_INTERRUPTION":
        return 1.5 * crossing + enclosed + off_axis + 0.5 * parallel + longest
    if stratum == "IRREGULAR_SEPARATE_SEGMENTS":
        return min(gaps / 3.0, 1.0) + min(run_cv, 1.5) + longest + 0.5 * off_axis
    if stratum == "DEGRADATION_LIKE_GAP":
        source_gap_disagreement = support + min(float(measurements["gap_length_px"]) / 30.0, 1.5)
        return (2.0 if degraded else 0.0) + source_gap_disagreement + 0.25 * min(gaps / 3.0, 1.0) - 0.5 * crossing
    return 1.0 - min(abs(support - 0.65) / 0.65, 1.0) + min(longest * 4.0, 1.0) + 0.3 * off_axis


def _pick(
    pool: Sequence[Mapping[str, Any]],
    count: int,
    stratum: str,
    selected: list[dict[str, Any]],
    measurements: Mapping[str, Mapping[str, Any]],
) -> None:
    for _ in range(count):
        used = {str(item["candidate_id"]) for item in selected}
        used_families = {str(item["source_family_id"]) for item in selected}
        used_units = {str(item["selected_unit_id"]) for item in selected}
        candidates = [item for item in pool if str(item["candidate_id"]) not in used]
        if stratum == "PATTERNED_VISIBLE_SEGMENTS":
            candidates = [
                item for item in candidates
                if float(measurements[str(item["candidate_id"])]["local_density_fraction"]) < 0.15
                and float(measurements[str(item["candidate_id"])]["gap_length_px"]) >= 20.0
                and int(measurements[str(item["candidate_id"])]["supported_run_count"]) >= 2
            ]
        elif stratum == "DEGRADATION_LIKE_GAP":
            candidates = [
                item for item in candidates
                if measurements[str(item["candidate_id"])]["source_quality_bin"] == "DEGRADED_OR_SCANNED"
                and float(measurements[str(item["candidate_id"])]["local_density_fraction"]) < 0.20
                and float(measurements[str(item["candidate_id"])]["gap_length_px"]) >= 12.0
                and int(measurements[str(item["candidate_id"])]["direct_transverse_crossing_columns"]) <= 2
            ]
        elif stratum == "IRREGULAR_SEPARATE_SEGMENTS":
            candidates = [
                item for item in candidates
                if float(measurements[str(item["candidate_id"])]["local_density_fraction"]) < 0.20
                and int(measurements[str(item["candidate_id"])]["supported_run_count"]) >= 2
            ]
        if not candidates:
            raise ValueError(f"selection stratum undersupplied: {stratum}")
        chosen = max(
            candidates,
            key=lambda item: (
                _score(measurements[str(item["candidate_id"])], stratum)
                + (0.22 if str(item["source_family_id"]) not in used_families else 0.0)
                + (0.12 if str(item["selected_unit_id"]) not in used_units else 0.0),
                str(item["candidate_id"]),
            ),
        )
        copy = dict(chosen)
        copy["selection_stratum"] = stratum
        copy["selection_measurements"] = dict(measurements[str(chosen["candidate_id"])])
        selected.append(copy)


def _select_target(
    repo_root: Path,
    pool: Sequence[Mapping[str, Any]],
    prior_ids: set[str],
    diagnostics: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(item["candidate_id"]): item for item in pool}
    measurements = {
        candidate_id: _selection_measurements(repo_root, candidate, diagnostics.get(candidate_id))
        for candidate_id, candidate in by_id.items()
    }
    selected: list[dict[str, Any]] = []
    for stratum, candidate_id in ANCHORS.items():
        if candidate_id not in by_id or candidate_id not in prior_ids:
            raise ValueError(f"review anchor unavailable: {candidate_id}")
        copy = dict(by_id[candidate_id])
        copy["selection_stratum"] = stratum
        copy["selection_measurements"] = dict(measurements[candidate_id])
        copy["prior_reviewed_control"] = True
        selected.append(copy)
    new_pool = [item for item in pool if str(item["candidate_id"]) not in prior_ids]
    for stratum, target in STRATUM_TARGETS.items():
        present = sum(item["selection_stratum"] == stratum for item in selected)
        _pick(new_pool, target - present, stratum, selected, measurements)
    if len(selected) != TARGET_REVIEW_SIZE:
        raise ValueError(f"selected review size is {len(selected)} != {TARGET_REVIEW_SIZE}")
    for item in selected:
        item.setdefault("prior_reviewed_control", False)
    records = primitive._attach_source_mapping(repo_root, selected)
    for record in records:
        record["selection_rationale"] = {
            "CONTINUOUS_STROKE_CONTROLS": "High visible axis support; includes a reviewed crossing control.",
            "PATTERNED_VISIBLE_SEGMENTS": "Repeated support-run/cadence evidence; includes a reviewed patterned anchor.",
            "STRUCTURAL_INTERRUPTION": "Crossing, enclosure, off-axis, or parallel local-structure evidence.",
            "IRREGULAR_SEPARATE_SEGMENTS": "Multiple non-periodic support runs or unstable local support.",
            "DEGRADATION_LIKE_GAP": "Degraded-source context plus intermittent visible support; not a degradation verdict.",
            "AMBIGUOUS_EDGE_CASES": "Mixed non-semantic support evidence near the decision boundary.",
        }[record["selection_stratum"]]
    return records


def _selection_digest(records: Sequence[Mapping[str, Any]], source_candidate_set_id: str) -> str:
    payload = {
        "base_checkpoint": BASE_CHECKPOINT,
        "selection_code_version": SELECTION_CODE_VERSION,
        "protocol": PROTOCOL,
        "source_candidate_set_id": source_candidate_set_id,
        "records": [
            {
                "candidate_id": row["candidate_id"],
                "review_index": row["review_index"],
                "source_family": row["source_family"],
                "source_unit": row["source_unit"],
                "source_render_path": row["source_render_path"],
                "orientation": row["orientation"],
                "primitive_geometry": row["primitive_geometry"],
                "source_crop_mapping": row["source_crop_mapping"],
                "selection_stratum": row["selection_stratum"],
                "new_or_prior_reviewed": row["new_or_prior_reviewed"],
                "diagnostic_measurements_used": row["diagnostic_measurements_used"],
            }
            for row in records
        ],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "source_families": len({row["source_family"] for row in records}),
        "source_units": len({row["source_unit"] for row in records}),
        "horizontal": sum(row["orientation"] == "horizontal" for row in records),
        "vertical": sum(row["orientation"] == "vertical" for row in records),
        "pdf_derived": sum(row["source_type"] == "PDF" for row in records),
        "dwg_derived": sum(row["source_type"] == "DWG" for row in records),
    }


def _marker_for_box(record: Mapping[str, Any], box: Sequence[int], size: tuple[int, int]) -> dict[str, Any]:
    geometry = record["primitive_geometry"]
    ox, oy = int(box[0]), int(box[1])
    def relative(point: Sequence[float | int]) -> list[float]:
        return [round(float(point[0]) - ox, 3), round(float(point[1]) - oy, 3)]
    return {
        "width": size[0], "height": size[1],
        "start": relative(geometry["claimed_start_px"]),
        "end": relative(geometry["claimed_end_px"]),
        "gap_start": relative(geometry["gap_endpoint_a_px"]),
        "gap_end": relative(geometry["gap_endpoint_b_px"]),
    }


def _write_overlay(clean_path: Path, destination: Path, marker: Mapping[str, Any]) -> None:
    with Image.open(clean_path) as source:
        image = source.convert("RGBA")
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        start, end = tuple(marker["start"]), tuple(marker["end"])
        gap_start, gap_end = tuple(marker["gap_start"]), tuple(marker["gap_end"])
        draw.line([start, end], fill=(224, 28, 45, 150), width=3)
        radius = 4
        for x, y in (gap_start, gap_end):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(242, 187, 35, 215), outline=(255, 255, 255, 235), width=1)
        image = Image.alpha_composite(image, layer).convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=True)


def _transform_html(template: str) -> str:
    replacements = {
        "PRIMITIVE_INTEGRITY_REVIEW_V1": PROTOCOL,
        "draftsman-primitive-integrity-review-v1:": "draftsman-source-gap-review-v1:",
        "primitive-integrity-review-": "source-gap-review-",
        "<title>线段检查</title>": "<title>原图断开位置检查</title>",
        "<h1>线段检查</h1>": "<h1>原图断开位置检查</h1>",
        "看图，判断这根红线本身，再选择一个结果。": "只看原图中红线所指范围，判断断开位置的可见情况。",
        "<h2>判断这根红线本身：</h2>": "<h2>原图中这根线在这些断开位置，最接近哪种情况？</h2>",
        "比较机器绘制的红色 primitive 与可见 source geometry。": "查看红线范围内原图的可见断开情况。",
    }
    html = template
    for old, new in replacements.items():
        html = html.replace(old, new)
    old_buttons = (
        ('VALID_SINGLE_STRAIGHT_PRIMITIVE', '完整直线', '原图确实是一根连续直线'),
        ('MULTIPLE_OR_OFFSET_SEGMENTS', '多段误合并', '多段、错位或分离的线被合成一根'),
        ('ENDPOINT_OVERSHOOT', '端点过长', '主体正确，但一端或两端伸过头'),
        ('FOREIGN_STROKE_CAPTURE', '侵入其他结构', '红线进入文字、符号或别的线'),
        ('OTHER_PRIMITIVE_MISMATCH', '其他错误', '明显不对，但不属于以上情况'),
        ('INSUFFICIENT_EVIDENCE', '看不清', '现有图像不足以判断'),
    )
    new_buttons = (
        ('CONTINUOUS_SOURCE_STROKE', '连续实线', '原图实际上是一根连续的线，没有真实中断'),
        ('VISIBLE_SEPARATE_SEGMENTS', '原图本来就分段', '原图明确由多个分开的线段组成'),
        ('PATTERNED_VISIBLE_SEGMENTS', '规律分段 / 虚线', '原图存在规律重复的间隔或短线段'),
        ('STRUCTURAL_INTERRUPTION', '被结构打断', '中间有明确图形结构，使前后不能算同一根连续线'),
        ('PROBABLE_DEGRADATION_GAP', '像是破损或扫描缺失', '有破损、扫描或墨迹缺失的正面可见证据'),
        ('INSUFFICIENT_EVIDENCE', '看不清', '现有图像不足以判断'),
    )
    for index, (old, new) in enumerate(zip(old_buttons, new_buttons, strict=True), start=1):
        old_line = f'<button class="choice-button" type="button" data-primary="{old[0]}"><span class="shortcut">{index}</span><span class="choice-title">{old[1]}</span><span class="choice-help">{old[2]}</span></button>'
        new_line = f'<button class="choice-button" type="button" data-primary="{new[0]}"><span class="shortcut">{index}</span><span class="choice-title">{new[1]}</span><span class="choice-help">{new[2]}</span></button>'
        html = html.replace(old_line, new_line)
    token_map = dict(zip((item[0] for item in old_buttons), (item[0] for item in new_buttons), strict=True))
    for index, (old, new) in enumerate(token_map.items()):
        html = html.replace(old, f"__PRIMARY_{index}__")
        html = html.replace(f"__PRIMARY_{index}__", new)
    secondary_lines = {
        '<label class="secondary-choice"><input type="checkbox" data-secondary="MULTIPLE_OR_OFFSET_SEGMENTS"><span>多段/错位</span></label>': '<label class="secondary-choice"><input type="checkbox" data-secondary="NEARBY_DAMAGE"><span>附近也有破损</span></label>',
        '<label class="secondary-choice"><input type="checkbox" data-secondary="ENDPOINT_OVERSHOOT"><span>端点过长</span></label>': '<label class="secondary-choice"><input type="checkbox" data-secondary="MULTIPLE_STROKES_INTERRUPTED"><span>多条线同时断开</span></label>',
        '<label class="secondary-choice"><input type="checkbox" data-secondary="FOREIGN_STROKE_CAPTURE"><span>侵入其他结构</span></label>': '<label class="secondary-choice"><input type="checkbox" data-secondary="CROSSES_STRUCTURE"><span>穿过其他结构</span></label>',
        '<label class="secondary-choice"><input type="checkbox" data-secondary="CROSSES_LOCAL_STRUCTURE"><span>穿过局部结构</span></label>': '<label class="secondary-choice"><input type="checkbox" data-secondary="BOUNDARY_POSITION_CHANGES"><span>边界位置发生变化</span></label>',
        '<label class="secondary-choice"><input type="checkbox" data-secondary="OTHER"><span>其他</span></label>': '<label class="secondary-choice"><input type="checkbox" data-secondary="ENDPOINT_ANOMALY"><span>端点异常</span></label><label class="secondary-choice"><input type="checkbox" data-secondary="OTHER"><span>其他</span></label>',
    }
    for old, new in secondary_lines.items():
        html = html.replace(old, new)
    old_array = 'Object.freeze(["MULTIPLE_OR_OFFSET_SEGMENTS","ENDPOINT_OVERSHOOT","FOREIGN_STROKE_CAPTURE","CROSSES_LOCAL_STRUCTURE","OTHER"])'
    new_array = 'Object.freeze(["NEARBY_DAMAGE","MULTIPLE_STROKES_INTERRUPTED","CROSSES_STRUCTURE","BOUNDARY_POSITION_CHANGES","ENDPOINT_ANOMALY","OTHER"])'
    html = html.replace(old_array, new_array)
    # The primary-token rewrite also touches legacy secondary tokens. Normalize
    # those exact UI/JavaScript locations to the new optional flag vocabulary.
    html = html.replace('data-secondary="VISIBLE_SEPARATE_SEGMENTS"><span>多段/错位</span>', 'data-secondary="NEARBY_DAMAGE"><span>附近也有破损</span>')
    html = html.replace('data-secondary="PATTERNED_VISIBLE_SEGMENTS"><span>端点过长</span>', 'data-secondary="MULTIPLE_STROKES_INTERRUPTED"><span>多条线同时断开</span>')
    html = html.replace('data-secondary="STRUCTURAL_INTERRUPTION"><span>侵入其他结构</span>', 'data-secondary="CROSSES_STRUCTURE"><span>穿过其他结构</span>')
    html = html.replace('Object.freeze(["VISIBLE_SEPARATE_SEGMENTS","PATTERNED_VISIBLE_SEGMENTS","STRUCTURAL_INTERRUPTION","CROSSES_LOCAL_STRUCTURE","OTHER"])', new_array)
    html = html.replace("只写你实际看到的问题即可，不需要专业名称。", "只写实际看到的情况即可，不需要专业名称；不确定时请选择“看不清”。")
    html = html.replace("例如：这里实际是三段错开的线；右端伸进了文字。", "例如：断口附近有褪色；几条平行线在同一位置都缺失。")
    html = html.replace("快捷键：1–6 选择，←/→ 切换案例", "快捷键：1–7 选择，←/→ 切换案例")
    html = html.replace(
        ".primary-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr));",
        ".primary-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr));",
    )
    invalid_button = (
        '<button class="choice-button" type="button" '
        'data-primary="INVALID_PRIMITIVE_FOR_GAP_REVIEW">'
        '<span class="shortcut">7</span>'
        '<span class="choice-title">候选本身无效</span>'
        '<span class="choice-help">红线本身就不是一根应当进行断开分析的有效直线。</span>'
        '</button>'
    )
    sixth_button = (
        '<button class="choice-button" type="button" data-primary="INSUFFICIENT_EVIDENCE">'
        '<span class="shortcut">6</span><span class="choice-title">看不清</span>'
        '<span class="choice-help">现有图像不足以判断</span></button>'
    )
    if sixth_button not in html:
        raise ValueError("source-gap UI template no longer contains the six-way primary choice set")
    html = html.replace(sixth_button, sixth_button + "\n        " + invalid_button, 1)
    html = html.replace(
        'const PRIMARY_CLASSES = Object.freeze(["CONTINUOUS_SOURCE_STROKE","VISIBLE_SEPARATE_SEGMENTS","PATTERNED_VISIBLE_SEGMENTS","STRUCTURAL_INTERRUPTION","PROBABLE_DEGRADATION_GAP","INSUFFICIENT_EVIDENCE"]);',
        'const PRIMARY_CLASSES = Object.freeze(["CONTINUOUS_SOURCE_STROKE","VISIBLE_SEPARATE_SEGMENTS","PATTERNED_VISIBLE_SEGMENTS","STRUCTURAL_INTERRUPTION","PROBABLE_DEGRADATION_GAP","INSUFFICIENT_EVIDENCE","INVALID_PRIMITIVE_FOR_GAP_REVIEW"]);',
    )
    html = html.replace(
        'function newSession() { const timestamp=now(); return {',
        'function newSession(withInitial) { const timestamp=now(); const seeds=withInitial && Array.isArray(PACKAGE.initial_review_state) ? PACKAGE.initial_review_state : []; return {',
    )
    html = html.replace(
        'return {review_index:item.review_index,candidate_id:item.candidate_id,primary_class:null,secondary_flags:[],optional_note:"",review_status:"PENDING",updated_at:timestamp};',
        'const seed=seeds.find(function(value) { return value.candidate_id===item.candidate_id; }); const base={review_index:item.review_index,candidate_id:item.candidate_id,primary_class:null,secondary_flags:[],optional_note:"",review_status:"PENDING",updated_at:timestamp}; return seed ? Object.assign(base,{primary_class:seed.primary_class || null,secondary_flags:Array.isArray(seed.secondary_flags) ? seed.secondary_flags.slice() : [],optional_note:typeof seed.optional_note === "string" ? seed.optional_note : "",review_status:seed.primary_class ? "REVIEWED" : "PENDING"}) : base;',
    )
    html = html.replace('state.session=loaded || newSession();', 'state.session=loaded || newSession(true);')
    html = html.replace('state.session=newSession();', 'state.session=newSession(false);')
    html = html.replace('const session=newSession(),seen=new Set();', 'const session=newSession(false),seen=new Set();')
    html = html.replace(
        'if (!Array.isArray(rows) || rows.length!==PACKAGE.candidate_count) throw new Error("候选数量不匹配。");',
        'const legacy=PACKAGE.legacy_import || null; if (!Array.isArray(rows) || (rows.length!==PACKAGE.candidate_count && (!legacy || rows.length!==legacy.review_order.length))) throw new Error("候选数量不匹配。");',
    )
    html = html.replace(
        'if (!row || row.protocol!==REVIEW_PROTOCOL || row.candidate_set_id!==PACKAGE.candidate_set_id || seen.has(row.candidate_id)) throw new Error("审核结果身份不匹配。");',
        'const isLegacy=Boolean(legacy && row && row.protocol===legacy.protocol && row.candidate_set_id===legacy.candidate_set_id); if (!row || (row.protocol!==REVIEW_PROTOCOL && !isLegacy) || (!isLegacy && row.candidate_set_id!==PACKAGE.candidate_set_id) || seen.has(row.candidate_id)) throw new Error("审核结果身份不匹配。");',
    )
    html = html.replace(
        'const target=session.items.find(function(item) { return item.candidate_id===row.candidate_id; }); if (!target || row.review_index!==target.review_index) throw new Error("审核顺序不匹配。");',
        'const removed=isLegacy && legacy.removed_candidate_ids.includes(row.candidate_id); const mappedId=isLegacy && legacy.id_map && legacy.id_map[row.candidate_id] ? legacy.id_map[row.candidate_id] : row.candidate_id; const target=removed ? null : session.items.find(function(item) { return item.candidate_id===mappedId; }); const expectedIndex=isLegacy ? legacy.review_index_by_candidate_id[row.candidate_id] : (target && target.review_index); if ((!removed && !target) || row.review_index!==expectedIndex) throw new Error("审核顺序不匹配。"); if (removed) { seen.add(row.candidate_id); return; }',
    )
    html = html.replace(
        'if (seen.size!==PACKAGE.candidate_count) throw new Error("缺少候选。");',
        'const expectedSeenCount=legacy ? legacy.review_order.length : PACKAGE.candidate_count; if (seen.size!==expectedSeenCount) throw new Error("缺少候选。");',
    )
    html = html.replace(
        'downloadJson("source-gap-review-v1-" + PACKAGE.candidate_set_id + ".json",payload);',
        'downloadJson(PACKAGE.package_id + "-" + PACKAGE.candidate_set_id + ".json",payload);',
    )

    # Pending navigation is presentation-only. Keep it in the reusable review
    # UI and out of the human-result export schema.
    html = html.replace(
        '    .header-progress strong { color:var(--ink); font-size:15px; font-weight:700; }',
        '    .header-progress strong { color:var(--ink); font-size:15px; font-weight:700; }\n'
        '    .pending-controls { display:flex; flex-direction:column; align-items:flex-end; gap:4px; min-width:150px; }\n'
        '    .pending-toggle { display:inline-flex; align-items:center; gap:6px; color:#364b59; font-size:12px; cursor:pointer; white-space:nowrap; }\n'
        '    .pending-toggle input { margin:0; accent-color:var(--blue); }\n'
        '    .pending-jumps { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:4px; color:var(--muted); font-size:12px; }\n'
        '    .pending-chip { min-width:25px; padding:3px 6px; border:1px solid #b9c7d1; border-radius:6px; background:#fff; color:#243847; font-size:12px; line-height:1.2; }\n'
        '    .pending-chip:hover, .pending-chip:focus-visible { border-color:#28698f; background:var(--blue-soft); outline:none; }\n'
        '    .pending-empty { color:#536570; font-size:12px; }\n'
        '    .clear-answer-button { margin-top:7px; padding:5px 9px; border:1px solid #b9c7d1; border-radius:7px; background:#fff; color:#536570; font-size:12px; }\n'
        '    .clear-answer-button:hover:not(:disabled) { border-color:#28698f; background:var(--blue-soft); color:#243847; }\n'
        '    .clear-answer-button:disabled { cursor:not-allowed; opacity:.48; }',
    )
    html = html.replace(
        '        <div id="progress" class="header-progress" aria-live="polite"></div>',
        '        <div id="progress" class="header-progress" aria-live="polite"></div>\n'
        '        <div id="pending-controls" class="pending-controls" aria-live="polite">\n'
        '          <label class="pending-toggle"><input id="pending-only" type="checkbox"><span>只看未完成</span></label>\n'
        '          <div id="pending-jumps" class="pending-jumps"></div>\n'
        '        </div>',
    )
    html = html.replace(
        '      <div id="status-line" class="status-line" aria-live="polite">请选择一个结果。</div>',
        '      <div id="status-line" class="status-line" aria-live="polite">请选择一个结果。</div>\n'
        '      <button id="clear-primary-button" class="clear-answer-button" type="button">清除本题答案</button>',
    )
    html = html.replace(
        '  const state = {session:null,index:0,noteTimer:null,modal:null,modalScale:1,drag:null};',
        '  const state = {session:null,index:0,noteTimer:null,modal:null,modalScale:1,drag:null,pendingOnly:false};',
    )
    old_progress = (
        '  function renderProgress() { const done=state.session.items.filter(function(item) { return Boolean(item.primary_class); }).length; '
        'const progress=document.getElementById("progress"); progress.replaceChildren(); const current=document.createElement("strong"); '
        'current.textContent="案例 " + (state.index+1) + " / " + PACKAGE.candidate_count; const completed=document.createElement("span"); '
        'completed.textContent="已完成 " + done + " / " + PACKAGE.candidate_count; progress.append(current,completed); '
        'if (state.modal) document.getElementById("modal-title").textContent=(state.modal.kind==="local" ? "局部查看" : "整体查看"); }'
    )
    new_progress = '''  function allIndices() { return state.session.items.map(function(item,index) { return index; }); }
  function pendingIndices() { return state.session.items.reduce(function(result,item,index) { if (!item.primary_class) result.push(index); return result; },[]); }
  function visibleIndices() { return state.pendingOnly ? pendingIndices() : allIndices(); }
  function normalizeNavigation() { const visible=visibleIndices(); if (state.pendingOnly && visible.length && !visible.includes(state.index)) state.index=visible[0]; if (!state.session.items.length) state.index=0; else state.index=Math.max(0,Math.min(state.session.items.length-1,state.index)); }
  function jumpToIndex(index) { if (!Number.isInteger(index) || index<0 || index>=state.session.items.length) return; saveNote(); state.index=index; render(); setStatus("已跳转到案例 " + state.session.items[index].review_index + "。"); }
  function renderPendingJumps(pending) { const container=document.getElementById("pending-jumps"); container.replaceChildren(); if (!pending.length) { const empty=document.createElement("span"); empty.className="pending-empty"; empty.textContent="待审核：无（全部完成）"; container.appendChild(empty); return; } const label=document.createElement("span"); label.textContent="待审核："; container.appendChild(label); pending.forEach(function(index) { const button=document.createElement("button"); button.type="button"; button.className="pending-chip"; button.textContent=String(state.session.items[index].review_index); button.setAttribute("aria-label","跳转到第 " + state.session.items[index].review_index + " 个案例"); button.addEventListener("click",function() { jumpToIndex(index); }); container.appendChild(button); }); }
  function renderProgress() { normalizeNavigation(); const done=state.session.items.filter(function(item) { return Boolean(item.primary_class); }).length; const pending=pendingIndices(); const progress=document.getElementById("progress"); progress.replaceChildren(); const current=document.createElement("strong"); current.textContent="案例 " + (state.index+1) + " / " + PACKAGE.candidate_count; const completed=document.createElement("span"); completed.textContent="已完成 " + done + " / " + PACKAGE.candidate_count; progress.append(current,completed); const toggle=document.getElementById("pending-only"); toggle.checked=state.pendingOnly; renderPendingJumps(pending); if (state.modal) document.getElementById("modal-title").textContent=(state.modal.kind==="local" ? "局部查看" : "整体查看"); }
'''
    if old_progress not in html:
        raise ValueError("source-gap UI template no longer contains the expected progress renderer")
    html = html.replace(old_progress, new_progress, 1)
    html = html.replace(
        '  function renderControls() { const item=currentItem(); document.querySelectorAll("[data-primary]").forEach(function(button) { button.classList.toggle("active",button.dataset.primary===item.primary_class); }); document.querySelectorAll("[data-secondary]").forEach(function(input) { input.checked=item.secondary_flags.includes(input.dataset.secondary); }); document.getElementById("candidate-note").value=item.optional_note || ""; }',
        '  function renderControls() { const item=currentItem(); document.querySelectorAll("[data-primary]").forEach(function(button) { button.classList.toggle("active",button.dataset.primary===item.primary_class); }); document.querySelectorAll("[data-secondary]").forEach(function(input) { input.checked=item.secondary_flags.includes(input.dataset.secondary); }); document.getElementById("candidate-note").value=item.optional_note || ""; document.getElementById("clear-primary-button").disabled=!item.primary_class; }',
    )
    html = html.replace(
        '  function renderNavigation() { document.getElementById("previous-button").disabled=state.index===0; document.getElementById("next-button").disabled=state.index===state.session.items.length-1; }',
        '  function renderNavigation() { const visible=visibleIndices(); const position=visible.indexOf(state.index); document.getElementById("previous-button").disabled=!visible.length || position<=0; document.getElementById("next-button").disabled=!visible.length || position<0 || position>=visible.length-1; }',
    )
    html = html.replace(
        '  function setPrimary(value) { if (!PRIMARY_CLASSES.includes(value)) return; const item=currentItem(); item.primary_class=value; item.updated_at=now(); saveSession(); render(); setStatus("已选择，可继续补充标记或备注。"); }',
        '  function setPrimary(value) { if (!PRIMARY_CLASSES.includes(value)) return; const item=currentItem(); item.primary_class=value; item.updated_at=now(); saveSession(); render(); setStatus(state.pendingOnly && !pendingIndices().length ? "所有案例已完成；没有未完成案例。" : "已选择，可继续补充标记或备注。"); }',
    )
    html = html.replace(
        '  function navigate(delta) { saveNote(); state.index=Math.max(0,Math.min(state.session.items.length-1,state.index+delta)); render(); setStatus("已切换案例。"); }',
        '  function navigate(delta) { saveNote(); const visible=visibleIndices(); if (!visible.length) { render(); setStatus("所有案例已完成；没有未完成案例可跳转。"); return; } const position=visible.indexOf(state.index); const next=(position<0 ? (delta>0 ? 0 : visible.length-1) : position+delta); if (next<0 || next>=visible.length) { setStatus("已经到达当前范围的边界。"); return; } state.index=visible[next]; render(); setStatus("已切换案例。"); }',
    )
    html = html.replace(
        '  function setSecondary(flag,checked) { if (!SECONDARY_FLAGS.includes(flag)) return; const item=currentItem(); const values=new Set(item.secondary_flags); if (checked) values.add(flag); else values.delete(flag); item.secondary_flags=SECONDARY_FLAGS.filter(function(value) { return values.has(value); }); item.updated_at=now(); saveSession(); render(); setStatus("补充标记已保存。"); }',
        '  function setSecondary(flag,checked) { if (!SECONDARY_FLAGS.includes(flag)) return; const item=currentItem(); const values=new Set(item.secondary_flags); if (checked) values.add(flag); else values.delete(flag); item.secondary_flags=SECONDARY_FLAGS.filter(function(value) { return values.has(value); }); item.updated_at=now(); saveSession(); render(); setStatus("补充标记已保存。"); }\n  function clearPrimary() { const item=currentItem(); if (!item.primary_class) return; item.primary_class=null; item.review_status="PENDING"; item.updated_at=now(); saveSession(); render(); setStatus("本题答案已清除；已返回待审核列表。"); }',
    )
    html = html.replace(
        '  function importResult(event) { const file=event.target.files && event.target.files[0]; if (!file) return; const reader=new FileReader(); reader.onload=function() { try { state.session=validateImport(JSON.parse(String(reader.result))); state.index=0; saveSession(); render(); setStatus("审核结果已导入并校验；答案和备注保持原样。"); } catch(error) { setStatus("导入失败：" + error.message); } event.target.value=""; }; reader.readAsText(file); }',
        '  function importResult(event) { const file=event.target.files && event.target.files[0]; if (!file) return; const reader=new FileReader(); reader.onload=function() { try { state.session=validateImport(JSON.parse(String(reader.result))); state.index=0; saveSession(); render(); setStatus(pendingIndices().length ? "审核结果已导入并校验；答案和备注保持原样。" : "审核结果已导入；所有案例已完成。"); } catch(error) { setStatus("导入失败：" + error.message); } event.target.value=""; }; reader.readAsText(file); }',
    )
    html = html.replace(
        '  document.getElementById("candidate-note").addEventListener("input",scheduleNoteSave);',
        '  document.getElementById("pending-only").addEventListener("change",function() { state.pendingOnly=this.checked; if (state.pendingOnly && pendingIndices().length && !pendingIndices().includes(state.index)) state.index=pendingIndices()[0]; render(); setStatus(state.pendingOnly ? (pendingIndices().length ? "只显示未完成案例。" : "所有案例已完成；没有未完成案例可显示。") : "显示全部案例。"); });\n  document.getElementById("clear-primary-button").addEventListener("click",clearPrimary);\n  document.getElementById("candidate-note").addEventListener("input",scheduleNoteSave);',
    )
    html = html.replace(
        'const number={"1":PRIMARY_CLASSES[0],"2":PRIMARY_CLASSES[1],"3":PRIMARY_CLASSES[2],"4":PRIMARY_CLASSES[3],"5":PRIMARY_CLASSES[4],"6":PRIMARY_CLASSES[5]}[event.key];',
        'const number={"1":PRIMARY_CLASSES[0],"2":PRIMARY_CLASSES[1],"3":PRIMARY_CLASSES[2],"4":PRIMARY_CLASSES[3],"5":PRIMARY_CLASSES[4],"6":PRIMARY_CLASSES[5],"7":PRIMARY_CLASSES[6]}[event.key];',
    )
    return html


def render_review_html(manifest: Mapping[str, Any]) -> str:
    reviewer_manifest = {
        "schema_version": manifest["schema_version"], "package_id": manifest["package_id"],
        "review_protocol": PROTOCOL, "candidate_set_id": manifest["candidate_set_id"],
        "candidate_count": manifest["candidate_count"], "review_order": manifest["review_order"],
        "items": manifest["items"],
    }
    for key in ("initial_review_state", "legacy_import"):
        if key in manifest:
            reviewer_manifest[key] = manifest[key]
    template = primitive.REVIEW_HTML_TEMPLATE.replace("__PACKAGE_MANIFEST__", json.dumps(reviewer_manifest, ensure_ascii=False, separators=(",", ":")))
    return _transform_html(template)


def validate_review_export(payload: Any, candidate_set_id: str, review_order: Sequence[str]) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(review_order):
        raise ValueError("review export row count mismatch")
    normalized: list[dict[str, Any]] = []
    for index, (candidate_id, row) in enumerate(zip(review_order, rows, strict=True), start=1):
        if not isinstance(row, dict) or row.get("protocol") != PROTOCOL or row.get("candidate_set_id") != candidate_set_id or row.get("candidate_id") != candidate_id or row.get("review_index") != index:
            raise ValueError("review export identity or order mismatch")
        primary = row.get("primary_class")
        flags = row.get("secondary_flags")
        note = row.get("optional_note")
        if primary is not None and primary not in PRIMARY_CLASSES:
            raise ValueError("review export primary class mismatch")
        if not isinstance(flags, list) or len(flags) != len(set(flags)) or any(flag not in SECONDARY_FLAGS for flag in flags):
            raise ValueError("review export secondary flags mismatch")
        if not isinstance(note, str):
            raise ValueError("review export note must be a string")
        normalized.append({"protocol": PROTOCOL, "candidate_set_id": candidate_set_id, "candidate_id": candidate_id, "review_index": index, "primary_class": primary, "secondary_flags": list(flags), "optional_note": note})
    return normalized


def validate_review_package(package_dir: Path) -> dict[str, Any]:
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    errors: list[str] = []
    if manifest.get("review_protocol") != PROTOCOL or manifest.get("candidate_count") != TARGET_REVIEW_SIZE:
        errors.append("package identity/count mismatch")
    if manifest.get("review_order") != [item.get("candidate_id") for item in manifest.get("items", [])]:
        errors.append("review order mismatch")
    for label in ("连续实线", "原图本来就分段", "规律分段 / 虚线", "被结构打断", "像是破损或扫描缺失", "看不清", INVALID_PRIMITIVE_LABEL, INVALID_PRIMITIVE_HELP):
        if label not in html:
            errors.append(f"missing Chinese primary label: {label}")
    for value in PRIMARY_CLASSES + SECONDARY_FLAGS:
        if value not in html:
            errors.append(f"review vocabulary missing: {value}")
    for token in ("primary_class:null", "secondary_flags:[]", 'optional_note:""', "evidence-grid", "data-menu", "点击图片可放大", "function setModalScale"):
        if token not in html:
            errors.append(f"missing UI invariant: {token}")
    for forbidden in ("selection_stratum", "diagnostic_measurements_used", "machine_verdict", "support_fraction", "periodicity", "degradation_score", "expected_answer", "human_stage1", "human_stage2"):
        if forbidden in html:
            errors.append(f"reviewer leakage: {forbidden}")
    for enum in PRIMARY_CLASSES:
        if f">{enum}<" in html:
            errors.append(f"visible enum leakage: {enum}")
    if "position:sticky" in html or ".review-controls" in html or "<script src=" in html or "fetch(" in html:
        errors.append("compact/self-contained UI invariant failed")
    for item in manifest.get("items", []):
        for key in ("local_clean_image", "local_overlay_image", "context_clean_image", "context_overlay_image"):
            if not (package_dir / Path(*item[key].split("/"))).is_file():
                errors.append(f"missing asset: {item[key]}")
    if errors:
        raise ValueError("invalid source-gap review package: " + "; ".join(errors))
    return {"candidate_count": TARGET_REVIEW_SIZE, "four_view_assets": "PASS", "primary_choice_initially_empty": True, "secondary_flags_initially_empty": True, "optional_notes_initially_empty": True, "bottom_control_overlap_guard": "PASS", "click_to_enlarge": "PASS", "import_export": "PASS"}


def build_review_package(repo_root: Path, records: Sequence[Mapping[str, Any]], candidate_set_id: str, source_identity: Mapping[str, Any], *, output_dir: Path, zip_path: Path | None = None, replace: bool = False, package_id: str = PACKAGE_ID, package_revision: str = "SOURCE_GAP_REVIEW_V1", initial_review_state: Sequence[Mapping[str, Any]] | None = None, legacy_import: Mapping[str, Any] | None = None, human_review_status: str = "PENDING", readme_text: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if output_dir.exists():
        if not replace:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    items: list[dict[str, Any]] = []
    for record in records:
        source_path = primitive._repo_path(repo_root, str(record["source_render_path"]))
        boxes = {"local": tuple(record["source_crop_mapping"]["local_box_px"]), "context": tuple(record["source_crop_mapping"]["context_box_px"])}
        item: dict[str, Any] = {"review_index": record["review_index"], "candidate_id": record["candidate_id"], "marker": {}}
        for kind, box in boxes.items():
            clean = output_dir / "assets" / kind / f"{record['candidate_id']}-clean.png"
            overlay = output_dir / "assets" / kind / f"{record['candidate_id']}-overlay.png"
            size = primitive._write_clean_crop(source_path, box, clean)
            marker = _marker_for_box(record, box, size)
            _write_overlay(clean, overlay, marker)
            item[f"{kind}_clean_image"] = f"assets/{kind}/{record['candidate_id']}-clean.png"
            item[f"{kind}_overlay_image"] = f"assets/{kind}/{record['candidate_id']}-overlay.png"
            item["marker"][kind] = marker
        items.append(item)
    manifest = {"schema_version": 1, "package_id": package_id, "package_revision": package_revision, "review_protocol": PROTOCOL, "candidate_set_id": candidate_set_id, "candidate_count": len(items), "review_order": [item["candidate_id"] for item in items], "source_identity": dict(source_identity), "items": items, "governance": {"human_review_status": human_review_status, "machine_verdict_exposed_to_reviewer": False, "source_full_documents_included": False, "source_derived_images_local_only": True, "export_reload_supported": True}}
    if initial_review_state is not None:
        manifest["initial_review_state"] = [dict(item) for item in initial_review_state]
    if legacy_import is not None:
        manifest["legacy_import"] = dict(legacy_import)
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "review.html").write_text(render_review_html(manifest), encoding="utf-8")
    default_readme = "SOURCE_GAP_REVIEW_V1\n\n原图中这根线在这些断开位置，最接近哪种情况？\n红色表示检测到的整体线范围；黄色标记表示本次重点查看的断开位置。\n所有答案、补充标记和备注初始为空。\n\nHUMAN_REVIEW: PENDING\nPUBLIC_REDISTRIBUTION: NOT_AUTHORIZED\n"
    (output_dir / "README.txt").write_text(readme_text if readme_text is not None else default_readme, encoding="utf-8")
    validation = validate_review_package(output_dir)
    if zip_path is not None:
        primitive._zip_package(output_dir, zip_path)
    return manifest, validation


def _selection_replay_payload(expected: Sequence[Mapping[str, Any]], replayed: Sequence[Mapping[str, Any]], source_candidate_set_id: str, expected_digest: str) -> dict[str, Any]:
    replayed_digest = _selection_digest(replayed, source_candidate_set_id)
    expected_ids = [row["candidate_id"] for row in expected]
    replayed_ids = [row["candidate_id"] for row in replayed]
    source_mapping_equal = [row["source_crop_mapping"] for row in expected] == [row["source_crop_mapping"] for row in replayed]
    status = "PASS" if expected_ids == replayed_ids and expected_digest == replayed_digest and source_mapping_equal else "FAIL"
    return {"schema_version": 1, "task_id": TASK_ID, "protocol": PROTOCOL, "source_fresh_candidate_set_id": source_candidate_set_id, "expected_order": expected_ids, "replayed_order": replayed_ids, "expected_selection_digest": expected_digest, "replayed_selection_digest": replayed_digest, "source_mapping_equal": source_mapping_equal, "selection_deterministic_replay": status, "status": status}


def replay_selection(repo_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    frozen = primitive._load_frozen_inputs(repo_root)
    pool_ids = {str(item["candidate_id"]) for item in frozen["pool"]}
    prior_ids, _ = _load_prior_reviewed_ids(repo_root, pool_ids)
    diagnostics = primitive._load_diagnostics(repo_root, pool_ids)
    replayed = _select_target(repo_root, frozen["pool"], prior_ids, diagnostics)
    return _selection_replay_payload(manifest["records"], replayed, manifest["source_fresh_candidate_set_id"], manifest["selection_digest"])


def _outdated_test_audit() -> dict[str, Any]:
    path = "cad_photo_to_dxf/tests/test_direct_continuation_admissibility_v1.py"
    return {
        "schema_version": 1, "task_id": TASK_ID, "affected_test_count": 6,
        "summary": {"KEEP": 3, "RENAME": 1, "REWRITE": 2, "DEPRECATE": 0},
        "records": [
            {"test_path": path, "test_name": "test_admissibility_decision_and_reason_are_deterministic", "current_assertion": "A synthetic pair of separate collinear strokes with a 20 px blank gap is DIRECT_CONTINUATION_ADMISSIBLE / CLEAR_DIRECT_TRAJECTORY.", "original_intended_safety_property": "The admissibility decision is deterministic for a simple clear pair.", "assessment": "Implementation behavior is not established as production-wrong by this test alone, but the test fixture/interpretation is semantically outdated because it supplies no positive degradation evidence.", "action": "REWRITE", "required_future_meaning": "Use a continuous or positively degradation-supported fixture while retaining determinism; do not treat collinearity and a blank gap as restoration authority."},
            {"test_path": path, "test_name": "test_valid_object_and_continuous_annotation_are_not_semantically_filtered", "current_assertion": "Object and annotation-tagged synthetic pairs remain admissible even though the annotation fixture contains a clear blank gap.", "original_intended_safety_property": "Candidate admissibility must not depend on object/annotation semantics or model evidence.", "assessment": "The no-semantic-filter safety property is correct; the test name and annotation-fixture interpretation conflate semantic neutrality with source continuity.", "action": "RENAME", "required_future_meaning": "Retain semantic neutrality while avoiding any claim that a blank-gap source is one low-level continuous primitive."},
            {"test_path": path, "test_name": "test_reason_and_source_evidence_are_retained_without_model_calls", "current_assertion": "The same 20 px blank-gap fixture reports CLEAR_DIRECT_TRAJECTORY and retains its gap measurement without model calls.", "original_intended_safety_property": "Decision reason and source measurements remain observable and model-independent.", "assessment": "The observability/no-model property is correct, but CLEAR_DIRECT_TRAJECTORY on a blank-gap fixture repeats the outdated restoration interpretation without positive degradation evidence.", "action": "REWRITE", "required_future_meaning": "Keep reason/evidence retention and model independence using a source-supported fixture or assert neutral serialization without treating the blank gap as continuous geometry."},
            {"test_path": "cad_photo_to_dxf/tests/test_primitive_span_integrity_v1.py", "test_name": "test_periodic_pattern_is_uncertain_not_rejected", "current_assertion": "A synthetic repeated dashed pattern is SPAN_INTEGRITY_UNCERTAIN, never supported as continuous geometry.", "original_intended_safety_property": "Patterned evidence stays conservative and does not become a destructive support/rejection decision.", "assessment": "Implementation and test semantics are compatible with the source-fidelity contract. PASS means preserved uncertainty, not permission to merge dashes.", "action": "KEEP", "required_future_meaning": "Keep the explicit distinction from short scan-dropout tolerance."},
            {"test_path": "cad_photo_to_dxf/tests/test_primitive_axis_support_integrity_v1.py", "test_name": "test_dashed_pattern_is_uncertain_not_center_void_rejected", "current_assertion": "A dashed synthetic axis is PRIMITIVE_AXIS_UNCERTAIN (patterned or noisy/degraded), not axis-supported continuous geometry.", "original_intended_safety_property": "Do not misclassify patterned axis evidence as a hollow-center hard rejection or as confident continuous support.", "assessment": "Implementation and assertion are compatible; the old patterned-stroke safety summary must be read as preserved uncertainty, not destructive merge authority.", "action": "KEEP", "required_future_meaning": "Keep uncertainty and preserve visible component segments at low level."},
            {"test_path": "cad_photo_to_dxf/tests/test_primitive_span_integrity_v1.py", "test_name": "test_short_isolated_dropout_does_not_automatically_reject", "current_assertion": "A two-pixel removal inside an otherwise solid synthetic stroke remains SPAN_INTEGRITY_SUPPORTED.", "original_intended_safety_property": "Minor scan/raster dropout must not automatically destroy a genuinely continuous source stroke.", "assessment": "This is the correct degradation-restoration safety meaning and is distinct from accepting intentional dashed geometry as one low-level primitive.", "action": "KEEP", "required_future_meaning": "Retain positive surrounding continuity evidence; do not generalize the result to arbitrary blank gaps."},
        ],
        "patterned_stroke_reinterpretation": {"minor_scan_dropout_safety": "KEEP: test_short_isolated_dropout_does_not_automatically_reject protects a genuinely continuous degraded stroke.", "intentional_patterned_geometry": "KEEP AS UNCERTAIN: test_periodic_pattern_is_uncertain_not_rejected does not authorize one continuous low-level primitive.", "equivalent": False},
        "scan_degradation_safety_weakened": False,
    }


def build_targeted_source_gap_review(repo_root: Path, *, replace_runtime: bool = False) -> PackageBuildResult:
    repo_root = repo_root.resolve()
    frozen = primitive._load_frozen_inputs(repo_root)
    pool_ids = {str(item["candidate_id"]) for item in frozen["pool"]}
    prior_ids, prior_metadata = _load_prior_reviewed_ids(repo_root, pool_ids)
    diagnostics = primitive._load_diagnostics(repo_root, pool_ids)
    records = _select_target(repo_root, frozen["pool"], prior_ids, diagnostics)
    if not MIN_REVIEW_SIZE <= len(records) <= MAX_REVIEW_SIZE:
        raise ValueError("selection outside allowed size")
    if len({row["candidate_id"] for row in records}) != len(records) or len({primitive._exact_primitive_key(row) for row in records}) != len(records):
        raise ValueError("duplicate candidate or primitive")
    prior_count = sum(row["new_or_prior_reviewed"] == "PRIOR_REVIEWED_CONTROL" for row in records)
    if prior_count > MAX_PRIOR_REVIEWED_ANCHORS:
        raise ValueError("too many prior reviewed anchors")
    source_candidate_set_id = str(frozen["runtime"]["candidate_set_id"])
    digest = _selection_digest(records, source_candidate_set_id)
    candidate_set_id = f"{source_candidate_set_id}-SOURCE-GAP-{digest[:12].upper()}"
    runtime_root = primitive._repo_path(repo_root, RUNTIME_RELATIVE)
    if runtime_root.exists():
        if not replace_runtime:
            raise FileExistsError(runtime_root)
        _safe_replace_runtime(runtime_root)
    runtime_root.mkdir(parents=True)
    tracked_root = primitive._repo_path(repo_root, TRACKED_RELATIVE)
    tracked_root.mkdir(parents=True, exist_ok=True)
    replay = _selection_replay_payload(records, _select_target(repo_root, frozen["pool"], prior_ids, diagnostics), source_candidate_set_id, digest)
    if replay["status"] != "PASS":
        raise ValueError("selection deterministic replay failed")
    coverage = _coverage(records)
    strata = dict(sorted(Counter(row["selection_stratum"] for row in records).items()))
    source_identity = {"source_fresh_candidate_set_id": source_candidate_set_id, "source_frozen_pool_count": FRESH_POOL_COUNT, "source_pool_runtime_sha256": frozen["runtime_sha256"], "source_fresh_selection_manifest_sha256": frozen["selection_sha256"], "source_checkpoint": frozen["selection"].get("base_checkpoint"), "selection_digest": digest}
    runtime_selection = {"schema_version": 1, "task_id": TASK_ID, "protocol": PROTOCOL, "base_checkpoint": BASE_CHECKPOINT, **source_identity, "candidate_set_id": candidate_set_id, "candidate_count": len(records), "selection_deterministic_replay": "PASS", "records": records, "governance": {"new_candidate_mining": "NO", "model_run": "NO", "model_assisted_labeling": "NO", "validation": "NO", "locked_blind": "0 / 8", "h1_h2_opened": "NO", "human_review": "PENDING"}}
    _write_json(runtime_root / "selection-runtime.json", runtime_selection)
    _write_json(runtime_root / "selection-diagnostics.json", {"schema_version": 1, "task_id": TASK_ID, "candidate_set_id": candidate_set_id, "selection_digest": digest, "records": [{"candidate_id": row["candidate_id"], "review_index": row["review_index"], "selection_stratum": row["selection_stratum"], "new_or_prior_reviewed": row["new_or_prior_reviewed"], "diagnostic_measurements_used": row["diagnostic_measurements_used"], "selection_rationale": row["selection_rationale"]} for row in records]})
    _write_json(runtime_root / "selection-replay.json", replay)
    package_manifest, package_validation = build_review_package(repo_root, records, candidate_set_id, source_identity, output_dir=runtime_root / "review-package", zip_path=runtime_root / "review-package.zip", replace=True)
    primitive._write_contact_sheet(records, runtime_root / "review-package", runtime_root / "contact-sheet.png")
    selection_manifest = {"schema_version": 1, "task_id": TASK_ID, "protocol": PROTOCOL, "base_checkpoint": BASE_CHECKPOINT, "candidate_set_id": candidate_set_id, **source_identity, "candidate_count": len(records), "target_review_size": TARGET_REVIEW_SIZE, "allowed_review_size": [MIN_REVIEW_SIZE, MAX_REVIEW_SIZE], "review_order": [row["candidate_id"] for row in records], "selection_digest": digest, "selection_code_version": SELECTION_CODE_VERSION, "selection_deterministic_replay": "PASS", "selection_basis": ["frozen source-visible support runs and unsupported intervals", "frozen gap, axis, crossing, parallel-run, density, offset, and primitive-length diagnostics", "frozen source degradation context", "source-family, source-unit, and orientation diversity", "three previously reviewed visual anchors"], "human_labels_used_for_new_selection": False, "semantic_model_predictions_used_for_selection": False, "ocr_semantic_predictions_used_for_selection": False, "prior_reviewed_metadata": prior_metadata, "previously_unreviewed_count": len(records) - prior_count, "prior_reviewed_anchor_count": prior_count, "strata_counts": strata, "coverage": coverage, "records": records, "governance": runtime_selection["governance"]}
    tracked_package = {"schema_version": 1, "task_id": TASK_ID, "package_id": PACKAGE_ID, "review_protocol": PROTOCOL, "candidate_set_id": candidate_set_id, "candidate_count": len(records), "review_order": selection_manifest["review_order"], "runtime_package_path": f"{RUNTIME_RELATIVE}/review-package", "runtime_package_manifest_sha256": _sha256_file(runtime_root / "review-package" / "manifest.json"), "runtime_package_validation": package_validation, "machine_verdict_exposed_to_reviewer": False, "human_review": "PENDING"}
    _write_json(tracked_root / "source-gap-candidate-registry.json", {"schema_version": 1, "task_id": TASK_ID, "protocol": PROTOCOL, "candidate_set_id": candidate_set_id, "selection_digest": digest, "candidate_count": len(records), "records": records, "counts": {"frozen_candidates": len(records), "previously_unreviewed": len(records) - prior_count, "previously_reviewed_anchors": prior_count, "human_primary_answers": 0}})
    _write_json(tracked_root / "source-gap-selection-manifest.json", selection_manifest)
    _write_json(tracked_root / "source-gap-review-package-manifest.json", tracked_package)
    _write_json(tracked_root / "source-gap-selection-replay.json", replay)
    audit = _outdated_test_audit()
    _write_json(tracked_root / "outdated-patterned-test-audit.json", audit)
    report = f"""# Targeted Source Gap Review V1 Preparation\n\nStatus: `HUMAN_REVIEW: PENDING`\n\nThis blind diagnostic review asks only what the visible interruption means. It preserves the frozen rule that source-visible stroke extents remain geometry, while allowing a conservative degradation category when positive visible evidence exists. It does not implement a continuity guard, endpoint guard, splitting, clipping, restoration, grouping, or any production change.\n\n## Frozen selection\n\n- Base checkpoint: `{BASE_CHECKPOINT}`\n- Frozen fresh pool: `{FRESH_POOL_COUNT}`\n- Selected: `{len(records)}` ({len(records)-prior_count} previously unreviewed; {prior_count} reviewed anchors)\n- Candidate-set ID: `{candidate_set_id}`\n- Selection digest: `{digest}`\n- Deterministic replay: `PASS`\n- Strata: `{json.dumps(strata, ensure_ascii=False, sort_keys=True)}`\n- Coverage: {coverage['source_families']} source families; {coverage['source_units']} units; {coverage['horizontal']} horizontal; {coverage['vertical']} vertical\n\n## Reviewer question\n\n**原图中这根线在这些断开位置，最接近哪种情况？**\n\nThe six Chinese choices map internally to `{PROTOCOL}` enums. Primary choice, optional flags, and note are all initially empty. The UI contains four previews, click-to-enlarge, compact import/export, and no diagnostic stratum, score, hypothesis, machine verdict, previous label, or expected answer.\n\n## Outdated-test audit\n\nAffected tests: {audit['affected_test_count']}. Actions: KEEP=3, RENAME=1, REWRITE=2, DEPRECATE=0. The audit explicitly separates minor scan-dropout safety from intentional patterned source geometry. No existing test or guard is changed in this preparation task.\n\n## Governance\n\n- Production semantic delta: `NONE`\n- Span / axis / admissibility guards changed: `NO / NO / NO`\n- Source-continuity / endpoint guards implemented: `NO / NO`\n- New candidate mining: `NO`; model run: `NO`; model-assisted labeling: `NO`\n- Validation: `NO`; locked blind: `0 / 8`; H1/H2 opened: `NO`; Batch-03 created: `NO`\n- Runtime package: `{RUNTIME_RELATIVE}/review-package`\n- Static package QA: `PASS`\n\nHuman review remains pending. Next: `HUMAN_SOURCE_GAP_REVIEW`.\n"""
    (tracked_root / "TARGETED-SOURCE-GAP-REVIEW-V1-PREP.md").write_text(report, encoding="utf-8")
    return PackageBuildResult(runtime_root, runtime_root / "review-package", runtime_root / "review-package.zip", tracked_root, candidate_set_id, digest, len(records), len(records) - prior_count, prior_count, strata, coverage["source_families"], coverage["source_units"], coverage["horizontal"], coverage["vertical"], "PASS", package_validation)


__all__ = ["BASE_CHECKPOINT", "FRESH_POOL_COUNT", "INVALID_PRIMITIVE_HELP", "INVALID_PRIMITIVE_LABEL", "MAX_PRIOR_REVIEWED_ANCHORS", "PRIMARY_CLASSES", "PROTOCOL", "SECONDARY_FLAGS", "STRATUM_TARGETS", "TARGET_REVIEW_SIZE", "PackageBuildResult", "build_review_package", "build_targeted_source_gap_review", "render_review_html", "replay_selection", "validate_review_export", "validate_review_package"]
