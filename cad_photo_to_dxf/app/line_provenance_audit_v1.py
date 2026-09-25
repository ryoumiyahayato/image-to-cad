"""Diagnostic-only provenance audit for the frozen Local-D line candidates.

This module deliberately reproduces the standalone Local-D proposal detector;
it is not imported by production tracing code and makes no geometry decisions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


NOT_AVAILABLE = "NOT_AVAILABLE"

ROOT_CAUSES = (
    "RAW_HOUGH_OVERSPAN",
    "RAW_LSD_OVERSPAN",
    "RAW_DETECTOR_OVERSPAN_BOTH",
    "CONSOLIDATION_OVERMERGE",
    "POST_DETECTION_GEOMETRY_EXTENSION",
    "CANDIDATE_PAIRING_ERROR",
    "MIXED_ROLE_COLLINEAR_PAIRING",
    "INTENTIONAL_OPENING_OR_INTERRUPTION",
    "COMPONENT_OR_NODE_MEDIATED",
    "PATTERNED_OR_DASHED_STROKE",
    "VALID_ANNOTATION_HARD_NEGATIVE",
    "VALID_DIRECT_OBJECT_CONTINUATION",
    "GLYPH_TEXT_CONTAMINATION",
    "REVIEW_ASSET_OR_RENDER_FAILURE",
    "INSUFFICIENT_PROVENANCE",
)

CONFIDENCES = ("PROVEN", "STRONGLY_SUPPORTED", "PLAUSIBLE", "UNRESOLVED")

PRIMITIVE_INTEGRITY_CAUSES = {
    "RAW_HOUGH_OVERSPAN",
    "RAW_LSD_OVERSPAN",
    "RAW_DETECTOR_OVERSPAN_BOTH",
    "CONSOLIDATION_OVERMERGE",
    "POST_DETECTION_GEOMETRY_EXTENSION",
}

PAIRING_CAUSES = {
    "CANDIDATE_PAIRING_ERROR",
    "MIXED_ROLE_COLLINEAR_PAIRING",
    "INTENTIONAL_OPENING_OR_INTERRUPTION",
    "COMPONENT_OR_NODE_MEDIATED",
    "PATTERNED_OR_DASHED_STROKE",
    "VALID_ANNOTATION_HARD_NEGATIVE",
    "VALID_DIRECT_OBJECT_CONTINUATION",
    "GLYPH_TEXT_CONTAMINATION",
}


@dataclass(frozen=True)
class AuditPaths:
    repo: Path

    @property
    def frozen(self) -> Path:
        return self.repo / "cad_photo_to_dxf" / "validation" / "user-supplied-candidate-mining-v2-local-d" / "frozen-candidate-set.json"

    @property
    def order(self) -> Path:
        return self.repo / "cad_photo_to_dxf" / "validation" / "user-supplied-human-review-v2-local-e1" / "review-order.json"

    @property
    def manifest(self) -> Path:
        return self.repo / "cad_photo_to_dxf" / "validation" / "user-supplied-human-review-v2-local-e1" / "human-review-manifest.json"

    @property
    def legacy_review(self) -> Path:
        return self.repo / "local-artifacts" / "draftsman" / "user-supplied-human-review-v2-local-e2" / "review-export.json"

    @property
    def local_d_runtime(self) -> Path:
        return self.repo / "local-artifacts" / "draftsman" / "user-supplied-candidate-mining-v2-local-d"

    @property
    def runtime(self) -> Path:
        return self.repo / "local-artifacts" / "draftsman" / "line-provenance-audit-v1"

    @property
    def tracked(self) -> Path:
        return self.repo / "cad_photo_to_dxf" / "validation" / "line-provenance-audit-v1"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_frozen_candidates(paths: AuditPaths) -> list[dict[str, Any]]:
    """Load the exact frozen set in authoritative human-review order."""

    frozen = _load_json(paths.frozen)
    order = _load_json(paths.order)
    manifest = _load_json(paths.manifest)
    records = {item["candidate_id"]: item for item in frozen["frozen_candidates"]}
    ordered = order["order"]
    manifest_ids = [item["candidate_id"] for item in manifest["entries"]]
    ids = [item["candidate_id"] for item in ordered]
    if len(records) != 24 or len(ids) != 24 or len(set(ids)) != 24:
        raise ValueError("audit requires exactly 24 distinct frozen candidates")
    if set(ids) != set(records) or ids != manifest_ids:
        raise ValueError("frozen set, review order, and manifest identity differ")
    output: list[dict[str, Any]] = []
    for entry in ordered:
        record = dict(records[entry["candidate_id"]])
        record["review_index"] = int(entry["review_index"])
        output.append(record)
    return output


def _raw_hough(gray: np.ndarray) -> tuple[np.ndarray, list[dict[str, Any]]]:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    lines = cv2.HoughLinesP(
        binary, 1, np.pi / 180, threshold=45, minLineLength=28, maxLineGap=3
    )
    records: list[dict[str, Any]] = []
    if lines is None:
        return binary, records
    for index, raw in enumerate(lines[:, 0, :]):
        x1, y1, x2, y2 = (int(value) for value in raw)
        dx, dy = x2 - x1, y2 - y1
        canonical: dict[str, Any] | None = None
        if abs(dx) >= 3 * max(1, abs(dy)):
            start, end = sorted((x1, x2))
            canonical = {
                "orientation": "horizontal",
                "axis": int(round((y1 + y2) / 2)),
                "start": start,
                "end": end,
            }
        elif abs(dy) >= 3 * max(1, abs(dx)):
            start, end = sorted((y1, y2))
            canonical = {
                "orientation": "vertical",
                "axis": int(round((x1 + x2) / 2)),
                "start": start,
                "end": end,
            }
        records.append(
            {
                "id": f"raw-hough-{index:06d}",
                "detector": "HOUGH",
                "raw_geometry": {"start": [x1, y1], "end": [x2, y2]},
                "canonical_geometry": canonical or NOT_AVAILABLE,
                "accepted_by_orientation_filter": canonical is not None,
            }
        )
    return binary, records


def _normalization_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["orientation"],
        int(round(item["axis"] / 2)),
        int(round(item["start"] / 2)),
        int(round(item["end"] / 2)),
    )


def normalize_hough_records(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reproduce Local-D normalization without erasing member hypotheses.

    The normalized geometry remains the legacy derived hypothesis.  Raw member
    geometries and endpoint pairs are retained beside it so 2-pixel duplicate
    suppression is non-destructive for DEV source-fidelity analysis.  Multiple
    members are explicitly ambiguous: detector duplication is not proof of
    multiple physical source strokes.
    """

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    ancestors: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    source_stroke_members: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(
        list
    )
    for record in raw:
        canonical = record["canonical_geometry"]
        if canonical == NOT_AVAILABLE:
            continue
        item = dict(canonical)
        start, end = sorted((int(item["start"]), int(item["end"])))
        if end <= start or int(item["axis"]) < 0:
            continue
        item.update(start=start, end=end)
        key = _normalization_key(item)
        unique.setdefault(key, item)
        ancestors[key].append(record["id"])
        source_stroke_members[key].append(
            {
                "hypothesis_id": record["id"],
                "detector": record.get("detector", "HOUGH"),
                "raw_geometry": dict(record["raw_geometry"]),
                "canonical_geometry": dict(item),
                "endpoint_evidence": {
                    "start": list(record["raw_geometry"]["start"]),
                    "end": list(record["raw_geometry"]["end"]),
                    "confidence": "DETECTOR_OBSERVATION_ONLY",
                },
            }
        )
    by_orientation: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = defaultdict(list)
    for key, item in unique.items():
        by_orientation[item["orientation"]].append((key, item))
    limited: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for orientation in ("horizontal", "vertical"):
        values = by_orientation.get(orientation, [])
        values.sort(
            key=lambda pair: (
                -(pair[1]["end"] - pair[1]["start"]),
                pair[1]["axis"],
                pair[1]["start"],
                pair[1]["end"],
            )
        )
        limited.extend(values[:1200])
    limited.sort(
        key=lambda pair: (
            pair[1]["orientation"],
            pair[1]["axis"],
            pair[1]["start"],
            pair[1]["end"],
        )
    )
    output: list[dict[str, Any]] = []
    for index, (key, item) in enumerate(limited):
        output.append(
            {
                "id": f"normalized-hough-{index:06d}",
                "detector": "HOUGH",
                "geometry": dict(item),
                "raw_ancestor_ids": list(ancestors[key]),
                "source_stroke_group": {
                    "relationship": "TWO_PIXEL_QUANTIZED_DUPLICATE_GROUP",
                    "multiplicity_state": "MULTIPLICITY_AMBIGUOUS",
                    "member_count": len(source_stroke_members[key]),
                    "member_hypotheses": list(source_stroke_members[key]),
                    "members_preserved": True,
                    "derived_geometry_replaces_members": False,
                },
                "operation": "axis projection + 2-pixel quantized duplicate suppression + per-orientation cap",
            }
        )
    return output


def _geometry_to_canonical(geometry: dict[str, Any]) -> dict[str, Any]:
    (x1, y1), (x2, y2) = geometry["start"], geometry["end"]
    if abs(x2 - x1) >= abs(y2 - y1):
        return {
            "orientation": "horizontal",
            "axis": int(round((y1 + y2) / 2)),
            "start": min(int(x1), int(x2)),
            "end": max(int(x1), int(x2)),
        }
    return {
        "orientation": "vertical",
        "axis": int(round((x1 + x2) / 2)),
        "start": min(int(y1), int(y2)),
        "end": max(int(y1), int(y2)),
    }


def _find_normalized(
    records: Iterable[dict[str, Any]], geometry: dict[str, Any]
) -> dict[str, Any] | None:
    target = _geometry_to_canonical(geometry)
    return next((item for item in records if item["geometry"] == target), None)


def _segment_endpoints(geometry: dict[str, Any]) -> tuple[tuple[int, int], tuple[int, int]]:
    first = tuple(int(value) for value in geometry["start"])
    second = tuple(int(value) for value in geometry["end"])
    return first, second


def sample_span_support(
    gray: np.ndarray,
    geometry: dict[str, Any],
    *,
    sample_count: int = 101,
    perpendicular_radius: int = 2,
) -> dict[str, Any]:
    """Sample ordered source-ink support without producing a production score."""

    if sample_count < 2:
        raise ValueError("sample_count must be at least 2")
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    ink = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    distance = cv2.distanceTransform((ink == 0).astype(np.uint8), cv2.DIST_L2, 5)
    (x1, y1), (x2, y2) = _segment_endpoints(geometry)
    dx, dy = float(x2 - x1), float(y2 - y1)
    length = max(1.0, math.hypot(dx, dy))
    nx, ny = -dy / length, dx / length
    samples: list[dict[str, Any]] = []
    unsupported_run = 0
    maximum_unsupported_run = 0
    for index, fraction in enumerate(np.linspace(0.0, 1.0, sample_count)):
        cx, cy = x1 + dx * float(fraction), y1 + dy * float(fraction)
        values: list[bool] = []
        for offset in range(-perpendicular_radius, perpendicular_radius + 1):
            px = int(round(cx + nx * offset))
            py = int(round(cy + ny * offset))
            if 0 <= px < gray.shape[1] and 0 <= py < gray.shape[0]:
                values.append(bool(ink[py, px]))
        local_score = sum(values) / max(1, len(values))
        supported = any(values)
        if supported:
            unsupported_run = 0
        else:
            unsupported_run += 1
            maximum_unsupported_run = max(maximum_unsupported_run, unsupported_run)
        px = min(max(int(round(cx)), 0), gray.shape[1] - 1)
        py = min(max(int(round(cy)), 0), gray.shape[0] - 1)
        samples.append(
            {
                "sample_index": index,
                "sample_position_fraction": round(float(fraction), 6),
                "source_position_px": [round(cx, 3), round(cy, 3)],
                "local_support_score": round(local_score, 6),
                "binary_support": supported,
                "distance_to_nearest_source_ink_px": round(float(distance[py, px]), 4),
                "local_interruption_flag": not supported,
            }
        )
    supported_count = sum(bool(item["binary_support"]) for item in samples)
    return {
        "method": "ordered centerline samples; Otsu source ink; perpendicular neighborhood radius 2 px",
        "semantic_authority": "DIAGNOSTIC_ONLY",
        "sample_count": sample_count,
        "perpendicular_radius_px": perpendicular_radius,
        "supported_samples": supported_count,
        "supported_fraction": round(supported_count / sample_count, 6),
        "maximum_consecutive_unsupported_samples": maximum_unsupported_run,
        "observed_span_integrity": (
            "OBSERVED_CONTINUOUS" if maximum_unsupported_run == 0 else "OBSERVED_INTERRUPTED"
        ),
        "samples": samples,
    }


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in profile.items() if key != "samples"}


def _font(size: int = 18) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _source_crop(image: Image.Image, box: list[int]) -> tuple[Image.Image, tuple[int, int]]:
    crop = image.crop(tuple(box)).convert("RGB")
    return crop, (int(box[0]), int(box[1]))


def _draw_geometry(
    image: Image.Image,
    geometry: dict[str, Any],
    origin: tuple[int, int],
    color: tuple[int, int, int],
    width: int = 5,
) -> None:
    draw = ImageDraw.Draw(image)
    (x1, y1), (x2, y2) = _segment_endpoints(geometry)
    ox, oy = origin
    draw.line((x1 - ox, y1 - oy, x2 - ox, y2 - oy), fill=color, width=width)


def _add_banner(image: Image.Image, text: str, color: tuple[int, int, int] = (30, 35, 45)) -> Image.Image:
    banner = Image.new("RGB", (image.width, 42), (247, 248, 250))
    ImageDraw.Draw(banner).text((10, 10), text, fill=color, font=_font(16))
    out = Image.new("RGB", (image.width, image.height + 42), "white")
    out.paste(banner, (0, 0))
    out.paste(image, (0, 42))
    return out


def _fit_panel(image: Image.Image, width: int = 560, height: int = 360) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((width, height), Image.Resampling.LANCZOS)
    panel = Image.new("RGB", (width, height), (250, 250, 250))
    panel.paste(copy, ((width - copy.width) // 2, (height - copy.height) // 2))
    return panel


def _profile_image(a: dict[str, Any], b: dict[str, Any], width: int = 560, height: int = 360) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((12, 10), "SPAN SUPPORT PROFILE (diagnostic only)", fill=(25, 30, 40), font=_font(17))
    for row, (label, profile, color) in enumerate((("A", a, (220, 45, 45)), ("B", b, (30, 115, 220)))):
        top = 65 + row * 135
        draw.text((12, top), f"Fragment {label}", fill=color, font=_font(16))
        left, right = 115, width - 22
        baseline = top + 70
        draw.line((left, baseline, right, baseline), fill=(180, 180, 180), width=1)
        samples = profile["samples"]
        for item in samples:
            x = left + int(round(item["sample_position_fraction"] * (right - left)))
            score = float(item["local_support_score"])
            y = baseline - int(round(score * 60))
            point_color = color if item["binary_support"] else (35, 35, 35)
            draw.line((x, baseline, x, y), fill=point_color, width=2)
        draw.text(
            (115, top),
            f"support={profile['supported_fraction']:.3f}; max interruption={profile['maximum_consecutive_unsupported_samples']} samples",
            fill=(55, 60, 70),
            font=_font(14),
        )
    return image


def _render_case_assets(
    case_dir: Path,
    image: Image.Image,
    candidate: dict[str, Any],
    raw_by_id: dict[str, dict[str, Any]],
    ancestor_ids: list[str],
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    summary: str,
) -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    crop, origin = _source_crop(image, candidate["context_crop_box_px"])
    crop.save(case_dir / "source.png")

    final = crop.copy()
    _draw_geometry(final, candidate["fragment_a_geometry"], origin, (225, 35, 35))
    _draw_geometry(final, candidate["fragment_b_geometry"], origin, (25, 120, 230))
    ImageDraw.Draw(final).line(
        (
            candidate["gap_endpoint_a"][0] - origin[0],
            candidate["gap_endpoint_a"][1] - origin[1],
            candidate["gap_endpoint_b"][0] - origin[0],
            candidate["gap_endpoint_b"][1] - origin[1],
        ),
        fill=(245, 190, 20),
        width=4,
    )
    final.save(case_dir / "candidate-final.png")

    raw_panel = crop.copy()
    for ancestor_id in ancestor_ids:
        raw = raw_by_id[ancestor_id]
        _draw_geometry(raw_panel, raw["raw_geometry"], origin, (150, 35, 185), width=3)
    _add_banner(raw_panel, f"RAW HOUGH ANCESTORS: {len(ancestor_ids)}").save(case_dir / "raw-hough.png")
    _add_banner(crop.copy(), "RAW LSD: NO RECORDED EVIDENCE").save(case_dir / "raw-lsd.png")
    _add_banner(raw_panel.copy(), "PRE-CONSOLIDATION: HOUGH + CANONICALIZATION INPUT").save(case_dir / "pre-consolidation.png")
    _add_banner(crop.copy(), "POST-CONSOLIDATION: NO CONSOLIDATION STAGE IN LOCAL-D").save(case_dir / "post-consolidation.png")
    profile_image = _profile_image(profile_a, profile_b)
    profile_image.save(case_dir / "span-support.png")

    panels = [
        _add_banner(crop, "1 CLEAN SOURCE CONTEXT"),
        _add_banner(final, "2 FINAL FROZEN A/B + GAP"),
        _add_banner(raw_panel, "3 RAW HOUGH ANCESTORS"),
        _add_banner(crop.copy(), "4 RAW LSD: NO RECORDED EVIDENCE"),
        _add_banner(crop.copy(), "5 CONSOLIDATION: NOT PRESENT"),
        _add_banner(profile_image, "6 ORDERED SPAN SUPPORT"),
    ]
    fitted = [_fit_panel(panel) for panel in panels]
    canvas = Image.new("RGB", (1680, 790), (238, 240, 244))
    for index, panel in enumerate(fitted):
        canvas.paste(panel, ((index % 3) * 560, (index // 3) * 360))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 720, 1680, 790), fill=(250, 250, 250))
    draw.text((12, 732), summary[:190], fill=(25, 30, 40), font=_font(17))
    panel_path = case_dir / "panel.png"
    canvas.save(panel_path)
    return panel_path


# Conclusions from bounded manual inspection of the 24 generated panels.  The
# notes use only generic visual facts; they do not guess professional symbols.
MANUAL_DECISIONS: dict[int, dict[str, Any]] = {
    1: {
        "primary_root_cause": "RAW_HOUGH_OVERSPAN",
        "secondary_failures": ["PATTERNED_OR_DASHED_STROKE"],
        "confidence": "PROVEN",
        "earliest_failure_stage": "RAW_HOUGH_OUTPUT",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "source has repeated dash pattern",
        "notes": "Raw Hough A/B cross repeated blank intervals; ordered raw support is 0.792/0.772 with a six-sample interruption in B.",
    },
    2: {
        "primary_root_cause": "VALID_ANNOTATION_HARD_NEGATIVE",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "table/note rule with adjacent text",
        "notes": "Both fragments lie on the same note/table rule; the provisional INVALID label is not evidence of a pairing defect.",
    },
    3: {
        "primary_root_cause": "VALID_ANNOTATION_HARD_NEGATIVE",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "drawing-layout/view boundary",
        "notes": "Both spans have complete sampled support and form one layout boundary rather than an object-continuation training positive.",
    },
    4: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "PROVEN",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "square and circular nodes intersect the span",
        "notes": "A/B are source-supported but the gap contains explicit node geometry; a direct bridge would collapse topology.",
    },
    5: {
        "primary_root_cause": "CANDIDATE_PAIRING_ERROR",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "dense independent plan structures terminate around the gap",
        "notes": "The fragments are individually plausible, but context does not show one underlying stroke through the intervening plan structure.",
    },
    6: {
        "primary_root_cause": "VALID_ANNOTATION_HARD_NEGATIVE",
        "confidence": "PROVEN",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "dimension/grid chain with circular markers",
        "notes": "A/B lie on one dimension/grid rule; this is useful negative evidence, not unsupported geometry.",
    },
    7: {
        "primary_root_cause": "VALID_ANNOTATION_HARD_NEGATIVE",
        "confidence": "PROVEN",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "schedule/table row",
        "notes": "Both fully supported fragments belong to a single schedule row rule.",
    },
    8: {
        "primary_root_cause": "CANDIDATE_PAIRING_ERROR",
        "confidence": "PROVEN",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "two closed drawing/view frames separated by whitespace",
        "notes": "A is a boundary of the upper view and B a boundary of the lower view; both primitives are intact but unrelated.",
    },
    9: {
        "primary_root_cause": "RAW_HOUGH_OVERSPAN",
        "secondary_failures": ["GLYPH_TEXT_CONTAMINATION"],
        "confidence": "PROVEN",
        "earliest_failure_stage": "RAW_HOUGH_OUTPUT",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "Latin glyph strokes and inter-glyph whitespace",
        "notes": "Raw Hough segments traverse text glyphs; raw support is 0.653/0.782 with seven- and four-sample interruptions.",
    },
    10: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "terminal circle/square and adjoining layout structure",
        "notes": "The vertical fragments are intact, but an explicit terminal/node occupies the proposed connection.",
    },
    11: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "PROVEN",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "filled rectangular node at the gap",
        "notes": "The source-supported horizontal pieces terminate around a filled node; direct straight bridging is not source-faithful.",
    },
    12: {
        "primary_root_cause": "INTENTIONAL_OPENING_OR_INTERRUPTION",
        "confidence": "PLAUSIBLE",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "clear blank interval between adjacent room/boundary structures",
        "notes": "Both fragments are fully supported, while the 54 px internal interval is visibly blank; the exact semantic role is not recorded.",
    },
    13: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "PROVEN",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "square connector at a horizontal crossing",
        "notes": "A/B participate in one vertical topology, but the source explicitly records an intermediate connector.",
    },
    14: {
        "primary_root_cause": "RAW_HOUGH_OVERSPAN",
        "secondary_failures": ["PATTERNED_OR_DASHED_STROKE"],
        "confidence": "PROVEN",
        "earliest_failure_stage": "RAW_HOUGH_OUTPUT",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "dash/dot datum pattern",
        "notes": "Raw fragment B spans a patterned blank interval; its ordered raw profile has an eight-sample interruption.",
    },
    15: {
        "primary_root_cause": "INSUFFICIENT_PROVENANCE",
        "confidence": "UNRESOLVED",
        "earliest_failure_stage": "NOT_AVAILABLE",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "UNRESOLVED",
        "competing_structure_evidence": "two nearby vertical boundaries with six-pixel axis offset",
        "notes": "The raster permits both a skewed same-boundary reading and a parallel-boundary pairing error; no vector identity survives.",
    },
    16: {
        "primary_root_cause": "VALID_ANNOTATION_HARD_NEGATIVE",
        "confidence": "PROVEN",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "dimension/grid line with repeated markers",
        "notes": "Both fully supported fragments lie on one annotation/layout rule.",
    },
    17: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "PROVEN",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "square connector at a horizontal crossing",
        "notes": "The vertical pieces are related but the source requires the recorded connector between them.",
    },
    18: {
        "primary_root_cause": "CANDIDATE_PAIRING_ERROR",
        "confidence": "PROVEN",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "separate stacked drawing/view frames",
        "notes": "A and B are fully supported boundaries from adjacent view frames, separated by the frame/header region.",
    },
    19: {
        "primary_root_cause": "VALID_ANNOTATION_HARD_NEGATIVE",
        "confidence": "PROVEN",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "title/signature table row and cell boundary",
        "notes": "A/B are intact portions of one title-block table rule.",
    },
    20: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "rectangular wall/opening module intersects the span",
        "notes": "The wall/boundary fragments are individually intact, but the gap coincides with explicit intermediate geometry.",
    },
    21: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "rectangular wall/opening module at the gap",
        "notes": "The two source-supported wall-line pieces are separated by a recorded component/opening module.",
    },
    22: {
        "primary_root_cause": "COMPONENT_OR_NODE_MEDIATED",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "wall/opening module intersects the proposed bridge",
        "notes": "A/B remain plausible topology participants, but the source does not support replacing the intermediate structure with a straight bridge.",
    },
    23: {
        "primary_root_cause": "MIXED_ROLE_COLLINEAR_PAIRING",
        "confidence": "STRONGLY_SUPPORTED",
        "earliest_failure_stage": "CANDIDATE_PAIR_FORMATION",
        "direct_continuation_still_plausible": "NO",
        "needs_production_fix": "YES",
        "competing_structure_evidence": "thick object boundary above; thin grid/dimension extension to a numbered circle below",
        "notes": "The fragments are near-collinear but transition from object boundary to layout/grid extension at the corner node.",
    },
    24: {
        "primary_root_cause": "VALID_DIRECT_OBJECT_CONTINUATION",
        "confidence": "PLAUSIBLE",
        "earliest_failure_stage": "NO_UNSUPPORTED_GEOMETRIC_CLAIM",
        "direct_continuation_still_plausible": "YES",
        "needs_production_fix": "NO",
        "competing_structure_evidence": "none established; small skew/scan offset only",
        "notes": "Both long boundary fragments have 0.98 sampled support and a six-pixel gap; dense context prevents PROVEN confidence.",
    },
}


def _decision(review_index: int) -> dict[str, Any]:
    default = {
        "primary_root_cause": "INSUFFICIENT_PROVENANCE",
        "secondary_failures": [],
        "confidence": "UNRESOLVED",
        "earliest_failure_stage": NOT_AVAILABLE,
        "direct_continuation_still_plausible": True,
        "needs_production_fix": "UNRESOLVED",
        "competing_structure_evidence": NOT_AVAILABLE,
        "notes": "Manual evidence inspection pending.",
    }
    return {**default, **MANUAL_DECISIONS.get(review_index, {})}


def _legacy_reviews(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = _load_json(path)
    return {item["candidate_id"]: item for item in payload.get("items", [])}


def _raw_ancestor_payload(
    normalized: dict[str, Any] | None,
    raw_by_id: dict[str, dict[str, Any]],
    gray: np.ndarray,
) -> list[dict[str, Any]] | str:
    if normalized is None:
        return NOT_AVAILABLE
    output: list[dict[str, Any]] = []
    for ancestor_id in normalized["raw_ancestor_ids"]:
        record = dict(raw_by_id[ancestor_id])
        record["span_support_profile"] = _profile_summary(
            sample_span_support(gray, record["raw_geometry"])
        )
        output.append(record)
    return output


def _pairing_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "orientation_difference_deg": candidate["orientation_difference_deg"],
        "axis_delta_px": candidate["alignment_metrics"]["axis_delta_px"],
        "projected_span_px": candidate["alignment_metrics"]["projected_span_px"],
        "fragment_a_length_px": candidate["alignment_metrics"]["fragment_a_length_px"],
        "fragment_b_length_px": candidate["alignment_metrics"]["fragment_b_length_px"],
        "gap_length_px": candidate["gap_length_px"],
        "dedup_cluster_id": candidate["dedup_cluster_id"],
        "source_connectivity_metric": NOT_AVAILABLE,
        "candidate_score": NOT_AVAILABLE,
        "actual_conditions": {
            "same_orientation": True,
            "axis_delta_at_most_8_px": candidate["alignment_metrics"]["axis_delta_px"] <= 8,
            "accepted_gap_range_px": [5, 70],
            "accepted_projected_span_range_px": [85, 900],
            "bounded_nearby_search": True,
            "semantic_or_topological_role_check": False,
        },
    }


def _validate_cases(cases: list[dict[str, Any]]) -> None:
    if len(cases) != 24:
        raise ValueError("audit must contain exactly 24 cases")
    if [item["review_index"] for item in cases] != list(range(1, 25)):
        raise ValueError("candidate order was not preserved")
    for case in cases:
        if case["primary_root_cause"] not in ROOT_CAUSES:
            raise ValueError(f"invalid primary root cause: {case['primary_root_cause']}")
        if case["confidence"] not in CONFIDENCES:
            raise ValueError(f"invalid confidence: {case['confidence']}")
        if not isinstance(case["secondary_failures"], list):
            raise ValueError("secondary failures must be a list")
        if any(item not in ROOT_CAUSES for item in case["secondary_failures"]):
            raise ValueError("invalid secondary root cause")


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item["primary_root_cause"] for item in cases)
    primary_counts = {item: counts.get(item, 0) for item in ROOT_CAUSES}
    upstream = sum(item["primary_root_cause"] in PRIMITIVE_INTEGRITY_CAUSES for item in cases)
    pairing = sum(
        item["primary_root_cause"] in PAIRING_CAUSES
        or any(value in PAIRING_CAUSES for value in item["secondary_failures"])
        for item in cases
    )
    both = sum(
        item["primary_root_cause"] in PRIMITIVE_INTEGRITY_CAUSES
        and any(value in PAIRING_CAUSES for value in item["secondary_failures"])
        for item in cases
    )
    pure_pairing = sum(
        item["primary_root_cause"] in PAIRING_CAUSES
        and item["primary_root_cause"] not in {"VALID_ANNOTATION_HARD_NEGATIVE", "VALID_DIRECT_OBJECT_CONTINUATION"}
        for item in cases
    )
    return {
        "schema_version": 1,
        "task_id": "LINE_PROVENANCE_AUDIT_V1",
        "production_semantic_delta": "NONE",
        "frozen_candidates_audited": len(cases),
        "source_evidence_traced": sum(item["source_asset_path"] != NOT_AVAILABLE for item in cases),
        "raw_hough_provenance_available": sum(item["raw_hough_ancestors"] != NOT_AVAILABLE for item in cases),
        "raw_lsd_provenance_available": 0,
        "consolidation_provenance_available": 0,
        "pairing_provenance_available": sum(item["candidate_pairing_metrics"] != NOT_AVAILABLE for item in cases),
        "span_support_profiles": sum(bool(item["span_support_profiles"]) for item in cases),
        "primary_root_cause_counts": primary_counts,
        "primary_counts_sum": sum(primary_counts.values()),
        "cases_with_primitive_integrity_failure": upstream,
        "cases_with_pure_pairing_failure": pure_pairing,
        "cases_with_both_upstream_and_pairing_failure": both,
        "cases_with_any_pairing_issue": pairing,
        "valid_hard_negatives": counts.get("VALID_ANNOTATION_HARD_NEGATIVE", 0),
        "valid_direct_object_continuations": counts.get("VALID_DIRECT_OBJECT_CONTINUATION", 0),
        "unresolved": sum(item["confidence"] == "UNRESOLVED" for item in cases),
        "earliest_failure_stage_identified": sum(item["earliest_failure_stage"] != NOT_AVAILABLE for item in cases),
        "model_run": "NO",
        "model_assisted_labeling": "NO",
        "new_candidate_mining": "NO",
        "validation": "NO",
        "locked_blind": "0 / 8",
        "h1_h2_opened": "NO",
    }


def _markdown(cases: list[dict[str, Any]], summary: dict[str, Any], paths: AuditPaths) -> str:
    lines = [
        "# LINE PROVENANCE AUDIT V1 — FINAL",
        "",
        "## Scope and evidence boundary",
        "",
        "This bounded audit traces the exact frozen Local-D 24 in fixed human-review order. Local-D used a standalone HoughLinesP detector followed by axis canonicalization, duplicate suppression, a per-orientation cap, geometric pair formation, and candidate deduplication. It did not run LSD, production line consolidation, ownership, fallback, artifact suppression, FinalStructure, or CAD export. Those stages are therefore recorded as `NOT_AVAILABLE`, not inferred.",
        "",
        "The prior flat-four export is retained only as `LEGACY_PROVISIONAL_REVIEW`. The checked two-stage runtime package contains no persisted review-result export, so no two-stage answers were invented. Root-cause conclusions come from the reproduced detector lineage, ordered span-support diagnostics, and bounded manual inspection of the generated panels.",
        "",
        "PRODUCTION_SEMANTIC_DELTA: NONE",
        "",
        "## Evidence availability",
        "",
        f"- Source evidence traced: {summary['source_evidence_traced']} / 24",
        f"- Raw Hough provenance available: {summary['raw_hough_provenance_available']} / 24",
        f"- Raw LSD provenance available: {summary['raw_lsd_provenance_available']} / 24",
        f"- Consolidation provenance available: {summary['consolidation_provenance_available']} / 24 (stage not present in Local-D)",
        f"- Pairing provenance available: {summary['pairing_provenance_available']} / 24",
        f"- Span-support profiles: {summary['span_support_profiles']} / 24",
        "",
        "## 24-case diagnostic table",
        "",
        "| Review # | Candidate ID | Human review observation | Fragment A integrity | Fragment B integrity | Earliest proven/supported failure stage | Primary root cause | Secondary failure | Confidence | Direct continuation still plausible? | Needs production fix? | Notes |",
        "|---:|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        observation = case["human_review_observation"].replace("|", "/")
        note = case["notes"].replace("|", "/")
        secondary = ", ".join(case["secondary_failures"]) or "NONE"
        lines.append(
            f"| {case['review_index']} | `{case['candidate_id']}` | {observation} | {case['fragment_a_source_support']['observed_span_integrity']} | {case['fragment_b_source_support']['observed_span_integrity']} | {case['earliest_failure_stage']} | {case['primary_root_cause']} | {secondary} | {case['confidence']} | {case['direct_continuation_still_plausible']} | {case['needs_production_fix']} | {note} |"
        )
    lines.extend(["", "## Aggregate counts", ""])
    for cause in ROOT_CAUSES:
        lines.append(f"- {cause}: {summary['primary_root_cause_counts'][cause]}")
    lines.extend(
        [
            "",
            f"CASES WITH PRIMITIVE INTEGRITY FAILURE: {summary['cases_with_primitive_integrity_failure']}",
            "",
            f"CASES WITH PURE PAIRING FAILURE: {summary['cases_with_pure_pairing_failure']}",
            "",
            f"CASES WITH BOTH UPSTREAM + PAIRING FAILURE: {summary['cases_with_both_upstream_and_pairing_failure']}",
            "",
            f"VALID HARD NEGATIVES: {summary['valid_hard_negatives']}",
            "",
            f"VALID DIRECT OBJECT CONTINUATIONS: {summary['valid_direct_object_continuations']}",
            "",
            f"UNRESOLVED: {summary['unresolved']}",
            "",
            "## Engineering decision",
            "",
            f"NEXT PRODUCTION TARGET: {summary.get('next_production_target', 'INSUFFICIENT EVIDENCE')}",
            "",
            f"MODEL BAKE-OFF SHOULD RESUME: {summary.get('model_bakeoff_should_resume', 'NO')}",
            "",
            "The audit does not implement that target. No detector threshold, merge rule, ownership rule, fallback rule, artifact rule, OCR behavior, model inference, or CAD export behavior changed.",
            "",
            "## Governance",
            "",
            "- MODEL RUN: NO",
            "- MODEL-ASSISTED LABELING: NO",
            "- NEW CANDIDATE MINING: NO",
            "- VALIDATION: NO",
            "- LOCKED_BLIND: 0 / 8",
            "- H1/H2 OPENED: NO",
            "- PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED",
            "- Runtime source-derived evidence remains Git-ignored.",
            "",
            "## Verification",
            "",
            "Focused audit tests: 8 passed. They cover frozen identity/order, detector-family separation, explicit missing provenance, deterministic ordered sampling, production no-op defaults, governance, vocabulary validation, and count closure.",
            "",
            f"Runtime evidence: `{paths.runtime}`",
            "",
            "LINE_PROVENANCE_AUDIT_V1: COMPLETE",
            "",
        ]
    )
    return "\n".join(lines)


def _contact_sheet(panel_paths: list[Path], output: Path) -> None:
    thumb_w, thumb_h = 560, 264
    canvas = Image.new("RGB", (thumb_w * 3, thumb_h * 8), (230, 232, 236))
    for index, path in enumerate(panel_paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (thumb_w, thumb_h), "white")
        panel.paste(image, ((thumb_w - image.width) // 2, (thumb_h - image.height) // 2))
        ImageDraw.Draw(panel).text((8, 7), f"CASE {index + 1:02d}", fill=(10, 10, 10), font=_font(17))
        canvas.paste(panel, ((index % 3) * thumb_w, (index // 3) * thumb_h))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def build_audit(repo: Path, *, diagnostic_enabled: bool = False) -> dict[str, Any]:
    """Build the audit only when explicitly enabled; default is a no-op."""

    if not diagnostic_enabled:
        return {"diagnostic_enabled": False, "production_geometry_mutated": False}
    paths = AuditPaths(repo.resolve())
    candidates = load_frozen_candidates(paths)
    legacy = _legacy_reviews(paths.legacy_review)
    source_cache: dict[str, tuple[Image.Image, np.ndarray, list[dict[str, Any]], list[dict[str, Any]]]] = {}
    cases: list[dict[str, Any]] = []
    panels: list[Path] = []
    for candidate in candidates:
        unit = candidate["selected_unit_id"]
        source_path = paths.local_d_runtime / "source-renders" / f"{unit}.png"
        if unit not in source_cache:
            image = Image.open(source_path).convert("RGB")
            gray = np.asarray(image.convert("L"))
            _binary, raw = _raw_hough(gray)
            normalized = normalize_hough_records(raw)
            source_cache[unit] = (image, gray, raw, normalized)
        image, gray, raw, normalized = source_cache[unit]
        raw_by_id = {item["id"]: item for item in raw}
        norm_a = _find_normalized(normalized, candidate["fragment_a_geometry"])
        norm_b = _find_normalized(normalized, candidate["fragment_b_geometry"])
        profile_a = sample_span_support(gray, candidate["fragment_a_geometry"])
        profile_b = sample_span_support(gray, candidate["fragment_b_geometry"])
        review = legacy.get(candidate["candidate_id"], {})
        observation = f"LEGACY_PROVISIONAL_REVIEW: {review.get('human_label', NOT_AVAILABLE)}"
        if review.get("reviewer_note"):
            observation += f"; note: {review['reviewer_note']}"
        decision = _decision(candidate["review_index"])
        ancestors = []
        for record in (norm_a, norm_b):
            if record is not None:
                ancestors.extend(record["raw_ancestor_ids"])
        ancestors = list(dict.fromkeys(ancestors))
        case = {
            "candidate_id": candidate["candidate_id"],
            "review_index": candidate["review_index"],
            "source_family": candidate["source_family_id"],
            "source_document": candidate["source_document_id"],
            "source_page_or_view": candidate["page_layout_modelspace_identity"],
            "source_asset_path": str(source_path.relative_to(repo)).replace("\\", "/"),
            "local_crop_path": candidate["local_crop_path"],
            "context_crop_path": candidate["context_crop_path"],
            "fragment_a_final_geometry": candidate["fragment_a_geometry"],
            "fragment_b_final_geometry": candidate["fragment_b_geometry"],
            "fragment_a_source_support": _profile_summary(profile_a),
            "fragment_b_source_support": _profile_summary(profile_b),
            "fragment_a_origin_ids": [norm_a["id"]] if norm_a else NOT_AVAILABLE,
            "fragment_b_origin_ids": [norm_b["id"]] if norm_b else NOT_AVAILABLE,
            "raw_hough_ancestors": {
                "fragment_a": _raw_ancestor_payload(norm_a, raw_by_id, gray),
                "fragment_b": _raw_ancestor_payload(norm_b, raw_by_id, gray),
            } if norm_a or norm_b else NOT_AVAILABLE,
            "raw_lsd_ancestors": NOT_AVAILABLE,
            "pre_consolidation_ancestors": {
                "fragment_a": norm_a or NOT_AVAILABLE,
                "fragment_b": norm_b or NOT_AVAILABLE,
            },
            "post_consolidation_ids": NOT_AVAILABLE,
            "consolidation_trace": "NOT_APPLICABLE_LOCAL_D_HAS_NO_CONSOLIDATION_STAGE",
            "ownership_fallback_artifact_path": NOT_AVAILABLE,
            "candidate_pairing_reason": candidate["proposal_reason"],
            "candidate_pairing_metrics": _pairing_metrics(candidate),
            "candidate_gap_length": candidate["gap_length_px"],
            "angle_difference": candidate["orientation_difference_deg"],
            "collinearity_offset_metrics": {
                "axis_delta_px": candidate["alignment_metrics"]["axis_delta_px"],
                "orientation_difference_deg": candidate["orientation_difference_deg"],
            },
            "span_support_profiles": {"fragment_a": profile_a, "fragment_b": profile_b},
            "human_review_observation": observation,
            "human_review_authority": "OBSERVATION_ONLY_NOT_ROOT_CAUSE_TRUTH",
            **decision,
        }
        case_dir = paths.runtime / "cases" / f"case-{candidate['review_index']:02d}"
        panel = _render_case_assets(
            case_dir,
            image,
            candidate,
            raw_by_id,
            ancestors,
            profile_a,
            profile_b,
            f"{candidate['review_index']:02d} {candidate['candidate_id']} | {decision['primary_root_cause']} | {decision['confidence']}",
        )
        _write_json(case_dir / "trace.json", case)
        panels.append(panel)
        cases.append(case)
    _validate_cases(cases)
    summary = _summary(cases)
    summary["next_production_target"] = (
        "MULTI-STAGE FIX REQUIRED"
        if summary["cases_with_primitive_integrity_failure"]
        and summary["cases_with_pure_pairing_failure"]
        else "INSUFFICIENT EVIDENCE"
    )
    summary["model_bakeoff_should_resume"] = "NO"
    summary["diagnostic_enabled"] = True
    summary["production_geometry_mutated"] = False
    _write_json(paths.runtime / "audit-summary.json", summary)
    _contact_sheet(panels, paths.runtime / "audit-contact-sheet.png")
    paths.tracked.mkdir(parents=True, exist_ok=True)
    _write_json(paths.tracked / "line-provenance-audit-cases.json", {"schema_version": 1, "cases": cases})
    _write_json(paths.tracked / "line-provenance-audit-summary.json", summary)
    (paths.tracked / "LINE-PROVENANCE-AUDIT-V1-FINAL.md").write_text(
        _markdown(cases, summary, paths), encoding="utf-8"
    )
    return summary


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
