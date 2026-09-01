"""Minimal backend-neutral editable CAD IR and table-rule assembly."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Sequence

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_logical import LogicalDrawingManifest, LogicalTableRule


DRAFTSMAN_CAD_IR_VERSION = "draftsman-editable-cad-ir-v1"
DRAFTSMAN_FINAL_ASSEMBLY_VERSION = "draftsman-final-entity-assembly-v1"
DRAFTSMAN_VS1_QUALITY_VERSION = "draftsman-vs1-quality-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError("CAD IR points require two coordinates")
    return _number(value[0]), _number(value[1])


@dataclass(frozen=True)
class EditableCadLine:
    stable_entity_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    layer_style_ref: str
    logical_entity_id: str
    provenance_ref: str
    schema_version: str = DRAFTSMAN_CAD_IR_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _point(self.start))
        object.__setattr__(self, "end", _point(self.end))
        if self.end < self.start:
            raise ValueError("CAD IR line endpoints must be canonical")
        if self.length <= 0.0:
            raise ValueError("CAD IR line must have positive length")
        expected = semantic_id(
            "editable-cad-line",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_entity_id != expected:
            raise ValueError("stable_entity_id does not match CAD IR semantics")

    @property
    def length(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @classmethod
    def from_logical_table_rule(
        cls,
        rule: LogicalTableRule,
        *,
        layer_style_ref: str = "TABLE_RULE",
    ) -> EditableCadLine:
        identity = {
            "start": list(rule.start),
            "end": list(rule.end),
            "layer_style_ref": layer_style_ref,
            "logical_entity_id": rule.logical_entity_id,
            "provenance_ref": rule.provenance_id,
        }
        return cls(
            stable_entity_id=semantic_id(
                "editable-cad-line",
                DRAFTSMAN_CAD_IR_VERSION,
                identity,
            ),
            start=rule.start,
            end=rule.end,
            layer_style_ref=layer_style_ref,
            logical_entity_id=rule.logical_entity_id,
            provenance_ref=rule.provenance_id,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "start": list(self.start),
            "end": list(self.end),
            "layer_style_ref": self.layer_style_ref,
            "logical_entity_id": self.logical_entity_id,
            "provenance_ref": self.provenance_ref,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_entity_id": self.stable_entity_id,
            "entity_kind": "LINE",
            **self.identity_payload(),
            "length": _number(self.length),
        }


@dataclass(frozen=True)
class EditableCadIrManifest:
    source_document_id: str
    source_page: int
    coordinate_space: str
    logical_manifest_id: str
    lines: tuple[EditableCadLine, ...]
    assembly_version: str = DRAFTSMAN_FINAL_ASSEMBLY_VERSION
    schema_version: str = DRAFTSMAN_CAD_IR_VERSION

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.lines, key=lambda item: item.stable_entity_id))
        if self.lines != ordered:
            raise ValueError("CAD IR entities must use canonical ID order")
        if len({item.stable_entity_id for item in self.lines}) != len(self.lines):
            raise ValueError("CAD IR entity IDs must be unique")
        logical_ids = [item.logical_entity_id for item in self.lines]
        if len(set(logical_ids)) != len(logical_ids):
            raise ValueError("Final assembly must emit one line per logical rule")

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "editable-cad-ir-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": int(self.source_page),
                "coordinate_space": self.coordinate_space,
                "logical_manifest_id": self.logical_manifest_id,
                "assembly_version": self.assembly_version,
                "entity_ids": [item.stable_entity_id for item in self.lines],
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "coordinate_space": self.coordinate_space,
            "logical_manifest_id": self.logical_manifest_id,
            "assembly_version": self.assembly_version,
            "line_count": len(self.lines),
            "lines": [item.to_dict() for item in self.lines],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def assemble_editable_cad_ir(
    logical: LogicalDrawingManifest,
) -> EditableCadIrManifest:
    """Assemble exactly one canonical editable LINE per logical table rule."""

    lines = tuple(
        sorted(
            (
                EditableCadLine.from_logical_table_rule(rule)
                for rule in logical.table_rules
            ),
            key=lambda item: item.stable_entity_id,
        )
    )
    return EditableCadIrManifest(
        source_document_id=logical.source_document_id,
        source_page=logical.source_page,
        coordinate_space="normalized-page-point",
        logical_manifest_id=logical.manifest_id,
        lines=lines,
    )


@dataclass(frozen=True)
class Vs1QualityMetrics:
    logical_entity_count: int
    cad_ir_line_count: int
    final_entities_per_logical_rule: float
    unnecessary_fragments: int
    unsupported_geometry: int
    missing_logical_entities: int
    extra_logical_entities: int
    schema_version: str = DRAFTSMAN_VS1_QUALITY_VERSION

    @property
    def passed(self) -> bool:
        return (
            self.logical_entity_count == self.cad_ir_line_count
            and self.final_entities_per_logical_rule == 1.0
            and self.unnecessary_fragments == 0
            and self.unsupported_geometry == 0
            and self.missing_logical_entities == 0
            and self.extra_logical_entities == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_entity_count": self.logical_entity_count,
            "cad_ir_line_count": self.cad_ir_line_count,
            "final_entities_per_logical_rule": self.final_entities_per_logical_rule,
            "unnecessary_fragments": self.unnecessary_fragments,
            "unsupported_geometry": self.unsupported_geometry,
            "missing_logical_entities": self.missing_logical_entities,
            "extra_logical_entities": self.extra_logical_entities,
            "passed": self.passed,
        }


def audit_vs1_cad_ir(
    logical: LogicalDrawingManifest,
    cad_ir: EditableCadIrManifest,
    *,
    expected_logical_entity_count: int,
    tolerance: float = 1e-6,
) -> Vs1QualityMetrics:
    logical_by_id = {item.logical_entity_id: item for item in logical.table_rules}
    cad_counts: dict[str, int] = {logical_id: 0 for logical_id in logical_by_id}
    unsupported = 0
    for line in cad_ir.lines:
        rule = logical_by_id.get(line.logical_entity_id)
        if rule is None:
            unsupported += 1
            continue
        cad_counts[rule.logical_entity_id] += 1
        if (
            line.start != rule.start
            or line.end != rule.end
            or line.provenance_ref != rule.provenance_id
            or rule.unsupported_length > tolerance
        ):
            unsupported += 1
    counts = tuple(cad_counts.values())
    unnecessary = sum(max(0, value - 1) for value in counts)
    average = (
        0.0
        if not logical.table_rules
        else _number(len(cad_ir.lines) / len(logical.table_rules))
    )
    return Vs1QualityMetrics(
        logical_entity_count=len(logical.table_rules),
        cad_ir_line_count=len(cad_ir.lines),
        final_entities_per_logical_rule=average,
        unnecessary_fragments=unnecessary,
        unsupported_geometry=unsupported,
        missing_logical_entities=max(
            0,
            int(expected_logical_entity_count) - len(logical.table_rules),
        ),
        extra_logical_entities=max(
            0,
            len(logical.table_rules) - int(expected_logical_entity_count),
        ),
    )
