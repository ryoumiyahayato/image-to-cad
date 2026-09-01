"""Domain-neutral, deterministic raster evidence frontend for Draftsman VS3."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from math import cos, pi, sin
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from .draftsman_contract import canonical_json_bytes, semantic_id


DRAFTSMAN_RASTER_EVIDENCE_VERSION = "draftsman-raster-evidence-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


class RasterPrimitiveKind(str, Enum):
    GLYPH_SHAPE = "GLYPH_SHAPE"
    TAG_REGION = "TAG_REGION"
    LINE_FRAGMENT = "LINE_FRAGMENT"


@dataclass(frozen=True)
class RasterEvidenceConfig:
    hough_dp: float = 1.0
    hough_min_distance_px: float = 11.0
    hough_edge_threshold: float = 80.0
    hough_accumulator_threshold: float = 14.0
    minimum_circle_radius_px: int = 5
    maximum_circle_radius_px: int = 15
    maximum_glyph_radius_px: int = 9
    minimum_tag_radius_px: int = 9
    maximum_tag_dx_px: int = 26
    minimum_tag_dy_px: int = 14
    maximum_tag_dy_px: int = 38
    foreground_threshold: int = 175
    port_probe_length_px: int = 28
    port_probe_half_height_px: int = 3
    evidence_port_support_minimum: float = 0.55
    adaptive_block_size: int = 31
    adaptive_constant: float = 12.0
    horizontal_kernel_length_px: int = 31
    maximum_line_thickness_px: int = 8
    normalized_patch_size: int = 21
    normalized_patch_margin_px: int = 2
    schema_version: str = DRAFTSMAN_RASTER_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        if self.adaptive_block_size < 3 or self.adaptive_block_size % 2 == 0:
            raise ValueError("Adaptive threshold block size must be odd and >= 3")
        if self.normalized_patch_size < 5 or self.normalized_patch_size % 2 == 0:
            raise ValueError("Normalized patch size must be odd and >= 5")
        if not 0.0 <= self.evidence_port_support_minimum <= 1.0:
            raise ValueError("Evidence port support must be in [0, 1]")

    @property
    def config_id(self) -> str:
        return semantic_id(
            "draftsman-raster-evidence-config",
            self.schema_version,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in self.__dict__.items()
            if key != "schema_version"
        }


@dataclass(frozen=True)
class RasterGlyphEvidence:
    stable_evidence_id: str
    source_bbox_px: tuple[int, int, int, int]
    center_px: tuple[int, int]
    radius_px: int
    normalized_patch_rows: tuple[str, ...]
    ring_coverage: float
    schema_version: str = DRAFTSMAN_RASTER_EVIDENCE_VERSION
    kind: RasterPrimitiveKind = RasterPrimitiveKind.GLYPH_SHAPE

    @classmethod
    def create(
        cls,
        *,
        source_identity: dict[str, object],
        center_px: tuple[int, int],
        radius_px: int,
        normalized_patch_rows: Iterable[str],
        ring_coverage: float,
    ) -> RasterGlyphEvidence:
        rows = tuple(normalized_patch_rows)
        x_value, y_value = center_px
        bbox = (
            x_value - radius_px,
            y_value - radius_px,
            x_value + radius_px,
            y_value + radius_px,
        )
        identity = {
            **source_identity,
            "kind": RasterPrimitiveKind.GLYPH_SHAPE.value,
            "source_bbox_px": list(bbox),
            "center_px": list(center_px),
            "radius_px": radius_px,
            "normalized_patch_rows": list(rows),
            "ring_coverage": _number(ring_coverage),
        }
        return cls(
            stable_evidence_id=semantic_id(
                "draftsman-raster-glyph-evidence",
                DRAFTSMAN_RASTER_EVIDENCE_VERSION,
                identity,
            ),
            source_bbox_px=bbox,
            center_px=center_px,
            radius_px=radius_px,
            normalized_patch_rows=rows,
            ring_coverage=_number(ring_coverage),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_evidence_id": self.stable_evidence_id,
            "kind": self.kind.value,
            "source_bbox_px": list(self.source_bbox_px),
            "center_px": list(self.center_px),
            "radius_px": self.radius_px,
            "normalized_patch_rows": list(self.normalized_patch_rows),
            "ring_coverage": self.ring_coverage,
        }


@dataclass(frozen=True)
class RasterTagRegionEvidence:
    stable_evidence_id: str
    source_bbox_px: tuple[int, int, int, int]
    center_px: tuple[int, int]
    radius_px: int
    content_candidate: str | None = None
    schema_version: str = DRAFTSMAN_RASTER_EVIDENCE_VERSION
    kind: RasterPrimitiveKind = RasterPrimitiveKind.TAG_REGION

    @classmethod
    def create(
        cls,
        *,
        source_identity: dict[str, object],
        center_px: tuple[int, int],
        radius_px: int,
    ) -> RasterTagRegionEvidence:
        x_value, y_value = center_px
        bbox = (
            x_value - radius_px,
            y_value - radius_px,
            x_value + radius_px,
            y_value + radius_px,
        )
        identity = {
            **source_identity,
            "kind": RasterPrimitiveKind.TAG_REGION.value,
            "source_bbox_px": list(bbox),
            "center_px": list(center_px),
            "radius_px": radius_px,
            "content_candidate": None,
        }
        return cls(
            stable_evidence_id=semantic_id(
                "draftsman-raster-tag-region-evidence",
                DRAFTSMAN_RASTER_EVIDENCE_VERSION,
                identity,
            ),
            source_bbox_px=bbox,
            center_px=center_px,
            radius_px=radius_px,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_evidence_id": self.stable_evidence_id,
            "kind": self.kind.value,
            "source_bbox_px": list(self.source_bbox_px),
            "center_px": list(self.center_px),
            "radius_px": self.radius_px,
            "content_candidate": self.content_candidate,
        }


@dataclass(frozen=True)
class RasterLineFragmentEvidence:
    stable_evidence_id: str
    source_bbox_px: tuple[int, int, int, int]
    start: tuple[float, float]
    end: tuple[float, float]
    thickness_px: int
    schema_version: str = DRAFTSMAN_RASTER_EVIDENCE_VERSION
    kind: RasterPrimitiveKind = RasterPrimitiveKind.LINE_FRAGMENT

    @classmethod
    def create(
        cls,
        *,
        source_identity: dict[str, object],
        image_height: int,
        source_bbox_px: tuple[int, int, int, int],
    ) -> RasterLineFragmentEvidence:
        left, top, right, bottom = source_bbox_px
        source_y = (top + bottom) / 2.0
        start = (_number(left), _number(image_height - source_y))
        end = (_number(right), _number(image_height - source_y))
        identity = {
            **source_identity,
            "kind": RasterPrimitiveKind.LINE_FRAGMENT.value,
            "source_bbox_px": list(source_bbox_px),
            "start": list(start),
            "end": list(end),
            "thickness_px": bottom - top + 1,
        }
        return cls(
            stable_evidence_id=semantic_id(
                "draftsman-raster-line-fragment-evidence",
                DRAFTSMAN_RASTER_EVIDENCE_VERSION,
                identity,
            ),
            source_bbox_px=source_bbox_px,
            start=start,
            end=end,
            thickness_px=bottom - top + 1,
        )

    @property
    def length(self) -> float:
        return self.end[0] - self.start[0]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_evidence_id": self.stable_evidence_id,
            "kind": self.kind.value,
            "source_bbox_px": list(self.source_bbox_px),
            "start": list(self.start),
            "end": list(self.end),
            "thickness_px": self.thickness_px,
            "length": _number(self.length),
        }


RasterEvidencePrimitive = (
    RasterGlyphEvidence | RasterTagRegionEvidence | RasterLineFragmentEvidence
)


@dataclass(frozen=True)
class RasterElectricalCandidateEvidence:
    stable_candidate_id: str
    glyph_evidence_id: str
    tag_evidence_id: str
    nearby_line_evidence_ids: tuple[str, ...]
    source_center_px: tuple[int, int]
    radius_px: int
    left_line_support: float
    right_line_support: float
    normalized_frame_bounds: tuple[float, float, float, float]
    schema_version: str = DRAFTSMAN_RASTER_EVIDENCE_VERSION

    @classmethod
    def create(
        cls,
        *,
        source_identity: dict[str, object],
        glyph: RasterGlyphEvidence,
        tag: RasterTagRegionEvidence,
        line_ids: Iterable[str],
        left_line_support: float,
        right_line_support: float,
        image_height: int,
    ) -> RasterElectricalCandidateEvidence:
        ordered_lines = tuple(sorted(set(line_ids)))
        x_value, y_value = glyph.center_px
        radius = glyph.radius_px
        frame = (
            _number(x_value - radius),
            _number(image_height - (y_value + radius)),
            _number(x_value + radius),
            _number(image_height - (y_value - radius)),
        )
        identity = {
            **source_identity,
            "glyph_evidence_id": glyph.stable_evidence_id,
            "tag_evidence_id": tag.stable_evidence_id,
            "nearby_line_evidence_ids": list(ordered_lines),
            "source_center_px": list(glyph.center_px),
            "radius_px": radius,
            "left_line_support": _number(left_line_support),
            "right_line_support": _number(right_line_support),
            "normalized_frame_bounds": list(frame),
        }
        return cls(
            stable_candidate_id=semantic_id(
                "draftsman-raster-electrical-candidate",
                DRAFTSMAN_RASTER_EVIDENCE_VERSION,
                identity,
            ),
            glyph_evidence_id=glyph.stable_evidence_id,
            tag_evidence_id=tag.stable_evidence_id,
            nearby_line_evidence_ids=ordered_lines,
            source_center_px=glyph.center_px,
            radius_px=radius,
            left_line_support=_number(left_line_support),
            right_line_support=_number(right_line_support),
            normalized_frame_bounds=frame,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_candidate_id": self.stable_candidate_id,
            "glyph_evidence_id": self.glyph_evidence_id,
            "tag_evidence_id": self.tag_evidence_id,
            "nearby_line_evidence_ids": list(self.nearby_line_evidence_ids),
            "source_center_px": list(self.source_center_px),
            "radius_px": self.radius_px,
            "left_line_support": self.left_line_support,
            "right_line_support": self.right_line_support,
            "normalized_frame_bounds": list(self.normalized_frame_bounds),
        }


@dataclass(frozen=True)
class RasterEvidenceManifest:
    source_document_id: str
    source_page: int
    source_sha256: str
    image_size_px: tuple[int, int]
    transform_id: str
    producer_config_id: str
    primitives: tuple[RasterEvidencePrimitive, ...]
    candidates: tuple[RasterElectricalCandidateEvidence, ...]
    schema_version: str = DRAFTSMAN_RASTER_EVIDENCE_VERSION

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-raster-evidence-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": self.source_page,
                "source_sha256": self.source_sha256,
                "image_size_px": list(self.image_size_px),
                "transform_id": self.transform_id,
                "producer_config_id": self.producer_config_id,
                "primitive_ids": [item.stable_evidence_id for item in self.primitives],
                "candidate_ids": [item.stable_candidate_id for item in self.candidates],
            },
        )

    def primitive_by_id(self) -> dict[str, RasterEvidencePrimitive]:
        return {item.stable_evidence_id: item for item in self.primitives}

    @property
    def line_fragments(self) -> tuple[RasterLineFragmentEvidence, ...]:
        return tuple(
            item for item in self.primitives if isinstance(item, RasterLineFragmentEvidence)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_sha256": self.source_sha256,
            "image_size_px": list(self.image_size_px),
            "transform_id": self.transform_id,
            "producer_config_id": self.producer_config_id,
            "primitive_count": len(self.primitives),
            "candidate_count": len(self.candidates),
            "primitives": [item.to_dict() for item in self.primitives],
            "candidates": [item.to_dict() for item in self.candidates],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _normalized_patch_rows(
    grayscale: np.ndarray,
    *,
    center: tuple[int, int],
    radius: int,
    config: RasterEvidenceConfig,
) -> tuple[str, ...]:
    x_value, y_value = center
    margin = radius + config.normalized_patch_margin_px
    patch = grayscale[
        y_value - margin : y_value + margin + 1,
        x_value - margin : x_value + margin + 1,
    ]
    normalized = cv2.resize(
        patch,
        (config.normalized_patch_size, config.normalized_patch_size),
        interpolation=cv2.INTER_AREA,
    )
    _, binary = cv2.threshold(
        normalized,
        0,
        1,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    return tuple(
        "".join("#" if value else "." for value in row) for row in binary
    )


def _ring_coverage(
    grayscale: np.ndarray,
    *,
    center: tuple[int, int],
    radius: int,
    threshold: int,
) -> float:
    x_value, y_value = center
    hits = 0
    sample_count = 36
    for angle in np.linspace(0.0, 2.0 * pi, sample_count, endpoint=False):
        hit = False
        for delta in (-1, 0, 1):
            sample_x = int(round(x_value + (radius + delta) * cos(float(angle))))
            sample_y = int(round(y_value + (radius + delta) * sin(float(angle))))
            if grayscale[sample_y, sample_x] < threshold:
                hit = True
                break
        hits += int(hit)
    return _number(hits / sample_count)


def _port_support(
    foreground: np.ndarray,
    *,
    center: tuple[int, int],
    radius: int,
    side: str,
    config: RasterEvidenceConfig,
) -> float:
    x_value, y_value = center
    if side == "LEFT":
        start = max(0, x_value - radius - config.port_probe_length_px)
        stop = max(0, x_value - radius - 1)
    else:
        start = min(foreground.shape[1], x_value + radius + 1)
        stop = min(
            foreground.shape[1],
            x_value + radius + config.port_probe_length_px,
        )
    columns = range(start, stop)
    hits = 0
    total = 0
    for column in columns:
        top = max(0, y_value - config.port_probe_half_height_px)
        bottom = min(
            foreground.shape[0],
            y_value + config.port_probe_half_height_px + 1,
        )
        hits += int(bool(foreground[top:bottom, column].any()))
        total += 1
    return _number(hits / max(1, total))


def extract_raster_electrical_evidence(
    path: str | Path,
    *,
    source_document_id: str,
    source_page: int,
    config: RasterEvidenceConfig | None = None,
) -> RasterEvidenceManifest:
    """Extract high-recall shape/tag/line facts without electrical identity."""

    selected_config = config or RasterEvidenceConfig()
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    grayscale = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if grayscale is None:
        raise ValueError(f"Could not load raster source: {source}")
    height, width = grayscale.shape
    source_sha = sha256(source.read_bytes()).hexdigest()
    transform_id = semantic_id(
        "raster-image-to-cad-transform",
        DRAFTSMAN_RASTER_EVIDENCE_VERSION,
        {
            "source_document_id": source_document_id,
            "source_page": source_page,
            "source_sha256": source_sha,
            "image_size_px": [width, height],
            "source_space": "image-pixel-y-down",
            "target_space": "normalized-image-pixel-y-up",
            "operation": "x'=x; y'=image_height-y",
        },
    )
    source_identity = {
        "source_document_id": source_document_id,
        "source_page": source_page,
        "source_sha256": source_sha,
        "transform_id": transform_id,
        "producer_config_id": selected_config.config_id,
    }
    blurred = cv2.GaussianBlur(grayscale, (3, 3), 0)
    detected = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=selected_config.hough_dp,
        minDist=selected_config.hough_min_distance_px,
        param1=selected_config.hough_edge_threshold,
        param2=selected_config.hough_accumulator_threshold,
        minRadius=selected_config.minimum_circle_radius_px,
        maxRadius=selected_config.maximum_circle_radius_px,
    )
    circles = (
        []
        if detected is None
        else sorted(
            tuple(int(value) for value in circle)
            for circle in np.round(detected[0]).astype(int)
        )
    )
    small = [
        item for item in circles if item[2] <= selected_config.maximum_glyph_radius_px
    ]
    tags = [item for item in circles if item[2] >= selected_config.minimum_tag_radius_px]
    binary = cv2.adaptiveThreshold(
        grayscale,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        selected_config.adaptive_block_size,
        selected_config.adaptive_constant,
    )
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (selected_config.horizontal_kernel_length_px, 1),
        ),
    )
    contours, _ = cv2.findContours(
        horizontal,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    line_primitives: list[RasterLineFragmentEvidence] = []
    for contour in contours:
        x_value, y_value, line_width, line_height = cv2.boundingRect(contour)
        if (
            line_width < selected_config.horizontal_kernel_length_px
            or line_height > selected_config.maximum_line_thickness_px
        ):
            continue
        line_primitives.append(
            RasterLineFragmentEvidence.create(
                source_identity=source_identity,
                image_height=height,
                source_bbox_px=(
                    x_value,
                    y_value,
                    x_value + line_width - 1,
                    y_value + line_height - 1,
                ),
            )
        )
    line_primitives.sort(key=lambda item: item.stable_evidence_id)
    foreground = (
        np.asarray(
            cv2.compare(
                grayscale,
                selected_config.foreground_threshold,
                cv2.CMP_LT,
            ),
            dtype=np.uint8,
        )
        // 255
    )
    primitive_by_id: dict[str, RasterEvidencePrimitive] = {
        item.stable_evidence_id: item for item in line_primitives
    }
    candidates: list[RasterElectricalCandidateEvidence] = []
    for x_value, y_value, radius in small:
        if (
            x_value - radius - selected_config.normalized_patch_margin_px < 0
            or y_value - radius - selected_config.normalized_patch_margin_px < 0
            or x_value + radius + selected_config.normalized_patch_margin_px >= width
            or y_value + radius + selected_config.normalized_patch_margin_px >= height
        ):
            continue
        related_tags = [
            item
            for item in tags
            if abs(item[0] - x_value) <= selected_config.maximum_tag_dx_px
            and selected_config.minimum_tag_dy_px
            <= item[1] - y_value
            <= selected_config.maximum_tag_dy_px
        ]
        if not related_tags:
            continue
        left_support = _port_support(
            foreground,
            center=(x_value, y_value),
            radius=radius,
            side="LEFT",
            config=selected_config,
        )
        right_support = _port_support(
            foreground,
            center=(x_value, y_value),
            radius=radius,
            side="RIGHT",
            config=selected_config,
        )
        if max(left_support, right_support) < selected_config.evidence_port_support_minimum:
            continue
        selected_tag = min(
            related_tags,
            key=lambda item: (
                abs(item[0] - x_value) + abs(item[1] - y_value),
                item,
            ),
        )
        glyph = RasterGlyphEvidence.create(
            source_identity=source_identity,
            center_px=(x_value, y_value),
            radius_px=radius,
            normalized_patch_rows=_normalized_patch_rows(
                grayscale,
                center=(x_value, y_value),
                radius=radius,
                config=selected_config,
            ),
            ring_coverage=_ring_coverage(
                grayscale,
                center=(x_value, y_value),
                radius=radius,
                threshold=selected_config.foreground_threshold,
            ),
        )
        tag = RasterTagRegionEvidence.create(
            source_identity=source_identity,
            center_px=(selected_tag[0], selected_tag[1]),
            radius_px=selected_tag[2],
        )
        nearby_line_ids = tuple(
            item.stable_evidence_id
            for item in line_primitives
            if item.source_bbox_px[3] >= y_value - 6
            and item.source_bbox_px[1] <= y_value + 6
            and item.source_bbox_px[2] >= x_value - 40
            and item.source_bbox_px[0] <= x_value + 40
        )
        primitive_by_id[glyph.stable_evidence_id] = glyph
        primitive_by_id[tag.stable_evidence_id] = tag
        candidates.append(
            RasterElectricalCandidateEvidence.create(
                source_identity=source_identity,
                glyph=glyph,
                tag=tag,
                line_ids=nearby_line_ids,
                left_line_support=left_support,
                right_line_support=right_support,
                image_height=height,
            )
        )
    return RasterEvidenceManifest(
        source_document_id=source_document_id,
        source_page=source_page,
        source_sha256=source_sha,
        image_size_px=(width, height),
        transform_id=transform_id,
        producer_config_id=selected_config.config_id,
        primitives=tuple(
            sorted(primitive_by_id.values(), key=lambda item: item.stable_evidence_id)
        ),
        candidates=tuple(
            sorted(candidates, key=lambda item: item.stable_candidate_id)
        ),
    )
