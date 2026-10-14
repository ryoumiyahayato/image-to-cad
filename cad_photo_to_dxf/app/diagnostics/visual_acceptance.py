from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

import cv2
import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform

from app.core.structure import FinalStructure, metadata_to_jsonable
from app.ocr.librecad_lff import librecad_font_available, librecad_text_path
from app.export.ocr_outline_export import NativeTextPlacement, native_text_placement
from app.ocr.text_output_contract import accepted_ocr_texts
from app.core.member_binding import resolve_draftsman_output


VISUAL_ACCEPTANCE_SCHEMA_VERSION = "visual-acceptance-v1"
ALLOWED_CORPUS_SPLITS = {None, "DEV", "GOLDEN"}


@dataclass(frozen=True)
class VisualLayerSelection:
    structure_lines: bool = True
    texts: bool = True
    symbols: bool = True
    unverified_geometry: bool = True
    review_warnings: bool = True


@dataclass(frozen=True)
class VisualAcceptanceImages:
    original: np.ndarray
    reconstructed: np.ndarray
    overlay: np.ndarray


@dataclass(frozen=True)
class VisualAcceptanceRun:
    run_id: str
    directory: Path
    overview_path: Path
    structure_id: str
    entity_count: int


def plain_language_status(value: str) -> str:
    return {
        "CONFIRMED": "已确认",
        "MIXED": "部分确认，请结合原图检查",
        "UNKNOWN": "状态未知，请人工检查",
        "UNVERIFIED": "语义未确认，但几何已保留",
        "SEMANTIC_IDENTITY_UNVERIFIED": "语义未确认，但几何已保留",
    }.get(value, value)


def _source_bgr(source: np.ndarray, structure: FinalStructure) -> np.ndarray:
    if source is None or source.size == 0:
        raise ValueError("Visual acceptance source image must not be empty")
    height, width = source.shape[:2]
    if (width, height) != structure.source_size_px:
        raise ValueError(
            "Source and FinalStructure must use the same pixel coordinate system"
        )
    if source.ndim == 2:
        return cv2.cvtColor(source, cv2.COLOR_GRAY2BGR)
    if source.ndim == 3 and source.shape[2] == 3:
        return np.ascontiguousarray(source.copy())
    if source.ndim == 3 and source.shape[2] == 4:
        return cv2.cvtColor(source, cv2.COLOR_BGRA2BGR)
    raise ValueError("Visual acceptance source must be grayscale, BGR, or BGRA")


def _paint_mask(
    image: np.ndarray, mask: np.ndarray | None, color: tuple[int, int, int]
) -> None:
    if mask is None:
        return
    image[mask > 0] = color


def _draw_deployable_text(
    image: np.ndarray,
    placement: NativeTextPlacement,
    color: tuple[int, int, int],
) -> None:
    """Rasterize the canonical native-TEXT placement in source coordinates."""

    if not librecad_font_available():
        raise RuntimeError("Packaged Unicode LFF is required for VQA text rendering")
    metrics = placement.metrics
    if metrics.fallback_reason:
        raise ValueError(
            "Packaged Unicode LFF cannot render native TEXT without fallback: "
            f"{metrics.fallback_reason}"
        )
    path = librecad_text_path(placement.content)
    bounds = path.boundingRect()
    if path.isEmpty() or bounds.width() <= 0.0 or bounds.height() <= 0.0:
        return
    geometry = placement.geometry
    scale_y = geometry.character_height / metrics.em_height
    scale_x = scale_y * geometry.width_factor
    image_height, image_width = image.shape[:2]
    transform = QTransform()
    transform.translate(
        float(geometry.insert[0]),
        float(image_height) - float(geometry.insert[1]),
    )
    transform.rotate(-float(geometry.rotation))
    transform.scale(scale_x, scale_y)

    canvas = QImage(
        image.data,
        image_width,
        image_height,
        int(image.strides[0]),
        QImage.Format.Format_BGR888,
    )
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(int(color[2]), int(color[1]), int(color[0])))
    pen.setCosmetic(True)
    pen.setWidthF(
        max(
            1.0,
            min(geometry.target_width, geometry.target_height) / 42.0,
        )
    )
    painter.setPen(pen)
    painter.drawPath(transform.map(path))
    painter.end()


def render_visual_acceptance(
    source: np.ndarray,
    structure: FinalStructure,
    *,
    layers: VisualLayerSelection | None = None,
    source_opacity: float = 0.72,
    cad_opacity: float = 0.82,
) -> VisualAcceptanceImages:
    """Render a source-aligned comparison from the canonical export structure."""

    selected = layers or VisualLayerSelection()
    resolved_output = resolve_draftsman_output(structure)
    member_lookup = (
        {} if resolved_output is None else resolved_output.members_by_locator
    )

    def member_visible(collection: str, index: int) -> bool:
        if resolved_output is None:
            return True
        member = member_lookup.get((collection, index))
        if member is None or member.emit_mode == "ALIAS_NO_EMIT" or not member.default_visible:
            return False
        return {
            "structure_lines": selected.structure_lines,
            "symbols": selected.symbols,
            "texts": selected.texts,
            "source_backup": selected.unverified_geometry,
        }.get(member.preview_category, False)
    original = _source_bgr(source, structure)
    height, width = original.shape[:2]
    reconstructed = np.full((height, width, 3), 255, dtype=np.uint8)
    if selected.structure_lines:
        for arc in structure.arcs:
            count = min(4096, max(32, int(abs(arc.sweep_angle_deg)*np.pi/180*arc.radius/.5)+1))
            points = np.rint([arc.point_at(t) for t in np.linspace(0, 1, count)]).astype(np.int32)
            cv2.polylines(reconstructed, [points], False, (55, 70, 20), max(1, int(np.ceil(arc.stroke_width_px))))

    if selected.structure_lines or resolved_output is not None:
        for path_index, path in enumerate(structure.contours):
            if not member_visible("contours", path_index):
                continue
            points = np.asarray(path.points, dtype=np.float32)
            if len(points) < 2:
                continue
            cv2.polylines(
                reconstructed,
                [np.rint(points).astype(np.int32)],
                True,
                (55, 70, 20),
                1,
                cv2.LINE_AA,
            )
        for line_index, line in enumerate(structure.straight_lines):
            if not member_visible("straight_lines", line_index):
                continue
            cv2.line(
                reconstructed,
                (int(round(line.x1)), int(round(line.y1))),
                (int(round(line.x2)), int(round(line.y2))),
                (210, 90, 20),
                max(1, int(round(line.width))),
                cv2.LINE_AA,
            )

    if selected.texts:
        for text_index, text in enumerate(structure.texts):
            if text not in accepted_ocr_texts(structure.texts):
                continue
            if not member_visible("texts", text_index):
                continue
            color = (185, 35, 175) if text.replacement_safe else (0, 145, 255)
            placement = native_text_placement(
                text,
                transform=lambda x, y: (x, float(height) - y),
            )
            if placement is None:
                raise ValueError(
                    "Eligible OCR candidate has no finite VQA placement: "
                    f"{text.bbox!r}"
                )
            _draw_deployable_text(
                reconstructed,
                placement,
                color,
            )

    if selected.symbols:
        for item_index, item in enumerate(structure.logos):
            if not member_visible("logos", item_index):
                continue
            x, y, item_width, item_height = item.bbox
            crop = reconstructed[y : y + item_height, x : x + item_width]
            crop[item.mask > 0] = (35, 140, 230)
            cv2.rectangle(
                reconstructed,
                (x, y),
                (x + item_width, y + item_height),
                (35, 140, 230),
                1,
            )
        for item_index, item in enumerate(structure.signatures):
            if not member_visible("signatures", item_index):
                continue
            x, y, item_width, item_height = item.bbox
            crop = reconstructed[y : y + item_height, x : x + item_width]
            crop[item.mask > 0] = (35, 140, 230)
            cv2.rectangle(
                reconstructed,
                (x, y),
                (x + item_width, y + item_height),
                (35, 140, 230),
                1,
            )

    if selected.unverified_geometry:
        _paint_mask(
            reconstructed,
            structure.uncertain_text_outline_mask,
            (0, 165, 255),
        )

    if selected.review_warnings and structure.warnings:
        thickness = max(2, min(width, height) // 300)
        cv2.rectangle(
            reconstructed,
            (thickness, thickness),
            (width - thickness - 1, height - thickness - 1),
            (20, 20, 220),
            thickness,
        )

    source_alpha = max(0.0, min(1.0, float(source_opacity)))
    cad_alpha = max(0.0, min(1.0, float(cad_opacity)))
    overlay = cv2.addWeighted(
        original,
        source_alpha,
        np.full_like(original, 255),
        1.0 - source_alpha,
        0.0,
    )
    cad_mask = np.any(reconstructed < 245, axis=2)
    if np.any(cad_mask):
        overlay[cad_mask] = cv2.addWeighted(
            overlay[cad_mask],
            1.0 - cad_alpha,
            reconstructed[cad_mask],
            cad_alpha,
            0.0,
        )
    return VisualAcceptanceImages(original, reconstructed, overlay)


def _entity_references(structure: FinalStructure) -> list[dict[str, Any]]:
    resolved_output = resolve_draftsman_output(structure)
    member_lookup = (
        {} if resolved_output is None else resolved_output.members_by_locator
    )
    shared = {
        "final_structure_id": structure.structure_id,
        "upstream_provenance": metadata_to_jsonable(structure.provenance),
    }
    references: list[dict[str, Any]] = []

    def resolved_member(collection: str, index: int):
        member = member_lookup.get((collection, index))
        if member is not None and (
            member.emit_mode == "ALIAS_NO_EMIT" or not member.default_visible
        ):
            return False, member
        return True, member

    for index, path in enumerate(structure.contours):
        include, member = resolved_member("contours", index)
        if not include:
            continue
        xs = [float(point[0]) for point in path.points]
        ys = [float(point[1]) for point in path.points]
        references.append(
            {
                **shared,
                "entity_id": getattr(member, "member_id", f"contour-{index:06d}"),
                "category": getattr(member, "semantic_role", "structure_line"),
                "source_region": [min(xs), min(ys), max(xs), max(ys)],
                "candidate_or_evidence_ids": [],
            }
        )
    for index, line in enumerate(structure.straight_lines):
        include, member = resolved_member("straight_lines", index)
        if not include:
            continue
        references.append(
            {
                **shared,
                "entity_id": getattr(member, "member_id", f"straight-line-{index:06d}"),
                "category": getattr(member, "semantic_role", "structure_line"),
                "source_region": [
                    min(line.x1, line.x2),
                    min(line.y1, line.y2),
                    max(line.x1, line.x2),
                    max(line.y1, line.y2),
                ],
                "candidate_or_evidence_ids": list(line.source_ids),
                "history": list(line.history),
            }
        )
    for arc in structure.arcs:
        references.append({**shared, 'entity_id': arc.object_id, 'entity_type': 'ARC',
                           'category': 'structure_line', 'source_region': list(arc.bounds),
                           'candidate_or_evidence_ids': list(arc.replaced_members),
                           'source': arc.payload()['source']})
    for index, text in enumerate(structure.texts):
        include, member = resolved_member("texts", index)
        if not include:
            continue
        x, y, box_width, box_height = text.bbox
        references.append(
            {
                **shared,
                "entity_id": getattr(member, "member_id", f"text-{index:06d}"),
                "category": getattr(member, "semantic_role", "text"),
                "source_region": [x, y, x + box_width, y + box_height],
                "candidate_or_evidence_ids": [],
                "text": text.text,
                "status": ("CONFIRMED" if text.replacement_safe else "UNVERIFIED"),
            }
        )
    for index, item in enumerate(structure.logos):
        include, member = resolved_member("logos", index)
        if not include:
            continue
        x, y, item_width, item_height = item.bbox
        references.append(
            {
                **shared,
                "entity_id": getattr(member, "member_id", f"logo-{index:06d}"),
                "category": getattr(member, "semantic_role", "symbol"),
                "source_region": [x, y, x + item_width, y + item_height],
                "candidate_or_evidence_ids": [],
            }
        )
    for index, item in enumerate(structure.signatures):
        include, member = resolved_member("signatures", index)
        if not include:
            continue
        x, y, item_width, item_height = item.bbox
        references.append(
            {
                **shared,
                "entity_id": getattr(member, "member_id", f"signature-{index:06d}"),
                "category": getattr(member, "semantic_role", "symbol"),
                "source_region": [x, y, x + item_width, y + item_height],
                "candidate_or_evidence_ids": [],
            }
        )
    return references


def _safe_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part)[:48] or "source"


def _write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError(f"Could not encode visual acceptance image: {path.name}")
    path.write_bytes(encoded.tobytes())


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _panel(image: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (
            max(1, int(round(image.shape[1] * scale))),
            max(1, int(round(image.shape[0] * scale))),
        ),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
    )
    panel: np.ndarray = np.full((height, width, 3), 247, dtype=np.uint8)
    y = (height - resized.shape[0]) // 2
    x = (width - resized.shape[1]) // 2
    panel[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return panel


def build_overview_image(
    images: VisualAcceptanceImages,
    *,
    source_label: str,
    page_label: str,
    commit: str,
    run_id: str,
    entity_count: int,
    verdict: str | None,
) -> np.ndarray:
    panel_width, panel_height = 720, 720
    body = np.hstack(
        [
            _panel(images.original, panel_width, panel_height),
            _panel(images.reconstructed, panel_width, panel_height),
            _panel(images.overlay, panel_width, panel_height),
        ]
    )
    canvas: np.ndarray = np.full(
        (panel_height + 150, panel_width * 3, 3), 255, dtype=np.uint8
    )
    canvas[80 : 80 + panel_height] = body
    cv2.putText(
        canvas,
        "SOURCE                          FINAL RECONSTRUCTION                         OVERLAY",
        (24, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (25, 25, 25),
        2,
        cv2.LINE_AA,
    )
    footer = (
        f"source={source_label}  page={page_label}  commit={commit[:12]}  "
        f"run={run_id}  entities={entity_count}  verdict={verdict or 'PENDING'}"
    )
    cv2.putText(
        canvas,
        footer[:210],
        (24, panel_height + 125),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (40, 40, 40),
        1,
        cv2.LINE_AA,
    )
    return canvas


def current_git_commit(repository_root: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return completed.stdout.strip() or "UNKNOWN"


def default_visual_acceptance_root(start: Path | None = None) -> Path:
    override = os.environ.get("CADPHOTO_VISUAL_ACCEPTANCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Documents" / "CADPhotoToDXF" / "visual-acceptance"


def create_visual_acceptance_run(
    source: np.ndarray,
    structure: FinalStructure,
    *,
    output_root: Path,
    source_label: str,
    page_label: str,
    commit: str,
    corpus_split: str | None = None,
    layers: VisualLayerSelection | None = None,
    timestamp: datetime | None = None,
) -> tuple[VisualAcceptanceRun, VisualAcceptanceImages]:
    if corpus_split not in ALLOWED_CORPUS_SPLITS:
        raise ValueError("VQA-S1 accepts only GOLDEN, DEV, or ordinary user sources")
    images = render_visual_acceptance(source, structure, layers=layers)
    now = timestamp or datetime.now(timezone.utc)
    run_id = (
        f"{now.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{_safe_slug(source_label)}-{structure.structure_id[:10]}"
    )
    directory = output_root / run_id
    suffix = 2
    while directory.exists():
        directory = output_root / f"{run_id}-{suffix:02d}"
        suffix += 1
    run_id = directory.name
    directory.mkdir(parents=True, exist_ok=False)
    references = _entity_references(structure)
    entity_count = len(references)
    _write_png(directory / "original.png", images.original)
    _write_png(directory / "reconstructed.png", images.reconstructed)
    _write_png(directory / "overlay.png", images.overlay)
    overview = build_overview_image(
        images,
        source_label=source_label,
        page_label=page_label,
        commit=commit,
        run_id=run_id,
        entity_count=entity_count,
        verdict=None,
    )
    overview_path = directory / "visual_acceptance_overview.png"
    _write_png(overview_path, overview)
    _write_json(
        directory / "human_review.json",
        {
            "schema_version": VISUAL_ACCEPTANCE_SCHEMA_VERSION,
            "run_id": run_id,
            "verdict": None,
            "issue_tags": [],
            "reviewed_at": None,
        },
    )
    _write_json(
        directory / "developer_details.json",
        {
            "schema_version": VISUAL_ACCEPTANCE_SCHEMA_VERSION,
            "run_id": run_id,
            "source_label": source_label,
            "page_label": page_label,
            "corpus_split": corpus_split,
            "commit": commit,
            "final_structure_id": structure.structure_id,
            "source_size_px": list(structure.source_size_px),
            "entity_count": entity_count,
            "warnings": list(structure.warnings),
            "layers": asdict(layers or VisualLayerSelection()),
            "entity_references": references,
            "image_sha256": {
                name: sha256((directory / name).read_bytes()).hexdigest()
                for name in ("original.png", "reconstructed.png", "overlay.png")
            },
        },
    )
    return (
        VisualAcceptanceRun(
            run_id=run_id,
            directory=directory,
            overview_path=overview_path,
            structure_id=structure.structure_id,
            entity_count=entity_count,
        ),
        images,
    )


def update_human_review(
    run: VisualAcceptanceRun,
    *,
    verdict: str,
    issue_tags: list[str],
    source_label: str,
    page_label: str,
    commit: str,
) -> None:
    if verdict not in {"PASS", "PARTIAL", "FAIL"}:
        raise ValueError("Human verdict must be PASS, PARTIAL, or FAIL")
    _write_json(
        run.directory / "human_review.json",
        {
            "schema_version": VISUAL_ACCEPTANCE_SCHEMA_VERSION,
            "run_id": run.run_id,
            "verdict": verdict,
            "issue_tags": sorted(set(issue_tags)),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    loaded = [
        cv2.imread(str(run.directory / name), cv2.IMREAD_COLOR)
        for name in ("original.png", "reconstructed.png", "overlay.png")
    ]
    if any(image is None for image in loaded):
        raise OSError("Visual acceptance source images are missing")
    images = VisualAcceptanceImages(loaded[0], loaded[1], loaded[2])  # type: ignore[arg-type]
    overview = build_overview_image(
        images,
        source_label=source_label,
        page_label=page_label,
        commit=commit,
        run_id=run.run_id,
        entity_count=run.entity_count,
        verdict=verdict,
    )
    _write_png(run.overview_path, overview)
