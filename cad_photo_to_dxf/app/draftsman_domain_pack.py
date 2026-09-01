"""Fixed, replaceable Domain Pack contract for Draftsman logical assembly."""

from __future__ import annotations

from dataclasses import dataclass
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


class DomainPack(Protocol):
    @property
    def pack_id(self) -> str: ...

    @property
    def descriptor(self) -> DomainPackDescriptor: ...

    @property
    def table_rule_conventions(self) -> tuple[TableRuleConvention, ...]: ...


@dataclass(frozen=True)
class ElectricalDomainPackV0:
    """Golden-scoped v0 pack: only the electrical drawing-index convention."""

    descriptor: DomainPackDescriptor
    table_rule_conventions: tuple[TableRuleConvention, ...]

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
        }
