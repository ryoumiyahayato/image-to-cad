from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from .auxiliary_recognition import TextCandidate
from .final_structure import FinalStructure, build_final_structure, final_structure_from_trace_result
from .line_detect import LineSegment
from .logo_detection import LogoRegion
from .raster_trace import RasterTraceResult, TracePath
from .signature_overlay import SignatureRegion


@dataclass(frozen=True)
class StoredTrace:
    binary: np.ndarray
    paths: tuple[TracePath, ...]
    threshold: int
    foreground_pixels: int
    vertex_count: int
    warnings: tuple[str, ...]
    texts: tuple[TextCandidate, ...] = ()
    signatures: tuple[SignatureRegion, ...] = ()
    straight_lines: tuple[LineSegment, ...] = ()
    preview_binary: np.ndarray | None = None
    logos: tuple[LogoRegion, ...] = ()
    final_structure: FinalStructure | None = None


def _serialize_lines(lines: tuple[LineSegment, ...]) -> str:
    return json.dumps(
        [
            {
                "x1": line.x1,
                "y1": line.y1,
                "x2": line.x2,
                "y2": line.y2,
                "width": line.width,
                "confidence": line.confidence,
                "layer": line.layer,
                "source_ids": list(line.source_ids),
                "history": list(line.history),
                "classification_confidence": line.classification_confidence,
                "classification_reasons": list(line.classification_reasons),
            }
            for line in lines
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _deserialize_lines(value: str) -> tuple[LineSegment, ...]:
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Trace cache straight-line metadata is invalid JSON") from exc
    results: list[LineSegment] = []
    for item in payload:
        try:
            results.append(
                LineSegment(
                    x1=float(item["x1"]),
                    y1=float(item["y1"]),
                    x2=float(item["x2"]),
                    y2=float(item["y2"]),
                    width=float(item.get("width", 1.0)),
                    confidence=float(item.get("confidence", 1.0)),
                    layer=str(item.get("layer", "DETAIL")),
                    source_ids=tuple(str(value) for value in item.get("source_ids", ())),
                    history=tuple(str(value) for value in item.get("history", ())),
                    classification_confidence=float(
                        item.get("classification_confidence", 1.0)
                    ),
                    classification_reasons=tuple(
                        str(value)
                        for value in item.get("classification_reasons", ())
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(results)


def _serialize_texts(texts: tuple[TextCandidate, ...]) -> str:
    return json.dumps(
        [
            {
                "text": item.text,
                "bbox": list(item.bbox),
                "confidence": item.confidence,
                "kind": item.kind,
                "rotation_deg": item.rotation_deg,
                "quad": [list(point) for point in item.quad] if item.quad else None,
                "source": item.source,
                "approved": item.approved,
                "reviewed": item.reviewed,
                "font_family": item.font_family,
                "font_file": item.font_file,
                "font_match_score": item.font_match_score,
                "character_boxes": [list(box) for box in item.character_boxes],
                "replacement_safe": item.replacement_safe,
                "review_note": item.review_note,
            }
            for item in texts
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _deserialize_texts(value: str) -> tuple[TextCandidate, ...]:
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Trace cache OCR text metadata is invalid JSON") from exc
    results: list[TextCandidate] = []
    for item in payload:
        bbox = tuple(int(number) for number in item.get("bbox", ()))
        if len(bbox) != 4:
            continue
        raw_quad = item.get("quad")
        quad = None
        if raw_quad:
            points = tuple((float(point[0]), float(point[1])) for point in raw_quad)
            if len(points) == 4:
                quad = points
        character_boxes = tuple(
            (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
            for box in item.get("character_boxes", ())
            if len(box) == 4
        )
        results.append(
            TextCandidate(
                text=str(item.get("text", "")),
                bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                confidence=float(item.get("confidence", 0.0)),
                kind=str(item.get("kind", "text_candidate")),
                rotation_deg=float(item.get("rotation_deg", 0.0)),
                quad=quad,
                source=str(item.get("source", "cache")),
                approved=bool(item.get("approved", True)),
                reviewed=bool(item.get("reviewed", False)),
                font_family=str(item.get("font_family", "")),
                font_file=str(item.get("font_file", "")),
                font_match_score=float(item.get("font_match_score", 0.0)),
                character_boxes=character_boxes,
                replacement_safe=bool(item.get("replacement_safe", True)),
                review_note=str(item.get("review_note", "")),
            )
        )
    return tuple(results)


def _packed_binary(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    normalized = np.ascontiguousarray(binary, dtype=np.uint8)
    foreground = np.ravel(normalized < 128)
    return (
        np.packbits(foreground, bitorder="little"),
        np.asarray(normalized.shape[:2], dtype=np.int64),
    )


def _unpack_binary(packed: np.ndarray, shape: np.ndarray) -> np.ndarray:
    values = tuple(int(value) for value in np.asarray(shape).reshape(-1))
    if len(values) != 2 or values[0] <= 0 or values[1] <= 0:
        raise ValueError("Trace cache binary shape is invalid")
    pixel_count = values[0] * values[1]
    foreground = np.unpackbits(
        np.asarray(packed, dtype=np.uint8),
        bitorder="little",
        count=pixel_count,
    ).reshape(values)
    return np.where(foreground > 0, 0, 255).astype(np.uint8)


def _packed_signatures(
    signatures: tuple[SignatureRegion, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    bboxes = np.asarray([item.bbox for item in signatures], dtype=np.int32).reshape(-1, 4)
    shapes = np.asarray([item.mask.shape for item in signatures], dtype=np.int32).reshape(-1, 2)
    offsets = np.zeros(len(signatures) + 1, dtype=np.int64)
    chunks: list[np.ndarray] = []
    cursor = 0
    for index, item in enumerate(signatures):
        packed = np.packbits(
            np.ravel(np.ascontiguousarray(item.mask) > 0),
            bitorder="little",
        )
        chunks.append(packed)
        cursor += len(packed)
        offsets[index + 1] = cursor
    payload = (
        np.concatenate(chunks)
        if chunks
        else np.empty((0,), dtype=np.uint8)
    )
    return bboxes, shapes, offsets, payload


def _unpack_signatures(
    bboxes: np.ndarray,
    shapes: np.ndarray,
    offsets: np.ndarray,
    payload: np.ndarray,
) -> tuple[SignatureRegion, ...]:
    boxes = np.asarray(bboxes, dtype=np.int32).reshape(-1, 4)
    mask_shapes = np.asarray(shapes, dtype=np.int32).reshape(-1, 2)
    starts = np.asarray(offsets, dtype=np.int64).reshape(-1)
    raw = np.asarray(payload, dtype=np.uint8).reshape(-1)
    if len(mask_shapes) != len(boxes) or len(starts) != len(boxes) + 1:
        raise ValueError("Trace cache signature metadata lengths do not match")
    if not len(starts) or starts[0] != 0 or starts[-1] != len(raw):
        raise ValueError("Trace cache signature offsets are invalid")
    results: list[SignatureRegion] = []
    for index, box in enumerate(boxes):
        height, width = (int(value) for value in mask_shapes[index])
        if height <= 0 or width <= 0:
            raise ValueError("Trace cache signature shape is invalid")
        packed = raw[int(starts[index]) : int(starts[index + 1])]
        mask = np.unpackbits(
            packed,
            bitorder="little",
            count=height * width,
        ).reshape((height, width))
        results.append(
            SignatureRegion(
                bbox=tuple(int(value) for value in box),
                mask=np.where(mask > 0, 255, 0).astype(np.uint8),
            )
        )
    return tuple(results)


def _packed_logos(
    logos: tuple[LogoRegion, ...],
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    bboxes, shapes, offsets, payload = _packed_signatures(
        tuple(SignatureRegion(item.bbox, item.mask) for item in logos)
    )
    metadata = np.asarray(
        [
            (item.structural_score, item.hole_count, item.contour_count)
            for item in logos
        ],
        dtype=np.float64,
    ).reshape(-1, 3)
    return bboxes, shapes, offsets, payload, metadata


def _unpack_logos(
    bboxes: np.ndarray,
    shapes: np.ndarray,
    offsets: np.ndarray,
    payload: np.ndarray,
    metadata: np.ndarray,
) -> tuple[LogoRegion, ...]:
    regions = _unpack_signatures(bboxes, shapes, offsets, payload)
    values = np.asarray(metadata, dtype=np.float64).reshape(-1, 3)
    if len(values) != len(regions):
        raise ValueError("Trace cache logo metadata lengths do not match")
    return tuple(
        LogoRegion(
            bbox=region.bbox,
            mask=region.mask,
            structural_score=float(values[index, 0]),
            hole_count=int(round(values[index, 1])),
            contour_count=int(round(values[index, 2])),
        )
        for index, region in enumerate(regions)
    )


def save_trace_cache(path: str | Path, result: RasterTraceResult) -> Path:
    """Atomically store a page using packed pixels and uncompressed arrays.

    The old cache used zlib on an 80-megapixel byte image, which spent substantial
    CPU time after every page. A one-bit foreground mask is already compact, so
    writing it with ``np.savez`` is much faster while remaining lossless.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    structure = final_structure_from_trace_result(result)
    path_count = len(structure.contours)
    offsets = np.zeros(path_count + 1, dtype=np.int64)
    parent = np.full(path_count, -1, dtype=np.int32)
    depth = np.zeros(path_count, dtype=np.int32)
    root = np.zeros(path_count, dtype=np.int32)
    point_arrays: list[np.ndarray] = []
    cursor = 0
    for index, trace_path in enumerate(structure.contours):
        points = np.asarray(trace_path.points, dtype=np.float32).reshape(-1, 2)
        point_arrays.append(points)
        cursor += len(points)
        offsets[index + 1] = cursor
        parent[index] = -1 if trace_path.parent is None else int(trace_path.parent)
        depth[index] = int(trace_path.depth)
        root[index] = int(trace_path.root)
    all_points = (
        np.concatenate(point_arrays, axis=0)
        if point_arrays
        else np.empty((0, 2), dtype=np.float32)
    )
    warnings = np.asarray(structure.warnings, dtype=np.str_)
    texts_json = np.asarray([_serialize_texts(structure.texts)], dtype=np.str_)
    lines_json = np.asarray(
        [_serialize_lines(structure.straight_lines)],
        dtype=np.str_,
    )
    binary_packed, binary_shape = _packed_binary(structure.contour_binary)
    preview_source = (
        structure.preview_binary
        if structure.preview_binary is not None
        else structure.contour_binary
    )
    preview_packed, preview_shape = _packed_binary(preview_source)
    signature_bboxes, signature_shapes, signature_offsets, signature_packed = (
        _packed_signatures(structure.signatures)
    )
    (
        logo_bboxes,
        logo_shapes,
        logo_offsets,
        logo_packed,
        logo_metadata,
    ) = _packed_logos(structure.logos)
    structure_id = np.asarray([structure.structure_id], dtype=np.str_)
    provenance_json = np.asarray(
        [
            json.dumps(
                dict(structure.provenance),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        ],
        dtype=np.str_,
    )

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            np.savez(
                handle,
                cache_version=np.asarray([7], dtype=np.int32),
                binary_packed=binary_packed,
                binary_shape=binary_shape,
                preview_present=np.asarray(
                    [structure.preview_binary is not None],
                    dtype=np.uint8,
                ),
                preview_packed=preview_packed,
                preview_shape=preview_shape,
                points=all_points,
                offsets=offsets,
                parent=parent,
                depth=depth,
                root=root,
                threshold=np.asarray([structure.threshold], dtype=np.int32),
                foreground_pixels=np.asarray(
                    [np.count_nonzero(structure.contour_binary == 0)],
                    dtype=np.int64,
                ),
                vertex_count=np.asarray(
                    [sum(len(path.points) for path in structure.contours)],
                    dtype=np.int64,
                ),
                warnings=warnings,
                structure_id=structure_id,
                provenance_json=provenance_json,
                texts_json=texts_json,
                lines_json=lines_json,
                signature_bboxes=signature_bboxes,
                signature_shapes=signature_shapes,
                signature_offsets=signature_offsets,
                signature_packed=signature_packed,
                logo_bboxes=logo_bboxes,
                logo_shapes=logo_shapes,
                logo_offsets=logo_offsets,
                logo_packed=logo_packed,
                logo_metadata=logo_metadata,
            )
        temporary_path.replace(target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return target


def load_trace_cache(path: str | Path) -> StoredTrace:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    with np.load(source, allow_pickle=False) as archive:
        required = {
            "points",
            "offsets",
            "parent",
            "depth",
            "root",
            "threshold",
            "foreground_pixels",
            "vertex_count",
            "warnings",
        }
        missing = required.difference(archive.files)
        if missing:
            raise ValueError(f"Trace cache is missing fields: {sorted(missing)}")
        if "binary_packed" in archive.files and "binary_shape" in archive.files:
            binary = _unpack_binary(
                archive["binary_packed"],
                archive["binary_shape"],
            )
        elif "binary" in archive.files:
            binary = np.ascontiguousarray(archive["binary"], dtype=np.uint8)
        else:
            raise ValueError("Trace cache is missing binary image data")
        preview_present = (
            bool(np.asarray(archive["preview_present"]).reshape(-1)[0])
            if "preview_present" in archive.files
            else {"preview_packed", "preview_shape"}.issubset(archive.files)
        )
        preview_binary = (
            _unpack_binary(
                archive["preview_packed"],
                archive["preview_shape"],
            )
            if (
                preview_present
                and {"preview_packed", "preview_shape"}.issubset(archive.files)
            )
            else None
        )
        points = np.asarray(archive["points"], dtype=np.float32)
        offsets = np.asarray(archive["offsets"], dtype=np.int64)
        parent = np.asarray(archive["parent"], dtype=np.int32)
        depth = np.asarray(archive["depth"], dtype=np.int32)
        root = np.asarray(archive["root"], dtype=np.int32)
        threshold = int(np.asarray(archive["threshold"]).reshape(-1)[0])
        foreground_pixels = int(
            np.asarray(archive["foreground_pixels"]).reshape(-1)[0]
        )
        vertex_count = int(np.asarray(archive["vertex_count"]).reshape(-1)[0])
        warnings = tuple(str(value) for value in archive["warnings"].tolist())
        texts = (
            _deserialize_texts(str(np.asarray(archive["texts_json"]).reshape(-1)[0]))
            if "texts_json" in archive.files
            else ()
        )
        straight_lines = (
            _deserialize_lines(str(np.asarray(archive["lines_json"]).reshape(-1)[0]))
            if "lines_json" in archive.files
            else ()
        )
        signatures = (
            _unpack_signatures(
                archive["signature_bboxes"],
                archive["signature_shapes"],
                archive["signature_offsets"],
                archive["signature_packed"],
            )
            if {
                "signature_bboxes",
                "signature_shapes",
                "signature_offsets",
                "signature_packed",
            }.issubset(archive.files)
            else ()
        )
        logos = (
            _unpack_logos(
                archive["logo_bboxes"],
                archive["logo_shapes"],
                archive["logo_offsets"],
                archive["logo_packed"],
                archive["logo_metadata"],
            )
            if {
                "logo_bboxes",
                "logo_shapes",
                "logo_offsets",
                "logo_packed",
                "logo_metadata",
            }.issubset(archive.files)
            else ()
        )
        stored_structure_id = (
            str(np.asarray(archive["structure_id"]).reshape(-1)[0])
            if "structure_id" in archive.files
            else None
        )
        provenance = {}
        if "provenance_json" in archive.files:
            try:
                value = json.loads(
                    str(np.asarray(archive["provenance_json"]).reshape(-1)[0])
                )
                if isinstance(value, dict):
                    provenance = value
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Trace cache provenance metadata is invalid JSON"
                ) from exc

    path_count = len(parent)
    if offsets.shape != (path_count + 1,):
        raise ValueError("Trace cache offsets do not match path metadata")
    if not (len(depth) == len(root) == path_count):
        raise ValueError("Trace cache path metadata lengths do not match")
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("Trace cache points must have shape (N, 2)")
    if offsets[0] != 0 or offsets[-1] != len(points):
        raise ValueError("Trace cache point offsets are invalid")

    paths: list[TracePath] = []
    for index in range(path_count):
        start = int(offsets[index])
        end = int(offsets[index + 1])
        path_points = tuple(
            (float(point[0]), float(point[1])) for point in points[start:end]
        )
        parent_value = int(parent[index])
        if parent_value >= index:
            raise ValueError("Trace cache parent must precede its child")
        paths.append(
            TracePath(
                points=path_points,
                parent=parent_value if parent_value >= 0 else None,
                depth=int(depth[index]),
                root=int(root[index]),
            )
        )
    if int(sum(len(path.points) for path in paths)) != vertex_count:
        raise ValueError("Trace cache vertex count does not match stored paths")
    final_structure = build_final_structure(
        source_size_px=(binary.shape[1], binary.shape[0]),
        contour_binary=binary,
        contours=tuple(paths),
        straight_lines=straight_lines,
        texts=texts,
        logos=logos,
        signatures=signatures,
        preview_binary=preview_binary,
        threshold=threshold,
        warnings=warnings,
        provenance=provenance,
    )
    if (
        stored_structure_id is not None
        and stored_structure_id != final_structure.structure_id
    ):
        raise ValueError("Trace cache final structure fingerprint does not match")
    return StoredTrace(
        binary=binary,
        paths=tuple(paths),
        threshold=threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=warnings,
        texts=texts,
        signatures=signatures,
        straight_lines=straight_lines,
        preview_binary=preview_binary,
        logos=logos,
        final_structure=final_structure,
    )
