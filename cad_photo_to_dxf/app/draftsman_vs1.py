"""Shadow-only VS1 orchestration and human-readable preview artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import ezdxf
from PIL import Image, ImageDraw

from .draftsman_cad_ir import (
    EditableCadIrManifest,
    Vs1QualityMetrics,
    assemble_editable_cad_ir,
    audit_vs1_cad_ir,
)
from .draftsman_domain_pack import DomainPack, ElectricalDomainPackV0
from .draftsman_logical import LogicalDrawingManifest, assemble_logical_table_rules
from .draftsman_pdf_evidence import (
    PdfPathEvidenceManifest,
    extract_pdf_path_evidence,
)


DRAFTSMAN_VS1_VERSION = "draftsman-vs1-vector-table-rule-v1"


@dataclass(frozen=True)
class DraftsmanVs1Result:
    evidence: PdfPathEvidenceManifest
    logical: LogicalDrawingManifest
    cad_ir: EditableCadIrManifest
    quality: Vs1QualityMetrics
    schema_version: str = DRAFTSMAN_VS1_VERSION

    @property
    def evidence_sha256(self) -> str:
        return sha256(self.evidence.canonical_bytes()).hexdigest()

    @property
    def logical_sha256(self) -> str:
        return sha256(self.logical.canonical_bytes()).hexdigest()

    @property
    def cad_ir_sha256(self) -> str:
        return sha256(self.cad_ir.canonical_bytes()).hexdigest()

    def replay_identity(self) -> tuple[str, str, str]:
        return self.evidence_sha256, self.logical_sha256, self.cad_ir_sha256


def run_draftsman_vs1(
    source: str | Path,
    *,
    source_document_id: str,
    page_number: int,
    expected_logical_entity_count: int,
    domain_pack: DomainPack | None = None,
) -> DraftsmanVs1Result:
    """Run the independent vector-evidence-to-CAD-IR shadow slice."""

    pack = domain_pack or ElectricalDomainPackV0.create()
    evidence = extract_pdf_path_evidence(
        source,
        source_document_id=source_document_id,
        page_number=page_number,
    )
    logical = assemble_logical_table_rules(evidence, pack)
    cad_ir = assemble_editable_cad_ir(logical)
    quality = audit_vs1_cad_ir(
        logical,
        cad_ir,
        expected_logical_entity_count=expected_logical_entity_count,
    )
    return DraftsmanVs1Result(evidence, logical, cad_ir, quality)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_vs1_preview_dxf(
    path: str | Path,
    cad_ir: EditableCadIrManifest,
) -> Path:
    """Write a simple line-only preview; never used by production export."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = ezdxf.new("R2010", setup=False)
    document.layers.add("TABLE_RULE", color=7)
    document.ezdxf_metadata()["CREATED_BY_EZDXF"] = DRAFTSMAN_VS1_VERSION
    modelspace = document.modelspace()
    for line in sorted(
        cad_ir.lines,
        key=lambda item: (item.start[1], item.start[0], item.stable_entity_id),
    ):
        modelspace.add_line(
            line.start,
            line.end,
            dxfattribs={"layer": "TABLE_RULE", "color": 7},
        )
    fixed_metadata = ezdxf.options.write_fixed_meta_data_for_testing
    try:
        ezdxf.options.write_fixed_meta_data_for_testing = True
        document.saveas(target)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = fixed_metadata
    return target


def write_vs1_preview_png(
    path: str | Path,
    cad_ir: EditableCadIrManifest,
    *,
    scale: float = 2.0,
    margin_px: int = 32,
) -> Path:
    """Render only assembled CAD IR lines, with no raster evidence substitution."""

    if not cad_ir.lines:
        raise ValueError("Cannot preview an empty CAD IR")
    x_min = min(line.start[0] for line in cad_ir.lines)
    x_max = max(line.end[0] for line in cad_ir.lines)
    y_min = min(line.start[1] for line in cad_ir.lines)
    y_max = max(line.end[1] for line in cad_ir.lines)
    width = int(round((x_max - x_min) * scale)) + margin_px * 2
    height = int(round((y_max - y_min) * scale)) + margin_px * 2
    image = Image.new("RGB", (max(width, 1), max(height, 1)), "white")
    draw = ImageDraw.Draw(image)
    for line in cad_ir.lines:
        start = (
            margin_px + (line.start[0] - x_min) * scale,
            margin_px + (y_max - line.start[1]) * scale,
        )
        end = (
            margin_px + (line.end[0] - x_min) * scale,
            margin_px + (y_max - line.end[1]) * scale,
        )
        draw.line((start, end), fill="black", width=2)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=False)
    return target


def write_vs1_artifacts(
    output_dir: str | Path,
    *,
    source_path: str | Path,
    result: DraftsmanVs1Result,
    replay_identities: tuple[tuple[str, str, str], ...],
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    target_fragment_ids = sorted(
        {
            fragment_id
            for rule in result.logical.table_rules
            for fragment_id in rule.source_fragment_ids
        }
    )
    target_path_ids = sorted(
        {
            path_id
            for rule in result.logical.table_rules
            for path_id in rule.source_path_evidence_ids
        }
    )
    replay_pass = len(set(replay_identities)) == 1 and len(replay_identities) >= 2
    evidence_summary = {
        "schema_version": DRAFTSMAN_VS1_VERSION,
        "source": {
            "path": str(Path(source_path).resolve()),
            "source_document_id": result.evidence.source_document_id,
            "source_page": result.evidence.source_page,
            "source_sha256": result.evidence.source_sha256,
            "page_size_pt": list(result.evidence.page_size_pt),
            "page_transform_id": result.evidence.page_transform_id,
        },
        "evidence_manifest_id": result.evidence.manifest_id,
        "evidence_sha256": result.evidence_sha256,
        "native_pdf_path_evidence": result.evidence.native_path_count,
        "target_row_rule_evidence": len(target_fragment_ids),
        "target_source_fragment_ids": target_fragment_ids,
        "target_source_path_evidence_ids": target_path_ids,
        "replay": {
            "runs": len(replay_identities),
            "passed": replay_pass,
            "identities": [list(identity) for identity in replay_identities],
        },
    }

    evidence_path = output / "vs1-evidence-summary.json"
    logical_path = output / "vs1-logical-entities.json"
    cad_path = output / "vs1-cad-ir.json"
    dxf_path = output / "vs1-preview.dxf"
    png_path = output / "vs1-preview.png"
    report_path = output / "VS1_REPORT.md"
    _write_json(evidence_path, evidence_summary)
    _write_json(
        logical_path,
        {
            **result.logical.to_dict(),
            "canonical_sha256": result.logical_sha256,
        },
    )
    _write_json(
        cad_path,
        {
            **result.cad_ir.to_dict(),
            "canonical_sha256": result.cad_ir_sha256,
            "quality": result.quality.to_dict(),
        },
    )
    write_vs1_preview_dxf(dxf_path, result.cad_ir)
    write_vs1_preview_png(png_path, result.cad_ir)
    report = f"""# DRAFTSMAN VS1 REPORT

- Contract: `{DRAFTSMAN_VS1_VERSION}`
- Source: `{Path(source_path).resolve()}` page {result.evidence.source_page}
- Source SHA-256: `{result.evidence.source_sha256}`
- Native PDF PATH evidence: **{result.evidence.native_path_count}**
- Target row-rule evidence fragments: **{len(target_fragment_ids)}**
- Logical `TABLE_RULE`: **{len(result.logical.table_rules)}**
- Editable CAD IR `LINE`: **{len(result.cad_ir.lines)}**
- Final CAD entities per logical rule: **{result.quality.final_entities_per_logical_rule}**
- Unnecessary fragments: **{result.quality.unnecessary_fragments}**
- Unsupported geometry: **{result.quality.unsupported_geometry}**
- Missing logical entities: **{result.quality.missing_logical_entities}**
- Extra logical entities: **{result.quality.extra_logical_entities}**
- Deterministic replay: **{'PASS' if replay_pass else 'FAIL'}** ({len(replay_identities)} runs)
- Product-quality gate: **{'PASS' if result.quality.passed else 'FAIL'}**
- Production integration: **NONE (shadow-only)**

The DXF and PNG previews contain only the final assembled row-rule lines. They do
not contain raster detector output, source underlay, candidate fragments, or M3
diagnostic layers. Every CAD IR line references one LogicalTableRule, and every
LogicalTableRule retains its native PDF path/fragment provenance.
"""
    report_path.write_text(report, encoding="utf-8")
    return evidence_path, logical_path, cad_path, dxf_path, png_path, report_path
