from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

import cv2
import ezdxf
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPen, QTransform


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.image_loader import load_image, save_image  # noqa: E402
from app.librecad_lff import librecad_text_path  # noqa: E402
from app.preview_renderer import render_final_structure_preview  # noqa: E402
from app.processing_contract import (  # noqa: E402
    ProductionProcessingConfig,
    ProductionProcessingService,
)
from app.text_output_contract import (  # noqa: E402
    text_output_decisions,
    text_output_summary,
)
from app.trace_single_export import export_final_structure_dxf  # noqa: E402
from scripts.run_real_document_regression import _audit_content  # noqa: E402
from run_recovery_probe import (  # noqa: E402
    _base_layer,
    _entity_source_mask,
    _semantic_observation,
    _text_geometry_record,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate resumable, independent editable-TEXT acceptance "
            "artifacts for every listed page."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=VALIDATION_ROOT / "full-validation-manifest.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=VALIDATION_ROOT / "pages",
    )
    parser.add_argument(
        "--formal-manifest",
        type=Path,
        default=PROJECT_ROOT / "tests/real_regression/manifest.json",
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        default=(),
        help="Run only these IDs. Omit to select every manifest entry.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip a page when its completed entity audit already exists.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List selected run IDs without processing.",
    )
    return parser


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _resolved_input(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    if not path.is_relative_to(PROJECT_ROOT):
        raise ValueError("Validation input must remain inside the project")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _load_manifests(
    validation_path: Path,
    formal_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    runs = list(validation["runs"])
    formal_by_id = {
        str(item["id"]): item for item in formal["documents"]
    }
    run_ids = [str(item["id"]) for item in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("Full-validation run IDs must be unique")
    for run in runs:
        for document_id in run.get("formal_document_ids", []):
            if str(document_id) not in formal_by_id:
                raise ValueError(
                    f"{run['id']}: unknown formal document {document_id}"
                )
    return runs, formal_by_id


def _mask_png(path: Path, mask: np.ndarray | None, shape: tuple[int, int]) -> None:
    image = np.full(shape, 255, dtype=np.uint8)
    if mask is not None:
        image[np.asarray(mask) > 0] = 0
    save_image(path, image)


def _native_text_image(
    document: ezdxf.document.Drawing,
    *,
    shape: tuple[int, int],
    output_path: Path,
) -> np.ndarray:
    height, width = shape
    canvas = QImage(width, height, QImage.Format.Format_Grayscale8)
    canvas.fill(255)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    pen = QPen(Qt.GlobalColor.black)
    pen.setWidthF(1.0)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for entity in document.modelspace().query("TEXT"):
        path = librecad_text_path(str(entity.dxf.text))
        transform = QTransform()
        transform.translate(
            float(entity.dxf.insert.x),
            float(height) - float(entity.dxf.insert.y),
        )
        transform.rotate(-float(entity.dxf.rotation))
        scale = float(entity.dxf.height) / 9.0
        transform.scale(
            scale * float(entity.dxf.width),
            scale,
        )
        painter.drawPath(transform.map(path))
    painter.end()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(output_path), "PNG"):
        raise ValueError(f"Could not save native TEXT render: {output_path}")
    rendered = cv2.imread(str(output_path), cv2.IMREAD_GRAYSCALE)
    if rendered is None or rendered.shape != shape:
        raise ValueError("Native TEXT render has unexpected dimensions")
    return rendered


def _default_view(
    structure: Any,
    native_text: np.ndarray,
    output_path: Path,
) -> np.ndarray:
    view = np.where(
        structure.contour_binary < 128,
        0,
        255,
    ).astype(np.uint8)
    for line in structure.straight_lines:
        cv2.line(
            view,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            0,
            max(1, int(round(float(line.width)))),
            cv2.LINE_8,
        )
    if structure.uncertain_text_outline_mask is not None:
        view[structure.uncertain_text_outline_mask > 0] = 0
    view[native_text < 128] = 0
    for region in structure.signatures:
        x, y, width, height = region.bbox
        crop = view[y : y + height, x : x + width]
        if crop.shape == region.mask.shape:
            crop[region.mask > 0] = 0
    save_image(output_path, view)
    return view


def _layer_counts(
    document: ezdxf.document.Drawing,
) -> Counter[str]:
    return Counter(
        _base_layer(str(entity.dxf.layer))
        for entity in document.modelspace()
    )


def _layer_state(
    document: ezdxf.document.Drawing,
    name: str,
) -> dict[str, bool]:
    if name not in document.layers:
        return {
            "present": False,
            "off": False,
            "frozen": False,
            "default_visible": False,
        }
    layer = document.layers.get(name)
    return {
        "present": True,
        "off": bool(layer.is_off()),
        "frozen": bool(layer.is_frozen()),
        "default_visible": not (
            layer.is_off() or layer.is_frozen()
        ),
    }


def _owned_text_symbol_counts(
    structure: Any,
    document: ezdxf.document.Drawing,
) -> dict[str, int]:
    shape = structure.contour_binary.shape
    editable_mask = structure.editable_text_source_mask
    uncertain_mask = structure.uncertain_text_outline_mask
    general_source = structure.contour_binary < 128
    editable_owned = np.zeros(shape, dtype=np.uint8)
    uncertain_owned = np.zeros(shape, dtype=np.uint8)
    if editable_mask is not None:
        editable_owned[general_source & (editable_mask > 0)] = 255
    if uncertain_mask is not None:
        uncertain_owned[general_source & (uncertain_mask > 0)] = 255

    counts: Counter[str] = Counter()
    for entity in document.modelspace():
        if _base_layer(str(entity.dxf.layer)) != "TRACE_TEXT_SYMBOL":
            continue
        entity_mask = _entity_source_mask(entity, shape=shape)
        if editable_mask is not None:
            geometric = int(
                np.count_nonzero(
                    (entity_mask > 0) & (editable_mask > 0)
                )
            )
            counts["eligible_geometric_touch_pixels"] += geometric
            counts["eligible_geometric_touch_objects"] += int(geometric > 0)
            counts["eligible_owned_objects"] += int(
                np.any((entity_mask > 0) & (editable_owned > 0))
            )
        if uncertain_mask is not None:
            geometric = int(
                np.count_nonzero(
                    (entity_mask > 0) & (uncertain_mask > 0)
                )
            )
            counts["uncertain_geometric_touch_pixels"] += geometric
            counts["uncertain_geometric_touch_objects"] += int(geometric > 0)
            counts["uncertain_owned_objects"] += int(
                np.any((entity_mask > 0) & (uncertain_owned > 0))
            )
    counts["eligible_owned_pixels"] = int(cv2.countNonZero(editable_owned))
    counts["uncertain_owned_pixels"] = int(cv2.countNonZero(uncertain_owned))
    return {
        key: int(counts[key])
        for key in (
            "eligible_owned_objects",
            "eligible_owned_pixels",
            "eligible_geometric_touch_objects",
            "eligible_geometric_touch_pixels",
            "uncertain_owned_objects",
            "uncertain_owned_pixels",
            "uncertain_geometric_touch_objects",
            "uncertain_geometric_touch_pixels",
        )
    }


def _geometry_payload(
    native_texts: list[Any],
) -> dict[str, Any]:
    records = [
        _text_geometry_record(entity, index)
        for index, entity in enumerate(native_texts, start=1)
    ]
    valid = [
        item
        for item in records
        if item.get("geometry_contract_present") is True
    ]

    def values(key: str) -> list[float]:
        return [
            float(item[key])
            for item in valid
            if item.get(key) is not None
        ]

    height_ratios = values("rendered_to_target_height_ratio")
    width_ratios = values("rendered_to_target_width_ratio")
    center_errors = values("center_error")
    rotation_errors = values("rotation_error")
    width_factors = values("width_factor")
    return {
        "record_count": len(records),
        "contract_present_count": len(valid),
        "all_entity_types_TEXT": all(
            item.get("entity_type") == "TEXT" for item in records
        ),
        "all_finite": all(item.get("finite") is True for item in valid),
        "metric_sources": dict(
            Counter(
                str(item.get("metric_source", "missing"))
                for item in records
            )
        ),
        "metric_fallbacks": dict(
            Counter(
                str(item.get("metric_fallback", "missing"))
                for item in records
            )
        ),
        "width_factor_clamped_count": sum(
            bool(item.get("width_factor_clamped", False))
            for item in valid
        ),
        "width_factor_below_0_60_count": sum(
            float(item.get("width_factor", 0.0)) < 0.60
            for item in valid
        ),
        "minimum_width_factor": min(width_factors) if width_factors else None,
        "maximum_width_factor": max(width_factors) if width_factors else None,
        "minimum_rendered_to_target_height_ratio": (
            min(height_ratios) if height_ratios else None
        ),
        "maximum_rendered_to_target_height_ratio": (
            max(height_ratios) if height_ratios else None
        ),
        "minimum_rendered_to_target_width_ratio": (
            min(width_ratios) if width_ratios else None
        ),
        "maximum_rendered_to_target_width_ratio": (
            max(width_ratios) if width_ratios else None
        ),
        "maximum_center_error": max(center_errors) if center_errors else None,
        "maximum_rotation_error": (
            max(rotation_errors) if rotation_errors else None
        ),
        "records": records,
    }


def _roundtrip_audit(
    dxf_path: Path,
    *,
    expected_text_count: int,
) -> dict[str, Any]:
    with TemporaryDirectory(
        prefix="editable-text-roundtrip-",
        dir=dxf_path.parent,
    ) as temporary:
        output = Path(temporary) / "roundtrip.dxf"
        document = ezdxf.readfile(dxf_path)
        texts = list(document.modelspace().query("TEXT"))
        original = str(texts[0].dxf.text) if texts else None
        marker = None
        if texts:
            marker = f"{original} [editable-roundtrip]"
            texts[0].dxf.text = marker
        document.saveas(output)
        reopened = ezdxf.readfile(output)
        audit = reopened.audit()
        reopened_texts = list(reopened.modelspace().query("TEXT"))
        return {
            "initial_TEXT_count": len(texts),
            "reopened_TEXT_count": len(reopened_texts),
            "expected_TEXT_count": int(expected_text_count),
            "modified_original": original,
            "modified_value": marker,
            "modified_value_preserved": bool(
                marker is None
                or (
                    reopened_texts
                    and str(reopened_texts[0].dxf.text) == marker
                )
            ),
            "all_reopened_entities_still_TEXT": all(
                entity.dxftype() == "TEXT" for entity in reopened_texts
            ),
            "audit_error_count": len(audit.errors),
            "passed": bool(
                len(texts)
                == len(reopened_texts)
                == expected_text_count
                and (
                    marker is None
                    or (
                        reopened_texts
                        and str(reopened_texts[0].dxf.text) == marker
                    )
                )
                and not audit.errors
            ),
        }


def _formal_safety_audit(
    run: Mapping[str, Any],
    formal_by_id: Mapping[str, dict[str, Any]],
    *,
    source_image: np.ndarray,
    structure: Any,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    raw_preview = render_final_structure_preview(structure)
    for document_id in run.get("formal_document_ids", []):
        formal = formal_by_id[str(document_id)]
        content, errors = _audit_content(
            formal,
            source_image=source_image,
            structure=structure,
            preview=raw_preview,
        )
        expected_lines = int(formal["expected"]["straight_line_count"])
        observed_lines = len(structure.straight_lines)
        if observed_lines != expected_lines:
            errors.append(
                "straight_line_count mismatch: "
                f"{observed_lines} != {expected_lines}"
            )
        records.append(
            {
                "formal_document_id": str(document_id),
                "expected_straight_line_count": expected_lines,
                "observed_straight_line_count": observed_lines,
                "content_audit": content,
                "errors": errors,
                "passed": not errors,
            }
        )
    return {
        "mode": (
            "formal_page_exact_baseline"
            if records
            else "whole_source_page_without_frozen_page_metric"
        ),
        "records": records,
        "passed": all(item["passed"] for item in records),
        "baseline_was_updated": False,
    }


def _review_markdown(
    run: Mapping[str, Any],
    routing: Mapping[str, Any],
    geometry: Mapping[str, Any],
    entity: Mapping[str, Any],
) -> str:
    summary = routing["summary"]
    checks = entity["checks"]
    hard_rejects = routing["hard_rejected_candidates"]
    reject_lines = (
        "\n".join(
            "- `{candidate_id}`: `{hard_reject_reason}` — `{text}`".format(
                **item
            )
            for item in hard_rejects
        )
        if hard_rejects
        else "- None."
    )
    check_lines = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in checks.items()
    )
    return (
        f"# {run['id']}\n\n"
        f"- Input: `{run['input']}`\n"
        f"- Page / DPI: {run['page']} / {run['dpi']}\n"
        f"- FinalStructure: `{routing['structure_id']}`\n"
        f"- OCR candidates: {summary['ocr_candidate_count']}\n"
        f"- TEXT eligible / native TEXT: "
        f"{summary['text_emit_eligible_count']} / "
        f"{entity['native_TEXT_count']}\n"
        f"- Confidence hard rejects: "
        f"{summary['confidence_hard_reject_count']}\n"
        f"- Invalid geometry rejects: {summary['invalid_geometry_count']}\n"
        f"- Hidden source-outline backup candidates / entities: "
        f"{summary['source_outline_backup_count']} / "
        f"{entity['source_text_outline_entity_count']}\n"
        f"- Uncertain candidates / entities: "
        f"{summary['fallback_count']} / "
        f"{entity['uncertain_text_outline_entity_count']}\n"
        f"- TRACE_TEXT_SYMBOL entities: {entity['text_symbol_entity_count']}\n"
        f"- Maximum center / rotation error: "
        f"{geometry['maximum_center_error']} / "
        f"{geometry['maximum_rotation_error']}\n"
        f"- Width-factor range: {geometry['minimum_width_factor']} to "
        f"{geometry['maximum_width_factor']}\n"
        f"- Overall: {'PASS' if entity['passed'] else 'FAIL'}\n\n"
        "## Acceptance checks\n\n"
        f"{check_lines}\n\n"
        "## Candidates without native TEXT\n\n"
        f"{reject_lines}\n"
    )


def _process_run(
    run: dict[str, Any],
    *,
    output_root: Path,
    formal_by_id: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    run_id = str(run["id"])
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    source_path = _resolved_input(str(run["input"]))
    page_number = int(run["page"])
    dpi = float(run["dpi"])
    page_index = page_number - 1 if source_path.suffix.lower() == ".pdf" else 0
    started = perf_counter()
    image = load_image(
        source_path,
        page_index=page_index,
        pdf_dpi=int(round(dpi)),
        grayscale=True,
    )
    config = ProductionProcessingConfig(source_dpi=dpi, enable_ocr=True)
    result = ProductionProcessingService.process_page(image, config)
    structure = result.final_structure
    if structure is None:
        raise AssertionError("Production processing returned no FinalStructure")
    structure.assert_valid()

    dxf_path = run_root / f"{run_id}.dxf"
    export = export_final_structure_dxf(structure, dxf_path)
    document = ezdxf.readfile(dxf_path)
    dxf_audit = document.audit()
    modelspace = document.modelspace()
    native_texts = list(modelspace.query("TEXT"))
    decisions = text_output_decisions(structure.texts)
    summary = text_output_summary(structure.texts)
    layer_counts = _layer_counts(document)
    source_layer = _layer_state(document, "SOURCE_TEXT_OUTLINE")
    uncertain_layer = _layer_state(document, "TEXT_FALLBACK_OUTLINE")
    semantic = _semantic_observation(structure)
    candidate_records = [
        item
        for item in semantic.get("candidates", [])
        if isinstance(item, dict)
    ]
    symbol = _owned_text_symbol_counts(structure, document)
    geometry = _geometry_payload(native_texts)
    routing = {
        "schema_version": 1,
        "run_id": run_id,
        "input": str(source_path),
        "input_sha256": _file_sha256(source_path),
        "page": page_number,
        "dpi": dpi,
        "source_shape": [int(value) for value in image.shape],
        "structure_id": structure.structure_id,
        "processing_contract": config.payload(),
        "summary": summary.payload(),
        "hard_rejected_candidates": [
            {
                "candidate_id": f"ocr-{index + 1:03d}",
                "text": str(decision.candidate.text),
                "bbox": [
                    int(value) for value in decision.candidate.bbox
                ],
                "hard_reject_reason": decision.hard_reject_reason,
            }
            for index, decision in enumerate(decisions)
            if not decision.text_emit_eligible
        ],
        "decisions": [
            {
                "candidate_id": f"ocr-{index + 1:03d}",
                **decision.payload(),
            }
            for index, decision in enumerate(decisions)
        ],
        "semantic_ownership": semantic,
    }
    _write_json(
        run_root / f"{run_id}-text-routing.json",
        routing,
    )
    geometry_report = {
        "schema_version": 1,
        "run_id": run_id,
        "structure_id": structure.structure_id,
        **geometry,
    }
    _write_json(
        run_root / f"{run_id}-text-geometry.json",
        geometry_report,
    )

    ocr_png = run_root / f"{run_id}-ocr-text-only.png"
    native_text_image = _native_text_image(
        document,
        shape=structure.contour_binary.shape,
        output_path=ocr_png,
    )
    _mask_png(
        run_root / f"{run_id}-source-outline-only.png",
        structure.source_text_outline_mask,
        structure.contour_binary.shape,
    )
    _mask_png(
        run_root / f"{run_id}-uncertain-text-only.png",
        structure.uncertain_text_outline_mask,
        structure.contour_binary.shape,
    )
    _default_view(
        structure,
        native_text_image,
        run_root / f"{run_id}-default-view.png",
    )

    formal_safety = _formal_safety_audit(
        run,
        formal_by_id,
        source_image=image,
        structure=structure,
    )
    roundtrip = _roundtrip_audit(
        dxf_path,
        expected_text_count=int(summary.text_emit_eligible_count),
    )
    primary_conflicts = sum(
        not bool(item.get("primary_semantic_unique", False))
        for item in candidate_records
    )
    ownership_violations = sum(
        not bool(item.get("source_pixels_conserved", False))
        for item in candidate_records
    )
    replacement_unsafe_fallback = sum(
        not decision.candidate.replacement_safe
        and decision.state.value == "text_fallback_outline"
        and decision.hard_reject_reason is None
        for decision in decisions
    )
    source_outline_visible_duplicates = (
        int(summary.source_outline_backup_count)
        if source_layer["default_visible"]
        else 0
    )
    visible_duplicate_count = (
        source_outline_visible_duplicates
        + int(symbol["eligible_owned_objects"])
    )
    ocr_layer_entities = [
        entity
        for entity in modelspace
        if _base_layer(str(entity.dxf.layer)) == "OCR_TEXT"
    ]
    finite_geometry = all(
        item.get("finite") is True
        and item.get("entity_type") == "TEXT"
        and isfinite(float(item.get("width_factor", float("nan"))))
        and float(item.get("width_factor", 0.0)) >= 0.72
        and abs(
            float(
                item.get(
                    "rendered_to_target_height_ratio",
                    float("nan"),
                )
            )
            - 1.0
        )
        <= 1e-6
        and float(item.get("center_error", float("inf"))) <= 1e-6
        and float(item.get("rotation_error", float("inf"))) <= 1e-6
        for item in geometry["records"]
    )
    checks = {
        "native_TEXT_count_equals_text_emit_eligible_count": (
            len(native_texts)
            == int(summary.text_emit_eligible_count)
            == int(export.text_count)
        ),
        "replacement_unsafe_does_not_downgrade_eligible_text": (
            replacement_unsafe_fallback == 0
        ),
        "eligible_candidate_enters_TRACE_TEXT_SYMBOL_count_is_zero": (
            symbol["eligible_owned_objects"] == 0
            and symbol["eligible_owned_pixels"] == 0
        ),
        "candidate_primary_semantic_conflict_count_is_zero": (
            primary_conflicts == 0
        ),
        "candidate_source_pixel_ownership_is_conserved": (
            ownership_violations == 0
        ),
        "fallback_and_text_symbol_conflict_count_is_zero": (
            symbol["uncertain_owned_objects"] == 0
            and symbol["uncertain_owned_pixels"] == 0
        ),
        "unsafe_source_outline_backup_is_default_hidden": (
            int(summary.source_outline_backup_count) == 0
            or (
                source_layer["present"]
                and source_layer["off"]
                and source_layer["frozen"]
                and not source_layer["default_visible"]
            )
        ),
        "no_duplicate_visible_text_representation": (
            visible_duplicate_count == 0
        ),
        "every_OCR_TEXT_layer_entity_is_native_TEXT": (
            len(ocr_layer_entities) == len(native_texts)
            and all(
                entity.dxftype() == "TEXT"
                for entity in ocr_layer_entities
            )
        ),
        "native_TEXT_geometry_contract_passes": (
            geometry["contract_present_count"] == len(native_texts)
            and geometry["all_entity_types_TEXT"]
            and geometry["all_finite"]
            and finite_geometry
        ),
        "DXF_audit_error_count_is_zero": not dxf_audit.errors,
        "DXF_read_save_read_and_edit_passes": roundtrip["passed"],
        "preview_and_DXF_consumed_same_FinalStructure": (
            export.structure_id == structure.structure_id
        ),
        "formal_structure_and_protection_audit_passes": (
            formal_safety["passed"]
        ),
        "OCR_threshold_contract_recorded_unchanged": (
            config.threshold_summary()
            == ProductionProcessingConfig().threshold_summary()
        ),
        "baseline_was_not_updated": not formal_safety["baseline_was_updated"],
    }
    entity_report = {
        "schema_version": 1,
        "run_id": run_id,
        "structure_id": structure.structure_id,
        "dxf_path": str(dxf_path.resolve()),
        "dxf_sha256": _file_sha256(dxf_path),
        "native_TEXT_count": len(native_texts),
        "source_text_outline_candidate_count": int(
            summary.source_outline_backup_count
        ),
        "source_text_outline_entity_count": int(
            layer_counts["SOURCE_TEXT_OUTLINE"]
        ),
        "uncertain_text_candidate_count": int(
            summary.fallback_outline_count
        ),
        "uncertain_text_outline_entity_count": int(
            layer_counts["TEXT_FALLBACK_OUTLINE"]
        ),
        "text_symbol_entity_count": int(
            layer_counts["TRACE_TEXT_SYMBOL"]
        ),
        "residual_OCR_candidate_count": int(
            summary.residual_graphic_count
        ),
        "eligible_candidate_text_symbol_count": int(
            symbol["eligible_owned_objects"]
        ),
        "candidate_primary_semantic_conflict_count": int(
            primary_conflicts
        ),
        "candidate_source_ownership_violation_count": int(
            ownership_violations
        ),
        "fallback_and_text_symbol_conflict_count": int(
            symbol["uncertain_owned_objects"]
        ),
        "duplicate_visible_representation_count": int(
            visible_duplicate_count
        ),
        "replacement_unsafe_fallback_without_hard_reject_count": int(
            replacement_unsafe_fallback
        ),
        "layer_entity_counts": dict(sorted(layer_counts.items())),
        "source_text_outline_layer": source_layer,
        "uncertain_text_outline_layer": uncertain_layer,
        "text_symbol_ownership": symbol,
        "dxf_audit_error_count": len(dxf_audit.errors),
        "roundtrip": roundtrip,
        "formal_structural_safety": formal_safety,
        "checks": checks,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "passed": all(checks.values()),
    }
    _write_json(
        run_root / f"{run_id}-entity-audit.json",
        entity_report,
    )
    review = _review_markdown(
        run,
        routing,
        geometry_report,
        entity_report,
    )
    (
        run_root / f"{run_id}-review.md"
    ).write_text(review, encoding="utf-8")
    return entity_report


def _build_index(
    runs: list[dict[str, Any]],
    output_root: Path,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for run in runs:
        run_id = str(run["id"])
        audit_path = (
            output_root
            / run_id
            / f"{run_id}-entity-audit.json"
        )
        if not audit_path.is_file():
            records.append(
                {
                    "id": run_id,
                    "status": "pending",
                    "passed": False,
                }
            )
            continue
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        records.append(
            {
                "id": run_id,
                "status": "complete",
                "passed": bool(audit["passed"]),
                "structure_id": audit["structure_id"],
                "native_TEXT_count": audit["native_TEXT_count"],
                "dxf_path": audit["dxf_path"],
                "entity_audit": str(audit_path.resolve()),
            }
        )
    complete = sum(item["status"] == "complete" for item in records)
    passed = sum(
        item["status"] == "complete" and item["passed"]
        for item in records
    )
    return {
        "schema_version": 1,
        "git_commit": _git_output("rev-parse", "HEAD"),
        "expected_run_count": len(runs),
        "complete_run_count": complete,
        "passed_run_count": passed,
        "all_complete": complete == len(runs),
        "all_passed": (
            complete == len(runs)
            and passed == len(runs)
        ),
        "runs": records,
    }


def main() -> int:
    args = _parser().parse_args()
    runs, formal_by_id = _load_manifests(
        args.manifest.resolve(),
        args.formal_manifest.resolve(),
    )
    requested = set(str(value) for value in args.ids)
    selected = [
        run for run in runs
        if not requested or str(run["id"]) in requested
    ]
    missing = requested - {str(run["id"]) for run in runs}
    if missing:
        raise ValueError(
            f"Unknown validation run IDs: {', '.join(sorted(missing))}"
        )
    if args.list:
        for run in selected:
            print(str(run["id"]))
        return 0

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    failures = 0
    for index, run in enumerate(selected, start=1):
        run_id = str(run["id"])
        audit_path = (
            output_root
            / run_id
            / f"{run_id}-entity-audit.json"
        )
        if args.resume and audit_path.is_file():
            print(f"[{index}/{len(selected)}] SKIP {run_id}", flush=True)
            continue
        print(f"[{index}/{len(selected)}] START {run_id}", flush=True)
        try:
            report = _process_run(
                run,
                output_root=output_root,
                formal_by_id=formal_by_id,
            )
        except Exception as exc:
            failures += 1
            _write_json(
                output_root / run_id / f"{run_id}-failure.json",
                {
                    "run_id": run_id,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            print(
                f"[{index}/{len(selected)}] ERROR {run_id}: {exc}",
                flush=True,
            )
            continue
        failures += int(not report["passed"])
        print(
            f"[{index}/{len(selected)}] "
            f"{'PASS' if report['passed'] else 'FAIL'} {run_id} "
            f"({report['elapsed_seconds']}s)",
            flush=True,
        )

    index = _build_index(runs, output_root)
    _write_json(VALIDATION_ROOT / "per-page-index.json", index)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
