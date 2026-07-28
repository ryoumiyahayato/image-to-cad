from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class StageSpec:
    index: int
    key: str
    slug: str
    name: str
    upstream_keys: tuple[str, ...]

    @property
    def stage_id(self) -> str:
        return f"stage-{self.index:02d}-{self.slug}"


STAGE_SPECS = (
    StageSpec(1, "original_page", "original-page", "原始页面", ()),
    StageSpec(2, "original_gray", "original-gray", "原始灰度图", ("original_page",)),
    StageSpec(
        3,
        "normalized_background",
        "normalized-background",
        "归一化背景图",
        ("original_gray",),
    ),
    StageSpec(
        4,
        "binary_foreground",
        "binary-foreground",
        "二值前景图",
        ("normalized_background",),
    ),
    StageSpec(
        5,
        "legacy_closing",
        "legacy-closing",
        "旧闭运算结果",
        ("binary_foreground",),
    ),
    StageSpec(
        6,
        "structural_roi",
        "structural-roi",
        "新结构 ROI",
        ("line_candidates_text_filtered",),
    ),
    StageSpec(
        7,
        "raw_line_candidates",
        "raw-line-candidates",
        "原始直线候选",
        ("binary_foreground",),
    ),
    StageSpec(
        8,
        "line_candidates_text_filtered",
        "line-candidates-text-filtered",
        "文字过滤后的直线候选",
        ("raw_line_candidates", "text_candidate_mask"),
    ),
    StageSpec(
        9,
        "candidate_endpoints",
        "candidate-endpoints",
        "候选端点",
        ("line_candidates_text_filtered",),
    ),
    StageSpec(
        10,
        "approved_connections",
        "approved-connections",
        "被批准的连接",
        ("structural_roi", "candidate_endpoints", "conflict_mask"),
    ),
    StageSpec(
        11,
        "rejected_connections",
        "rejected-connections",
        "被拒绝的连接",
        ("structural_roi", "candidate_endpoints", "conflict_mask"),
    ),
    StageSpec(
        12,
        "endpoint_snap",
        "endpoint-snap",
        "端点吸附前后结果",
        ("line_candidates_text_filtered",),
    ),
    StageSpec(
        13,
        "intersection_extension",
        "intersection-extension",
        "交点延伸前后结果",
        ("structural_roi", "approved_connections", "endpoint_snap"),
    ),
    StageSpec(
        14,
        "ocr_raw_tiles",
        "ocr-raw-tiles",
        "OCR 原始 tile",
        ("original_gray",),
    ),
    StageSpec(
        15,
        "ocr_rule_removed_tiles",
        "ocr-rule-removed-tiles",
        "OCR 去表格线 tile",
        ("ocr_raw_tiles",),
    ),
    StageSpec(
        16,
        "ocr_text_boxes",
        "ocr-text-boxes",
        "OCR 文本框",
        ("ocr_raw_tiles", "ocr_rule_removed_tiles"),
    ),
    StageSpec(
        17,
        "text_candidate_mask",
        "text-candidate-mask",
        "文字候选 mask",
        ("binary_foreground", "ocr_text_boxes"),
    ),
    StageSpec(
        18,
        "logo_candidate_mask",
        "logo-candidate-mask",
        "Logo 候选 mask",
        ("binary_foreground",),
    ),
    StageSpec(
        19,
        "signature_candidate_mask",
        "signature-candidate-mask",
        "签名候选 mask",
        ("binary_foreground",),
    ),
    StageSpec(
        20,
        "structural_line_candidate_mask",
        "structural-line-candidate-mask",
        "结构线候选 mask",
        ("line_candidates_text_filtered", "intersection_extension"),
    ),
    StageSpec(
        21,
        "conflict_mask",
        "conflict-mask",
        "冲突 mask",
        (
            "text_candidate_mask",
            "logo_candidate_mask",
            "signature_candidate_mask",
            "structural_line_candidate_mask",
        ),
    ),
    StageSpec(
        22,
        "residual_mask",
        "residual-mask",
        "residual mask",
        ("conflict_mask",),
    ),
    StageSpec(
        23,
        "final_structural_layer",
        "final-structural-layer",
        "最终结构线层",
        ("intersection_extension", "structural_line_candidate_mask"),
    ),
    StageSpec(
        24,
        "final_text_layer",
        "final-text-layer",
        "最终文字层",
        ("ocr_text_boxes", "text_candidate_mask"),
    ),
    StageSpec(
        25,
        "final_outline_layer",
        "final-outline-layer",
        "最终轮廓层",
        ("logo_candidate_mask", "signature_candidate_mask", "residual_mask"),
    ),
    StageSpec(
        26,
        "actual_dxf_render",
        "actual-dxf-render",
        "实际 DXF 渲染结果",
        ("final_structural_layer", "final_text_layer", "final_outline_layer"),
    ),
)
STAGE_BY_KEY = {stage.key: stage for stage in STAGE_SPECS}


class ObservationSink(Protocol):
    def record(
        self,
        stage_key: str,
        *,
        image: np.ndarray | None = None,
        payload: Mapping[str, Any] | None = None,
        status: str = "captured",
    ) -> None: ...


def observe(
    sink: ObservationSink | None,
    stage_key: str,
    *,
    image: np.ndarray | None = None,
    payload: Mapping[str, Any] | None = None,
    status: str = "captured",
) -> None:
    if sink is None:
        return
    if stage_key not in STAGE_BY_KEY:
        raise KeyError(f"Unknown observability stage: {stage_key}")
    sink.record(
        stage_key,
        image=image,
        payload=payload,
        status=status,
    )


def line_payload(line: Any) -> dict[str, Any]:
    return {
        "start": [float(line.x1), float(line.y1)],
        "end": [float(line.x2), float(line.y2)],
        "width": float(line.width),
        "confidence": float(line.confidence),
        "layer": str(line.layer),
        "source_ids": [str(value) for value in line.source_ids],
        "history": [str(value) for value in line.history],
    }


def lines_payload(lines: Sequence[Any]) -> list[dict[str, Any]]:
    return [line_payload(line) for line in lines]


def text_payload(text: Any) -> dict[str, Any]:
    return {
        "text": str(text.text),
        "bbox": [int(value) for value in text.bbox],
        "confidence": float(text.confidence),
        "kind": str(text.kind),
        "rotation_deg": float(text.rotation_deg),
        "source": str(text.source),
        "approved": bool(text.approved),
        "reviewed": bool(text.reviewed),
        "replacement_safe": bool(text.replacement_safe),
    }


def texts_payload(texts: Sequence[Any]) -> list[dict[str, Any]]:
    return [text_payload(text) for text in texts]


def roi_payload(roi: Any) -> dict[str, Any]:
    return {
        "roi_id": str(roi.roi_id),
        "purpose": str(roi.purpose),
        "bbox": [int(value) for value in roi.bbox],
        "line_indices": [int(value) for value in roi.line_indices],
        "evidence_intersections": [
            [float(point[0]), float(point[1])]
            for point in roi.evidence_intersections
        ],
        "confidence": float(roi.confidence),
    }


def rois_payload(rois: Sequence[Any]) -> list[dict[str, Any]]:
    return [roi_payload(roi) for roi in rois]


def rasterize_lines(
    lines: Sequence[Any],
    image_shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(image_shape, dtype=np.uint8)
    for line in lines:
        cv2.line(
            mask,
            (int(round(float(line.x1))), int(round(float(line.y1)))),
            (int(round(float(line.x2))), int(round(float(line.y2)))),
            255,
            max(1, int(round(float(line.width)))),
            cv2.LINE_8,
        )
    return mask


def rasterize_endpoints(
    lines: Sequence[Any],
    image_shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(image_shape, dtype=np.uint8)
    for line in lines:
        for x, y in ((line.x1, line.y1), (line.x2, line.y2)):
            cv2.circle(
                mask,
                (int(round(float(x))), int(round(float(y)))),
                3,
                255,
                -1,
                cv2.LINE_8,
            )
    return mask


def rasterize_rois(
    rois: Sequence[Any],
    image_shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(image_shape, dtype=np.uint8)
    for roi in rois:
        x, y, width, height = (int(value) for value in roi.bbox)
        mask[y : y + height, x : x + width] = 255
    return mask


def rasterize_connections(
    connections: Sequence[Mapping[str, Any]],
    image_shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(image_shape, dtype=np.uint8)
    for connection in connections:
        start = connection.get("start")
        end = connection.get("end")
        if not (
            isinstance(start, Sequence)
            and len(start) >= 2
            and isinstance(end, Sequence)
            and len(end) >= 2
        ):
            continue
        cv2.line(
            mask,
            (int(round(float(start[0]))), int(round(float(start[1])))),
            (int(round(float(end[0]))), int(round(float(end[1])))),
            255,
            1,
            cv2.LINE_8,
        )
    return mask


def rasterize_text_boxes(
    texts: Sequence[Any],
    image_shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(image_shape, dtype=np.uint8)
    height, width = image_shape
    for text in texts:
        x, y, box_width, box_height = (int(value) for value in text.bbox)
        left = max(0, min(width - 1, x))
        top = max(0, min(height - 1, y))
        right = max(left, min(width - 1, x + box_width - 1))
        bottom = max(top, min(height - 1, y + box_height - 1))
        cv2.rectangle(mask, (left, top), (right, bottom), 255, 1, cv2.LINE_8)
    return mask
