from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, cast

import numpy as np
from app.core.arc_types import ArcSegment
from app.core.native_fill import NativeFill

if TYPE_CHECKING:
    from app.ocr.auxiliary_recognition import TextCandidate
    from app.geometry.line_detect import LineSegment
    from app.ocr.logo_detection import LogoRegion
    from app.core.trace_types import TracePath
    from app.ocr.signature_overlay import SignatureRegion


FINAL_STRUCTURE_SCHEMA_VERSION = 4


def _freeze_metadata(
    value: object,
    *,
    active_ids: set[int] | None = None,
) -> object:
    """Detach and recursively freeze the supported JSON metadata domain."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Final structure metadata numbers must be finite")
        return value

    active = active_ids if active_ids is not None else set()
    identity = id(value)
    if identity in active:
        raise ValueError("Final structure metadata must not contain cycles")
    active.add(identity)
    try:
        if isinstance(value, MappingABC):
            frozen: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("Final structure metadata keys must be strings")
                frozen[key] = _freeze_metadata(item, active_ids=active)
            return MappingProxyType(frozen)
        if isinstance(value, (list, tuple)):
            return tuple(_freeze_metadata(item, active_ids=active) for item in value)
    finally:
        active.remove(identity)
    raise TypeError(
        "Final structure metadata supports only JSON objects, arrays, and scalars"
    )


def metadata_to_jsonable(value: object) -> object:
    """Return a detached JSON-compatible copy of frozen structure metadata."""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, MappingABC):
        return {str(key): metadata_to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [metadata_to_jsonable(item) for item in value]
    raise TypeError(f"Unsupported final structure metadata value: {type(value)!r}")


def _freeze_metadata_mapping(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    frozen = _freeze_metadata(value)
    if not isinstance(frozen, MappingABC):
        raise TypeError("Final structure metadata must be an object")
    return cast(Mapping[str, object], frozen)


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


def _exact_geometry_number(value: float) -> float | str:
    """Serialize binary64 geometry exactly without churning legacy IDs.

    Values already represented exactly by the historic six-decimal payload keep
    that payload, so ordinary existing structures retain their identity.  A
    value carrying additional binary64 geometry precision uses ``float.hex``;
    unlike display formatting this is locale independent and lossless.  Signed
    zero is normalized because the editable geometry model treats both zeros as
    the same point.
    """

    number = float(value)
    if not isfinite(number):
        raise ValueError("Final structure geometry numbers must be finite")
    if number == 0.0:
        return 0.0
    legacy = round(number, 6)
    if number == legacy:
        return legacy
    return number.hex()


def _mask_sha256(value: np.ndarray | None) -> str | None:
    if value is None:
        return None
    return sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _path_payload(path: Any) -> dict[str, object]:
    return {
        "points": [
            [_exact_geometry_number(x), _exact_geometry_number(y)]
            for x, y in path.points
        ],
        "parent": path.parent,
        "depth": int(path.depth),
        "root": int(path.root),
    }


def _line_payload(line: Any) -> dict[str, object]:
    return {
        "start": [
            _exact_geometry_number(line.x1),
            _exact_geometry_number(line.y1),
        ],
        "end": [
            _exact_geometry_number(line.x2),
            _exact_geometry_number(line.y2),
        ],
        "width": _exact_geometry_number(line.width),
        "layer": str(line.layer),
    }


def _text_payload(text: Any) -> dict[str, object]:
    # These fields either control native TEXT eligibility/placement/font metrics
    # or are written to the emitted entity. The finite/non-finite state of
    # rotation_deg is an eligibility gate, but its numeric value, character_boxes
    # and review_note are diagnostic-only in the current exporter.
    return {
        "text": str(text.text),
        "bbox": [int(value) for value in text.bbox],
        "quad": (
            None
            if text.quad is None
            else [
                [
                    _exact_geometry_number(point[0]),
                    _exact_geometry_number(point[1]),
                ]
                for point in text.quad
            ]
        ),
        "confidence": _rounded(text.confidence),
        "kind": str(text.kind),
        "source": str(text.source),
        "approved": bool(text.approved),
        "reviewed": bool(text.reviewed),
        "font_family": str(text.font_family),
        "font_file": str(text.font_file),
        "font_match_score": _rounded(text.font_match_score),
        "rotation_valid": bool(isfinite(float(text.rotation_deg))),
        "replacement_safe": bool(text.replacement_safe),
        **(
            {
                "display_quad": [
                    [_exact_geometry_number(v) for v in p] for p in text.display_quad
                ]
            }
            if text.display_quad is not None
            else {}
        ),
    }


def _masked_object_payload(item: Any) -> dict[str, object]:
    mask = np.ascontiguousarray(item.mask, dtype=np.uint8)
    payload = {
        "bbox": [int(value) for value in item.bbox],
        "mask_sha256": sha256(mask.tobytes()).hexdigest(),
        "foreground_pixels": int(np.count_nonzero(mask)),
    }
    if getattr(item, "visual_kind", "") == "engineering_graphic":
        payload["object_class"] = "GRAPHIC"
    return payload


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
    arcs: tuple[ArcSegment, ...] = ()
    native_fills: tuple[NativeFill, ...] = ()

    def __post_init__(self) -> None:
        if len(self.source_size_px) != 2 or any(
            isinstance(x, (bool, np.bool_)) for x in self.source_size_px
        ):
            raise ValueError("Final structure size must contain two dimensions")
        width, height = (int(x) for x in self.source_size_px)
        object.__setattr__(self, "source_size_px", (width, height))
        for name in (
            "contour_binary",
            "preview_binary",
            "editable_text_source_mask",
            "source_text_outline_mask",
            "uncertain_text_outline_mask",
        ):
            object.__setattr__(
                self, name, _immutable_mask(getattr(self, name), shape=(height, width))
            )
        for name in (
            "contours",
            "straight_lines",
            "texts",
            "warnings",
            "arcs",
            "native_fills",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("logos", "signatures"):
            object.__setattr__(
                self,
                name,
                tuple(_immutable_masked_object(x) for x in getattr(self, name)),
            )
        object.__setattr__(
            self, "provenance", _freeze_metadata_mapping(self.provenance)
        )
        object.__setattr__(
            self,
            "observations",
            tuple(_freeze_metadata_mapping(x) for x in self.observations),
        )
        self.assert_valid()

    def assert_valid(self) -> None:
        for fill in self.native_fills:
            if not isinstance(fill, NativeFill):
                raise TypeError(
                    "Final native fills must be validated NativeFill objects"
                )
            NativeFill.from_payload(fill.payload())
            if any(
                not (
                    0 <= x <= self.source_size_px[0]
                    and 0 <= y <= self.source_size_px[1]
                )
                for x, y in fill.points
            ):
                raise ValueError("Native fill outside source canvas")
        if len({f.object_id for f in self.native_fills}) != len(self.native_fills):
            raise ValueError("Duplicate native fill source")
        if any(not isinstance(arc, ArcSegment) for arc in self.arcs):
            raise TypeError("Final ARC members must be validated ArcSegments")
        for arc in self.arcs:
            ArcSegment.from_payload(arc.payload())
        if len({arc.object_id for arc in self.arcs}) != len(self.arcs):
            raise ValueError("Duplicate final ARC identity")
        replaced = [ref for arc in self.arcs for ref in arc.replaced_members]
        if len(set(replaced)) != len(replaced):
            raise ValueError("Multiple ARCs cannot own the same replaced member")
        if self.arcs and "draftsman_output_v1" in self.provenance:
            raise ValueError(
                "ARC members are not supported by the frozen draftsman-output-v1 binding"
            )
        width, height = self.source_size_px
        if width <= 0 or height <= 0:
            raise AssertionError("Final structure source size must be positive")
        expected_shape = (height, width)
        if self.contour_binary.shape != expected_shape:
            raise AssertionError("Contour binary does not match source coordinates")
        if (
            self.preview_binary is not None
            and self.preview_binary.shape != expected_shape
        ):
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
            raise AssertionError("Source and uncertain text outlines must be disjoint")
        if (
            self.source_text_outline_mask is not None
            and self.editable_text_source_mask is not None
            and np.any(
                (self.source_text_outline_mask > 0)
                & (self.editable_text_source_mask == 0)
            )
        ):
            raise AssertionError("Source outline backup must belong to editable text")
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
                    raise AssertionError(
                        "Masked object lies outside source coordinates"
                    )
        for path in self.contours:
            for point in path.points:
                _exact_geometry_number(point[0])
                _exact_geometry_number(point[1])
        if self.provenance.get("text_rule_contours"):
            actual = {
                tuple(path.points) for path in self.contours if path.depth % 2 == 0
            }
            for points in self.provenance["text_rule_contours"]:
                if tuple(tuple(p) for p in points) not in actual:
                    raise ValueError(
                        "Retained text rule must bind a complete final contour"
                    )
        if self.provenance.get("stroke_presentation", {}).get(
            "closed_scan_curve_records"
        ):
            from app.geometry.scan_curve_retention import validate_closed_curve_records

            validate_closed_curve_records(self)
        for text in self.texts:
            if text.display_quad is not None:
                if len(text.display_quad) != 4 or any(
                    len(p) != 2 for p in text.display_quad
                ):
                    raise ValueError("Display quad must contain four points")
                for point in text.display_quad:
                    for value in point:
                        _exact_geometry_number(value)
            if text.quad is None:
                continue
            for point in text.quad:
                _exact_geometry_number(point[0])
                _exact_geometry_number(point[1])

    @property
    def source_structure_id(self) -> str:
        """Existing source context, excluding optional display-only results."""
        if not any(t.display_quad is not None for t in self.texts):
            return self.structure_id
        return replace(
            self, texts=tuple(replace(t, display_quad=None) for t in self.texts)
        ).structure_id

    @property
    def structure_id(self) -> str:
        """Fingerprint observable structure/output, not run provenance."""
        return self.identity_for_schema(FINAL_STRUCTURE_SCHEMA_VERSION)

    def identity_for_schema(self, schema_version: int) -> str:
        """Existing cache integrity check, including legacy no-ARC schema 3."""
        if schema_version not in (3, FINAL_STRUCTURE_SCHEMA_VERSION):
            raise ValueError("Unsupported final structure identity schema")
        if schema_version == 3 and self.arcs:
            raise ValueError("Legacy structure identity cannot contain ARC")

        payload = {
            "schema_version": schema_version,
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
            "editable_text_source_sha256": _mask_sha256(self.editable_text_source_mask),
            "source_text_outline_sha256": _mask_sha256(self.source_text_outline_mask),
            "uncertain_text_outline_sha256": _mask_sha256(
                self.uncertain_text_outline_mask
            ),
            "contours": [_path_payload(path) for path in self.contours],
            "straight_lines": [
                _line_payload(line)
                for line in sorted(
                    self.straight_lines,
                    key=lambda item: (
                        float(item.y1),
                        float(item.x1),
                        float(item.y2),
                        float(item.x2),
                        float(item.width),
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
        if schema_version >= 4:
            payload["arcs"] = [
                arc.payload() for arc in sorted(self.arcs, key=lambda a: a.object_id)
            ]
        if self.native_fills:
            if schema_version < 4:
                raise ValueError("Legacy identity cannot contain native fills")
            payload["native_fills_v1"] = [f.payload() for f in self.native_fills]
        if self.provenance.get("native_source_group_replacements_v1"):
            payload["native_source_group_replacements_v1"] = metadata_to_jsonable(
                self.provenance["native_source_group_replacements_v1"]
            )
        if self.provenance.get("engineering_enclosures"):
            payload["engineering_enclosures"] = metadata_to_jsonable(
                self.provenance["engineering_enclosures"]
            )
        if self.provenance.get("stroke_presentation"):
            payload["stroke_presentation"] = metadata_to_jsonable(
                self.provenance["stroke_presentation"]
            )
        if self.provenance.get("text_rule_contours"):
            payload["text_rule_contours"] = metadata_to_jsonable(
                self.provenance["text_rule_contours"]
            )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(serialized).hexdigest()
