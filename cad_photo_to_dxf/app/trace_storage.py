from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from .auxiliary_recognition import TextCandidate
from .raster_trace import RasterTraceResult, TracePath


@dataclass(frozen=True)
class StoredTrace:
    binary: np.ndarray
    paths: tuple[TracePath, ...]
    threshold: int
    foreground_pixels: int
    vertex_count: int
    warnings: tuple[str, ...]
    texts: tuple[TextCandidate, ...] = ()


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
        bbox = tuple(int(value) for value in item.get("bbox", ()))
        if len(bbox) != 4:
            continue
        raw_quad = item.get("quad")
        quad = None
        if raw_quad:
            points = tuple((float(point[0]), float(point[1])) for point in raw_quad)
            if len(points) == 4:
                quad = points
        results.append(
            TextCandidate(
                text=str(item.get("text", "")),
                bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                confidence=float(item.get("confidence", 0.0)),
                kind=str(item.get("kind", "text_candidate")),
                rotation_deg=float(item.get("rotation_deg", 0.0)),
                quad=quad,
                source=str(item.get("source", "cache")),
            )
        )
    return tuple(results)


def save_trace_cache(path: str | Path, result: RasterTraceResult) -> Path:
    """Atomically store one full-resolution trace page in compressed arrays."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    path_count = len(result.paths)
    offsets = np.zeros(path_count + 1, dtype=np.int64)
    parent = np.full(path_count, -1, dtype=np.int32)
    depth = np.zeros(path_count, dtype=np.int32)
    root = np.zeros(path_count, dtype=np.int32)
    point_arrays: list[np.ndarray] = []
    cursor = 0
    for index, trace_path in enumerate(result.paths):
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
    warnings = np.asarray(result.warnings, dtype=np.str_)
    texts_json = np.asarray([_serialize_texts(tuple(result.texts))], dtype=np.str_)

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            np.savez_compressed(
                handle,
                binary=np.ascontiguousarray(result.binary, dtype=np.uint8),
                points=all_points,
                offsets=offsets,
                parent=parent,
                depth=depth,
                root=root,
                threshold=np.asarray([result.threshold], dtype=np.int32),
                foreground_pixels=np.asarray(
                    [result.foreground_pixels], dtype=np.int64
                ),
                vertex_count=np.asarray([result.vertex_count], dtype=np.int64),
                warnings=warnings,
                texts_json=texts_json,
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
            "binary",
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
        binary = np.ascontiguousarray(archive["binary"], dtype=np.uint8)
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
    return StoredTrace(
        binary=binary,
        paths=tuple(paths),
        threshold=threshold,
        foreground_pixels=foreground_pixels,
        vertex_count=vertex_count,
        warnings=warnings,
        texts=texts,
    )
