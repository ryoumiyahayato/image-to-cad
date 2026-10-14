"""Thin-stroke contracts plus a real USDA context; synthetic cases are not CAD truth."""

from dataclasses import replace
from pathlib import Path
import cv2
import numpy as np
import pytest
from app.geometry.line_detect import LineSegment
from app.geometry import scan_line_regularization as module
from app.geometry.scan_cleanup import prepare_scan_page


def fixture():
    binary = np.full((120, 100), 255, np.uint8)
    binary[25:86, 50] = 0
    gray = np.where(binary < 128, 100, 220).astype(np.uint8)
    seed = LineSegment(
        51.7,
        26.0,
        51.7,
        84.0,
        width=1.9,
        source_ids=("LSD-test",),
        history=("detected:lsd",),
    )
    return binary, gray, seed


def review(binary, gray, seed, others=(), protected=None):
    return module.isolated_scan_stroke_proposals(
        [seed],
        all_lines=[seed, *others],
        binary=binary,
        gray=gray,
        protected_mask=protected,
    )


def test_complete_stroke_fit_keeps_visible_cap_cells_and_does_not_mutate_source():
    b, g, s = fixture()
    original = b.copy()
    lines, r = review(b, g, s)
    (line,) = lines
    assert (line.x1, line.y1, line.x2, line.y2) == pytest.approx((50, 25, 50, 85))
    assert line.width == 1 and np.array_equal(b, original)
    assert r["decisions"][0]["complete_source_claim"]
    assert review(b, g, s)[0] == lines


@pytest.mark.parametrize(
    "kind",
    [
        "gap",
        "branch",
        "arrow",
        "curve",
        "protected",
        "weak",
        "shared_endpoint",
        "other_claim",
        "incomplete",
    ],
)
def test_rejects_unproved_stroke_content(kind):
    b, g, s = fixture()
    protected = None
    others = ()
    if kind == "gap":
        b[55, 50] = 255
    if kind == "branch":
        b[55, 50:55] = 0
    if kind == "arrow":
        b[25, 48:53] = 0
        b[26, 49:52] = 0
    if kind == "curve":
        b[:] = 255
        for y in range(25, 86):
            b[y, 50 + int(2 * np.sin((y - 25) / 60 * np.pi))] = 0
    if kind == "protected":
        protected = np.zeros_like(b)
        protected[50, 50] = 255
    if kind == "weak":
        g = np.where(b < 128, 200, 220).astype(np.uint8)
    if kind == "shared_endpoint":
        others = (replace(s, x2=70, source_ids=("peer",)),)
    if kind == "other_claim":
        others = (LineSegment(50, 20, 50, 90, width=1, source_ids=("peer",)),)
    if kind == "incomplete":
        b[10:100, 50] = 0
    lines, r = review(b, g, s, others, protected)
    assert not lines and r["decisions"][0]["decision"] == "REJECTED"


def test_independent_parallel_boundary_and_order_are_preserved():
    b, g, s = fixture()
    b[25:86, 44] = 0
    peer = LineSegment(44, 25, 44, 85, width=1, source_ids=("peer",))
    args = dict(binary=b, gray=g, protected_mask=None)
    lines, r = module.isolated_scan_stroke_proposals([s], all_lines=[s, peer], **args)
    assert len(lines) == 1 and peer.x1 == 44
    assert (
        module.isolated_scan_stroke_proposals([s], all_lines=[peer, s], **args)[0]
        == lines
    )


def test_budget_leaves_old_ink_and_marks_not_evaluated(monkeypatch):
    b, g, s = fixture()
    original = b.copy()
    monkeypatch.setattr(module, "MAX_CHECKS", 0)
    lines, r = review(b, g, s)
    assert not lines and np.array_equal(b, original)
    assert r["decisions"][0]["decision"] == "NOT_EVALUATED"


def test_real_usda_full_context_source_proof():
    image = cv2.imread(
        str(
            Path(__file__).parent
            / "real_regression/assets/regions/usda-bathroom-p4-240dpi.png"
        ),
        0,
    )
    prepared = prepare_scan_page(image)
    seed = LineSegment(
        277.65283203125,
        211.87982177734375,
        278.1883850097656,
        264.3871154785156,
        width=1.91,
        source_ids=("LSD-000525",),
        history=("detected:lsd",),
    )
    peer = LineSegment(
        272.4358825683594,
        261.87359619140625,
        272.7925109863281,
        86.87432098388672,
        width=1.91,
        source_ids=("LSD-000373",),
        history=("detected:lsd",),
    )
    lines, r = review(prepared.binary, prepared.gray, seed, [peer])
    (line,) = lines
    proof = r["decisions"][0]
    assert proof["component_box"] == [276, 211, 278, 266]
    assert proof["source_pixels"] == 75 and proof["profile_count"] == 55
    assert (
        proof["center_residual_max_px"] < 0.5
        and proof["minimum_station_contrast"] == 65
    )
    assert line.y1 == 211 and line.y2 == 265


def test_fresh_proposal_does_not_require_an_unrelated_surviving_line(monkeypatch):
    from app.geometry import straight_line_reconstruction as reconstruction

    b, g, seed = fixture()
    monkeypatch.setattr(reconstruction, "detect_lines", lambda *a, **kw: [seed])
    original = reconstruction.filter_text_like_lines

    def reject_all(lines, *a, **kw):
        _, protection = original(lines, *a, **kw)
        return [], protection

    monkeypatch.setattr(reconstruction, "filter_text_like_lines", reject_all)
    out = reconstruction.reconstruct_straight_lines(
        b, scan_support_gray=g, source_dpi=240
    )
    assert len(out) == 1 and "scan_component_centerline_v1" in out[0].history


def test_cache_identity_changes_without_changing_schema():
    from app.core.processing import (
        ProductionProcessingConfig,
        build_processing_cache_key,
    )

    old = ProductionProcessingConfig(
        algorithm_version=ProductionProcessingConfig().algorithm_version.removesuffix(
            "-isolated-scan-stroke-v1"
        )
    )
    args = dict(input_content_sha256="a" * 64, page_index=3)
    assert build_processing_cache_key(**args, config=old) != build_processing_cache_key(
        **args, config=ProductionProcessingConfig()
    )


def test_discarded_white_edge_locators_are_not_accepted_member_merging():
    b, g, s = fixture()
    peer = replace(s, x1=48.3, x2=48.3, source_ids=("LSD-other-edge",), width=2.9)
    args = dict(all_lines=[s, peer], binary=b, gray=g, protected_mask=None)
    assert not module.isolated_scan_stroke_proposals([s], **args)[0]
    lines, r = module.isolated_scan_stroke_proposals([s, peer], **args)
    assert len(lines) == 1
    proposed = next(d for d in r["decisions"] if d["decision"] == "PROPOSED")
    assert proposed["rejected_locator_source_ids"] == ["LSD-other-edge"]
    assert module.isolated_scan_stroke_proposals([peer, s], **args)[0] == lines
    # A second actual source band or shared endpoint forbids this association.
    b[25:86, 47] = 0
    assert not module.isolated_scan_stroke_proposals([s, peer], **args)[0]


def test_real_context_normal_service_ownership_save_and_export(tmp_path, monkeypatch):
    import ezdxf
    from app.core.processing import (
        ProductionProcessingService,
        ProductionProcessingConfig,
    )
    from app.core.cache import save_trace_cache, load_trace_cache
    from app.core.preview import render_emitted_dxf_preview
    from app.export.trace_single_export import export_final_structure_dxf

    image = cv2.imread(
        str(
            Path(__file__).parent
            / "real_regression/assets/regions/usda-bathroom-p4-240dpi.png"
        ),
        0,
    )
    config = ProductionProcessingConfig(source_dpi=240, enable_ocr=True)
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "isolated_scan_stroke_proposals",
            lambda *a, **kw: ((), {"decisions": []}),
        )
        before = ProductionProcessingService.process_page(image, config).final_structure
    result = ProductionProcessingService.process_page(image, config)
    after = result.final_structure
    fresh = [
        line for line in after.straight_lines if "scan_component_centerline_v1" in line.history
    ]
    assert (
        len(fresh) == 1 and len(after.straight_lines) == len(before.straight_lines) + 1
    )
    assert set(before.straight_lines) <= set(after.straight_lines)
    assert (
        before.texts == after.texts
        and before.logos == after.logos
        and before.arcs == after.arcs
    )
    removed = [
        p
        for p in before.contours
        if not any(p.points == q.points for q in after.contours)
    ]
    assert len(removed) == 1 and len(removed[0].points) == 17
    assert len(after.contours) == len(before.contours) - 1
    restored = load_trace_cache(
        save_trace_cache(tmp_path / "scan.npz", result)
    ).final_structure
    assert (
        restored.straight_lines == after.straight_lines
        and restored.contours == after.contours
    )
    export = export_final_structure_dxf(restored, tmp_path / "scan.dxf")
    doc = ezdxf.readfile(export.path)
    audit = doc.audit()
    assert not audit.errors and not audit.fixes
    assert len(doc.modelspace().query("LINE")) == len(after.straight_lines)
    fresh_entity = next(
        e
        for e in doc.modelspace().query("LINE")
        if abs(e.dxf.start.x - fresh[0].x1) < 1e-6
        and abs(e.dxf.start.y - (image.shape[0] - fresh[0].y1)) < 1e-6
    )
    assert fresh_entity.dxf.lineweight in (13, 25) and fresh_entity.has_xdata(
        "P3A_STROKE"
    )
    preview = render_emitted_dxf_preview(doc, tmp_path, after.source_size_px)
    assert preview.shape[:2] == image.shape and np.any(preview < 128)


def test_complete_scan_width_has_explicit_existing_weight_on_grey_paper():
    line = LineSegment(
        50.5,
        25.5,
        50.5,
        84.5,
        width=2,
        source_ids=("component",),
        history=("scan_component_centerline_v1",),
    )
    record = module.scan_stroke_line_record(line, 240)
    assert record["cad_lineweight"] == 25 and record["source_width_px"] == 2
    assert record["width_quantization_error_px"] < 0.5
    assert module.scan_stroke_line_record(replace(line, history=()), 240) is None
