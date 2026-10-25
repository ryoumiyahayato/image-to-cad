"""Bounded real-source study. Fixture creation edits copies; adapter is read-only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import ezdxf

from tools.drafting_rules.cli import ROOT, validate_files, compare_reports
from tools.drafting_rules.dxf_adapter import sha256
from tools.drafting_rules.source_adapter import validate_with_source
from tools.drafting_rules.study import write_json


SOURCE = ROOT / "cad_photo_to_dxf/tests/real_regression/assets/sources/warehouse-electrical-vector.pdf"


def make_case(output, crop, candidates, edit_text):
    from app.core.cache import save_trace_cache
    from app.core.image_loader import load_image
    from app.export.trace_single_export import export_final_structure_dxf
    from app.geometry import optimized_trace
    from app.ocr.ocr_fast import prepare_safe_candidate
    from app.ocr.ocr_layout import offset_candidate

    output.mkdir(parents=True, exist_ok=False)
    left, top, right, bottom = crop
    gray = load_image(SOURCE, page_index=1, pdf_dpi=136, grayscale=True)[top:bottom, left:right]
    candidates = tuple(offset_candidate(c, offset_x=-left, offset_y=-top) for c in candidates)
    with patch.object(optimized_trace, "recognize_text_candidates_optimized", return_value=(
        tuple(prepare_safe_candidate(gray, c) for c in candidates), (),
    )):
        traced = optimized_trace.trace_image_optimized(gray, enable_ocr=True, source_dpi=136, foreground_threshold=254)
    cache, before, after, evidence = (output / n for n in ("trace.npz", "before.dxf", "after.dxf", "evidence.json"))
    save_trace_cache(cache, traced, cache_key=dict(source_sha256=sha256(SOURCE), page=2, dpi=136, crop=crop))
    export_final_structure_dxf(traced.final_structure, before)
    doc = ezdxf.readfile(before)
    texts = list(doc.modelspace().query("TEXT"))
    target = next(e for e in texts if e.dxf.text == edit_text[0])
    target.dxf.text = edit_text[1]
    doc.saveas(after)
    data = dict(schema_version=1,
                source=dict(sha256=sha256(SOURCE), page=2, region=list(crop),
                            authority="Existing repository OCR observations; production cache and source replay", units="source_pixel"),
                before_sha256=sha256(before), after_sha256=sha256(after),
                texts=[dict(id=f"row-{i}", handle=e.dxf.handle, expected_text=e.dxf.text) for i, e in enumerate(texts)],
                edit=dict(allowed_handles=[target.dxf.handle]))
    if len(texts) == 3:
        # Same diagnosed source window as the old W02 cell fixture, not adapter logic.
        for row in data["texts"]:
            row["cell"] = [74, 81, 178, 132]
    write_json(evidence, data)
    return dict(before=before, after=after, source=SOURCE, evidence_path=evidence, cache=cache, dpi=136)


def run(output):
    from tests.test_table_text_layout import candidates
    from tests.test_source_text_layout import _candidate

    output.mkdir(parents=True, exist_ok=False)
    cell = make_case(output / "w02-cell", (4080, 2200, 4390, 2410), candidates(), ("Discipline", "DisciplineA"))
    # This second region is an existing test_source_text_layout observation on
    # the same page, not a second design or a new recognition result.
    clean = make_case(output / "w02-single", (4463, 2558, 4592, 2659),
                      (_candidate("施工图", (4493, 2588, 69, 41)),), ("施工图", "施工表"))
    summary = dict(cases={}, cad_editor="NOT_RUN", dwg_roundtrip="NOT_RUN", human_time_saved="NOT_RUN")
    for name, args in (("w02-cell", cell), ("w02-single", clean)):
        folder = output / name
        legacy = validate_files(args["before"], args["after"], args["source"], args["evidence_path"])
        replay = validate_with_source(**args)
        write_json(folder / "legacy.report.json", legacy)
        write_json(folder / "source.report.json", replay)
        comparison = compare_reports(legacy, replay)
        comparison.update(old_adapter="NONE", new_adapter=replay["adapter_version"],
                          new_adapter_sha256=replay["adapter_sha256"])
        write_json(folder / "comparison.json", comparison)
        summary["cases"][name] = dict(legacy=legacy["summary"], replay=replay["summary"],
                                    glyph=[dict(target=r["target"], status=r["status"], reason=r["reason"])
                                           for r in replay["results"] if r["rule"] == "source-glyph-exit"])
    # Reintroduce actual source contours on a new CAD copy, never in the adapter.
    from app.core.cache import load_trace_cache, save_trace_cache
    from app.export.trace_entity_writer import semantic_paths
    structure = load_trace_cache(clean["cache"]).final_structure
    controls = output / "controls"
    controls.mkdir()
    summary["controls"] = {}
    for name in ("source-restored", "mixed-member", "context-missing", "identity-mismatch"):
        doc = ezdxf.readfile(clean["after"])
        if name == "source-restored":
            for path in semantic_paths(structure.editable_text_source_mask):
                doc.modelspace().add_lwpolyline([(x, structure.source_size_px[1] - y) for x, y in path.points], close=True)
        elif name == "mixed-member":
            row = read_json_file(output / "w02-single/source.report.json")["source_ledger"]["rows"][0]
            y, x0, x1 = row["core_runs"][0]
            width, height = structure.source_size_px
            doc.modelspace().add_lwpolyline([(x0 + .5, height - y - .5), (x1, height - y - .5), (width - 9, 2)])
        after = controls / (name + ".dxf")
        doc.saveas(after)
        data = read_json_file(clean["evidence_path"])
        data["after_sha256"] = sha256(after)
        if name == "identity-mismatch":
            data["source"]["sha256"] = "0" * 64
        evidence_path = controls / (name + ".evidence.json")
        write_json(evidence_path, data)
        args = dict(clean, after=after, evidence_path=evidence_path)
        if name == "context-missing":
            cache = controls / "context-missing.npz"
            save_trace_cache(cache, load_trace_cache(clean["cache"]))
            args["cache"] = cache
        try:
            report = validate_with_source(**args)
            summary["controls"][name] = [r["status"] for r in report["results"] if r["rule"] == "source-glyph-exit"][0]
        except ValueError as error:
            report = dict(status="INPUT_ERROR", message=str(error))
            summary["controls"][name] = "INPUT_ERROR"
        write_json(controls / (name + ".report.json"), report)
    assert summary["controls"] == dict(zip(
        ("source-restored", "mixed-member", "context-missing", "identity-mismatch"),
        ("FAIL", "FAIL", "ABSTAIN", "INPUT_ERROR")))
    write_json(output / "summary.json", summary)
    return summary


def read_json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
