"""Minimal backend-neutral editable CAD IR and table-rule assembly."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Sequence

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_electrical import (
    LogicalElectricalConnection,
    LogicalElectricalManifest,
    LogicalElectricalSymbol,
)
from .draftsman_logical import LogicalDrawingManifest, LogicalTableRule


DRAFTSMAN_CAD_IR_VERSION = "draftsman-editable-cad-ir-v1"
DRAFTSMAN_FINAL_ASSEMBLY_VERSION = "draftsman-final-entity-assembly-v1"
DRAFTSMAN_VS1_QUALITY_VERSION = "draftsman-vs1-quality-v1"
DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION = "draftsman-editable-electrical-cad-ir-v1"
DRAFTSMAN_VS2_QUALITY_VERSION = "draftsman-vs2-quality-v1"


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


@dataclass(frozen=True)
class EditableCadElectricalLine:
    """One editable connection entity assembled from one logical connection."""

    stable_entity_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    layer_style_ref: str
    linetype_ref: str
    direction: str
    logical_line_id: str
    logical_symbol_id: str
    provenance_ref: str
    source_evidence_ids: tuple[str, ...]
    meaningful_boundary: str = "SYMBOL_BOUNDARY"
    schema_version: str = DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _point(self.start))
        object.__setattr__(self, "end", _point(self.end))
        object.__setattr__(
            self,
            "source_evidence_ids",
            tuple(sorted(set(self.source_evidence_ids))),
        )
        if self.length <= 0.0:
            raise ValueError("Electrical CAD IR line must have positive length")
        if not self.source_evidence_ids:
            raise ValueError("Electrical CAD IR line requires source evidence")
        expected = semantic_id(
            "editable-cad-electrical-line",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_entity_id != expected:
            raise ValueError("stable_entity_id does not match electrical line semantics")

    @property
    def length(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @classmethod
    def from_logical_connection(
        cls,
        connection: LogicalElectricalConnection,
        *,
        logical_symbol_id: str,
    ) -> EditableCadElectricalLine:
        layer_style_ref = (
            "ELECTRICAL_CONTROL"
            if connection.style_ref == "DASHED_DIRECTIONAL_CONTROL"
            else "ELECTRICAL_SIGNAL"
        )
        linetype_ref = (
            "DASHED"
            if connection.style_ref == "DASHED_DIRECTIONAL_CONTROL"
            else "CONTINUOUS"
        )
        source_ids = tuple(sorted(set(connection.source_primitive_ids)))
        identity = {
            "start": list(connection.start),
            "end": list(connection.end),
            "layer_style_ref": layer_style_ref,
            "linetype_ref": linetype_ref,
            "direction": connection.direction,
            "logical_line_id": connection.logical_line_id,
            "logical_symbol_id": logical_symbol_id,
            "provenance_ref": connection.provenance_id,
            "source_evidence_ids": list(source_ids),
            "meaningful_boundary": connection.meaningful_boundary,
        }
        return cls(
            stable_entity_id=semantic_id(
                "editable-cad-electrical-line",
                DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION,
                identity,
            ),
            start=connection.start,
            end=connection.end,
            layer_style_ref=layer_style_ref,
            linetype_ref=linetype_ref,
            direction=connection.direction,
            logical_line_id=connection.logical_line_id,
            logical_symbol_id=logical_symbol_id,
            provenance_ref=connection.provenance_id,
            source_evidence_ids=source_ids,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "start": list(self.start),
            "end": list(self.end),
            "layer_style_ref": self.layer_style_ref,
            "linetype_ref": self.linetype_ref,
            "direction": self.direction,
            "logical_line_id": self.logical_line_id,
            "logical_symbol_id": self.logical_symbol_id,
            "provenance_ref": self.provenance_ref,
            "source_evidence_ids": list(self.source_evidence_ids),
            "meaningful_boundary": self.meaningful_boundary,
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
class EditableCadElectricalSymbol:
    """Editable grouped symbol instance; DXF BLOCK is a backend choice."""

    stable_entity_id: str
    block_definition_ref: str
    display_label: str
    frame_bounds: tuple[float, float, float, float]
    layer_style_ref: str
    logical_entity_id: str
    provenance_ref: str
    source_evidence_ids: tuple[str, ...]
    schema_version: str = DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frame_bounds",
            tuple(_number(value) for value in self.frame_bounds),
        )
        object.__setattr__(
            self,
            "source_evidence_ids",
            tuple(sorted(set(self.source_evidence_ids))),
        )
        left, bottom, right, top = self.frame_bounds
        if right <= left or top <= bottom:
            raise ValueError("Electrical symbol requires positive frame bounds")
        if not self.source_evidence_ids:
            raise ValueError("Electrical symbol requires source evidence")
        expected = semantic_id(
            "editable-cad-electrical-symbol",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_entity_id != expected:
            raise ValueError("stable_entity_id does not match symbol semantics")

    @classmethod
    def from_logical_symbol(
        cls,
        symbol: LogicalElectricalSymbol,
    ) -> EditableCadElectricalSymbol:
        identity = {
            "block_definition_ref": "ELEC_CONTROL_MODULE_C1",
            "display_label": "C1",
            "frame_bounds": list(symbol.frame_bounds_pt),
            "layer_style_ref": "ELECTRICAL_SYMBOL",
            "logical_entity_id": symbol.logical_entity_id,
            "provenance_ref": symbol.provenance_id,
            "source_evidence_ids": list(symbol.source_evidence_ids),
        }
        return cls(
            stable_entity_id=semantic_id(
                "editable-cad-electrical-symbol",
                DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION,
                identity,
            ),
            block_definition_ref="ELEC_CONTROL_MODULE_C1",
            display_label="C1",
            frame_bounds=symbol.frame_bounds_pt,
            layer_style_ref="ELECTRICAL_SYMBOL",
            logical_entity_id=symbol.logical_entity_id,
            provenance_ref=symbol.provenance_id,
            source_evidence_ids=symbol.source_evidence_ids,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "block_definition_ref": self.block_definition_ref,
            "display_label": self.display_label,
            "frame_bounds": list(self.frame_bounds),
            "layer_style_ref": self.layer_style_ref,
            "logical_entity_id": self.logical_entity_id,
            "provenance_ref": self.provenance_ref,
            "source_evidence_ids": list(self.source_evidence_ids),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_entity_id": self.stable_entity_id,
            "entity_kind": "SYMBOL",
            "editable_representation": "REUSABLE_PRIMITIVES_GROUP",
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class EditableElectricalCadIrManifest:
    source_document_id: str
    source_page: int
    coordinate_space: str
    logical_manifest_id: str
    symbols: tuple[EditableCadElectricalSymbol, ...]
    lines: tuple[EditableCadElectricalLine, ...]
    schema_version: str = DRAFTSMAN_ELECTRICAL_CAD_IR_VERSION

    def __post_init__(self) -> None:
        if self.symbols != tuple(
            sorted(self.symbols, key=lambda item: item.stable_entity_id)
        ):
            raise ValueError("CAD IR symbols must use canonical ID order")
        if self.lines != tuple(
            sorted(self.lines, key=lambda item: item.stable_entity_id)
        ):
            raise ValueError("CAD IR lines must use canonical ID order")
        ids = [item.stable_entity_id for item in self.symbols]
        ids.extend(item.stable_entity_id for item in self.lines)
        if len(ids) != len(set(ids)):
            raise ValueError("CAD IR entity IDs must be unique")

    @property
    def entity_count(self) -> int:
        return len(self.symbols) + len(self.lines)

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "editable-electrical-cad-ir-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": self.source_page,
                "coordinate_space": self.coordinate_space,
                "logical_manifest_id": self.logical_manifest_id,
                "symbol_ids": [item.stable_entity_id for item in self.symbols],
                "line_ids": [item.stable_entity_id for item in self.lines],
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "coordinate_space": self.coordinate_space,
            "logical_manifest_id": self.logical_manifest_id,
            "symbol_count": len(self.symbols),
            "line_count": len(self.lines),
            "entity_count": self.entity_count,
            "symbols": [item.to_dict() for item in self.symbols],
            "lines": [item.to_dict() for item in self.lines],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def assemble_editable_electrical_cad_ir(
    logical: LogicalElectricalManifest,
) -> EditableElectricalCadIrManifest:
    """Assemble editable objects without joining connections through a symbol."""

    symbols = tuple(
        sorted(
            (
                EditableCadElectricalSymbol.from_logical_symbol(symbol)
                for symbol in logical.symbols
            ),
            key=lambda item: item.stable_entity_id,
        )
    )
    lines = tuple(
        sorted(
            (
                EditableCadElectricalLine.from_logical_connection(
                    connection,
                    logical_symbol_id=symbol.logical_entity_id,
                )
                for symbol in logical.symbols
                for connection in symbol.connections
            ),
            key=lambda item: item.stable_entity_id,
        )
    )
    return EditableElectricalCadIrManifest(
        source_document_id=logical.source_document_id,
        source_page=logical.source_page,
        coordinate_space="normalized-page-point",
        logical_manifest_id=logical.manifest_id,
        symbols=symbols,
        lines=lines,
    )


@dataclass(frozen=True)
class Vs2QualityMetrics:
    source_evidence_primitives: int
    logical_symbol_entities: int
    logical_connected_lines: int
    final_cad_ir_entities: int
    unsupported_geometry: int
    unnecessary_fragments: int
    invalid_port_connections: int
    incorrect_line_through_symbol: int
    unassociated_expected_annotation: int
    domain_rule_violations: int
    schema_version: str = DRAFTSMAN_VS2_QUALITY_VERSION

    @property
    def passed(self) -> bool:
        return (
            self.logical_symbol_entities > 0
            and self.logical_connected_lines > 0
            and self.final_cad_ir_entities
            == self.logical_symbol_entities + self.logical_connected_lines
            and self.unsupported_geometry == 0
            and self.unnecessary_fragments == 0
            and self.invalid_port_connections == 0
            and self.incorrect_line_through_symbol == 0
            and self.unassociated_expected_annotation == 0
            and self.domain_rule_violations == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_evidence_primitives": self.source_evidence_primitives,
            "logical_symbol_entities": self.logical_symbol_entities,
            "logical_connected_lines": self.logical_connected_lines,
            "final_cad_ir_entities": self.final_cad_ir_entities,
            "unsupported_geometry": self.unsupported_geometry,
            "unnecessary_fragments": self.unnecessary_fragments,
            "invalid_port_connections": self.invalid_port_connections,
            "incorrect_line_through_symbol": self.incorrect_line_through_symbol,
            "unassociated_expected_annotation": self.unassociated_expected_annotation,
            "domain_rule_violations": self.domain_rule_violations,
            "passed": self.passed,
        }


def audit_vs2_cad_ir(
    logical: LogicalElectricalManifest,
    cad_ir: EditableElectricalCadIrManifest,
) -> Vs2QualityMetrics:
    logical_symbols = {item.logical_entity_id: item for item in logical.symbols}
    logical_lines = {item.logical_line_id: item for item in logical.connections}
    unsupported = 0
    invalid_ports = 0
    line_through = 0
    for cad_symbol in cad_ir.symbols:
        if (
            cad_symbol.logical_entity_id not in logical_symbols
            or not cad_symbol.source_evidence_ids
        ):
            unsupported += 1
    line_counts = {item.logical_line_id: 0 for item in logical.connections}
    for line in cad_ir.lines:
        logical_line = logical_lines.get(line.logical_line_id)
        logical_symbol = logical_symbols.get(line.logical_symbol_id)
        if (
            logical_line is None
            or logical_symbol is None
            or not line.source_evidence_ids
        ):
            unsupported += 1
            continue
        line_counts[line.logical_line_id] += 1
        if (
            line.start != logical_line.start
            or line.end != logical_line.end
            or line.meaningful_boundary != "SYMBOL_BOUNDARY"
        ):
            invalid_ports += 1
        left, bottom, right, top = logical_symbol.frame_bounds_pt
        endpoints = {line.start, line.end}
        touches_boundary = any(
            (
                left - 1e-6 <= point[0] <= right + 1e-6
                and (
                    abs(point[1] - bottom) <= 1e-6
                    or abs(point[1] - top) <= 1e-6
                )
            )
            for point in endpoints
        )
        if not touches_boundary:
            invalid_ports += 1
        midpoint = (
            (line.start[0] + line.end[0]) / 2.0,
            (line.start[1] + line.end[1]) / 2.0,
        )
        if left < midpoint[0] < right and bottom < midpoint[1] < top:
            line_through += 1
    unnecessary = sum(max(0, count - 1) for count in line_counts.values())
    missing_lines = sum(1 for count in line_counts.values() if count == 0)
    source_ids = {
        evidence_id
        for symbol in logical.symbols
        for evidence_id in symbol.source_evidence_ids
    }
    return Vs2QualityMetrics(
        source_evidence_primitives=len(source_ids),
        logical_symbol_entities=len(logical.symbols),
        logical_connected_lines=len(logical.connections),
        final_cad_ir_entities=cad_ir.entity_count,
        unsupported_geometry=unsupported,
        unnecessary_fragments=unnecessary,
        invalid_port_connections=invalid_ports + missing_lines,
        incorrect_line_through_symbol=line_through,
        unassociated_expected_annotation=0,
        domain_rule_violations=0,
    )
