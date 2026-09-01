"""Fixed, replaceable Domain Pack contract for Draftsman logical assembly."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .draftsman_contract import semantic_id


DRAFTSMAN_DOMAIN_PACK_VERSION = "draftsman-domain-pack-v1"
ELECTRICAL_DOMAIN_PACK_V0_VERSION = "electrical-domain-pack-v0"


@dataclass(frozen=True)
class DomainPackDescriptor:
    domain_id: str
    pack_version: str
    compatible_contract_version: str = DRAFTSMAN_DOMAIN_PACK_VERSION

    @property
    def pack_id(self) -> str:
        return semantic_id(
            "draftsman-domain-pack",
            self.compatible_contract_version,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "domain_id": self.domain_id,
            "pack_version": self.pack_version,
            "compatible_contract_version": self.compatible_contract_version,
        }


@dataclass(frozen=True)
class TableRuleConvention:
    """Declarative geometry convention for a repeated directory table body."""

    convention_key: str
    logical_role: str
    minimum_fragment_span_page_fraction: float
    minimum_span_page_fraction: float
    horizontal_tolerance_pt: float
    common_endpoint_tolerance_pt: float
    maximum_fragment_gap_pt: float
    spacing_tolerance_pt: float
    minimum_regular_rule_count: int
    footer_band_max_height_pt: float
    footer_clearance_spacing_multiplier: float

    def __post_init__(self) -> None:
        if not (
            0.0
            < float(self.minimum_fragment_span_page_fraction)
            <= float(self.minimum_span_page_fraction)
            <= 1.0
        ):
            raise ValueError("Fragment/final span fractions must be ordered in (0, 1]")
        if any(
            float(value) < 0.0
            for value in (
                self.horizontal_tolerance_pt,
                self.common_endpoint_tolerance_pt,
                self.maximum_fragment_gap_pt,
                self.spacing_tolerance_pt,
                self.footer_band_max_height_pt,
                self.footer_clearance_spacing_multiplier,
            )
        ):
            raise ValueError("Table-rule tolerances must not be negative")
        if int(self.minimum_regular_rule_count) < 3:
            raise ValueError("A regular rule family requires at least three rules")

    @property
    def convention_id(self) -> str:
        return semantic_id(
            "draftsman-table-rule-convention",
            DRAFTSMAN_DOMAIN_PACK_VERSION,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "convention_key": self.convention_key,
            "logical_role": self.logical_role,
            "minimum_fragment_span_page_fraction": (
                self.minimum_fragment_span_page_fraction
            ),
            "minimum_span_page_fraction": self.minimum_span_page_fraction,
            "horizontal_tolerance_pt": self.horizontal_tolerance_pt,
            "common_endpoint_tolerance_pt": self.common_endpoint_tolerance_pt,
            "maximum_fragment_gap_pt": self.maximum_fragment_gap_pt,
            "spacing_tolerance_pt": self.spacing_tolerance_pt,
            "minimum_regular_rule_count": self.minimum_regular_rule_count,
            "footer_band_max_height_pt": self.footer_band_max_height_pt,
            "footer_clearance_spacing_multiplier": (
                self.footer_clearance_spacing_multiplier
            ),
        }


class ElectricalPortSide(str, Enum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class ElectricalConnectionStyle(str, Enum):
    CONTINUOUS_SIGNAL = "CONTINUOUS_SIGNAL"
    DASHED_DIRECTIONAL_CONTROL = "DASHED_DIRECTIONAL_CONTROL"


@dataclass(frozen=True)
class ElectricalPortRule:
    port_key: str
    side: ElectricalPortSide
    lateral_fraction: float
    connection_style: ElectricalConnectionStyle
    direction: str

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.lateral_fraction) <= 1.0:
            raise ValueError("Port lateral_fraction must be in [0, 1]")

    def to_dict(self) -> dict[str, object]:
        return {
            "port_key": self.port_key,
            "side": self.side.value,
            "lateral_fraction": self.lateral_fraction,
            "connection_style": self.connection_style.value,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class BoxedGlyphRecognitionSignature:
    minimum_frame_size_pt: float
    maximum_frame_size_pt: float
    interior_segment_count_multiset: tuple[int, ...]
    required_interior_path_count: int

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_frame_size_pt <= self.maximum_frame_size_pt:
            raise ValueError("Electrical frame-size limits must be ordered")
        if self.required_interior_path_count <= 0:
            raise ValueError("An electrical glyph signature requires interior evidence")
        if len(self.interior_segment_count_multiset) != self.required_interior_path_count:
            raise ValueError("Interior segment signature/path count mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            "minimum_frame_size_pt": self.minimum_frame_size_pt,
            "maximum_frame_size_pt": self.maximum_frame_size_pt,
            "interior_segment_count_multiset": list(
                self.interior_segment_count_multiset
            ),
            "required_interior_path_count": self.required_interior_path_count,
        }


@dataclass(frozen=True)
class RasterGlyphRecognitionSignature:
    """Declarative normalized raster signature, independent of source coordinates."""

    normalized_template_rows: tuple[str, ...]
    minimum_template_score: float
    minimum_ring_coverage: float
    minimum_port_support: float
    minimum_aligned_repetition: int
    alignment_tolerance_px: float
    minimum_connection_evidence_coverage: float
    allowed_variant: str

    def __post_init__(self) -> None:
        if not self.normalized_template_rows:
            raise ValueError("Raster signature requires a normalized template")
        width = len(self.normalized_template_rows[0])
        if width <= 0 or any(len(row) != width for row in self.normalized_template_rows):
            raise ValueError("Raster template rows must form a non-empty rectangle")
        if any(set(row) - {".", "#"} for row in self.normalized_template_rows):
            raise ValueError("Raster template rows may only use '.' and '#'")
        for value in (
            self.minimum_template_score,
            self.minimum_ring_coverage,
            self.minimum_port_support,
            self.minimum_connection_evidence_coverage,
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("Raster signature scores must be in [0, 1]")
        if self.minimum_aligned_repetition < 2:
            raise ValueError("Raster signature requires repeated source examples")
        if self.alignment_tolerance_px < 0.0:
            raise ValueError("Raster alignment tolerance must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "normalized_template_rows": list(self.normalized_template_rows),
            "minimum_template_score": self.minimum_template_score,
            "minimum_ring_coverage": self.minimum_ring_coverage,
            "minimum_port_support": self.minimum_port_support,
            "minimum_aligned_repetition": self.minimum_aligned_repetition,
            "alignment_tolerance_px": self.alignment_tolerance_px,
            "minimum_connection_evidence_coverage": (
                self.minimum_connection_evidence_coverage
            ),
            "allowed_variant": self.allowed_variant,
        }


@dataclass(frozen=True)
class ElectricalSymbolRule:
    rule_key: str
    inventory_canonical_identity: str
    canonical_domain_identity: str
    drawing_legend_identity: str
    recognition_signature: BoxedGlyphRecognitionSignature | None
    raster_recognition_signature: RasterGlyphRecognitionSignature | None
    ports: tuple[ElectricalPortRule, ...]
    body_crossing_permitted: bool
    annotation_expected: bool
    authority: str
    cad_block_ref: str
    display_label: str

    def __post_init__(self) -> None:
        if self.recognition_signature is None and self.raster_recognition_signature is None:
            raise ValueError("Electrical rule requires at least one recognition signature")

    @property
    def rule_id(self) -> str:
        return semantic_id(
            "draftsman-electrical-symbol-rule",
            DRAFTSMAN_DOMAIN_PACK_VERSION,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_key": self.rule_key,
            "inventory_canonical_identity": self.inventory_canonical_identity,
            "canonical_domain_identity": self.canonical_domain_identity,
            "drawing_legend_identity": self.drawing_legend_identity,
            "recognition_signature": (
                None
                if self.recognition_signature is None
                else self.recognition_signature.to_dict()
            ),
            "raster_recognition_signature": (
                None
                if self.raster_recognition_signature is None
                else self.raster_recognition_signature.to_dict()
            ),
            "ports": [port.to_dict() for port in self.ports],
            "body_crossing_permitted": self.body_crossing_permitted,
            "annotation_expected": self.annotation_expected,
            "authority": self.authority,
            "cad_block_ref": self.cad_block_ref,
            "display_label": self.display_label,
        }


class DomainPack(Protocol):
    @property
    def pack_id(self) -> str: ...

    @property
    def descriptor(self) -> DomainPackDescriptor: ...

    @property
    def table_rule_conventions(self) -> tuple[TableRuleConvention, ...]: ...

    @property
    def electrical_symbol_rules(self) -> tuple[ElectricalSymbolRule, ...]: ...


@dataclass(frozen=True)
class ElectricalDomainPackV0:
    """Golden-scoped v0 pack with one verified electrical symbol rule."""

    descriptor: DomainPackDescriptor
    table_rule_conventions: tuple[TableRuleConvention, ...]
    electrical_symbol_rules: tuple[ElectricalSymbolRule, ...]

    @classmethod
    def create(cls) -> ElectricalDomainPackV0:
        return cls(
            descriptor=DomainPackDescriptor(
                domain_id="electrical",
                pack_version=ELECTRICAL_DOMAIN_PACK_V0_VERSION,
            ),
            table_rule_conventions=(
                TableRuleConvention(
                    convention_key="electrical-drawing-index-body-row-rules",
                    logical_role="DIRECTORY_BODY_ROW_RULE",
                    minimum_fragment_span_page_fraction=0.20,
                    minimum_span_page_fraction=0.70,
                    horizontal_tolerance_pt=0.05,
                    common_endpoint_tolerance_pt=0.50,
                    maximum_fragment_gap_pt=0.50,
                    spacing_tolerance_pt=0.15,
                    minimum_regular_rule_count=5,
                    footer_band_max_height_pt=2.0,
                    footer_clearance_spacing_multiplier=2.5,
                ),
            ),
            electrical_symbol_rules=(
                ElectricalSymbolRule(
                    rule_key="single-input-output-control-module-c1",
                    inventory_canonical_identity="控制模块",
                    canonical_domain_identity=(
                        "ELECTRICAL.SINGLE_INPUT_OUTPUT_CONTROL_MODULE"
                    ),
                    drawing_legend_identity="单输入输出控制模块 (C1)",
                    recognition_signature=BoxedGlyphRecognitionSignature(
                        minimum_frame_size_pt=11.0,
                        maximum_frame_size_pt=15.5,
                        interior_segment_count_multiset=(4, 6, 8, 18, 18),
                        required_interior_path_count=5,
                    ),
                    raster_recognition_signature=None,
                    ports=(
                        ElectricalPortRule(
                            "TOP_SIGNAL_A",
                            ElectricalPortSide.TOP,
                            0.29,
                            ElectricalConnectionStyle.CONTINUOUS_SIGNAL,
                            "IN",
                        ),
                        ElectricalPortRule(
                            "TOP_SIGNAL_B",
                            ElectricalPortSide.TOP,
                            0.71,
                            ElectricalConnectionStyle.CONTINUOUS_SIGNAL,
                            "IN",
                        ),
                        ElectricalPortRule(
                            "BOTTOM_CONTROL_OUT",
                            ElectricalPortSide.BOTTOM,
                            0.28,
                            ElectricalConnectionStyle.DASHED_DIRECTIONAL_CONTROL,
                            "OUT",
                        ),
                        ElectricalPortRule(
                            "BOTTOM_CONTROL_IN",
                            ElectricalPortSide.BOTTOM,
                            0.72,
                            ElectricalConnectionStyle.DASHED_DIRECTIONAL_CONTROL,
                            "IN",
                        ),
                    ),
                    body_crossing_permitted=False,
                    annotation_expected=False,
                    authority=(
                        "drawing-specific page legend; inventory family ELEC-150-S06"
                    ),
                    cad_block_ref="ELEC_CONTROL_MODULE_C1",
                    display_label="C1",
                ),
                ElectricalSymbolRule(
                    rule_key="raster-smoke-detector-inline-horizontal",
                    inventory_canonical_identity="感烟",
                    canonical_domain_identity="ELECTRICAL.FIRE_ALARM.SMOKE_DETECTOR",
                    drawing_legend_identity="tags 140-177: 感烟",
                    recognition_signature=None,
                    raster_recognition_signature=RasterGlyphRecognitionSignature(
                        normalized_template_rows=(
                            ".....................",
                            ".....................",
                            "........####.........",
                            ".......#######.......",
                            ".....##########......",
                            "....############.....",
                            "....#############....",
                            "...##########.####...",
                            "...##########..###...",
                            ".####.######...######",
                            "#####..######..######",
                            "######...#####.######",
                            "..####...#####.####..",
                            "...##############....",
                            "....#######.#####....",
                            "....############.....",
                            ".....##########......",
                            "......########.......",
                            ".......########......",
                            ".........###.........",
                            "...........#.........",
                        ),
                        minimum_template_score=0.62,
                        minimum_ring_coverage=0.60,
                        minimum_port_support=0.85,
                        minimum_aligned_repetition=5,
                        alignment_tolerance_px=5.0,
                        minimum_connection_evidence_coverage=0.80,
                        allowed_variant="INLINE_HORIZONTAL_TWO_PORT",
                    ),
                    ports=(
                        ElectricalPortRule(
                            "LEFT_ALARM_BUS",
                            ElectricalPortSide.LEFT,
                            0.5,
                            ElectricalConnectionStyle.CONTINUOUS_SIGNAL,
                            "BIDIRECTIONAL",
                        ),
                        ElectricalPortRule(
                            "RIGHT_ALARM_BUS",
                            ElectricalPortSide.RIGHT,
                            0.5,
                            ElectricalConnectionStyle.CONTINUOUS_SIGNAL,
                            "BIDIRECTIONAL",
                        ),
                    ),
                    body_crossing_permitted=False,
                    annotation_expected=True,
                    authority=(
                        "drawing-specific tag range 140-177; inventory family "
                        "ELEC-150-S01; raster signature from repeated source examples"
                    ),
                    cad_block_ref="ELEC_SMOKE_DETECTOR",
                    display_label="S",
                ),
            ),
        )

    @property
    def pack_id(self) -> str:
        return semantic_id(
            "draftsman-domain-pack-instance",
            DRAFTSMAN_DOMAIN_PACK_VERSION,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "table_rule_conventions": [
                convention.to_dict() for convention in self.table_rule_conventions
            ],
            "electrical_symbol_rules": [
                rule.to_dict() for rule in self.electrical_symbol_rules
            ],
        }
