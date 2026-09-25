from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np


SCHEMA_VERSION = "input-fidelity-d1-v1"
_PANEL_COLUMNS = 6
_PANEL_WIDTH = 350
_PANEL_HEIGHT = 270
_PANEL_HEADER_HEIGHT = 52
_TRACE_HEADER_HEIGHT = 72
_TRACE_ROW_HEIGHT = _PANEL_HEADER_HEIGHT + _PANEL_HEIGHT
_TRACE_FOOTER_HEIGHT = 122


class FidelityCase:
    def __init__(
        self,
        case_id: str,
        source_group_id: str,
        kind: str,
        bundle_directory: Path,
        vqa_run_directory: Path,
        roi: tuple[int, int, int, int],
        target: tuple[int, int, int, int] | None,
        source_description: str,
        first_divergence_stage: str,
        failure_class: str,
        plain_conclusion: str,
    ) -> None:
        self.case_id = case_id
        self.source_group_id = source_group_id
        self.kind = kind
        self.bundle_directory = bundle_directory
        self.vqa_run_directory = vqa_run_directory
        self.roi = roi
        self.target = target
        self.source_description = source_description
        self.first_divergence_stage = first_divergence_stage
        self.failure_class = failure_class
        self.plain_conclusion = plain_conclusion


class _PanelSource:
    def __init__(
        self,
        label: str,
        stage_key: str | None = None,
        role: str | None = None,
        vqa_filename: str | None = None,
        display: str = "image",
    ) -> None:
        self.label = label
        self.stage_key = stage_key
        self.role = role
        self.vqa_filename = vqa_filename
        self.display = display


_LINE_PANELS = (
    _PanelSource("SOURCE", "original_page"),
    _PanelSource("PROCESSING INPUT", "original_gray"),
    _PanelSource("NORMALIZED", "normalized_background"),
    _PanelSource("BINARY", "binary_foreground"),
    _PanelSource(
        "EDGE PROPOSALS",
        "raw_line_candidates",
        "edge-proposals-before-recenter",
        display="mask-cyan",
    ),
    _PanelSource("RAW DETECTION", "raw_line_candidates", display="mask-cyan"),
    _PanelSource(
        "ELIGIBLE CANDIDATES",
        "line_candidates_text_filtered",
        "before-text-filter",
        display="mask-orange",
    ),
    _PanelSource(
        "TEXT FILTER MASK",
        "text_candidate_mask",
        "line-filter-protection",
        display="mask-red",
    ),
    _PanelSource(
        "FILTERED",
        "line_candidates_text_filtered",
        "after-text-filter",
        display="mask-orange",
    ),
    _PanelSource(
        "GEOMETRY",
        "structural_line_candidate_mask",
        "post-filter-candidates",
        display="mask-blue",
    ),
    _PanelSource("FINALSTRUCTURE", vqa_filename="reconstructed.png"),
    _PanelSource("VQA FINAL", vqa_filename="overlay.png"),
)

_TEXT_PANELS = (
    _PanelSource("SOURCE", "original_page"),
    _PanelSource("PROCESSING INPUT", "original_gray"),
    _PanelSource("OCR RAW INPUT", "ocr_raw_tiles"),
    _PanelSource("OCR CLEAN INPUT", "ocr_rule_removed_tiles"),
    _PanelSource(
        "OCR RAW RESULT",
        "ocr_text_boxes",
        "raw-recognition",
        display="mask-cyan",
    ),
    _PanelSource("TEXT CANDIDATE", "ocr_text_boxes", "", display="mask-orange"),
    _PanelSource(
        "OWNERSHIP MASK",
        "text_candidate_mask",
        "final-owned",
        display="mask-red",
    ),
    _PanelSource("FINAL TEXT", "final_text_layer", "", display="mask-blue"),
    _PanelSource("FINALSTRUCTURE", vqa_filename="reconstructed.png"),
    _PanelSource("VQA FINAL", vqa_filename="overlay.png"),
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_fidelity_manifest(path: Path) -> tuple[FidelityCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported input-fidelity manifest")
    cases = tuple(
        FidelityCase(
            str(item["case_id"]),
            str(item["source_group_id"]),
            str(item["kind"]),
            Path(str(item["bundle_directory"])).resolve(),
            Path(str(item["vqa_run_directory"])).resolve(),
            tuple(int(value) for value in item["roi"]),  # type: ignore[arg-type]
            (
                None
                if item.get("target") is None
                else tuple(int(value) for value in item["target"])  # type: ignore[arg-type]
            ),
            str(item["source_description"]),
            str(item["first_divergence_stage"]),
            str(item["failure_class"]),
            str(item["plain_conclusion"]),
        )
        for item in payload["cases"]
    )
    if not 3 <= len(cases) <= 5:
        raise ValueError("INPUT-FIDELITY-D1 requires three to five cases")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Input-fidelity case IDs must be unique")
    if any(case.kind not in {"line", "text"} for case in cases):
        raise ValueError("Input-fidelity case kind must be line or text")
    return cases


def _load_bundle(case: FidelityCase) -> Mapping[str, Any]:
    manifest_path = case.bundle_directory / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    normalized = str(payload["input"]["path"]).replace("\\", "/").lower()
    if "/corpus-v1/dev/" not in normalized:
        raise ValueError(f"{case.case_id}: diagnostic input is not DEV")
    if "locked_blind" in normalized or "/validation/" in normalized:
        raise ValueError(f"{case.case_id}: protected split is forbidden")
    return payload


def _stage(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    for item in payload["stages"]:
        if item["stage_key"] == key:
            return item
    raise KeyError(f"Bundle stage not found: {key}")


def _artifact(
    case: FidelityCase,
    payload: Mapping[str, Any],
    panel: _PanelSource,
) -> tuple[Path, Mapping[str, Any]]:
    if panel.vqa_filename is not None:
        path = case.vqa_run_directory / panel.vqa_filename
        return path, {}
    if panel.stage_key is None:
        raise ValueError("Panel has no artifact source")
    artifacts = _stage(payload, panel.stage_key)["artifacts"]
    candidates = [
        item
        for item in artifacts
        if panel.role is None or str(item.get("role", "")) == panel.role
    ]
    if not candidates:
        raise KeyError(
            f"{case.case_id}: {panel.stage_key} role={panel.role!r} not captured"
        )
    x, y, width, height = case.roi
    for item in candidates:
        metadata_path = case.bundle_directory / str(item["metadata_path"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        region = metadata.get("observation", {}).get("region")
        if region is None:
            return case.bundle_directory / str(item["path"]), metadata
        left, top, right, bottom = (int(value) for value in region)
        if left <= x and top <= y and x + width <= right and y + height <= bottom:
            return case.bundle_directory / str(item["path"]), metadata
    raise ValueError(f"{case.case_id}: ROI is not contained by a captured tile")


def _crop(
    image: np.ndarray,
    roi: tuple[int, int, int, int],
    metadata: Mapping[str, Any],
) -> np.ndarray:
    x, y, width, height = roi
    region = metadata.get("observation", {}).get("region")
    if region is not None:
        left, top, _right, _bottom = (int(value) for value in region)
        x -= left
        y -= top
    if x < 0 or y < 0 or x + width > image.shape[1] or y + height > image.shape[0]:
        raise ValueError("ROI lies outside captured stage coordinates")
    return np.ascontiguousarray(image[y : y + height, x : x + width])


def _source_crop(
    case: FidelityCase,
    payload: Mapping[str, Any],
) -> np.ndarray:
    panel = _LINE_PANELS[0]
    path, metadata = _artifact(case, payload, panel)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise OSError(path)
    return _crop(image, case.roi, metadata)


def _overlay_mask(
    source: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
) -> np.ndarray:
    if mask.ndim == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    active = mask > 127
    canvas = cv2.addWeighted(source, 0.38, np.full_like(source, 255), 0.62, 0.0)
    if np.any(active):
        paint = np.empty_like(canvas)
        paint[:] = color
        canvas[active] = cv2.addWeighted(canvas[active], 0.18, paint[active], 0.82, 0.0)
    return canvas


def _panel_image(
    case: FidelityCase,
    payload: Mapping[str, Any],
    panel: _PanelSource,
    source: np.ndarray,
) -> tuple[np.ndarray, Path, Mapping[str, Any]]:
    path, metadata = _artifact(case, payload, panel)
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise OSError(path)
    cropped = _crop(image, case.roi, metadata)
    if cropped.ndim == 2:
        cropped_bgr = cv2.cvtColor(cropped, cv2.COLOR_GRAY2BGR)
    else:
        cropped_bgr = cropped[:, :, :3].copy()
    colors = {
        "mask-red": (40, 40, 235),
        "mask-cyan": (230, 170, 20),
        "mask-orange": (20, 150, 245),
        "mask-blue": (230, 85, 40),
    }
    if panel.display in colors:
        cropped_bgr = _overlay_mask(source, cropped, colors[panel.display])
    return cropped_bgr, path, metadata


def _visible_text_summary(
    metadata: Mapping[str, Any],
    roi: tuple[int, int, int, int],
) -> str:
    observation = metadata.get("observation", {})
    texts = observation.get("texts", [])
    if not isinstance(texts, list):
        return ""
    roi_left, roi_top, roi_width, roi_height = roi
    roi_right = roi_left + roi_width
    roi_bottom = roi_top + roi_height
    values: list[str] = []
    for item in texts:
        if not isinstance(item, Mapping):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        left, top, width, height = (int(value) for value in bbox)
        if left + width < roi_left or left > roi_right:
            continue
        if top + height < roi_top or top > roi_bottom:
            continue
        value = str(item.get("text", ""))
        escaped = json.dumps(value, ensure_ascii=True)[1:-1]
        if escaped and escaped not in values:
            values.append(escaped)
    if not values:
        return ""
    return "text=" + " | ".join(values)[:72]


def _fit(
    image: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, float, int, int]:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (
            max(1, int(round(image.shape[1] * scale))),
            max(1, int(round(image.shape[0] * scale))),
        ),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_NEAREST,
    )
    canvas = np.full((height, width, 3), 248, dtype=np.uint8)
    left = (width - resized.shape[1]) // 2
    top = (height - resized.shape[0]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    return canvas, scale, left, top


def _draw_target(
    image: np.ndarray,
    case: FidelityCase,
    scale: float,
    left: int,
    top: int,
) -> None:
    if case.target is None:
        return
    x, y, _width, _height = case.roi
    x1, y1, x2, y2 = case.target
    for px, py in ((x1, y1), (x2, y2)):
        point = (
            left + int(round((px - x) * scale)),
            top + int(round((py - y) * scale)),
        )
        cv2.circle(image, point, 8, (0, 0, 255), 2, cv2.LINE_AA)


def build_case_trace(case: FidelityCase, output_path: Path) -> dict[str, object]:
    payload = _load_bundle(case)
    source_size = tuple(int(value) for value in payload["input"]["source_size_px"])
    x, y, width, height = case.roi
    if len(case.roi) != 4 or width <= 0 or height <= 0:
        raise ValueError(f"{case.case_id}: invalid ROI")
    if x < 0 or y < 0 or x + width > source_size[0] or y + height > source_size[1]:
        raise ValueError(f"{case.case_id}: ROI outside source coordinates")
    source = _source_crop(case, payload)
    panels = _TEXT_PANELS if case.kind == "text" else _LINE_PANELS
    sheet = np.full(
        (
            _TRACE_HEADER_HEIGHT + _TRACE_ROW_HEIGHT * 2 + _TRACE_FOOTER_HEIGHT,
            _PANEL_WIDTH * _PANEL_COLUMNS,
            3,
        ),
        255,
        dtype=np.uint8,
    )
    cv2.putText(
        sheet,
        f"{case.case_id}  {case.source_group_id}  {case.source_description}",
        (20, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.76,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    artifact_records: list[dict[str, str]] = []
    for index, panel in enumerate(panels):
        row, column = divmod(index, _PANEL_COLUMNS)
        origin_x = column * _PANEL_WIDTH
        origin_y = _TRACE_HEADER_HEIGHT + row * _TRACE_ROW_HEIGHT
        rendered, artifact_path, metadata = _panel_image(case, payload, panel, source)
        fitted, scale, left, top = _fit(rendered, _PANEL_WIDTH, _PANEL_HEIGHT)
        _draw_target(fitted, case, scale, left, top)
        sheet[
            origin_y + _PANEL_HEADER_HEIGHT : origin_y + _TRACE_ROW_HEIGHT,
            origin_x : origin_x + _PANEL_WIDTH,
        ] = fitted
        text_summary = _visible_text_summary(metadata, case.roi)
        cv2.putText(
            sheet,
            panel.label,
            (origin_x + 12, origin_y + (22 if text_summary else 34)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (30, 30, 30),
            1,
            cv2.LINE_AA,
        )
        if text_summary:
            cv2.putText(
                sheet,
                text_summary,
                (origin_x + 12, origin_y + 45),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.36,
                (55, 55, 55),
                1,
                cv2.LINE_AA,
            )
        artifact_records.append(
            {
                "panel": panel.label,
                "path": str(artifact_path),
                "sha256": _sha256(artifact_path),
            }
        )
    footer_y = _TRACE_HEADER_HEIGHT + _TRACE_ROW_HEIGHT * 2
    lines = (
        f"FIRST DIVERGENCE: {case.first_divergence_stage}    CLASS: {case.failure_class}",
        f"PLAIN CONCLUSION: {case.plain_conclusion}",
        f"ROI: x={x}, y={y}, width={width}, height={height}    red circles = same target endpoints",
    )
    for index, value in enumerate(lines):
        cv2.putText(
            sheet,
            value[:220],
            (20, footer_y + 34 + index * 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise OSError(output_path)
    return {
        "case_id": case.case_id,
        "source_group_id": case.source_group_id,
        "kind": case.kind,
        "roi": list(case.roi),
        "target": None if case.target is None else list(case.target),
        "source_sha256": str(payload["input"]["sha256"]),
        "structure_id": str(payload["structure_id"]),
        "first_divergence_stage": case.first_divergence_stage,
        "failure_class": case.failure_class,
        "artifact_sources": artifact_records,
        "output": str(output_path),
        "output_sha256": _sha256(output_path),
    }


def build_overview(
    case_outputs: Sequence[tuple[FidelityCase, Path]],
    output_path: Path,
) -> Path:
    if not 3 <= len(case_outputs) <= 5:
        raise ValueError("Overview requires three to five cases")
    width = _PANEL_WIDTH * _PANEL_COLUMNS
    summary_height = 72
    row_height = _TRACE_ROW_HEIGHT + summary_height
    sheet = np.full((74 + row_height * len(case_outputs), width, 3), 255, np.uint8)
    cv2.putText(
        sheet,
        "INPUT-FIDELITY-D1  SAME-ROI PRODUCTION PIPELINE TRACES",
        (22, 46),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    for index, (case, path) in enumerate(case_outputs):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise OSError(path)
        top = 74 + index * row_height
        if case.kind == "text":
            panel_indexes = (0, 2, 3, 4, 7, 9)
        else:
            panel_indexes = (0, 3, 5, 6, 8, 11)
        for output_column, panel_index in enumerate(panel_indexes):
            input_row, input_column = divmod(panel_index, _PANEL_COLUMNS)
            source_left = input_column * _PANEL_WIDTH
            source_top = _TRACE_HEADER_HEIGHT + input_row * _TRACE_ROW_HEIGHT
            cell = image[
                source_top : source_top + _TRACE_ROW_HEIGHT,
                source_left : source_left + _PANEL_WIDTH,
            ]
            target_left = output_column * _PANEL_WIDTH
            sheet[
                top : top + _TRACE_ROW_HEIGHT,
                target_left : target_left + _PANEL_WIDTH,
            ] = cell
        cv2.putText(
            sheet,
            f"{case.case_id}: {case.first_divergence_stage} / {case.failure_class}",
            (22, top + _TRACE_ROW_HEIGHT + 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            sheet,
            case.plain_conclusion[:210],
            (22, top + _TRACE_ROW_HEIGHT + 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (45, 45, 45),
            1,
            cv2.LINE_AA,
        )
        cv2.line(
            sheet,
            (0, top + row_height - 1),
            (width - 1, top + row_height - 1),
            (190, 190, 190),
            1,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise OSError(output_path)
    return output_path


def build_fidelity_artifacts(manifest_path: Path, output_directory: Path) -> Path:
    cases = load_fidelity_manifest(manifest_path)
    reports: list[dict[str, object]] = []
    outputs: list[tuple[FidelityCase, Path]] = []
    for case in cases:
        path = output_directory / f"pipeline_trace_{case.case_id.lower()}.png"
        reports.append(build_case_trace(case, path))
        outputs.append((case, path))
    overview = build_overview(
        outputs, output_directory / "input_fidelity_d1_overview.png"
    )
    report_path = output_directory / "input_fidelity_d1_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "cases": reports,
                "overview": str(overview),
                "overview_sha256": _sha256(overview),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report_path
