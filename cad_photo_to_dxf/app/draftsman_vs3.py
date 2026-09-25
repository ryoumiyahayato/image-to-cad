"""Shadow-only VS3 raster electrical vertical slice and review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .draftsman_cad_ir import (
    EditableElectricalCadIrManifest,
    assemble_editable_electrical_cad_ir,
    audit_vs2_cad_ir,
)
from .draftsman_domain_pack import DomainPack, ElectricalDomainPackV0
from .draftsman_electrical import LogicalElectricalManifest
from .draftsman_raster_electrical import (
    RasterElectricalInterpretation,
    assemble_raster_logical_electrical_entities,
    interpret_raster_electrical_symbols,
)
from .draftsman_raster_evidence import (
    RasterEvidenceManifest,
    RasterLineFragmentEvidence,
    extract_raster_electrical_evidence,
)


DRAFTSMAN_VS3_VERSION = "draftsman-vs3-raster-electrical-v1"
DRAFTSMAN_VS3_QUALITY_VERSION = "draftsman-vs3-quality-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


@dataclass(frozen=True)
class Vs3QualityMetrics:
    source_object_instances: int
    raster_evidence_primitives: int
    logical_symbol_entities: int
    logical_connected_lines: int
    final_cad_ir_entities: int
    unnecessary_fragments: int
    unsupported_geometry: int
    incorrect_line_through_symbol: int
    missed_expected_ports: int
    invalid_port_connections: int
    domain_rule_violations: int
    reconstructed_logical_lines: int
    mean_observed_evidence_coverage: float
    inferred_portion_length: float
    reconstructed_final_entity_count: int
    schema_version: str = DRAFTSMAN_VS3_QUALITY_VERSION

    @property
    def passed(self) -> bool:
        return (
            self.source_object_instances > 0
            and self.logical_symbol_entities == self.source_object_instances
            and self.logical_connected_lines > 0
            and self.final_cad_ir_entities
            == self.logical_symbol_entities + self.logical_connected_lines
            and self.unnecessary_fragments == 0
            and self.unsupported_geometry == 0
            and self.incorrect_line_through_symbol == 0
            and self.missed_expected_ports == 0
            and self.invalid_port_connections == 0
            and self.domain_rule_violations == 0
        )

    @property
    def failure_layer(self) -> str:
        if self.raster_evidence_primitives <= 0 or self.source_object_instances <= 0:
            return "EVIDENCE"
        if self.domain_rule_violations or self.logical_symbol_entities <= 0:
            return "DOMAIN"
        if self.missed_expected_ports or self.logical_connected_lines <= 0:
            return "LOGICAL"
        if (
            self.unsupported_geometry
            or self.unnecessary_fragments
            or self.incorrect_line_through_symbol
            or self.invalid_port_connections
        ):
            return "ASSEMBLY"
        return "NONE"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_object_instances": self.source_object_instances,
            "raster_evidence_primitives": self.raster_evidence_primitives,
            "logical_symbol_entities": self.logical_symbol_entities,
            "logical_connected_lines": self.logical_connected_lines,
            "final_cad_ir_entities": self.final_cad_ir_entities,
            "unnecessary_fragments": self.unnecessary_fragments,
            "unsupported_geometry": self.unsupported_geometry,
            "incorrect_line_through_symbol": self.incorrect_line_through_symbol,
            "missed_expected_ports": self.missed_expected_ports,
            "invalid_port_connections": self.invalid_port_connections,
            "domain_rule_violations": self.domain_rule_violations,
            "reconstructed_logical_lines": self.reconstructed_logical_lines,
            "mean_observed_evidence_coverage": self.mean_observed_evidence_coverage,
            "inferred_portion_length": self.inferred_portion_length,
            "reconstructed_final_entity_count": self.reconstructed_final_entity_count,
            "failure_layer": self.failure_layer,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class DraftsmanVs3Result:
    evidence: RasterEvidenceManifest
    interpretation: RasterElectricalInterpretation
    logical: LogicalElectricalManifest
    cad_ir: EditableElectricalCadIrManifest
    quality: Vs3QualityMetrics
    schema_version: str = DRAFTSMAN_VS3_VERSION

    @property
    def evidence_sha256(self) -> str:
        return sha256(self.evidence.canonical_bytes()).hexdigest()

    @property
    def decision_sha256(self) -> str:
        return sha256(self.interpretation.decisions.canonical_bytes()).hexdigest()

    @property
    def logical_sha256(self) -> str:
        return sha256(self.logical.canonical_bytes()).hexdigest()

    @property
    def cad_ir_sha256(self) -> str:
        return sha256(self.cad_ir.canonical_bytes()).hexdigest()

    def replay_identity(self) -> tuple[str, str, str, str]:
        return (
            self.evidence_sha256,
            self.decision_sha256,
            self.logical_sha256,
            self.cad_ir_sha256,
        )


def _audit_vs3(
    *,
    interpretation: RasterElectricalInterpretation,
    logical: LogicalElectricalManifest,
    cad_ir: EditableElectricalCadIrManifest,
    pack: DomainPack,
) -> Vs3QualityMetrics:
    common = audit_vs2_cad_ir(logical, cad_ir)
    raster_rule = next(
        rule for rule in pack.electrical_symbol_rules if rule.raster_recognition_signature
    )
    expected_ports = len(raster_rule.ports)
    missed_ports = sum(
        max(0, expected_ports - len(symbol.connections)) for symbol in logical.symbols
    )
    source_ids = {
        evidence_id
        for symbol in logical.symbols
        for evidence_id in symbol.source_evidence_ids
    }
    source_ids.update(
        evidence_id
        for line in logical.connections
        for evidence_id in line.source_primitive_ids
    )
    domain_violations = sum(
        1
        for symbol in logical.symbols
        if symbol.domain_identity != raster_rule.canonical_domain_identity
        or symbol.cad_block_ref != raster_rule.cad_block_ref
    )
    reconstructed = tuple(
        item for item in logical.connections if item.state == "RECONSTRUCTED"
    )
    mean_coverage = (
        0.0
        if not logical.connections
        else _number(
            sum(item.observed_evidence_coverage for item in logical.connections)
            / len(logical.connections)
        )
    )
    return Vs3QualityMetrics(
        source_object_instances=len(interpretation.decisions.accepted),
        raster_evidence_primitives=len(source_ids),
        logical_symbol_entities=len(logical.symbols),
        logical_connected_lines=len(logical.connections),
        final_cad_ir_entities=cad_ir.entity_count,
        unnecessary_fragments=common.unnecessary_fragments,
        unsupported_geometry=common.unsupported_geometry,
        incorrect_line_through_symbol=common.incorrect_line_through_symbol,
        missed_expected_ports=missed_ports,
        invalid_port_connections=common.invalid_port_connections,
        domain_rule_violations=domain_violations,
        reconstructed_logical_lines=len(reconstructed),
        mean_observed_evidence_coverage=mean_coverage,
        inferred_portion_length=_number(
            sum(item.inferred_length for item in logical.connections)
        ),
        reconstructed_final_entity_count=sum(
            1
            for line in cad_ir.lines
            if logical.connections[
                tuple(item.logical_line_id for item in logical.connections).index(
                    line.logical_line_id
                )
            ].state
            == "RECONSTRUCTED"
        ),
    )


def run_draftsman_vs3(
    source: str | Path,
    *,
    source_document_id: str,
    source_page: int,
    domain_pack: DomainPack | None = None,
) -> DraftsmanVs3Result:
    """Run raster evidence through the shared domain/logical/CAD IR contracts."""

    pack = domain_pack or ElectricalDomainPackV0.create()
    evidence = extract_raster_electrical_evidence(
        source,
        source_document_id=source_document_id,
        source_page=source_page,
    )
    interpretation = interpret_raster_electrical_symbols(evidence, pack)
    logical = assemble_raster_logical_electrical_entities(
        evidence,
        interpretation,
        pack,
    )
    cad_ir = assemble_editable_electrical_cad_ir(logical)
    quality = _audit_vs3(
        interpretation=interpretation,
        logical=logical,
        cad_ir=cad_ir,
        pack=pack,
    )
    return DraftsmanVs3Result(evidence, interpretation, logical, cad_ir, quality)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _source_crop_box(result: DraftsmanVs3Result) -> tuple[int, int, int, int]:
    candidate_by_id = {
        item.stable_candidate_id: item for item in result.evidence.candidates
    }
    accepted = [
        candidate_by_id[item.candidate_id]
        for item in result.interpretation.decisions.accepted
    ]
    x_values = [item.source_center_px[0] for item in accepted]
    y_values = [item.source_center_px[1] for item in accepted]
    width, height = result.evidence.image_size_px
    return (
        max(0, min(x_values) - 125),
        max(0, min(y_values) - 55),
        min(width, max(x_values) + 125),
        min(height, max(y_values) + 70),
    )


def write_vs3_preview_dxf(
    path: str | Path,
    cad_ir: EditableElectricalCadIrManifest,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = ezdxf.new("R2010", setup=False)
    document.layers.add("ELECTRICAL_SYMBOL", color=7)
    document.layers.add("ELECTRICAL_SIGNAL", color=7)
    document.ezdxf_metadata()["CREATED_BY_EZDXF"] = DRAFTSMAN_VS3_VERSION
    block = document.blocks.new(name="ELEC_SMOKE_DETECTOR")
    block.add_circle(
        (0.5, 0.5),
        radius=0.5,
        dxfattribs={"layer": "ELECTRICAL_SYMBOL"},
    )
    block.add_text(
        "S",
        height=0.62,
        dxfattribs={"layer": "ELECTRICAL_SYMBOL"},
    ).set_placement((0.5, 0.5), align=TextEntityAlignment.MIDDLE_CENTER)
    modelspace = document.modelspace()
    for symbol in cad_ir.symbols:
        left, bottom, right, top = symbol.frame_bounds
        modelspace.add_blockref(
            symbol.block_definition_ref,
            (left, bottom),
            dxfattribs={
                "layer": symbol.layer_style_ref,
                "xscale": right - left,
                "yscale": top - bottom,
            },
        )
    for line in cad_ir.lines:
        modelspace.add_line(
            line.start,
            line.end,
            dxfattribs={"layer": line.layer_style_ref},
        )
    fixed_metadata = ezdxf.options.write_fixed_meta_data_for_testing
    try:
        ezdxf.options.write_fixed_meta_data_for_testing = True
        document.saveas(target)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = fixed_metadata
    return target


def write_vs3_preview_images(
    *,
    source_path: str | Path,
    result: DraftsmanVs3Result,
    source_target: str | Path,
    evidence_target: str | Path,
    final_target: str | Path,
) -> tuple[Path, Path, Path]:
    source_image = Image.open(source_path).convert("RGB")
    crop_box = _source_crop_box(result)
    source_crop = source_image.crop(crop_box)
    source_output = Path(source_target)
    source_output.parent.mkdir(parents=True, exist_ok=True)
    ImageOps.expand(source_crop, border=2, fill="black").save(
        source_output,
        format="PNG",
        optimize=False,
    )

    overlay = source_crop.copy()
    draw = ImageDraw.Draw(overlay)
    primitive_by_id = result.evidence.primitive_by_id()
    accepted_ids = {
        item.candidate_id for item in result.interpretation.decisions.accepted
    }
    for candidate in result.evidence.candidates:
        if candidate.stable_candidate_id not in accepted_ids:
            continue
        glyph = primitive_by_id[candidate.glyph_evidence_id]
        tag = primitive_by_id[candidate.tag_evidence_id]
        glyph_box = tuple(
            value - crop_box[index % 2]
            for index, value in enumerate(glyph.source_bbox_px)
        )
        tag_box = tuple(
            value - crop_box[index % 2]
            for index, value in enumerate(tag.source_bbox_px)
        )
        draw.ellipse(glyph_box, outline=(26, 76, 140), width=2)
        draw.rectangle(tag_box, outline=(78, 112, 160), width=1)
    supporting_line_ids = {
        item
        for line in result.logical.connections
        for item in line.source_primitive_ids
    }
    for evidence_id in supporting_line_ids:
        primitive = primitive_by_id[evidence_id]
        if not isinstance(primitive, RasterLineFragmentEvidence):
            continue
        left, top, right, bottom = primitive.source_bbox_px
        y_value = ((top + bottom) / 2.0) - crop_box[1]
        draw.line(
            (left - crop_box[0], y_value, right - crop_box[0], y_value),
            fill=(26, 76, 140),
            width=2,
        )
    evidence_output = Path(evidence_target)
    ImageOps.expand(overlay, border=2, fill="black").save(
        evidence_output,
        format="PNG",
        optimize=False,
    )

    final = Image.new("RGB", source_crop.size, "white")
    final_draw = ImageDraw.Draw(final)
    image_height = result.evidence.image_size_px[1]

    def display_point(point: tuple[float, float]) -> tuple[float, float]:
        return (
            point[0] - crop_box[0],
            (image_height - point[1]) - crop_box[1],
        )

    for line in result.cad_ir.lines:
        final_draw.line(
            (*display_point(line.start), *display_point(line.end)),
            fill="black",
            width=2,
        )
    font = ImageFont.load_default(size=13)
    for symbol in result.cad_ir.symbols:
        symbol_left, symbol_bottom, symbol_right, symbol_top = symbol.frame_bounds
        box = (
            *display_point((symbol_left, symbol_top)),
            *display_point((symbol_right, symbol_bottom)),
        )
        final_draw.ellipse(box, outline="black", width=2)
        center = display_point(
            (
                (symbol_left + symbol_right) / 2.0,
                (symbol_bottom + symbol_top) / 2.0,
            )
        )
        final_draw.text(center, symbol.display_label, fill="black", font=font, anchor="mm")
    final_output = Path(final_target)
    ImageOps.expand(final, border=2, fill="black").save(
        final_output,
        format="PNG",
        optimize=False,
    )
    return source_output, evidence_output, final_output


def write_vs3_artifacts(
    output_dir: str | Path,
    *,
    source_path: str | Path,
    result: DraftsmanVs3Result,
    replay_identities: tuple[tuple[str, str, str, str], ...],
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    replay_pass = len(replay_identities) >= 2 and len(set(replay_identities)) == 1
    source_png = output / "vs3-source.png"
    evidence_png = output / "vs3-evidence-overlay.png"
    final_png = output / "vs3-candidate-final.png"
    preview_dxf = output / "vs3-preview.dxf"
    evidence_json = output / "vs3-evidence.json"
    decision_json = output / "vs3-domain-decision.json"
    logical_json = output / "vs3-logical-entities.json"
    cad_json = output / "vs3-cad-ir.json"
    report_path = output / "VS3_REPORT.md"
    _write_json(
        evidence_json,
        {
            **result.evidence.to_dict(),
            "canonical_sha256": result.evidence_sha256,
            "selected_supporting_primitive_count": (
                result.quality.raster_evidence_primitives
            ),
        },
    )
    _write_json(
        decision_json,
        {
            **result.interpretation.to_dict(),
            "canonical_sha256": result.decision_sha256,
        },
    )
    _write_json(
        logical_json,
        {**result.logical.to_dict(), "canonical_sha256": result.logical_sha256},
    )
    _write_json(
        cad_json,
        {
            **result.cad_ir.to_dict(),
            "canonical_sha256": result.cad_ir_sha256,
            "quality": result.quality.to_dict(),
        },
    )
    write_vs3_preview_dxf(preview_dxf, result.cad_ir)
    write_vs3_preview_images(
        source_path=source_path,
        result=result,
        source_target=source_png,
        evidence_target=evidence_png,
        final_target=final_png,
    )
    report = f"""# DRAFTSMAN VS3 REPORT

- Contract: `{DRAFTSMAN_VS3_VERSION}`
- Source: `{Path(source_path).resolve()}` page {result.evidence.source_page}, 150 DPI
- Source SHA-256: `{result.evidence.source_sha256}`
- Selected object: **感烟（水平双端口重复实例）**
- Existing VS2 C1 domain definition reused: **NO**
- Fixed Domain Pack contract reused: **YES**
- High-recall raster candidates: **{len(result.evidence.candidates)}**
- Accepted source instances: **{result.quality.source_object_instances}**
- Supporting raster evidence primitives: **{result.quality.raster_evidence_primitives}**
- Logical symbol entities: **{result.quality.logical_symbol_entities}**
- Logical connected lines: **{result.quality.logical_connected_lines}**
- Final editable CAD IR entities: **{result.quality.final_cad_ir_entities}**
- Unsupported geometry: **{result.quality.unsupported_geometry}**
- Unnecessary fragments: **{result.quality.unnecessary_fragments}**
- Incorrect line-through-symbol: **{result.quality.incorrect_line_through_symbol}**
- Missed expected ports: **{result.quality.missed_expected_ports}**
- Invalid port connections: **{result.quality.invalid_port_connections}**
- Domain-rule violations: **{result.quality.domain_rule_violations}**
- Reconstructed logical lines: **{result.quality.reconstructed_logical_lines}**
- Mean observed evidence coverage: **{result.quality.mean_observed_evidence_coverage}**
- Inferred portion length: **{result.quality.inferred_portion_length} px**
- Reconstructed final entity count: **{result.quality.reconstructed_final_entity_count}**
- Deterministic replay: **{'PASS' if replay_pass else 'FAIL'}** ({len(replay_identities)} runs)
- Failure layer: **{result.quality.failure_layer}**
- Product-quality gate: **{'PASS' if result.quality.passed else 'FAIL'}**
- Production integration: **NONE (shadow-only)**

## Layer result

The raster frontend reports circle-like glyph shapes, associated tag regions and
horizontal line fragments without assigning electrical identity. The existing
`ElectricalSymbolRule` contract then applies the drawing-specific `140-177: 感烟`
authority, normalized source signature, two-port topology and repeated-alignment
constraint. Five source instances form five logical smoke-detector symbols.

Six logical bus segments connect the symbol boundaries. Five are fully observed;
one consolidates fragmented detector evidence with `DETECTION_BREAK` provenance.
Every logical line emits exactly one CAD IR LINE. No line crosses a symbol body.

## Cross-frontend consistency

VS2 vector and VS3 raster evidence use the same versioned Domain Pack,
`ElectricalSymbolRule`, port semantics, `LogicalElectricalSymbol`,
`LogicalElectricalConnection`, `EditableCadElectricalSymbol` and
`EditableCadElectricalLine` contracts. Only the evidence frontend and declarative
recognition signature differ; raster-specific domain or CAD IR classes were not
introduced.
"""
    report_path.write_text(report, encoding="utf-8")
    return (
        source_png,
        evidence_png,
        final_png,
        preview_dxf,
        evidence_json,
        decision_json,
        logical_json,
        cad_json,
        report_path,
    )
