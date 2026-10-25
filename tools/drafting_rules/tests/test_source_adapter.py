"""Real source replay, saved-CAD controls, and explicit partial evidence."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import ezdxf
import numpy as np
import pytest

from tools.drafting_rules.cli import read_json, validate_files
from tools.drafting_rules.dxf_adapter import sha256
from tools.drafting_rules.source_adapter import validate_with_source, runs
from tools.drafting_rules.source_study import run, SOURCE


@pytest.fixture(scope="module")
def real_cases(tmp_path_factory):
    root = tmp_path_factory.mktemp("source-replay") / "study"
    summary = run(root)
    return root, summary


def case_args(root):
    return dict(before=root / "before.dxf", after=root / "after.dxf", source=SOURCE,
                evidence_path=root / "evidence.json", cache=root / "trace.npz", dpi=136)


def copy_case(real_cases, tmp_path, name="w02-single"):
    root = tmp_path / name
    shutil.copytree(real_cases[0] / name, root)
    return case_args(root)


def glyph(report):
    return [r for r in report["results"] if r["rule"] == "source-glyph-exit"]


def save_evidence(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def change_dxf(args, mutation):
    doc = ezdxf.readfile(args["after"])
    mutation(doc)
    doc.saveas(args["after"])
    evidence = read_json(args["evidence_path"])
    evidence["after_sha256"] = sha256(args["after"])
    save_evidence(args["evidence_path"], evidence)


def test_real_source_positive_binds_recognized_original_and_saved_edited_text(real_cases):
    root, summary = real_cases
    assert summary["cases"]["w02-single"]["glyph"][0]["status"] == "PASS"
    args = case_args(root / "w02-single")
    hashes = {str(p): sha256(p) for p in args.values() if isinstance(p, Path)}
    report = validate_with_source(**args)
    row = report["source_ledger"]["rows"][0]
    assert row["recognized_text"] == "施工图"
    assert ezdxf.readfile(args["after"]).entitydb[row["handle"]].dxf.text == "施工表"
    assert row["carrier_pixels"] > 0 and row["unowned_pixels"] == row["cache_uncovered_pixels"] == 0
    assert row["source_member_runs"] and row["residual_owned_core_pixels"] == 0
    assert all(sha256(p) == value for p, value in hashes.items())


def test_original_w02_retained_residue_is_failure_partial_rows_still_abstain(real_cases):
    root, summary = real_cases
    case = summary["cases"]["w02-cell"]
    assert case["legacy"] == {"PASS": 7, "ABSTAIN": 5}
    assert [r["status"] for r in case["glyph"]] == ["FAIL", "ABSTAIN", "ABSTAIN"]
    report = read_json(root / "w02-cell/source.report.json")
    rows = report["source_ledger"]["rows"]
    assert rows[0]["residual_owned_core_pixels"] > 0
    assert rows[0]["residual_handles"]
    assert rows[1]["shared_with"] and rows[1]["unowned_pixels"] > 0
    assert next(r for r in report["results"] if r["rule"] == "background-protection")["status"] == "ABSTAIN"
    assert next(r for r in report["results"] if r["rule"] == "table-line-parity")["status"] == "ABSTAIN"


def test_source_glyph_reintroduced_from_real_cache_is_detected(real_cases, tmp_path):
    from app.core.cache import load_trace_cache
    from app.export.trace_entity_writer import semantic_paths
    args = copy_case(real_cases, tmp_path)
    structure = load_trace_cache(args["cache"]).final_structure
    originals = semantic_paths(structure.editable_text_source_mask)
    def restore(doc):
        for path in originals:
            doc.modelspace().add_lwpolyline([(x, structure.source_size_px[1] - y) for x, y in path.points], close=True)
    change_dxf(args, restore)
    report = validate_with_source(**args)
    assert glyph(report)[0]["status"] == "FAIL"
    assert report["source_ledger"]["rows"][0]["residual_owned_core_pixels"] > 0


def test_missing_native_replacement_cannot_claim_verified_replacement_exit(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path)
    change_dxf(args, lambda doc: doc.modelspace().delete_entity(doc.modelspace().query("TEXT")[0]))
    report = validate_with_source(**args)
    assert glyph(report)[0]["status"] == "ABSTAIN"
    assert next(r for r in report["results"] if r["rule"] == "editable-text")["status"] == "FAIL"


def test_mixed_geometry_member_is_reported_not_wholly_owned_or_deleted(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path)
    original = validate_with_source(**args)
    row = original["source_ledger"]["rows"][0]
    y, x0, x1 = row["core_runs"][0]
    change_dxf(args, lambda doc: doc.modelspace().add_lwpolyline(
        [(x0 + .5, 101 - y - .5), (x1, 101 - y - .5), (120, 2)], close=False))
    after_hash = sha256(args["after"])
    report = validate_with_source(**args)
    assert glyph(report)[0]["status"] == "FAIL"
    assert report["source_ledger"]["rows"][0]["source_member_runs"] == row["source_member_runs"]
    assert report["source_ledger"]["original_pdf_path_binding"].startswith("NOT_AVAILABLE")
    assert sha256(args["after"]) == after_hash


@pytest.mark.parametrize("mutation", ["wrong-page", "wrong-dpi", "wrong-region", "wrong-source-hash"])
def test_source_identity_rejected_before_ownership_claims(real_cases, tmp_path, mutation):
    args = copy_case(real_cases, tmp_path)
    evidence = read_json(args["evidence_path"])
    if mutation == "wrong-page":
        evidence["source"]["page"] = 1
    elif mutation == "wrong-region":
        evidence["source"]["region"][0] += 1
    elif mutation == "wrong-source-hash":
        evidence["source"]["sha256"] = "0" * 64
    else:
        args["dpi"] = 135
    save_evidence(args["evidence_path"], evidence)
    with pytest.raises(ValueError):
        validate_with_source(**args)


def test_boolean_flags_cannot_manufacture_complete_source_evidence(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path, "w02-cell")
    evidence = read_json(args["evidence_path"])
    for row in evidence["texts"]:
        row.update(outline_mapping_complete=True, ownership_ref="pretend complete", source_outline_handles=[])
    save_evidence(args["evidence_path"], evidence)
    assert [r["status"] for r in glyph(validate_with_source(**args))] == ["FAIL", "ABSTAIN", "ABSTAIN"]


def test_manual_background_and_table_claims_cannot_remove_abstentions(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path, "w02-cell")
    doc = ezdxf.readfile(args["before"])
    line = doc.modelspace().query("LINE")[0]
    evidence = read_json(args["evidence_path"])
    evidence["protected"] = [dict(id="claimed-logo", role="logo", handles=[line.dxf.handle], authority="unverified claim")]
    evidence["table"] = dict(id="claimed-table", layer=line.dxf.layer, mapping_complete=True,
                             source_ref="unverified completeness flag",
                             source_segments=[[e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y]
                                              for e in doc.modelspace().query("LINE") if e.dxf.layer == line.dxf.layer])
    save_evidence(args["evidence_path"], evidence)
    legacy = validate_files(args["before"], args["after"], args["source"], args["evidence_path"])
    replay = validate_with_source(**args)
    for rule in ("background-protection", "table-line-parity"):
        assert next(r for r in legacy["results"] if r["rule"] == rule)["status"] == "PASS"
        assert all(r["status"] == "ABSTAIN" for r in replay["results"] if r["rule"] == rule)


def test_missing_cached_ownership_prevents_real_positive_pass(real_cases, tmp_path):
    from app.core.cache import load_trace_cache
    args = copy_case(real_cases, tmp_path)
    stored = load_trace_cache(args["cache"])
    # Simulate a partial producer artifact in memory, preserving source pixels.
    from dataclasses import replace
    partial = replace(stored, final_structure=replace(stored.final_structure, editable_text_source_mask=None))
    with patch("app.core.cache.load_trace_cache", return_value=partial):
        assert glyph(validate_with_source(**args))[0]["status"] == "ABSTAIN"


def test_conflicting_cache_source_identity_is_rejected(real_cases, tmp_path):
    from app.core.cache import load_trace_cache, save_trace_cache
    args = copy_case(real_cases, tmp_path)
    stored = load_trace_cache(args["cache"])
    identity = dict(stored.cache_key)
    identity["source_sha256"] = "0" * 64
    different = tmp_path / "wrong-identity.npz"
    save_trace_cache(different, stored, cache_key=identity)
    args["cache"] = different
    with pytest.raises(ValueError, match="SOURCE_CACHE_CONTEXT_IDENTITY_MISMATCH"):
        validate_with_source(**args)


def test_original_text_metadata_binding_mismatch_cannot_pass(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path)
    doc = ezdxf.readfile(args["before"])
    doc.modelspace().query("TEXT")[0].dxf.text = "unrelated"
    doc.saveas(args["before"])
    data = read_json(args["evidence_path"])
    data["before_sha256"] = sha256(args["before"])
    save_evidence(args["evidence_path"], data)
    assert glyph(validate_with_source(**args))[0]["status"] == "ABSTAIN"


def test_nondefault_ocs_cannot_use_renderer_local_coordinates(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path)
    change_dxf(args, lambda doc: doc.modelspace().add_lwpolyline(
        [(0, 0), (60, 0)], dxfattribs={"extrusion": (0, 0, -1)}))
    assert glyph(validate_with_source(**args))[0]["status"] == "ABSTAIN"


@pytest.mark.parametrize("mutation", ["other-contour", "line-missing", "line-duplicate", "line-extended"])
def test_unmapped_background_and_table_changes_are_not_approved(real_cases, tmp_path, mutation):
    args = copy_case(real_cases, tmp_path, "w02-cell")
    def mutate(doc):
        if mutation == "other-contour":
            doc.modelspace().query("LWPOLYLINE")[0].translate(1, 0, 0)
        else:
            line = doc.modelspace().query("LINE")[0]
            if mutation == "line-missing":
                doc.modelspace().delete_entity(line)
            elif mutation == "line-duplicate":
                doc.modelspace().add_line(line.dxf.start, line.dxf.end, dxfattribs={"layer": line.dxf.layer})
            else:
                line.dxf.end += (3, 0, 0)
    change_dxf(args, mutate)
    report = validate_with_source(**args)
    assert next(r for r in report["results"] if r["rule"] == "edit-isolation")["status"] == "FAIL"
    assert next(r for r in report["results"] if r["rule"] == "background-protection")["status"] == "ABSTAIN"
    assert next(r for r in report["results"] if r["rule"] == "table-line-parity")["status"] == "ABSTAIN"


def test_single_pdf_path_with_target_and_structure_abstains(tmp_path):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    from types import SimpleNamespace
    from app.core.image_loader import load_image
    from app.core.cache import save_trace_cache
    from app.core.structure_build import build_final_structure
    from app.export.trace_single_export import export_final_structure_dxf
    from app.geometry.raster_trace import trace_binary
    from app.geometry.scan_cleanup import prepare_scan_page
    from app.ocr.auxiliary_recognition import TextCandidate
    from app.ocr.ocr_fast import prepare_safe_candidate
    source = tmp_path / "shared.pdf"
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(180, 100)
    shape = raw.FPDFPageObj_CreateNewPath(20, 80)
    def line(a, b):
        raw.FPDFPath_MoveTo(shape, a[0], 100 - a[1])
        raw.FPDFPath_LineTo(shape, b[0], 100 - b[1])
    for x in (20, 50):
        line((x, 20), (x, 50))
        line((x + 15, 20), (x + 15, 50))
        line((x, 35), (x + 15, 35))
    line((0, 35), (175, 35))  # One paint PATH shared with structure.
    raw.FPDFPageObj_SetStrokeColor(shape, 0, 0, 0, 255)
    raw.FPDFPageObj_SetStrokeWidth(shape, 1)
    raw.FPDFPath_SetDrawMode(shape, 0, True)
    page.insert_obj(pdfium.PdfObject(shape))
    page.gen_content()
    assert raw.FPDFPage_CountObjects(page) == 1
    pdf.save(source)
    page.close()
    pdf.close()
    gray = load_image(source, page_index=0, pdf_dpi=72, grayscale=True)
    candidate = TextCandidate("HH", (18, 18, 50, 35), .999, "text_candidate", source="synthetic shared PATH")
    candidate = prepare_safe_candidate(gray, candidate)
    assert not candidate.replacement_safe
    binary = prepare_scan_page(gray, foreground_threshold=254).binary
    # Synthetic export/cache control, not a claimed full OCR pipeline run.
    structure = build_final_structure(source_size_px=(180, 100), contour_binary=binary,
                                      contours=trace_binary(binary), texts=(candidate,),
                                      preview_binary=binary, threshold=254)
    before, after, cache, evidence = (tmp_path / n for n in ("before.dxf", "after.dxf", "cache.npz", "evidence.json"))
    export_final_structure_dxf(structure, before)
    shutil.copyfile(before, after)
    save_trace_cache(cache, SimpleNamespace(final_structure=structure),
                     cache_key=dict(source_sha256=sha256(source), page=1, dpi=72, crop=[0, 0, 180, 100]))
    native = ezdxf.readfile(after).modelspace().query("TEXT")[0]
    save_evidence(evidence, dict(schema_version=1, before_sha256=sha256(before), after_sha256=sha256(after),
                               source=dict(sha256=sha256(source), page=1, region=[0, 0, 180, 100], authority="synthetic shared PDF path", units="source_pixel"),
                               texts=[dict(id="shared", handle=native.dxf.handle, expected_text="HH")]))
    result = validate_with_source(before, after, source, evidence, cache, 72)
    assert result["source_ledger"]["cache_context_verified"]
    assert result["source_ledger"]["rows"] == []
    assert glyph(result)[0]["status"] == "ABSTAIN"


def test_readonly_cli_independent_process(real_cases, tmp_path):
    args = copy_case(real_cases, tmp_path)
    output = tmp_path / "cli.json"
    command = [sys.executable, "-m", "tools.drafting_rules.source_adapter", "--output", str(output)]
    for k, value in args.items():
        command.extend(["--" + ("evidence" if k == "evidence_path" else k), str(value)])
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert glyph(read_json(output))[0]["status"] == "PASS"


def test_runs_are_lossless_and_stable():
    mask = np.array([[0, 1, 1, 0, 1], [1, 0, 0, 0, 0]], np.uint8)
    assert runs(mask) == [[0, 1, 3], [0, 4, 5], [1, 0, 1]]
