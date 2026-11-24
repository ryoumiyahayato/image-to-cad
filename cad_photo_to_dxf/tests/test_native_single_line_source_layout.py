"""One affine TEXT, original glyph responsibility, and actual saved resources.

The synthetic source is rasterized independently with Pillow. Raw recognition
replay is mocked only in saved-representation tests; no result here claims OCR.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import ezdxf
from ezdxf.fonts import fonts
from ezdxf.fonts.font_manager import FontManager
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from app.native_objects import cad_io, quality_review, text_contact_audit
from app.native_objects import single_line_labels as labels
from app.native_objects import single_line_source_layout as layout
from app.native_objects.single_line_text_audit import cold_native_text_bindings
from app.native_objects.source_row_font_registry import FONT_SPEC


ROI = [0, 0, 360, 200]
DPI = 200
MM = 25.4 / DPI


def _runs(mask):
    rows = []
    for y in np.flatnonzero(np.any(mask, axis=1)):
        edges = np.diff(np.pad(mask[y].astype(np.int8), (1, 1)))
        rows.extend([[int(y), int(a), int(b)] for a, b in zip(
            np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))])
    return rows


def _bbox(mask):
    yy, xx = np.nonzero(mask)
    return [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]


@pytest.fixture(scope="module")
def packaged_font():
    path = Path(layout.__file__).resolve().parents[2] / "resources/fonts" / FONT_SPEC["font"]
    if not path.is_file():
        pytest.skip("Pinned source-row font has not been prepared in this environment")
    return layout.source_row_font_path()


@pytest.fixture(scope="module")
def synthetic_row(packaged_font):
    literal = "PX-17,29"
    font = ImageFont.truetype(str(packaged_font), 36, layout_engine=ImageFont.Layout.BASIC)
    union = np.zeros((ROI[3], ROI[2]), np.uint8)
    components, x = [], 60.0
    for character in literal:
        raster = Image.new("L", (ROI[2], ROI[3]), 255)
        ImageDraw.Draw(raster).text((x, 115), character, fill=0, font=font, anchor="ls")
        mask = (np.asarray(raster) < 192).astype(np.uint8)
        components.append({
            "bbox_xyxy_px": _bbox(mask),
            "source_runs_y_x0_x1": _runs(mask),
            "source_role": "FULL_HEIGHT_GLYPH" if character.isalnum() else "PUNCTUATION",
        })
        union |= mask
        x += float(font.getlength(character))
    box = _bbox(union)
    graphic = np.zeros_like(union)
    cv2.line(graphic, (box[0] - 3, box[3] + 6), (box[2] + 3, box[3] + 6), 1, 1)
    cv2.line(graphic, (box[2] + 9, box[1] - 2), (box[2] + 9, box[3] + 8), 1, 1)
    cv2.circle(graphic, (box[0] - 18, box[1] - 4), 9, 1, 1)
    gray = np.where(union | graphic, 0, 255).astype(np.uint8)
    geometry = {
        "text": literal, "x": box[0], "y": box[3],
        "width_px": box[2] - box[0], "height_px": box[3] - box[1],
        "rotation_deg_image": 0.0,
    }
    partition = {
        "bbox_xyxy_px": box, "context_bbox_xyxy_px": list(ROI),
        "components": components, "source_support_runs_y_x0_x1": _runs(union),
        "recognition_excluded_graphic_runs_y_x0_x1": _runs(graphic),
        "text_contact_separation": {"independent_round_observations": []},
    }
    fitted = layout.fit_source_glyph_layout(geometry, partition, ROI, DPI, packaged_font, gray=gray)
    assert fitted["pass"], fitted
    return gray, geometry, partition, fitted


def _object(synthetic_row):
    _, geometry, partition, fitted = synthetic_row
    return {
        "id": "synthetic-source-row", "kind": "TEXT", "layer": "ANNOTATION",
        "geometry": deepcopy(geometry),
        "source_evidence": {"single_line_recovery": {
            "schema": "native-single-line-label-evidence-v1",
            "test_only": "raw replay mocked to isolate native layout and resource checks",
            "source_partition": deepcopy(partition), "layout_adoption": deepcopy(fitted),
        }},
    }


def _isolated_replay(monkeypatch, geometry):
    monkeypatch.setattr(labels, "verify_single_line_label_evidence", lambda *args, **kwargs: {
        "pass": True, "text": geometry["text"],
        "bbox_xyxy_px": [geometry["x"], geometry["y"] - geometry["height_px"],
                         geometry["x"] + geometry["width_px"], geometry["y"]],
        "new_OCR_calls": 0, "new_model_calls": 0,
    })


def _export(tmp_path, monkeypatch, synthetic_row, *, legacy=False):
    gray, geometry, _, _ = synthetic_row
    _isolated_replay(monkeypatch, geometry)
    objects = [_object(synthetic_row)]
    if legacy:
        objects.append({
            "id": "protected-existing-text", "kind": "TEXT", "layer": "ANNOTATION",
            "geometry": {"text": "STORE", "x": 250, "y": 165,
                         "height_px": 15, "width_px": 63, "rotation_deg_image": 0},
        })
    path = tmp_path / "source-row.dxf"
    cad_io.export_objects(objects, path, ROI, DPI, hashlib.sha256(gray.tobytes()).hexdigest())
    return path


def _rewrite_hash(path, metadata):
    metadata["dxf_sha256"] = cad_io.sha(path)
    path.with_suffix(".objects.json").write_text(json.dumps(metadata))


def test_original_pixels_and_components_select_one_deterministic_affine(synthetic_row, packaged_font):
    gray, geometry, partition, fitted = synthetic_row
    original, original_partition = gray.copy(), deepcopy(partition)
    replay = layout.fit_source_glyph_layout(geometry, partition, ROI, DPI, packaged_font)
    assert replay == fitted
    assert fitted["source_fit"]["one_transform_for_all_characters"]
    assert not fitted["policy"]["characters_individually_transformed"]
    assert len(fitted["source_neighbor_clearance"]["checks"]) == 3
    assert all(row["pass"] for row in fitted["source_neighbor_clearance"]["checks"])
    assert np.array_equal(gray, original) and partition == original_partition
    selected = fitted["selected_layout"]
    checked = layout.verify_source_glyph_layout(
        geometry, partition, ROI, DPI, packaged_font,
        {"text": geometry["text"], **selected}, gray=gray,
    )
    assert checked["pass"] and checked["actual_attributes_used"]
    companion = checked["actual_saved_LFF_literal_equivalence"]
    assert companion["pass"] and companion["all_literal_outlines_and_advances_checked"]
    assert companion["actual_LFF_file_read"]


@pytest.mark.parametrize("mutation", ["white_pixel", "missing_comma", "swapped", "unowned_pixel"])
def test_missing_or_nonoriginal_component_evidence_is_not_a_layout_hint(
    synthetic_row, packaged_font, mutation
):
    gray, geometry, partition, _ = deepcopy(synthetic_row)
    if mutation == "white_pixel":
        y, x, _ = partition["components"][0]["source_runs_y_x0_x1"][0]
        gray[y, x] = 255
    elif mutation == "missing_comma":
        partition["components"].pop(5)
    elif mutation == "swapped":
        partition["components"][0], partition["components"][1] = partition["components"][1], partition["components"][0]
    else:
        partition["source_support_runs_y_x0_x1"].append([20, 20, 21])
        gray[20, 20] = 0
    checked = layout.fit_source_glyph_layout(geometry, partition, ROI, DPI, packaged_font, gray=gray)
    assert not checked["pass"] and "selected_layout" not in checked


def test_one_original_contact_cannot_exempt_a_long_graphic_elsewhere(synthetic_row):
    gray, geometry, partition, _ = deepcopy(synthetic_row)
    first = partition["components"][0]["bbox_xyxy_px"]
    last = partition["components"][-1]["bbox_xyxy_px"]
    graphic = np.zeros_like(gray)
    # One connected graphic starts at original first-glyph ink, drops away,
    # then passes the final glyph with a proved blank row between them.
    y, a, _ = partition["components"][0]["source_runs_y_x0_x1"][0]
    cv2.line(graphic, (a, y), (first[0] - 7, y), 1, 1)
    cv2.line(graphic, (first[0] - 7, y), (first[0] - 7, last[3] + 3), 1, 1)
    cv2.line(graphic, (first[0] - 7, last[3] + 3), (last[2] + 5, last[3] + 3), 1, 1)
    partition["recognition_excluded_graphic_runs_y_x0_x1"] = _runs(graphic)
    gray[graphic != 0] = 0
    *_, neighbors = layout._source_data(geometry, partition, gray)
    assert sum(row["source_contact"] for row in neighbors) == 1
    protected = [row for row in neighbors if not row["source_contact"]]
    assert protected and any(rect[2] >= last[2] for row in protected for rect in row["rectangles"])
    assert all(row["required_gap_px"] > 0 for row in protected)


def test_contact_does_not_exempt_nearby_disconnected_short_stroke(synthetic_row):
    gray, geometry, partition, _ = deepcopy(synthetic_row)
    y, x, _ = partition["components"][0]["source_runs_y_x0_x1"][0]
    graphic = np.zeros_like(gray)
    graphic[y, x] = 1  # This graphic genuinely shares original glyph ink.
    graphic[y - 3, x:x + 2] = 1  # Distinct short stroke, with two blank rows.
    partition["recognition_excluded_graphic_runs_y_x0_x1"] = _runs(graphic)
    gray[graphic != 0] = 0
    *_, neighbors = layout._source_data(geometry, partition, gray)
    assert any(row["source_contact"] for row in neighbors)
    protected = [row for row in neighbors if not row["source_contact"]]
    assert len(protected) == 1
    assert protected[0]["rectangles"] == [[float(x), float(y - 3), float(x + 2), float(y - 2)]]
    assert protected[0]["required_gap_px"] > 0


@pytest.mark.parametrize("field", ["insert", "height", "width", "rotation"])
def test_saved_actual_transform_is_rechecked_even_when_receipt_is_unchanged(
    tmp_path, monkeypatch, synthetic_row, field
):
    path = _export(tmp_path, monkeypatch, synthetic_row)
    gray, _, _, _ = synthetic_row
    doc = ezdxf.readfile(path)
    entity = next(iter(doc.modelspace().query("TEXT")))
    if field == "insert":
        entity.dxf.insert += (10 * MM, 0, 0)
    elif field == "rotation":
        entity.dxf.rotation = 12
    else:
        setattr(entity.dxf, field, getattr(entity.dxf, field) * 1.3)
    doc.saveas(path)
    metadata = json.loads(path.with_suffix(".objects.json").read_text())
    _rewrite_hash(path, metadata)
    candidates, source = cold_native_text_bindings(path, ezdxf.readfile(path), gray, ROI, DPI, tmp_path)
    assert not candidates[0]["pass"] and not source[0]["pass"]
    assert source[0]["source_replay"]["pass"]
    if field == "rotation":
        assert "ACTUAL_TEXT_TRANSFORM_OR_CONTENT_CHANGED" in source[0]["failure"]
    else:
        checked = source[0]["actual_saved_source_component_layout"]
        assert checked["actual_attributes_used"] and not checked["pass"]


@pytest.mark.parametrize("mutation", ["font_bytes", "license_bytes", "lff_bytes", "lff_missing", "font_registry", "style", "style_width"])
def test_actual_alternate_resource_and_style_tamper_fails_cold(
    tmp_path, monkeypatch, synthetic_row, mutation
):
    path = _export(tmp_path, monkeypatch, synthetic_row)
    metadata = json.loads(path.with_suffix(".objects.json").read_text())
    doc = ezdxf.readfile(path)
    entity = next(iter(doc.modelspace().query("TEXT")))
    if mutation in ("font_bytes", "license_bytes", "lff_bytes"):
        key = {"font_bytes": "font", "license_bytes": "bundled_license", "lff_bytes": "librecad_font"}[mutation]
        with (tmp_path / FONT_SPEC[key]).open("ab") as stream:
            stream.write(b"changed resource identity")
    elif mutation == "lff_missing":
        (tmp_path / FONT_SPEC["librecad_font"]).unlink()
    elif mutation == "font_registry":
        row = next(r for r in metadata["fonts"] if r["font"] == FONT_SPEC["font"])
        row["sha256"] = "0" * 64
    elif mutation == "style":
        entity.dxf.style = "I2CAD_TEXT"
    else:
        doc.styles.get(FONT_SPEC["style"]).dxf.width = 1.05
    doc.saveas(path)
    _rewrite_hash(path, metadata)
    candidates, source = cold_native_text_bindings(
        path, ezdxf.readfile(path), synthetic_row[0], ROI, DPI, tmp_path,
    )
    assert not candidates[0]["pass"] and not source[0]["pass"]


@pytest.mark.parametrize("mutation", ["global_spacing", "glyph_outline", "missing_glyph"])
def test_companion_geometry_is_checked_even_when_resource_hash_is_coherently_rebound(
    tmp_path, monkeypatch, synthetic_row, packaged_font, mutation
):
    # Isolate the geometry proof from the immutable production resource lock:
    # a newly trusted hash alone cannot make a differing font pair equivalent.
    font = tmp_path / FONT_SPEC["font"]
    shutil.copyfile(packaged_font, font)
    companion = tmp_path / FONT_SPEC["librecad_font"]
    rows = packaged_font.with_name(FONT_SPEC["librecad_font"]).read_text().splitlines()
    changed, current = [], None
    for row in rows:
        if row.startswith("["):
            current = int(row[1:-1], 16)
        if mutation == "global_spacing" and row.startswith("# LetterSpacing:"):
            row = "# LetterSpacing: " + str(float(row.split(":", 1)[1]) * 1.05)
        if current == ord("P") and row and not row.startswith(("#", "[")):
            if mutation == "missing_glyph":
                continue
            if mutation == "glyph_outline":
                points = [list(map(float, item.split(","))) for item in row.split(";")]
                row = ";".join(f"{x + 0.1:.12f},{y:.12f}" for x, y in points)
        changed.append(row)
    companion.write_text("\n".join(changed) + "\n")
    profile = {**FONT_SPEC, "librecad_sha256": hashlib.sha256(companion.read_bytes()).hexdigest(),
               "librecad_bytes": companion.stat().st_size}
    monkeypatch.setattr(layout, "FONT_SPEC", profile)
    gray, geometry, partition, _ = synthetic_row
    checked = layout.fit_source_glyph_layout(geometry, partition, ROI, DPI, font, gray=gray)
    assert not checked["pass"] and "selected_layout" not in checked
    assert "LFF_LITERAL" in checked["reason"]


def test_one_saved_text_multifont_cold_and_preview_use_only_adjacent_resources(
    tmp_path, monkeypatch, synthetic_row
):
    path = _export(tmp_path, monkeypatch, synthetic_row, legacy=True)
    doc = ezdxf.readfile(path)
    assert len([e for e in doc.modelspace().query("TEXT") if e.dxf.layer != "REVIEW"]) == 2
    special = [e for e in doc.modelspace().query("TEXT") if e.dxf.style == FONT_SPEC["style"]]
    assert len(special) == 1 and special[0].dxf.text == synthetic_row[1]["text"]
    candidates, source = cold_native_text_bindings(path, doc, synthetic_row[0], ROI, DPI, tmp_path)
    assert len(candidates) == 2 and all(row["pass"] for row in candidates)
    assert len(source) == 1 and source[0]["pass"]
    assert source[0]["actual_saved_source_component_layout"]["pass"]
    assert text_contact_audit._neighbor_matches(
        special[0], _object(synthetic_row), ROI, DPI, tmp_path / FONT_SPEC["font"],
    )
    doc.styles.get(FONT_SPEC["style"]).dxf.width = 1.05
    assert not text_contact_audit._neighbor_matches(
        special[0], _object(synthetic_row), ROI, DPI, tmp_path / FONT_SPEC["font"],
    )
    doc.styles.get(FONT_SPEC["style"]).dxf.width = 1.0
    dependencies, _ = quality_review._font_dependencies(doc, path)
    assert all(row["pass"] for row in dependencies)
    before = tmp_path / "before.png"
    cad_io.render_saved(path, before, ROI, DPI)
    empty = FontManager()
    frozen_manager = empty.dumps()
    monkeypatch.setattr(fonts, "font_manager", empty)
    after = tmp_path / "without-host-fonts.png"
    record = cad_io.render_saved(path, after, ROI, DPI)
    assert np.array_equal(np.asarray(Image.open(before)), np.asarray(Image.open(after)))
    assert empty.dumps() == frozen_manager
    assert {r["font"] for r in record["portable_text_font"]["fonts"]} == {
        "DejaVuSans.ttf", FONT_SPEC["font"],
    }
    assert record["portable_text_font"]["system_font_fallback"] is False
    (tmp_path / FONT_SPEC["font"]).unlink()
    with pytest.raises(FileNotFoundError):
        cad_io.render_saved(path, tmp_path / "missing.png", ROI, DPI)
