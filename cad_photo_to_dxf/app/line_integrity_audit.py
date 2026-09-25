from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

import cv2
import numpy as np

from app.input_fidelity_diagnostic import (
    FidelityCase,
    _PanelSource,
    _load_bundle,
    _panel_image,
    _source_crop,
)


SCHEMA_VERSION = "line-integrity-audit-d2-v1"
ROOT_CAUSES = (
    "SOURCE_DEFECT",
    "INPUT_RENDER_DEFECT",
    "PREPROCESSING_DESTRUCTION",
    "DETECTION_LOSS",
    "DETECTION_FRAGMENTATION",
    "FILTERING_LOSS",
    "OWNERSHIP_MASK_DAMAGE",
    "GEOMETRY_PROCESSING_DAMAGE",
    "TOPOLOGY_DAMAGE",
    "PROMOTION_LOSS",
    "FINAL_ASSEMBLY_LOSS",
    "RENDER_ONLY_DEFECT",
    "NO_END_TO_END_DEFECT",
    "DIAGNOSTIC_TARGET_INVALID",
    "UNKNOWN",
)
_STATUSES = {"QUALIFIED", "REJECTED", "UNCERTAIN"}
_CONFIDENCES = {"HIGH", "MEDIUM", "LOW"}
_PANEL_WIDTH = 360
_PANEL_HEIGHT = 260
_PANEL_HEADER = 44
_COLUMNS = 4
_HEADER = 70
_FOOTER = 138

_PANELS = (
    _PanelSource("SOURCE", "original_page"),
    _PanelSource("PROCESSING INPUT", "original_gray"),
    _PanelSource("BINARY", "binary_foreground"),
    _PanelSource("RAW", "raw_line_candidates", display="mask-cyan"),
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


@dataclass(frozen=True)
class AuditCase:
    case_id: str
    source_group_id: str
    page: int
    bundle_directory: Path
    vqa_run_directory: Path
    roi: tuple[int, int, int, int]
    target: tuple[int, int, int, int]
    orientation: str
    approximate_width_px: float
    approximate_length_px: float
    target_type: str
    source_description: str
    status: str
    confidence: str
    qualification: Mapping[str, object]
    result_type: str
    root_cause: str
    first_true_divergence_stage: str
    first_divergence_event: str
    branch: str
    plain_conclusion: str
    success_control: bool
    paired_case_id: str | None
    rejection_reason: str | None
    source_support_dropped: bool
    fragment_first_risk: bool
    evidence: Mapping[str, object]

    def fidelity_case(self) -> FidelityCase:
        return FidelityCase(
            self.case_id,
            self.source_group_id,
            "line",
            self.bundle_directory,
            self.vqa_run_directory,
            self.roi,
            self.target,
            self.source_description,
            self.first_true_divergence_stage,
            self.root_cause,
            self.plain_conclusion,
        )


@dataclass(frozen=True)
class AuditRegistry:
    cases: tuple[AuditCase, ...]
    comparison_pairs: tuple[tuple[str, str, str], ...]
    architecture_risk: Mapping[str, str]
    full_page_sanity: tuple[tuple[str, Path], ...]


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_audit_registry(path: Path, repository_root: Path) -> AuditRegistry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported line-integrity audit registry")
    cases: list[AuditCase] = []
    for item in payload["cases"]:
        qualification = item["qualification"]
        case = AuditCase(
            case_id=str(item["case_id"]),
            source_group_id=str(item["source_group_id"]),
            page=int(item["page"]),
            bundle_directory=_resolve(repository_root, item["bundle_directory"]),
            vqa_run_directory=_resolve(repository_root, item["vqa_run_directory"]),
            roi=tuple(int(value) for value in item["roi"]),  # type: ignore[arg-type]
            target=tuple(int(value) for value in item["target"]),  # type: ignore[arg-type]
            orientation=str(item["orientation"]),
            approximate_width_px=float(item["approximate_width_px"]),
            approximate_length_px=float(item["approximate_length_px"]),
            target_type=str(item["target_type"]),
            source_description=str(item["source_description"]),
            status=str(item["status"]),
            confidence=str(item["confidence"]),
            qualification=dict(qualification),
            result_type=str(item.get("result_type", "NOT_COUNTED")),
            root_cause=str(item.get("root_cause", "DIAGNOSTIC_TARGET_INVALID")),
            first_true_divergence_stage=str(
                item.get("first_true_divergence_stage", "CASE_QUALIFICATION")
            ),
            first_divergence_event=str(
                item.get("first_divergence_event", "TARGET_MISMATCH")
            ),
            branch=str(item.get("branch", "not applicable")),
            plain_conclusion=str(item["plain_conclusion"]),
            success_control=bool(item.get("success_control", False)),
            paired_case_id=(
                None
                if item.get("paired_case_id") is None
                else str(item["paired_case_id"])
            ),
            rejection_reason=(
                None
                if item.get("rejection_reason") is None
                else str(item["rejection_reason"])
            ),
            source_support_dropped=bool(item.get("source_support_dropped", False)),
            fragment_first_risk=bool(item.get("fragment_first_risk", False)),
            evidence=dict(item.get("evidence", {})),
        )
        _validate_case(case)
        cases.append(case)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Audit case IDs must be unique")
    qualified = [case for case in cases if case.status == "QUALIFIED"]
    if not 8 <= len(qualified) <= 12:
        raise ValueError("D2 requires 8 to 12 qualified cases")
    by_id = {case.case_id: case for case in cases}
    pairs: list[tuple[str, str, str]] = []
    for pair in payload["comparison_pairs"]:
        success_id, failure_id = str(pair["success"]), str(pair["failure"])
        if success_id not in by_id or failure_id not in by_id:
            raise ValueError("Comparison pair refers to an unknown case")
        if not by_id[success_id].success_control:
            raise ValueError("Comparison pair success must be a success control")
        pairs.append((str(pair["label"]), success_id, failure_id))
    sanity = tuple(
        (
            str(item["source_group_id"]),
            _resolve(repository_root, item["vqa_run_directory"]),
        )
        for item in payload["full_page_sanity"]
    )
    return AuditRegistry(
        tuple(cases),
        tuple(pairs),
        dict(payload["architecture_risk"]),
        sanity,
    )


def _validate_case(case: AuditCase) -> None:
    if case.status not in _STATUSES or case.confidence not in _CONFIDENCES:
        raise ValueError(f"{case.case_id}: invalid status or confidence")
    if case.root_cause not in ROOT_CAUSES:
        raise ValueError(f"{case.case_id}: invalid root cause")
    if len(case.roi) != 4 or len(case.target) != 4:
        raise ValueError(f"{case.case_id}: invalid ROI or target")
    x, y, width, height = case.roi
    x1, y1, x2, y2 = case.target
    if width <= 0 or height <= 0 or not (
        x <= x1 < x + width
        and x <= x2 < x + width
        and y <= y1 < y + height
        and y <= y2 < y + height
    ):
        raise ValueError(f"{case.case_id}: target must stay inside ROI")
    allowed = str(case.qualification.get("allowed_as_false_break_case", ""))
    if allowed != case.status:
        raise ValueError(f"{case.case_id}: qualification status mismatch")
    if case.status == "QUALIFIED":
        required = (
            case.qualification.get("source_continuous") == "YES",
            case.qualification.get("processing_input_continuous") == "YES",
            case.qualification.get("coordinate_mapping_verified") is True,
            case.qualification.get("same_source_structure_endpoints") == "YES",
        )
        if not all(required):
            raise ValueError(f"{case.case_id}: qualified case lacks required evidence")
        if case.confidence == "LOW":
            raise ValueError(f"{case.case_id}: LOW confidence cannot enter census")
    elif case.rejection_reason is None:
        raise ValueError(f"{case.case_id}: rejected/uncertain case needs a reason")


def _fit(image: np.ndarray, width: int, height: int) -> tuple[np.ndarray, float, int, int]:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (
            max(1, int(round(image.shape[1] * scale))),
            max(1, int(round(image.shape[0] * scale))),
        ),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_NEAREST,
    )
    canvas: np.ndarray = np.full((height, width, 3), 248, np.uint8)
    left = (width - resized.shape[1]) // 2
    top = (height - resized.shape[0]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    return canvas, scale, left, top


def _draw_target(
    image: np.ndarray,
    case: AuditCase,
    scale: float,
    left: int,
    top: int,
) -> None:
    roi_x, roi_y, _width, _height = case.roi
    x1, y1, x2, y2 = case.target
    start = (
        left + int(round((x1 - roi_x) * scale)),
        top + int(round((y1 - roi_y) * scale)),
    )
    end = (
        left + int(round((x2 - roi_x) * scale)),
        top + int(round((y2 - roi_y) * scale)),
    )
    delta_x, delta_y = end[0] - start[0], end[1] - start[1]
    length = max(1.0, float(np.hypot(delta_x, delta_y)))
    offset = (
        int(round(-delta_y / length * 6.0)),
        int(round(delta_x / length * 6.0)),
    )
    guide_start = (start[0] + offset[0], start[1] + offset[1])
    guide_end = (end[0] + offset[0], end[1] + offset[1])
    guide_delta = (guide_end[0] - guide_start[0], guide_end[1] - guide_start[1])
    for distance in range(0, int(length) + 1, 12):
        ratio = distance / length
        point = (
            int(round(guide_start[0] + guide_delta[0] * ratio)),
            int(round(guide_start[1] + guide_delta[1] * ratio)),
        )
        cv2.circle(image, point, 1, (0, 0, 220), -1, cv2.LINE_AA)
    for point in (start, end):
        cv2.circle(image, point, 7, (0, 0, 255), 2, cv2.LINE_AA)


def _case_panels(case: AuditCase) -> list[tuple[str, np.ndarray]]:
    fidelity = case.fidelity_case()
    payload = _load_bundle(fidelity)
    normalized = str(payload["input"]["path"]).replace("\\", "/").lower()
    if "/corpus-v1/dev/" not in normalized:
        raise ValueError(f"{case.case_id}: only DEV input is permitted")
    if "locked_blind" in normalized or "/validation/" in normalized:
        raise ValueError(f"{case.case_id}: protected split is forbidden")
    source = _source_crop(fidelity, payload)
    output: list[tuple[str, np.ndarray]] = []
    for panel in _PANELS:
        rendered, _path, _metadata = _panel_image(fidelity, payload, panel, source)
        output.append((panel.label, rendered))
    return output


def build_case_artifact(case: AuditCase, output_path: Path) -> Path:
    panels = _case_panels(case)
    row_height = _PANEL_HEADER + _PANEL_HEIGHT
    canvas: np.ndarray = np.full(
        (_HEADER + row_height * 2 + _FOOTER, _PANEL_WIDTH * _COLUMNS, 3),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        f"{case.case_id}  {case.source_group_id}  {case.result_type}",
        (18, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    for index, (label, rendered) in enumerate(panels):
        row, column = divmod(index, _COLUMNS)
        x = column * _PANEL_WIDTH
        y = _HEADER + row * row_height
        cv2.putText(
            canvas,
            label,
            (x + 12, y + 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (30, 30, 30),
            1,
            cv2.LINE_AA,
        )
        fitted, scale, left, top = _fit(rendered, _PANEL_WIDTH, _PANEL_HEIGHT)
        _draw_target(fitted, case, scale, left, top)
        canvas[
            y + _PANEL_HEADER : y + row_height,
            x : x + _PANEL_WIDTH,
        ] = fitted
    footer = _HEADER + row_height * 2
    lines = (
        f"FIRST TRUE DIVERGENCE: {case.first_true_divergence_stage}  EVENT: {case.first_divergence_event}",
        f"ROOT CAUSE: {case.root_cause}  CONFIDENCE: {case.confidence}  BRANCH: {case.branch}",
        f"ROI: {case.roi}  TARGET: {case.target}  width~{case.approximate_width_px:g}px length~{case.approximate_length_px:g}px",
        f"CONCLUSION: {case.plain_conclusion}",
        "MARKER: red dotted guide is offset 6 px; endpoint circles remain on target",
    )
    for index, line in enumerate(lines):
        cv2.putText(
            canvas,
            line[:195],
            (18, footer + 23 + index * 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (30, 30, 30),
            1,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path


def _thumbnail(image: np.ndarray, width: int, height: int) -> np.ndarray:
    fitted, _scale, _left, _top = _fit(image, width, height)
    return fitted


def _target_thumbnail(
    image: np.ndarray, case: AuditCase, width: int, height: int
) -> np.ndarray:
    fitted, scale, left, top = _fit(image, width, height)
    _draw_target(fitted, case, scale, left, top)
    return fitted


def build_overview(cases: Sequence[AuditCase], output_path: Path) -> Path:
    qualified = [case for case in cases if case.status == "QUALIFIED"]
    panel_width, panel_height = 300, 180
    title_height, label_height = 66, 54
    canvas: np.ndarray = np.full(
        (title_height + len(qualified) * (label_height + panel_height), panel_width * 5, 3),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        "LINE-INTEGRITY-AUDIT-D2  SOURCE | BINARY | RAW | FILTERED | FINALSTRUCTURE",
        (18, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    indexes = (0, 2, 3, 4, 6)
    for row, case in enumerate(qualified):
        top = title_height + row * (label_height + panel_height)
        cv2.putText(
            canvas,
            f"{case.case_id} {case.source_group_id}  {case.result_type}  {case.root_cause}  first={case.first_true_divergence_stage}",
            (14, top + 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
        panels = _case_panels(case)
        for column, panel_index in enumerate(indexes):
            image = _target_thumbnail(
                panels[panel_index][1], case, panel_width, panel_height
            )
            canvas[
                top + label_height : top + label_height + panel_height,
                column * panel_width : (column + 1) * panel_width,
            ] = image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path


def build_matrix(cases: Sequence[AuditCase], output_path: Path) -> Path:
    row_height = 54
    canvas: np.ndarray = np.full(
        (92 + row_height * len(cases), 1900, 3),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        "LINE INTEGRITY ROOT CAUSE MATRIX",
        (20, 38),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "CASE / SOURCE / STATUS / RESULT / FIRST TRUE DIVERGENCE / ROOT CAUSE / CONFIDENCE",
        (20, 74),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.49,
        (45, 45, 45),
        1,
        cv2.LINE_AA,
    )
    for index, case in enumerate(cases):
        y = 92 + index * row_height
        if index % 2:
            canvas[y : y + row_height] = (246, 246, 246)
        line = (
            f"{case.case_id} | {case.source_group_id} | {case.status} | {case.result_type} | "
            f"{case.first_true_divergence_stage} | {case.root_cause} | {case.confidence}"
        )
        cv2.putText(
            canvas,
            line[:245],
            (20, y + 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path


def build_success_vs_failure(
    registry: AuditRegistry,
    output_path: Path,
) -> Path:
    by_id = {case.case_id: case for case in registry.cases}
    panel_width, panel_height = 250, 170
    header, pair_header = 70, 66
    canvas: np.ndarray = np.full(
        (
            header + len(registry.comparison_pairs) * (pair_header + panel_height * 2),
            panel_width * 5,
            3,
        ),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        "LINE INTEGRITY: SUCCESS CONTROL VS FAILURE  SOURCE | BINARY | RAW | FILTERED | FINAL",
        (18, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    indexes = (0, 2, 3, 4, 6)
    for pair_index, (label, success_id, failure_id) in enumerate(
        registry.comparison_pairs
    ):
        top = header + pair_index * (pair_header + panel_height * 2)
        cv2.putText(
            canvas,
            f"{label}: SUCCESS {success_id} (top) vs FAILURE {failure_id} (bottom)",
            (14, top + 37),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
        for row, case_id in enumerate((success_id, failure_id)):
            panels = _case_panels(by_id[case_id])
            for column, panel_index in enumerate(indexes):
                image = _target_thumbnail(
                    panels[panel_index][1], by_id[case_id], panel_width, panel_height
                )
                y = top + pair_header + row * panel_height
                canvas[
                    y : y + panel_height,
                    column * panel_width : (column + 1) * panel_width,
                ] = image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path


def build_full_page_sanity(
    entries: Sequence[tuple[str, Path]], output_path: Path
) -> Path:
    panel_width, panel_height = 520, 360
    header, row_header = 66, 48
    canvas: np.ndarray = np.full(
        (header + len(entries) * (row_header + panel_height), panel_width * 3, 3),
        255,
        np.uint8,
    )
    cv2.putText(
        canvas,
        "D2 FULL-PAGE SANITY  ORIGINAL | FINALSTRUCTURE | OVERLAY",
        (18, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    for row, (source_group_id, directory) in enumerate(entries):
        top = header + row * (row_header + panel_height)
        cv2.putText(
            canvas,
            f"{source_group_id}  instrumentation-only audit; production structure unchanged",
            (14, top + 31),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (30, 30, 30),
            1,
            cv2.LINE_AA,
        )
        for column, filename in enumerate(
            ("original.png", "reconstructed.png", "overlay.png")
        ):
            image = cv2.imread(str(directory / filename), cv2.IMREAD_COLOR)
            if image is None:
                raise OSError(directory / filename)
            canvas[
                top + row_header : top + row_header + panel_height,
                column * panel_width : (column + 1) * panel_width,
            ] = _thumbnail(image, panel_width, panel_height)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError(output_path)
    return output_path


def build_audit_artifacts(
    registry_path: Path,
    repository_root: Path,
    output_directory: Path,
) -> Path:
    registry = load_audit_registry(registry_path, repository_root)
    output_directory.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for case in registry.cases:
        if case.status != "QUALIFIED":
            continue
        output = output_directory / f"line_integrity_case_{case.case_id}.png"
        outputs.append(build_case_artifact(case, output))
    outputs.append(
        build_overview(
            registry.cases,
            output_directory / "line_integrity_d2_overview.png",
        )
    )
    outputs.append(
        build_matrix(
            registry.cases,
            output_directory / "line_integrity_root_cause_matrix.png",
        )
    )
    outputs.append(
        build_success_vs_failure(
            registry,
            output_directory / "line_integrity_success_vs_failure.png",
        )
    )
    outputs.append(
        build_full_page_sanity(
            registry.full_page_sanity,
            output_directory / "line_integrity_d2_full_page_sanity.png",
        )
    )
    qualified = [case for case in registry.cases if case.status == "QUALIFIED"]
    rejected = [case for case in registry.cases if case.status == "REJECTED"]
    counted = [case for case in qualified if case.confidence in {"HIGH", "MEDIUM"}]
    counts = Counter(case.root_cause for case in counted)
    counts["DIAGNOSTIC_TARGET_INVALID"] += len(rejected)
    failure_counts = Counter(
        case.root_cause
        for case in counted
        if not case.success_control and case.root_cause != "NO_END_TO_END_DEFECT"
    )
    repeated_candidates = sorted(
        root_cause for root_cause, count in failure_counts.items() if count == 2
    )
    common_failure_families = sorted(
        root_cause
        for root_cause, count in failure_counts.items()
        if count >= 3
        and len(
            {
                case.source_group_id
                for case in counted
                if case.root_cause == root_cause and not case.success_control
            }
        )
        >= 2
    )
    report = output_directory / "root_cause_census.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "registry_sha256": _hash(registry_path),
                "qualified_cases": len(qualified),
                "rejected_diagnostic_cases": len(rejected),
                "success_controls": sum(case.success_control for case in qualified),
                "root_cause_census": {
                    root_cause: counts[root_cause] for root_cause in ROOT_CAUSES
                },
                "rejection_reason_census": dict(
                    sorted(Counter(case.rejection_reason for case in rejected).items())
                ),
                "common_failure_families": common_failure_families,
                "repeated_candidates": repeated_candidates,
                "dominant_root_cause": (
                    common_failure_families[0]
                    if len(common_failure_families) == 1
                    else None
                ),
                "architecture_risk": dict(registry.architecture_risk),
                "cases": [
                    {
                        "case_id": case.case_id,
                        "source_group_id": case.source_group_id,
                        "status": case.status,
                        "confidence": case.confidence,
                        "qualification": dict(case.qualification),
                        "result_type": case.result_type,
                        "root_cause": case.root_cause,
                        "first_true_divergence_stage": case.first_true_divergence_stage,
                        "first_divergence_event": case.first_divergence_event,
                        "evidence": dict(case.evidence),
                    }
                    for case in registry.cases
                ],
                "artifacts": [
                    {"path": str(path), "sha256": _hash(path)} for path in outputs
                ],
                "production_semantic_delta": "NONE",
                "protected_splits": {
                    "locked_blind_runtime": "0 / 8",
                    "locked_blind_manual_inspection": "NO",
                    "validation_executed": "NO",
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report
