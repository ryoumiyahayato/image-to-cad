"""TEST_ONLY inspector contracts; real saved pages are run by the manifest."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import ezdxf
from ezdxf.math import Matrix44
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.quality import fidelity as f
from app.quality.fidelity_report import case_html, index_html


@pytest.fixture(scope="module", autouse=True)
def qt():
    app = QApplication.instance() or QApplication([])
    yield app


def test_recorded_transform_and_y_axis(tmp_path):
    ref = tmp_path / "calibration.json"
    ref.write_text(json.dumps({"mm_per_pixel": 0.5}), encoding="utf-8")
    meta = {
        "rendered_page_points": [50 * 72 / 25.4, 40 * 72 / 25.4],
        "physical_page": 1,
    }
    contract = f.coordinate_contract(
        {"scope": "FULL_PAGE", "size_px": [101, 81], "reference": str(ref)},
        meta,
        (81, 101),
        4,
    )
    assert contract["status"] == "VERIFIED"
    doc = ezdxf.new()
    line = doc.modelspace().add_line((10, 30), (20, 30))
    line.transform(Matrix44.scale(1 / contract["mm_per_pixel"]))
    assert f.bounds_source(line, 81) == [20, 21, 40, 21]


@pytest.mark.parametrize(
    "change", ["no_contract", "local_context", "size", "units", "scale", "page"]
)
def test_missing_or_wrong_frame_refuses_quantification(tmp_path, change):
    ref = tmp_path / "calibration.json"
    ref.write_text(
        json.dumps(
            {
                "mm_per_pixel": 1 if change != "scale" else 2,
                "physical_page": 2 if change == "page" else 1,
            }
        ),
        encoding="utf-8",
    )
    c = {
        "scope": "LOCAL_CONTEXT" if change == "local_context" else "FULL_PAGE",
        "size_px": [52 if change == "size" else 51, 41],
        "reference": str(ref),
    }
    meta = {
        "rendered_page_points": [50 * 72 / 25.4, 40 * 72 / 25.4],
        "physical_page": 1,
    }
    result = f.coordinate_contract(
        None if change == "no_contract" else c,
        meta,
        (41, 51),
        0 if change == "units" else 4,
    )
    assert result["status"] == "COORDINATE_CONTRACT_INCOMPLETE"


def test_rotation_metadata_and_page_budget(monkeypatch):
    class Page:
        def get_size(self):
            return (40, 60)

        def get_mediabox(self):
            return (0, 0, 60, 40)

        def get_cropbox(self):
            return (0, 0, 60, 40)

        def get_rotation(self):
            return 90

        def close(self):
            pass

    class Document:
        def __init__(self, _):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __len__(self):
            return 1

        def __getitem__(self, _):
            return Page()

    monkeypatch.setattr(f.pdfium, "PdfDocument", Document)
    assert f.page_metadata("TEST_ONLY", 1, 72, f.Limits())["rotation"] == 90
    with pytest.raises(ValueError, match="pixel budget"):
        f.page_metadata("TEST_ONLY", 1, 240, f.Limits(max_pixels=100))
    with pytest.raises(ValueError, match="outside"):
        f.page_metadata("TEST_ONLY", 2, 72, f.Limits())


def test_visible_and_hidden_layers_do_not_double_render(tmp_path):
    doc = ezdxf.new()
    doc.units = 4
    doc.layers.new("SOURCE_TEXT_OUTLINE")
    doc.layers.get("SOURCE_TEXT_OUTLINE").off()
    doc.layers.get("SOURCE_TEXT_OUTLINE").freeze()
    doc.modelspace().add_line((5, 10), (30, 10))
    doc.modelspace().add_line(
        (5, 20), (30, 20), dxfattribs={"layer": "SOURCE_TEXT_OUTLINE"}
    )
    path = tmp_path / "layers.dxf"
    doc.saveas(path)
    before = path.read_bytes()
    image, rows, audit, _ = f.read_dxf(path, 1, (50, 50), {}, f.Limits())
    assert sum(r["visible"] for r in rows) == 1
    assert image[30, 10] == 255 and image[40, 10] < 200
    assert audit == {"errors": 0, "fixes": 0}
    assert path.read_bytes() == before


def test_one_pixel_tolerance_reduces_AA_width_difference_without_hiding_gap():
    source = np.full((40, 60), 255, np.uint8)
    cad = source.copy()
    source[20:22, 5:55] = 0
    cad[19:22, 5:25] = 30
    cad[19:22, 35:55] = 30
    strict, _ = f.difference_masks(source, cad, tolerance=0)
    near, extra = f.difference_masks(source, cad, tolerance=1)
    assert 0 < near.sum() < strict.sum()
    assert not extra.any() and near[:, 28:32].sum() == 8


def test_text_image_open_arc_and_multiple_members_are_review_guards():
    rows = [
        dict(
            geometry_group=str(i),
            type=t,
            visible=True,
            bounds_source_px=[0, 0, 30, 30],
            source_association="SOURCE_UNDETERMINED",
        )
        for i, t in enumerate(["TEXT", "IMAGE", "ARC", "LINE"])
    ]
    r = {"bbox": [0, 0, 20, 20]}
    f.context(r, f.SpatialIndex(rows), f.Limits())
    assert len(r["guards"]) == 4
    assert r["source_state"] == "MULTIPLE_NEARBY_CAD_MEMBERS"
    assert r["owner_state"].startswith("UNKNOWN")
    assert r["review_priority"] == "TEXT_IMAGE_DISPLAY_REVIEW"


def test_actual_IMAGE_is_rendered_not_marked_as_missing_lines(tmp_path):
    rgba = np.zeros((5, 5, 4), np.uint8)
    rgba[:, :, 3] = 255
    assert cv2.imwrite(str(tmp_path / "qa.png"), rgba)
    doc = ezdxf.new()
    doc.units = 4
    asset = doc.add_image_def(filename="qa.png", size_in_pixel=(5, 5))
    doc.modelspace().add_image(asset, insert=(10, 10), size_in_units=(5, 5))
    path = tmp_path / "image.dxf"
    doc.saveas(path)
    image, rows, _, _ = f.read_dxf(path, 1, (30, 30), {}, f.Limits())
    assert (image < 200).sum() == 25
    assert rows[0]["type"] == "IMAGE"


def test_real_arc_sweep_is_not_closed_by_inspection(tmp_path):
    doc = ezdxf.new()
    doc.units = 4
    arc = doc.modelspace().add_arc((20, 20), 10, 0, 90)
    path = tmp_path / "arc.dxf"
    doc.saveas(path)
    before = path.read_bytes()
    image, rows, _, _ = f.read_dxf(path, 1, (50, 50), {}, f.Limits())
    assert rows[0]["geometry_source_CAD_axes"][-2:] == [0, 90]
    assert image[30, 10] == 255 and path.read_bytes() == before
    assert arc.dxf.end_angle == 90


def test_visual_improvement_measured_separately_from_qualification():
    source = np.full((60, 60), 255, np.uint8)
    cv2.circle(source, (30, 30), 15, 0, 1)
    old = source.copy()
    old[40:48] = 255
    a = f.metrics(source, old, 160, 0)
    b = f.metrics(source, source, 160, 0)
    assert a["missing_candidate_pixels"] > b["missing_candidate_pixels"] == 0
    candidates, _ = f.regions(*f.difference_masks(source, old), f.Limits())
    assert candidates and all(not c["modification_authorized"] for c in candidates)


def test_missing_trace_and_deterministic_regions(tmp_path):
    state, lookup, source = f.read_trace(None, (50, 50), 1, 240, f.Limits())
    assert (
        state["status"] == "SOURCE_ASSOCIATION_NOT_AVAILABLE"
        and not lookup
        and source is None
    )
    missing = np.zeros((200, 200), bool)
    missing[50:60, 60:70] = True
    extra = np.flipud(missing)
    assert f.regions(missing, extra, f.Limits()) == f.regions(
        missing, extra, f.Limits()
    )
    absent, _, _ = f.read_trace(tmp_path / "absent.npz", (50, 50), 1, 240, f.Limits())
    assert absent["status"] == "SOURCE_ASSOCIATION_NOT_AVAILABLE"


def test_font_and_tone_candidates_do_not_exhaust_geometry_budget():
    limits = f.Limits(max_candidates=4, max_details=3)
    source = np.zeros((200, 200), np.uint8)
    missing = source == 0
    prepared = np.full_like(source, 255)
    prepared[96:192, :96] = 0
    rows = [
        dict(
            id="font",
            bbox=[0, 0, 96, 96],
            missing_pixels=100,
            extra_pixels=300,
            guards=["TEXT"],
            review_priority="TEXT_IMAGE_DISPLAY_REVIEW",
        ),
        dict(
            id="tone",
            bbox=[96, 0, 192, 96],
            missing_pixels=9000,
            extra_pixels=0,
            guards=[],
            review_priority="GEOMETRY_SOURCE_REVIEW",
        ),
        dict(
            id="line",
            bbox=[0, 96, 96, 192],
            missing_pixels=30,
            extra_pixels=0,
            guards=[],
            review_priority="GEOMETRY_SOURCE_REVIEW",
        ),
    ]
    ranked = f.rank_regions(rows, prepared, missing, source, limits)
    assert ranked[0]["id"] == "line"
    assert (
        next(r for r in ranked if r["id"] == "tone")["review_priority"]
        == "TONAL_BACKGROUND_REVIEW"
    )


def test_bad_DXF_is_explicit_error(tmp_path):
    p = tmp_path / "bad.dxf"
    p.write_text("invalid TEST_ONLY file", encoding="utf-8")
    with pytest.raises((ezdxf.DXFError, OSError)):
        f.read_dxf(p, 1, (40, 40), {}, f.Limits())


def test_duplicate_native_geometry_does_not_claim_unique_saved_identity(tmp_path):
    doc = ezdxf.new()
    doc.units = 4
    doc.modelspace().add_line((2, 3), (20, 3))
    doc.modelspace().add_line((2, 3), (20, 3))
    path = tmp_path / "two.dxf"
    doc.saveas(path)
    lookup = {f.geometry_key("LINE", [2, 3, 20, 3]): [dict(kind="LINE", index=1)]}
    _, rows, _, _ = f.read_dxf(path, 1, (40, 40), lookup, f.Limits())
    assert all(r["geometry_group_members"] == 2 for r in rows)
    assert len({r["geometry_group"] for r in rows}) == 1
    assert all(r["source_association"].startswith("AMBIGUOUS") for r in rows)
    assert all(not r["modification_authorized"] for r in rows)


def test_deadline_does_not_run_unbounded():
    with pytest.raises(TimeoutError, match="deadline"):
        f.checkpoint(0, f.Limits(seconds=0.001))


def test_wrong_source_version_trace_downgrades_without_consuming_members(tmp_path):
    path = tmp_path / "wrong-source.npz"
    np.savez_compressed(
        path,
        cache_version=[11],
        final_structure_schema_version=[4],
        preview_shape=[3, 3],
        preview_packed=np.packbits(np.zeros(9, np.uint8)),
        cache_key_json=[
            json.dumps(
                dict(page_number=1, dpi=72, input_content_sha256="OTHER_TEST_ONLY")
            )
        ],
        structure_id=["TEST_ONLY"],
        lines_json=["[]"],
        texts_json=["[]"],
        provenance_json=["{}"],
    )
    state, members, prepared = f.read_trace(
        path,
        (3, 3),
        1,
        72,
        f.Limits(),
        source_identity={"sha256": "EXPECTED_TEST_ONLY"},
    )
    assert state["status"] == "SOURCE_ASSOCIATION_NOT_AVAILABLE"
    assert "version mismatch" in state["reason"] and not members and prepared is None


def test_complete_report_offline_and_inputs_unchanged(tmp_path, monkeypatch):
    pdf = tmp_path / "TEST_ONLY.pdf"
    pdf.write_bytes(b"TEST_ONLY loader mocked, not a valid source PDF")
    doc = ezdxf.new()
    doc.units = 4
    doc.modelspace().add_line((4, 20), (45, 20))
    dxf = tmp_path / "TEST_ONLY.dxf"
    doc.saveas(dxf)
    ref = tmp_path / "calibration.json"
    ref.write_text('{"mm_per_pixel":1}', encoding="utf-8")
    source = np.full((41, 51), 255, np.uint8)
    source[20, 4:46] = 0
    meta = dict(
        rendered_page_points=[50 * 72 / 25.4, 40 * 72 / 25.4],
        dpi=72,
        physical_page=1,
        media_box=[0, 0, 1, 1],
        crop_box=[0, 0, 1, 1],
        rotation=0,
    )
    monkeypatch.setattr(f, "page_metadata", lambda *_: meta)
    monkeypatch.setattr(f, "load_image", lambda *_, **__: source)
    case = dict(
        id="QA_TEST_ONLY",
        pdf=str(pdf),
        dxf=str(dxf),
        page=1,
        dpi=72,
        coordinate={"scope": "FULL_PAGE", "size_px": [51, 41], "reference": str(ref)},
    )
    inputs_before = [p.read_bytes() for p in [pdf, dxf, ref]]
    out = tmp_path / "report"
    a = f.inspect_case(case, out)
    b = f.inspect_case(case, out)
    assert a["candidates"] == b["candidates"] and a["metrics"] == b["metrics"]
    assert a["input_bytes_unchanged"] and a["automatic_verified_defects"] == 0
    case_html(a, out)
    index_html([a], tmp_path)
    html = (out / "report.html").read_text(encoding="utf-8")
    assert (
        '<meta charset="utf-8">' in html and "source.png" in html and "cad.png" in html
    )
    assert "https://" not in html and "<script src" not in html
    assert inputs_before == [p.read_bytes() for p in [pdf, dxf, ref]]
    assert (out / "entities.json").is_file()
