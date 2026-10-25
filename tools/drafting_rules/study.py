"""Reproduce one real bilingual title-block cell and fail controlled bad edits.

Uses the repository's retained PDF and reviewed OCR observations. No OCR/model
inference, downloads, automatic correction or production-entry integration.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from unittest.mock import patch

import cv2
import ezdxf

from tools.drafting_rules.cli import ROOT, validate_files, compare_reports
from tools.drafting_rules.dxf_adapter import sha256


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def run(output):
    # Exclusive directory creation preserves previous runs, including failures.
    output.mkdir(parents=True, exist_ok=False)
    from tests.test_table_text_layout import local_region
    from app.core.structure_build import final_structure_from_trace_result
    from app.core.preview import render_emitted_dxf_preview
    from app.export.trace_single_export import export_final_structure_dxf
    from app.geometry import optimized_trace
    from app.ocr.ocr_fast import prepare_safe_candidate

    source = ROOT / "cad_photo_to_dxf/tests/real_regression/assets/sources/warehouse-electrical-vector.pdf"
    gray, candidates = local_region()
    if not cv2.imwrite(str(output / "source-crop.png"), gray):
        raise OSError("Could not retain source crop")
    # Explicit saved-observation injection, matching the existing regression.
    # This is not a fresh recognition result and does not test OCR correctness.
    with patch.object(optimized_trace, "recognize_text_candidates_optimized", return_value=(
        tuple(prepare_safe_candidate(gray, t) for t in candidates), (),
    )):
        traced = optimized_trace.trace_image_optimized(
            gray, enable_ocr=True, source_dpi=136, foreground_threshold=254)
    structure = final_structure_from_trace_result(traced)
    before = output / "baseline.dxf"
    export_final_structure_dxf(structure, before)
    doc = ezdxf.readfile(before)
    texts = list(doc.modelspace().query("TEXT"))
    assert Counter(t.dxf.text for t in texts) == Counter(t.text for t in candidates)
    target = next(t for t in texts if t.dxf.text == "Discipline")
    target.dxf.text = "DisciplineA"
    after = output / "edited.dxf"
    doc.saveas(after)
    restored = ezdxf.readfile(after)
    assert restored.entitydb[target.dxf.handle].dxf.text == "DisciplineA"
    # The bounds come from the existing complete-cell proof in ocr_layout;
    # these fixture coordinates are observations, never engine constants.
    evidence = dict(schema_version=1,
                    source=dict(sha256=sha256(source), page=2, region=[4080, 2200, 4390, 2410],
                                authority="main test_table_text_layout.local_region; saved OCR observations; inner cell source window [74,78,178,129]",
                                units="source_pixel"),
                    before_sha256=sha256(before), after_sha256=sha256(after),
                    texts=[dict(id=f"row-{i}", handle=t.dxf.handle, expected_text=t.dxf.text,
                                cell=[74, 210 - 129, 178, 210 - 78]) for i, t in enumerate(texts)],
                    edit=dict(allowed_handles=[target.dxf.handle]))
    # No manufactured ownership of source outlines, background or line segments.
    # Those rules must abstain on this old DXF's insufficient member mappings.
    path = output / "evidence.json"
    write_json(path, evidence)
    positive = validate_files(before, after, source, path)
    write_json(output / "edited.report.json", positive)
    preview = render_emitted_dxf_preview(restored, output, structure.source_size_px)
    assert cv2.imwrite(str(output / "edited-preview.png"), preview)

    # Same actual saved CAD with a too-wide text edit, then with a non-target move.
    target = restored.entitydb[target.dxf.handle]
    target.dxf.text = "Discipline" * 8
    bad = output / "overflow.dxf"
    restored.saveas(bad)
    bad_evidence = json.loads(json.dumps(evidence))
    bad_evidence["after_sha256"] = sha256(bad)
    next(t for t in bad_evidence["texts"] if t["handle"] == target.dxf.handle)["expected_text"] = target.dxf.text
    bad_path = output / "overflow.evidence.json"
    write_json(bad_path, bad_evidence)
    negative = validate_files(before, bad, source, bad_path)
    write_json(output / "overflow.report.json", negative)
    write_json(output / "comparison.json", compare_reports(positive, negative))
    assert any(r["rule"] == "cell-fit" and r["status"] == "FAIL" for r in negative["results"])

    other = next(e for e in restored.modelspace() if e.dxftype() == "LWPOLYLINE")
    other.translate(1, 0, 0)
    changed = output / "unrelated-change.dxf"
    restored.saveas(changed)
    bad_evidence["after_sha256"] = sha256(changed)
    changed_evidence = output / "unrelated-change.evidence.json"
    write_json(changed_evidence, bad_evidence)
    collateral = validate_files(before, changed, source, changed_evidence)
    write_json(output / "unrelated-change.report.json", collateral)
    assert any(r["rule"] == "edit-isolation" and r["status"] == "FAIL" for r in collateral["results"])
    assert sha256(source) == evidence["source"]["sha256"]
    summary = dict(source=evidence["source"], baseline_entities=dict(Counter(e.dxftype() for e in doc.modelspace())),
                   positive=positive["summary"], overflow=negative["summary"], collateral=collateral["summary"],
                   baseline_dxf_sha256=sha256(before), edited_dxf_sha256=sha256(after),
                   recognition="NOT_RUN; reused saved OCR observations", editor="NOT_RUN",
                   production_entry="UNCHANGED", source_glyph_coverage="ABSTAIN; no complete saved member mapping",
                   background="ABSTAIN; no independent background mapping", table_lines="ABSTAIN; no complete source segment mapping")
    write_json(output / "study.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory under local-artifacts")
    args = parser.parse_args()
    print(json.dumps(run(args.output.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
