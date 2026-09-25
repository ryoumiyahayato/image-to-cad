"""Minimal Logical Drawing Model for complete horizontal table rules."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, Sequence

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_domain_pack import DomainPack, TableRuleConvention
from .draftsman_pdf_evidence import (
    PdfLineFragmentEvidence,
    PdfPathEvidenceManifest,
)


DRAFTSMAN_LOGICAL_MODEL_VERSION = "draftsman-logical-drawing-v1"
LOGICAL_TABLE_RULE_VERSION = "draftsman-logical-table-rule-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError("Logical geometry points require two coordinates")
    return _number(value[0]), _number(value[1])


@dataclass(frozen=True)
class LogicalTableRule:
    logical_entity_id: str
    source_document_id: str
    source_page: int
    start: tuple[float, float]
    end: tuple[float, float]
    source_fragment_ids: tuple[str, ...]
    source_path_evidence_ids: tuple[str, ...]
    domain_pack_id: str
    convention_id: str
    logical_role: str
    direct_evidence_length: float
    unsupported_length: float
    provenance_id: str
    schema_version: str = LOGICAL_TABLE_RULE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _point(self.start))
        object.__setattr__(self, "end", _point(self.end))
        if self.end < self.start:
            raise ValueError("Logical table-rule endpoints must be canonical")
        if self.length <= 0.0:
            raise ValueError("Logical table rule must have positive length")
        if not self.source_fragment_ids or not self.source_path_evidence_ids:
            raise ValueError("Logical table rule requires direct PDF evidence")
        if self.source_fragment_ids != tuple(sorted(set(self.source_fragment_ids))):
            raise ValueError("source_fragment_ids must use canonical unique order")
        if self.source_path_evidence_ids != tuple(
            sorted(set(self.source_path_evidence_ids))
        ):
            raise ValueError("source_path_evidence_ids must use canonical unique order")
        expected_provenance = semantic_id(
            "draftsman-logical-table-rule-provenance",
            self.schema_version,
            self.provenance_payload(),
        )
        if self.provenance_id != expected_provenance:
            raise ValueError("provenance_id does not match logical evidence")
        expected_entity = semantic_id(
            "draftsman-logical-table-rule",
            self.schema_version,
            self.identity_payload(),
        )
        if self.logical_entity_id != expected_entity:
            raise ValueError("logical_entity_id does not match table-rule semantics")

    @property
    def length(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @classmethod
    def create(
        cls,
        *,
        source_document_id: str,
        source_page: int,
        start: Sequence[float],
        end: Sequence[float],
        source_fragments: Sequence[PdfLineFragmentEvidence],
        domain_pack_id: str,
        convention: TableRuleConvention,
        direct_evidence_length: float,
    ) -> LogicalTableRule:
        normalized_start = _point(start)
        normalized_end = _point(end)
        if normalized_end < normalized_start:
            normalized_start, normalized_end = normalized_end, normalized_start
        fragment_ids = tuple(
            sorted({fragment.stable_fragment_id for fragment in source_fragments})
        )
        path_ids = tuple(
            sorted({fragment.parent_path_evidence_id for fragment in source_fragments})
        )
        geometry_length = hypot(
            normalized_end[0] - normalized_start[0],
            normalized_end[1] - normalized_start[1],
        )
        supported = min(geometry_length, max(0.0, float(direct_evidence_length)))
        provenance_payload = {
            "source_fragment_ids": list(fragment_ids),
            "source_path_evidence_ids": list(path_ids),
            "domain_pack_id": domain_pack_id,
            "convention_id": convention.convention_id,
        }
        provenance_id = semantic_id(
            "draftsman-logical-table-rule-provenance",
            LOGICAL_TABLE_RULE_VERSION,
            provenance_payload,
        )
        identity = {
            "source_document_id": source_document_id,
            "source_page": int(source_page),
            "start": list(normalized_start),
            "end": list(normalized_end),
            "logical_role": convention.logical_role,
            "provenance_id": provenance_id,
            "direct_evidence_length": _number(supported),
            "unsupported_length": _number(max(0.0, geometry_length - supported)),
        }
        return cls(
            logical_entity_id=semantic_id(
                "draftsman-logical-table-rule",
                LOGICAL_TABLE_RULE_VERSION,
                identity,
            ),
            source_document_id=source_document_id,
            source_page=int(source_page),
            start=normalized_start,
            end=normalized_end,
            source_fragment_ids=fragment_ids,
            source_path_evidence_ids=path_ids,
            domain_pack_id=domain_pack_id,
            convention_id=convention.convention_id,
            logical_role=convention.logical_role,
            direct_evidence_length=_number(supported),
            unsupported_length=_number(max(0.0, geometry_length - supported)),
            provenance_id=provenance_id,
        )

    def provenance_payload(self) -> dict[str, object]:
        return {
            "source_fragment_ids": list(self.source_fragment_ids),
            "source_path_evidence_ids": list(self.source_path_evidence_ids),
            "domain_pack_id": self.domain_pack_id,
            "convention_id": self.convention_id,
        }

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "start": list(self.start),
            "end": list(self.end),
            "logical_role": self.logical_role,
            "provenance_id": self.provenance_id,
            "direct_evidence_length": self.direct_evidence_length,
            "unsupported_length": self.unsupported_length,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_entity_id": self.logical_entity_id,
            "logical_kind": "TABLE_RULE",
            **self.identity_payload(),
            "source_fragment_ids": list(self.source_fragment_ids),
            "source_path_evidence_ids": list(self.source_path_evidence_ids),
            "domain_pack_id": self.domain_pack_id,
            "convention_id": self.convention_id,
            "length": _number(self.length),
        }


@dataclass(frozen=True)
class LogicalDrawingManifest:
    source_document_id: str
    source_page: int
    evidence_manifest_id: str
    domain_pack_id: str
    table_rules: tuple[LogicalTableRule, ...]
    schema_version: str = DRAFTSMAN_LOGICAL_MODEL_VERSION

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.table_rules, key=lambda item: item.logical_entity_id))
        if self.table_rules != ordered:
            raise ValueError("Logical entities must use canonical ID order")
        if len({item.logical_entity_id for item in self.table_rules}) != len(
            self.table_rules
        ):
            raise ValueError("Logical entity IDs must be unique")

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-logical-drawing-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": int(self.source_page),
                "evidence_manifest_id": self.evidence_manifest_id,
                "domain_pack_id": self.domain_pack_id,
                "logical_entity_ids": [
                    item.logical_entity_id for item in self.table_rules
                ],
            },
        )

    @property
    def target_evidence_fragment_count(self) -> int:
        return len(
            {
                fragment_id
                for rule in self.table_rules
                for fragment_id in rule.source_fragment_ids
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "evidence_manifest_id": self.evidence_manifest_id,
            "domain_pack_id": self.domain_pack_id,
            "logical_entity_count": len(self.table_rules),
            "target_evidence_fragment_count": self.target_evidence_fragment_count,
            "table_rules": [item.to_dict() for item in self.table_rules],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True)
class _HorizontalSpan:
    start_x: float
    end_x: float
    y: float
    fragments: tuple[PdfLineFragmentEvidence, ...]
    direct_coverage_length: float

    @property
    def length(self) -> float:
        return self.end_x - self.start_x


def _horizontal_fragments(
    evidence: PdfPathEvidenceManifest,
    convention: TableRuleConvention,
) -> tuple[PdfLineFragmentEvidence, ...]:
    minimum_length = (
        evidence.page_size_pt[0]
        * convention.minimum_fragment_span_page_fraction
    )
    selected = []
    for fragment in evidence.line_fragments():
        if abs(fragment.end[1] - fragment.start[1]) > convention.horizontal_tolerance_pt:
            continue
        if fragment.length < minimum_length:
            continue
        selected.append(fragment)
    return tuple(sorted(selected, key=lambda item: item.stable_fragment_id))


def _clusters_by_y(
    fragments: Sequence[PdfLineFragmentEvidence],
    tolerance: float,
) -> tuple[tuple[PdfLineFragmentEvidence, ...], ...]:
    ordered = sorted(
        fragments,
        key=lambda item: (
            (item.start[1] + item.end[1]) / 2.0,
            min(item.start[0], item.end[0]),
            item.stable_fragment_id,
        ),
    )
    clusters: list[list[PdfLineFragmentEvidence]] = []
    centers: list[float] = []
    for fragment in ordered:
        y_value = (fragment.start[1] + fragment.end[1]) / 2.0
        if not clusters or abs(y_value - centers[-1]) > tolerance:
            clusters.append([fragment])
            centers.append(y_value)
            continue
        clusters[-1].append(fragment)
        centers[-1] = sum(
            (item.start[1] + item.end[1]) / 2.0 for item in clusters[-1]
        ) / len(clusters[-1])
    return tuple(tuple(cluster) for cluster in clusters)


def _union_length(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted((min(start, end), max(start, end)) for start, end in intervals)
    if not ordered:
        return 0.0
    total = 0.0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
            continue
        total += end - start
        start, end = next_start, next_end
    return total + end - start


def _spans(
    fragments: Sequence[PdfLineFragmentEvidence],
    convention: TableRuleConvention,
) -> tuple[_HorizontalSpan, ...]:
    spans: list[_HorizontalSpan] = []
    for y_cluster in _clusters_by_y(
        fragments,
        convention.horizontal_tolerance_pt,
    ):
        ordered = sorted(
            y_cluster,
            key=lambda item: (min(item.start[0], item.end[0]), item.stable_fragment_id),
        )
        current: list[PdfLineFragmentEvidence] = []
        current_end = 0.0
        for fragment in ordered:
            start_x = min(fragment.start[0], fragment.end[0])
            end_x = max(fragment.start[0], fragment.end[0])
            if current and start_x > current_end + convention.maximum_fragment_gap_pt:
                spans.append(_span_from_fragments(current))
                current = []
            current.append(fragment)
            current_end = max(current_end, end_x) if len(current) > 1 else end_x
        if current:
            spans.append(_span_from_fragments(current))
    return tuple(
        sorted(
            spans,
            key=lambda item: (item.start_x, item.end_x, item.y),
        )
    )


def _span_from_fragments(
    fragments: Sequence[PdfLineFragmentEvidence],
) -> _HorizontalSpan:
    intervals = [
        (min(item.start[0], item.end[0]), max(item.start[0], item.end[0]))
        for item in fragments
    ]
    return _HorizontalSpan(
        start_x=_number(min(item[0] for item in intervals)),
        end_x=_number(max(item[1] for item in intervals)),
        y=_number(
            sum((item.start[1] + item.end[1]) / 2.0 for item in fragments)
            / len(fragments)
        ),
        fragments=tuple(sorted(fragments, key=lambda item: item.stable_fragment_id)),
        direct_coverage_length=_number(_union_length(intervals)),
    )


def _groups_by_common_span(
    spans: Sequence[_HorizontalSpan],
    tolerance: float,
) -> tuple[tuple[_HorizontalSpan, ...], ...]:
    groups: list[list[_HorizontalSpan]] = []
    for span in sorted(spans, key=lambda item: (item.start_x, item.end_x, item.y)):
        for group in groups:
            anchor = group[0]
            if (
                abs(anchor.start_x - span.start_x) <= tolerance
                and abs(anchor.end_x - span.end_x) <= tolerance
            ):
                group.append(span)
                break
        else:
            groups.append([span])
    return tuple(
        tuple(sorted(group, key=lambda item: item.y))
        for group in groups
    )


def _longest_regular_run(
    spans: Sequence[_HorizontalSpan],
    convention: TableRuleConvention,
) -> tuple[tuple[_HorizontalSpan, ...], float] | None:
    ordered = sorted(spans, key=lambda item: item.y)
    best: tuple[_HorizontalSpan, ...] = ()
    best_spacing = 0.0
    for first_index in range(len(ordered)):
        for second_index in range(first_index + 1, len(ordered)):
            spacing = ordered[second_index].y - ordered[first_index].y
            if spacing <= convention.spacing_tolerance_pt:
                continue
            run = [ordered[first_index], ordered[second_index]]
            expected = ordered[second_index].y + spacing
            for candidate in ordered[second_index + 1 :]:
                if abs(candidate.y - expected) <= convention.spacing_tolerance_pt:
                    run.append(candidate)
                    expected += spacing
                elif candidate.y > expected + convention.spacing_tolerance_pt:
                    break
            candidate_run = tuple(run)
            candidate_key = (
                len(candidate_run),
                _number(candidate_run[-1].y - candidate_run[0].y),
                _number(candidate_run[-1].length),
                _number(candidate_run[-1].y),
            )
            best_key = (
                len(best),
                _number(best[-1].y - best[0].y) if best else 0.0,
                _number(best[-1].length) if best else 0.0,
                _number(best[-1].y) if best else 0.0,
            )
            if candidate_key > best_key:
                best = candidate_run
                best_spacing = spacing
    if len(best) < convention.minimum_regular_rule_count:
        return None
    return best, _number(best_spacing)


def _footer_band_centers(
    evidence: PdfPathEvidenceManifest,
    *,
    span_start: float,
    span_end: float,
    convention: TableRuleConvention,
) -> tuple[float, ...]:
    centers = []
    for path in evidence.paths:
        if not path.paint.has_fill:
            continue
        x_min, y_min, x_max, y_max = path.bounds_pt
        if y_max - y_min > convention.footer_band_max_height_pt:
            continue
        if (
            abs(x_min - span_start) > convention.common_endpoint_tolerance_pt
            or abs(x_max - span_end) > convention.common_endpoint_tolerance_pt
        ):
            continue
        centers.append(_number((y_min + y_max) / 2.0))
    return tuple(sorted(set(centers)))


def _apply_footer_clearance(
    run: Sequence[_HorizontalSpan],
    spacing: float,
    footer_centers: Sequence[float],
    convention: TableRuleConvention,
) -> tuple[_HorizontalSpan, ...]:
    if not footer_centers:
        return tuple(run)
    aligned = [
        center
        for center in footer_centers
        if any(abs(span.y - center) <= convention.spacing_tolerance_pt for span in run)
    ]
    if not aligned:
        return tuple(run)
    footer_center = min(aligned)
    clearance = spacing * convention.footer_clearance_spacing_multiplier
    return tuple(
        span
        for span in run
        if span.y - footer_center > clearance + convention.spacing_tolerance_pt
    )


def assemble_logical_table_rules(
    evidence: PdfPathEvidenceManifest,
    domain_pack: DomainPack,
) -> LogicalDrawingManifest:
    """Apply pack conventions to evidence without changing the evidence set."""

    rules: list[LogicalTableRule] = []
    pack_id = domain_pack.pack_id
    for convention in domain_pack.table_rule_conventions:
        fragments = _horizontal_fragments(evidence, convention)
        spans = tuple(
            span
            for span in _spans(fragments, convention)
            if span.length
            >= evidence.page_size_pt[0] * convention.minimum_span_page_fraction
        )
        candidates: list[tuple[tuple[_HorizontalSpan, ...], float]] = []
        for common_group in _groups_by_common_span(
            spans,
            convention.common_endpoint_tolerance_pt,
        ):
            regular = _longest_regular_run(common_group, convention)
            if regular is not None:
                candidates.append(regular)
        if not candidates:
            continue
        selected_run, spacing = max(
            candidates,
            key=lambda item: (
                len(item[0]),
                item[0][-1].length,
                item[0][-1].y - item[0][0].y,
            ),
        )
        footer_centers = _footer_band_centers(
            evidence,
            span_start=selected_run[0].start_x,
            span_end=selected_run[0].end_x,
            convention=convention,
        )
        selected_run = _apply_footer_clearance(
            selected_run,
            spacing,
            footer_centers,
            convention,
        )
        for span in selected_run:
            rules.append(
                LogicalTableRule.create(
                    source_document_id=evidence.source_document_id,
                    source_page=evidence.source_page,
                    start=(span.start_x, span.y),
                    end=(span.end_x, span.y),
                    source_fragments=span.fragments,
                    domain_pack_id=pack_id,
                    convention=convention,
                    direct_evidence_length=span.direct_coverage_length,
                )
            )

    ordered = tuple(sorted(rules, key=lambda item: item.logical_entity_id))
    return LogicalDrawingManifest(
        source_document_id=evidence.source_document_id,
        source_page=evidence.source_page,
        evidence_manifest_id=evidence.manifest_id,
        domain_pack_id=pack_id,
        table_rules=ordered,
    )
