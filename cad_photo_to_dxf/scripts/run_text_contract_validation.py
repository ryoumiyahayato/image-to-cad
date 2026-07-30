from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any, Mapping

import cv2
import ezdxf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.optimized_trace import trace_image_optimized  # noqa: E402
from app.text_output_contract import (  # noqa: E402
    TextOutputState,
    decide_text_output,
    text_output_decisions,
    text_output_summary,
)
from app.trace_single_export import export_final_structure_dxf  # noqa: E402


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _decision_signature(decision: Any) -> tuple[object, ...]:
    return (
        decision.state.value,
        decision.output_layer,
        decision.editable,
        decision.downgrade_reason,
    )


def _font_independent(decision: Any) -> bool:
    candidate = decision.candidate
    variants = (
        candidate.__class__(
            **{
                **candidate.__dict__,
                "font_family": "Contract TTF",
                "font_file": "contract.ttf",
            }
        ),
        candidate.__class__(
            **{
                **candidate.__dict__,
                "font_family": "Contract LFF",
                "font_file": "contract.lff",
            }
        ),
    )
    expected = _decision_signature(decision)
    return all(
        _decision_signature(decide_text_output(item)) == expected
        for item in variants
    )


def _xdata_complete(entity: Any) -> bool:
    try:
        tags = entity.get_xdata("TEXT_OUTPUT_CONTRACT")
    except ezdxf.DXFValueError:
        return False
    strings = [str(tag.value) for tag in tags if tag.code == 1000]
    floats = [float(tag.value) for tag in tags if tag.code == 1040]
    integers = [int(tag.value) for tag in tags if tag.code == 1070]
    return bool(
        len(strings) >= 5
        and strings[0] == "editable_text"
        and len(floats) >= 4
        and integers
        and integers[0] == 1
    )


def _outline_source_pixels(
    structure: Any,
    decisions: tuple[Any, ...],
    state: TextOutputState,
) -> int:
    total = 0
    height, width = structure.contour_binary.shape
    for decision in decisions:
        if decision.state is not state:
            continue
        x, y, box_width, box_height = (
            int(value) for value in decision.candidate.bbox
        )
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + box_width)
        bottom = min(height, y + box_height)
        if right <= left or bottom <= top:
            continue
        total += int(
            cv2.countNonZero(
                255
                - structure.contour_binary[
                    top:bottom,
                    left:right,
                ]
            )
        )
    return total


def _document_record(
    document: Mapping[str, Any],
    *,
    artifacts: Path,
) -> dict[str, Any]:
    raster_path = Path(str(document["raster_path"]))
    image = cv2.imread(str(raster_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"Could not load validation page: {raster_path}")

    started = perf_counter()
    trace_result = trace_image_optimized(
        image,
        enable_ocr=True,
        source_dpi=float(document["page"]["dpi"]),
    )
    structure = trace_result.final_structure
    if structure is None:
        raise AssertionError("Trace pipeline did not produce FinalStructure")
    structure.assert_valid()

    artifacts.mkdir(parents=True, exist_ok=True)
    dxf_path = artifacts / f"{document['id']}.dxf"
    export_result = export_final_structure_dxf(
        structure,
        dxf_path,
    )
    dxf = ezdxf.readfile(dxf_path)
    audit = dxf.audit()
    modelspace = dxf.modelspace()
    decisions = text_output_decisions(structure.texts)
    repeated = text_output_decisions(structure.texts)
    summary = text_output_summary(structure.texts)

    layer_entity_counts: Counter[str] = Counter(
        str(entity.dxf.layer) for entity in modelspace
    )
    native_texts = list(modelspace.query("TEXT"))
    images = list(modelspace.query("IMAGE"))
    editable_count = sum(
        decision.state is TextOutputState.EDITABLE_TEXT
        for decision in decisions
    )
    fallback_count = sum(
        decision.state is TextOutputState.TEXT_FALLBACK_OUTLINE
        for decision in decisions
    )
    residual_count = sum(
        decision.state is TextOutputState.RESIDUAL_GRAPHIC
        for decision in decisions
    )
    fallback_outline_source_pixels = _outline_source_pixels(
        structure,
        decisions,
        TextOutputState.TEXT_FALLBACK_OUTLINE,
    )
    residual_outline_source_pixels = _outline_source_pixels(
        structure,
        decisions,
        TextOutputState.RESIDUAL_GRAPHIC,
    )
    state_stable = (
        [_decision_signature(item) for item in decisions]
        == [_decision_signature(item) for item in repeated]
    )
    font_independent = all(
        _font_independent(decision) for decision in decisions
    )
    reasons_complete = (
        sum(dict(summary.downgrade_reasons).values())
        == fallback_count + residual_count
    )
    checks = {
        "native_text_count_matches_contract": (
            len(native_texts)
            == export_result.text_count
            == editable_count
        ),
        "native_texts_use_ocr_text_layer": all(
            str(entity.dxf.layer) == "OCR_TEXT"
            for entity in native_texts
        ),
        "native_text_xdata_complete": all(
            _xdata_complete(entity) for entity in native_texts
        ),
        "fallback_layer_present_when_required": (
            fallback_outline_source_pixels == 0
            or layer_entity_counts["TEXT_FALLBACK_OUTLINE"] > 0
        ),
        "residual_layer_present_when_required": (
            residual_outline_source_pixels == 0
            or layer_entity_counts["RESIDUAL_GRAPHIC"] > 0
        ),
        "no_unexpected_fallback_layer_entities": (
            fallback_count > 0
            or layer_entity_counts["TEXT_FALLBACK_OUTLINE"] == 0
        ),
        "no_unexpected_residual_layer_entities": (
            residual_count > 0
            or layer_entity_counts["RESIDUAL_GRAPHIC"] == 0
        ),
        "images_are_reliable_signatures_only": (
            len(images)
            == len(structure.signatures)
            == export_result.signature_count
            and all(
                str(entity.dxf.layer) == "SIGNATURE_OVERLAY"
                for entity in images
            )
        ),
        "export_statistics_match_contract": (
            export_result.ocr_candidate_count
            == summary.ocr_candidate_count
            and export_result.fallback_text_count
            == summary.fallback_outline_count
            and export_result.residual_graphic_count
            == summary.residual_graphic_count
            and export_result.logo_count == len(structure.logos)
            and export_result.signature_count
            == len(structure.signatures)
            and dict(export_result.text_downgrade_reasons)
            == dict(summary.downgrade_reasons)
        ),
        "downgrade_reasons_complete": reasons_complete,
        "same_evidence_same_state": state_stable,
        "font_choice_does_not_change_editability": font_independent,
        "dxf_audit_passed": not audit.errors,
    }
    return {
        "id": str(document["id"]),
        "page": dict(document["page"]),
        "raster_path": str(raster_path.resolve()),
        "raster_sha256": _file_sha256(raster_path),
        "dxf_path": str(dxf_path.resolve()),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "structure_id": structure.structure_id,
        "ocr_candidate_count": summary.ocr_candidate_count,
        "text_count": summary.editable_text_count,
        "fallback_count": summary.fallback_outline_count,
        "residual_count": summary.residual_graphic_count,
        "fallback_outline_source_pixels": (
            fallback_outline_source_pixels
        ),
        "residual_outline_source_pixels": (
            residual_outline_source_pixels
        ),
        "logo_count": len(structure.logos),
        "signature_count": len(structure.signatures),
        "downgrade_reasons": dict(summary.downgrade_reasons),
        "layer_entity_counts": dict(sorted(layer_entity_counts.items())),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _run(args: argparse.Namespace) -> int:
    manifest_path = args.input_manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = args.artifacts.resolve()
    documents = [
        _document_record(document, artifacts=artifacts)
        for document in manifest["documents"]
    ]

    totals: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for document in documents:
        for key in (
            "ocr_candidate_count",
            "text_count",
            "fallback_count",
            "residual_count",
            "logo_count",
            "signature_count",
        ):
            totals[key] += int(document[key])
        reasons.update(document["downgrade_reasons"])

    acceptance = {
        "minimum_ten_pages": len(documents) >= 10,
        "all_documents_passed": all(
            document["passed"] for document in documents
        ),
        "ocr_candidates_observed": totals["ocr_candidate_count"] > 0,
        "native_text_observed": totals["text_count"] > 0,
        "fallback_outline_observed": totals["fallback_count"] > 0,
        "residual_graphic_observed": totals["residual_count"] > 0,
        "every_downgrade_has_reason": (
            sum(reasons.values())
            == totals["fallback_count"] + totals["residual_count"]
        ),
    }
    payload = {
        "schema_version": 1,
        "git_commit": _git_commit(),
        "input_manifest": str(manifest_path),
        "input_manifest_sha256": _file_sha256(manifest_path),
        "document_count": len(documents),
        "aggregate": {
            **dict(sorted(totals.items())),
            "downgrade_reasons": dict(sorted(reasons.items())),
            "document_elapsed_total_seconds": round(
                sum(
                    float(document["elapsed_seconds"])
                    for document in documents
                ),
                3,
            ),
        },
        "acceptance": acceptance,
        "documents": documents,
    }
    _write_json(args.output.resolve(), payload)
    print(args.output.resolve())
    if args.enforce and not all(acceptance.values()):
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate stable OCR TEXT, fallback outline, residual graphic, "
            "Logo and signature output semantics on real pages."
        )
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true")
    return parser


def main() -> int:
    return _run(_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
