from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

import numpy as np

if TYPE_CHECKING:
    from .auxiliary_recognition import TextCandidate
    from .line_detect import LineSegment
    from .logo_detection import LogoRegion
    from .raster_trace import RasterTraceResult, TracePath
    from .signature_overlay import SignatureRegion


FINAL_STRUCTURE_SCHEMA_VERSION = 2


def _immutable_mask(
    value: np.ndarray | None,
    *,
    shape: tuple[int, int] | None = None,
) -> np.ndarray | None:
    if value is None:
        return None
    normalized = np.ascontiguousarray(value, dtype=np.uint8).copy()
    if normalized.ndim != 2 or normalized.size == 0:
        raise ValueError("Final structure masks must be non-empty 8-bit 2D images")
    if shape is not None and normalized.shape != shape:
        raise ValueError("Final structure masks must use one source coordinate system")
    normalized.setflags(write=False)
    return normalized


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _mask_sha256(value: np.ndarray | None) -> str | None:
    if value is None:
        return None
    return sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _path_payload(path: Any) -> dict[str, object]:
    return {
        "points": [[_rounded(x), _rounded(y)] for x, y in path.points],
        "parent": path.parent,
        "depth": int(path.depth),
        "root": int(path.root),
    }


def _line_payload(line: Any) -> dict[str, object]:
    return {
        "start": [_rounded(line.x1), _rounded(line.y1)],
        "end": [_rounded(line.x2), _rounded(line.y2)],
        "width": _rounded(line.width),
        "layer": str(line.layer),
    }


def _text_payload(text: Any) -> dict[str, object]:
    return {
        "text": str(text.text),
        "bbox": [int(value) for value in text.bbox],
        "confidence": _rounded(text.confidence),
        "kind": str(text.kind),
        "approved": bool(text.approved),
        "reviewed": bool(text.reviewed),
        "replacement_safe": bool(text.replacement_safe),
    }


def _masked_object_payload(item: Any) -> dict[str, object]:
    mask = np.ascontiguousarray(item.mask, dtype=np.uint8)
    return {
        "bbox": [int(value) for value in item.bbox],
        "mask_sha256": sha256(mask.tobytes()).hexdigest(),
        "foreground_pixels": int(np.count_nonzero(mask)),
    }


def _immutable_masked_object(item: Any) -> Any:
    x, y, width, height = (int(value) for value in item.bbox)
    del x, y
    mask = _immutable_mask(item.mask, shape=(height, width))
    return replace(item, mask=mask)


@dataclass(frozen=True)
class FinalStructure:
    """The one immutable page model consumed by preview, cache and DXF export."""

    source_size_px: tuple[int, int]
    contour_binary: np.ndarray
    contours: tuple[TracePath, ...]
    straight_lines: tuple[LineSegment, ...] = ()
    texts: tuple[TextCandidate, ...] = ()
    logos: tuple[LogoRegion, ...] = ()
    signatures: tuple[SignatureRegion, ...] = ()
    editable_text_source_mask: np.ndarray | None = None
    source_text_outline_mask: np.ndarray | None = None
    uncertain_text_outline_mask: np.ndarray | None = None
    preview_binary: np.ndarray | None = None
    threshold: int = 128
    warnings: tuple[str, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=dict)
    observations: tuple[Mapping[str, object], ...] = ()

    def assert_valid(self) -> None:
        width, height = self.source_size_px
        if width <= 0 or height <= 0:
            raise AssertionError("Final structure source size must be positive")
        expected_shape = (height, width)
        if self.contour_binary.shape != expected_shape:
            raise AssertionError("Contour binary does not match source coordinates")
        if self.preview_binary is not None and self.preview_binary.shape != expected_shape:
            raise AssertionError("Preview binary does not match source coordinates")
        for mask in (
            self.editable_text_source_mask,
            self.source_text_outline_mask,
            self.uncertain_text_outline_mask,
        ):
            if mask is not None and mask.shape != expected_shape:
                raise AssertionError(
                    "Text semantic mask does not match source coordinates"
                )
        if (
            self.source_text_outline_mask is not None
            and self.uncertain_text_outline_mask is not None
            and np.any(
                (self.source_text_outline_mask > 0)
                & (self.uncertain_text_outline_mask > 0)
            )
        ):
            raise AssertionError(
                "Source and uncertain text outlines must be disjoint"
            )
        if (
            self.source_text_outline_mask is not None
            and self.editable_text_source_mask is not None
            and np.any(
                (self.source_text_outline_mask > 0)
                & (self.editable_text_source_mask == 0)
            )
        ):
            raise AssertionError(
                "Source outline backup must belong to editable text"
            )
        for collection in (self.logos, self.signatures):
            for item in collection:
                x, y, item_width, item_height = item.bbox
                if (
                    item_width <= 0
                    or item_height <= 0
                    or x < 0
                    or y < 0
                    or x + item_width > width
                    or y + item_height > height
                    or item.mask.shape != (item_height, item_width)
                ):
                    raise AssertionError("Masked object lies outside source coordinates")

    @property
    def structure_id(self) -> str:
        payload = {
            "schema_version": FINAL_STRUCTURE_SCHEMA_VERSION,
            "source_size_px": list(self.source_size_px),
            "contour_sha256": sha256(
                np.ascontiguousarray(self.contour_binary).tobytes()
            ).hexdigest(),
            "preview_sha256": (
                None
                if self.preview_binary is None
                else sha256(
                    np.ascontiguousarray(self.preview_binary).tobytes()
                ).hexdigest()
            ),
            "editable_text_source_sha256": _mask_sha256(
                self.editable_text_source_mask
            ),
            "source_text_outline_sha256": _mask_sha256(
                self.source_text_outline_mask
            ),
            "uncertain_text_outline_sha256": _mask_sha256(
                self.uncertain_text_outline_mask
            ),
            "contours": [_path_payload(path) for path in self.contours],
            "straight_lines": [
                _line_payload(line)
                for line in sorted(
                    self.straight_lines,
                    key=lambda item: (
                        _rounded(item.y1),
                        _rounded(item.x1),
                        _rounded(item.y2),
                        _rounded(item.x2),
                    ),
                )
            ],
            "texts": [
                _text_payload(text)
                for text in sorted(
                    self.texts,
                    key=lambda item: (item.bbox[1], item.bbox[0], item.text),
                )
            ],
            "logos": [
                _masked_object_payload(item)
                for item in sorted(self.logos, key=lambda item: item.bbox)
            ],
            "signatures": [
                _masked_object_payload(item)
                for item in sorted(self.signatures, key=lambda item: item.bbox)
            ],
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(serialized).hexdigest()


def build_final_structure(
    *,
    source_size_px: tuple[int, int],
    contour_binary: np.ndarray,
    contours: tuple[TracePath, ...],
    straight_lines: tuple[LineSegment, ...] = (),
    texts: tuple[TextCandidate, ...] = (),
    logos: tuple[LogoRegion, ...] = (),
    signatures: tuple[SignatureRegion, ...] = (),
    editable_text_source_mask: np.ndarray | None = None,
    source_text_outline_mask: np.ndarray | None = None,
    uncertain_text_outline_mask: np.ndarray | None = None,
    preview_binary: np.ndarray | None = None,
    threshold: int = 128,
    warnings: tuple[str, ...] = (),
    provenance: Mapping[str, object] | None = None,
    observations: tuple[Mapping[str, object], ...] = (),
) -> FinalStructure:
    width, height = (int(source_size_px[0]), int(source_size_px[1]))
    shape = (height, width)
    structure = FinalStructure(
        source_size_px=(width, height),
        contour_binary=_immutable_mask(contour_binary, shape=shape),
        contours=tuple(contours),
        straight_lines=tuple(straight_lines),
        texts=tuple(texts),
        logos=tuple(_immutable_masked_object(item) for item in logos),
        signatures=tuple(
            _immutable_masked_object(item) for item in signatures
        ),
        editable_text_source_mask=_immutable_mask(
            editable_text_source_mask,
            shape=shape,
        ),
        source_text_outline_mask=_immutable_mask(
            source_text_outline_mask,
            shape=shape,
        ),
        uncertain_text_outline_mask=_immutable_mask(
            uncertain_text_outline_mask,
            shape=shape,
        ),
        preview_binary=_immutable_mask(preview_binary, shape=shape),
        threshold=int(threshold),
        warnings=tuple(warnings),
        provenance=MappingProxyType(dict(provenance or {})),
        observations=tuple(
            MappingProxyType(dict(item))
            for item in observations
        ),
    )
    structure.assert_valid()
    return structure


def final_structure_from_trace_result(
    result: RasterTraceResult,
) -> FinalStructure:
    existing = getattr(result, "final_structure", None)
    if existing is not None:
        existing.assert_valid()
        return existing
    height, width = result.binary.shape[:2]
    return build_final_structure(
        source_size_px=(width, height),
        contour_binary=result.binary,
        contours=tuple(result.paths),
        straight_lines=tuple(result.straight_lines),
        texts=tuple(result.texts),
        logos=tuple(getattr(result, "logos", ())),
        signatures=tuple(result.signatures),
        preview_binary=result.preview_binary,
        threshold=int(result.threshold),
        warnings=tuple(result.warnings),
        provenance={"adapter": "RasterTraceResult"},
    )
