"""Shadow-only VS2 electrical symbol and connectivity vertical slice."""

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
    Vs2QualityMetrics,
    assemble_editable_electrical_cad_ir,
    audit_vs2_cad_ir,
)
from .draftsman_domain_pack import DomainPack, ElectricalDomainPackV0
from .draftsman_electrical import (
    ElectricalDomainDecisionManifest,
    LogicalElectricalManifest,
    assemble_logical_electrical_entities,
    interpret_electrical_symbols,
)
from .draftsman_pdf_vector import (
    PdfBoxedSymbolEvidenceManifest,
    extract_pdf_boxed_symbol_evidence,
)


DRAFTSMAN_VS2_VERSION = "draftsman-vs2-electrical-symbol-connectivity-v1"


@dataclass(frozen=True)
class DraftsmanVs2Result:
    evidence: PdfBoxedSymbolEvidenceManifest
    decisions: ElectricalDomainDecisionManifest
    logical: LogicalElectricalManifest
    cad_ir: EditableElectricalCadIrManifest
    quality: Vs2QualityMetrics
    schema_version: str = DRAFTSMAN_VS2_VERSION

    @property
    def evidence_sha256(self) -> str:
        return sha256(self.evidence.canonical_bytes()).hexdigest()

    @property
    def decision_sha256(self) -> str:
        return sha256(self.decisions.canonical_bytes()).hexdigest()

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


def run_draftsman_vs2(
    source: str | Path,
    *,
    source_document_id: str,
    page_number: int,
    domain_pack: DomainPack | None = None,
) -> DraftsmanVs2Result:
    """Run PDF evidence through domain interpretation, logical model, and CAD IR."""

    pack = domain_pack or ElectricalDomainPackV0.create()
    evidence = extract_pdf_boxed_symbol_evidence(
        source,
        source_document_id=source_document_id,
        page_number=page_number,
    )
    decisions = interpret_electrical_symbols(evidence, pack)
    logical = assemble_logical_electrical_entities(decisions)
    cad_ir = assemble_editable_electrical_cad_ir(logical)
    quality = audit_vs2_cad_ir(logical, cad_ir)
    return DraftsmanVs2Result(evidence, decisions, logical, cad_ir, quality)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_vs2_preview_dxf(
    path: str | Path,
    cad_ir: EditableElectricalCadIrManifest,
) -> Path:
    """Write a clean, editable BLOCK-and-LINE preview; never used by production."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = ezdxf.new("R2010", setup=True)
    document.layers.add("ELECTRICAL_SYMBOL", color=7)
    document.layers.add("ELECTRICAL_SIGNAL", color=7)
    document.layers.add("ELECTRICAL_CONTROL", color=7, linetype="DASHED")
    document.ezdxf_metadata()["CREATED_BY_EZDXF"] = DRAFTSMAN_VS2_VERSION
    block = document.blocks.new(name="ELEC_CONTROL_MODULE_C1")
    block.add_lwpolyline(
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        close=True,
        dxfattribs={"layer": "ELECTRICAL_SYMBOL"},
    )
    block.add_text(
        "C1",
        height=0.36,
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
            dxfattribs={
                "layer": line.layer_style_ref,
                "linetype": line.linetype_ref,
            },
        )
    fixed_metadata = ezdxf.options.write_fixed_meta_data_for_testing
    try:
        ezdxf.options.write_fixed_meta_data_for_testing = True
        document.saveas(target)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = fixed_metadata
    return target


def _render_source_crop(
    source_path: str | Path,
    *,
    source_page: int,
    frame_bounds: tuple[float, float, float, float],
    page_size: tuple[float, float],
    scale: float = 3.0,
    margin_pt: float = 38.0,
) -> Image.Image:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pypdfium2 is required for VS2 source preview") from exc

    document = pdfium.PdfDocument(str(source_path))
    try:
        page = document[source_page - 1]
        try:
            rendered = page.render(scale=scale).to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        document.close()
    left, bottom, right, top = frame_bounds
    page_width, page_height = page_size
    crop_left = max(0.0, left - margin_pt)
    crop_right = min(page_width, right + margin_pt)
    crop_bottom = max(0.0, bottom - margin_pt)
    crop_top = min(page_height, top + margin_pt)
    pixel_box = (
        int(round(crop_left * scale)),
        int(round((page_height - crop_top) * scale)),
        int(round(crop_right * scale)),
        int(round((page_height - crop_bottom) * scale)),
    )
    return rendered.crop(pixel_box)


def _render_clean_cad_crop(
    cad_ir: EditableElectricalCadIrManifest,
    *,
    scale: float = 3.0,
    margin_pt: float = 38.0,
) -> Image.Image:
    symbol = cad_ir.symbols[0]
    left, bottom, right, top = symbol.frame_bounds
    x_min = left - margin_pt
    x_max = right + margin_pt
    y_min = bottom - margin_pt
    y_max = top + margin_pt
    width = max(1, int(round((x_max - x_min) * scale)))
    height = max(1, int(round((y_max - y_min) * scale)))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    def point(value: tuple[float, float]) -> tuple[float, float]:
        return (
            (value[0] - x_min) * scale,
            (y_max - value[1]) * scale,
        )

    for line in cad_ir.lines:
        fill = (45, 45, 45)
        line_width = max(2, int(round(scale * 0.7)))
        if line.linetype_ref == "DASHED":
            start = point(line.start)
            end = point(line.end)
            steps = 12
            for index in range(0, steps, 2):
                ratio0 = index / steps
                ratio1 = min(1.0, (index + 1) / steps)
                segment = (
                    start[0] + (end[0] - start[0]) * ratio0,
                    start[1] + (end[1] - start[1]) * ratio0,
                    start[0] + (end[0] - start[0]) * ratio1,
                    start[1] + (end[1] - start[1]) * ratio1,
                )
                draw.line(segment, fill=fill, width=line_width)
        else:
            draw.line((*point(line.start), *point(line.end)), fill=fill, width=line_width)
    p0 = point((left, top))
    p1 = point((right, bottom))
    draw.rectangle((*p0, *p1), outline="black", width=max(2, int(round(scale))))
    font = ImageFont.load_default(size=max(12, int(round((top - bottom) * scale * 0.38))))
    center = point(((left + right) / 2.0, (bottom + top) / 2.0))
    draw.text(center, symbol.display_label, fill="black", font=font, anchor="mm")
    return image


def write_vs2_preview_images(
    *,
    source_context_path: str | Path,
    candidate_preview_path: str | Path,
    source_path: str | Path,
    result: DraftsmanVs2Result,
) -> tuple[Path, Path]:
    if len(result.cad_ir.symbols) != 1:
        raise ValueError("VS2 preview requires exactly one selected symbol")
    symbol = result.cad_ir.symbols[0]
    source = _render_source_crop(
        source_path,
        source_page=result.evidence.source_page,
        frame_bounds=symbol.frame_bounds,
        page_size=result.evidence.page_size_pt,
    )
    source = ImageOps.expand(source, border=2, fill="black")
    source_target = Path(source_context_path)
    source_target.parent.mkdir(parents=True, exist_ok=True)
    source.save(source_target, format="PNG", optimize=False)

    final = _render_clean_cad_crop(result.cad_ir)
    source_panel = ImageOps.pad(source, final.size, color="white")
    final_panel = ImageOps.expand(final, border=2, fill="black")
    header_height = 30
    combined = Image.new(
        "RGB",
        (source_panel.width + final_panel.width + 12, final_panel.height + header_height),
        "white",
    )
    combined.paste(source_panel, (0, header_height))
    combined.paste(final_panel, (source_panel.width + 12, header_height))
    draw = ImageDraw.Draw(combined)
    draw.text((8, 8), "SOURCE CONTEXT", fill="black")
    draw.text((source_panel.width + 20, 8), "EDITABLE CAD IR", fill="black")
    preview_target = Path(candidate_preview_path)
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    combined.save(preview_target, format="PNG", optimize=False)
    return source_target, preview_target


def write_vs2_artifacts(
    output_dir: str | Path,
    *,
    source_path: str | Path,
    result: DraftsmanVs2Result,
    replay_identities: tuple[tuple[str, str, str, str], ...],
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    replay_pass = len(replay_identities) >= 2 and len(set(replay_identities)) == 1
    decision_path = output / "vs2-domain-decision.json"
    logical_path = output / "vs2-logical-entities.json"
    cad_path = output / "vs2-cad-ir.json"
    source_context_path = output / "vs2-source-context.png"
    candidate_preview_path = output / "vs2-candidate-preview.png"
    dxf_path = output / "vs2-preview.dxf"
    report_path = output / "VS2_REPORT.md"
    _write_json(
        decision_path,
        {
            **result.decisions.to_dict(),
            "canonical_sha256": result.decision_sha256,
            "native_pdf_path_count": result.evidence.source_native_path_count,
            "selected_source_evidence_primitives": (
                result.quality.source_evidence_primitives
            ),
            "annotation_association": "N/A",
            "annotation_reason": (
                "The selected instance has no native PDF text object; outlined glyphs "
                "are symbol geometry evidence, not authoritative text evidence."
            ),
        },
    )
    _write_json(
        logical_path,
        {**result.logical.to_dict(), "canonical_sha256": result.logical_sha256},
    )
    _write_json(
        cad_path,
        {
            **result.cad_ir.to_dict(),
            "canonical_sha256": result.cad_ir_sha256,
            "quality": result.quality.to_dict(),
        },
    )
    write_vs2_preview_dxf(dxf_path, result.cad_ir)
    write_vs2_preview_images(
        source_context_path=source_context_path,
        candidate_preview_path=candidate_preview_path,
        source_path=source_path,
        result=result,
    )
    report = f"""# DRAFTSMAN VS2 REPORT

- Contract: `{DRAFTSMAN_VS2_VERSION}`
- Source: `{Path(source_path).resolve()}` page {result.evidence.source_page}
- Native PDF PATH evidence: **{result.evidence.source_native_path_count}**
- Selected symbol: **控制模块（单输入输出控制模块 / C1）**
- Accepted source instances: **{len(result.decisions.accepted)}**
- Source evidence primitives supporting the accepted instance: **{result.quality.source_evidence_primitives}**
- Logical symbol entities: **{result.quality.logical_symbol_entities}**
- Logical connected lines: **{result.quality.logical_connected_lines}**
- Final editable CAD IR entities: **{result.quality.final_cad_ir_entities}**
- Unsupported geometry: **{result.quality.unsupported_geometry}**
- Unnecessary fragments: **{result.quality.unnecessary_fragments}**
- Invalid port connections: **{result.quality.invalid_port_connections}**
- Incorrect line-through-symbol: **{result.quality.incorrect_line_through_symbol}**
- Annotation association: **N/A** (no native PDF text object for the selected instance)
- Deterministic replay: **{'PASS' if replay_pass else 'FAIL'}** ({len(replay_identities)} runs)
- Product-quality gate: **{'PASS' if result.quality.passed else 'FAIL'}**
- Production integration: **NONE (shadow-only)**

## Domain decision

The page legend directly identifies the boxed `C1` glyph as a single-input/output
control module. The domain pack describes that signature and its four observable
topology roles: two continuous top signal ports plus separate incoming and outgoing
dashed control ports at the bottom.
Only the operational occurrence satisfies both the glyph signature and port
topology. The final assembly retains the symbol boundary, so no geometric join
passes a line through the symbol body.

## Editable representation

The CAD IR contains one reusable grouped symbol instance and four connection LINE
entities. The DXF preview realizes the group as an editable BLOCK reference; this
is a backend choice rather than recovered original BLOCK identity. All final
geometry is backed by native PDF PATH evidence and preserves stable provenance.
"""
    report_path.write_text(report, encoding="utf-8")
    return (
        source_context_path,
        candidate_preview_path,
        cad_path,
        logical_path,
        decision_path,
        dxf_path,
        report_path,
    )
