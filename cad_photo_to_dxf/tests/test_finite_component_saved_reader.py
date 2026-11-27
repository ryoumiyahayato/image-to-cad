"""Saved files, byte-bound fonts and explicit failures for issue 62's reader."""
import hashlib
import json
from fractions import Fraction

import ezdxf
import numpy as np
import pytest
from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app.native_objects.finite_component_saved_reader import (
    APPID,
    context_for_scope,
    exact_points,
    saved_source_geometries,
    sha256,
)
from app.native_objects.finite_component_source_audit import audit_saved_source_component


def _font(path, *, advance=600):
    """An openly generated test font; no local/system font dependency."""
    order = [".notdef", "space", "A", "x", "p", "D"]
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        if name not in (".notdef", "space"):
            top, bottom = (1000, 0) if name in ("A", "D") else (500, -200 if name == "p" else 0)
            pen.moveTo((0, bottom))
            pen.lineTo((500, bottom))
            if name == "D":
                pen.qCurveTo((900, 500), (500, top))
            else:
                pen.lineTo((500, top))
            pen.lineTo((0, top))
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: "space", 65: "A", 120: "x", 112: "p", 68: "D"})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (350 if name == "space" else advance, 0) for name in order})
    builder.setupHorizontalHeader(ascent=1000, descent=-200)
    builder.setupNameTable({"familyName": "IndependentTest", "styleName": "Regular", "uniqueFontIdentifier": "Test",
                           "fullName": "IndependentTest Regular", "psName": "IndependentTest-Regular"})
    builder.setupOS2(sTypoAscender=1000, sTypoDescender=-200, usWinAscent=1000, usWinDescent=200)
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)
    return sha256(path)


def _identity(entity, oid):
    entity.set_xdata(APPID, [(1000, json.dumps({"id": oid, "PASS": True, "source_chain": "forged"}))])


def _drawing(tmp_path, text="D D"):
    font_path = tmp_path / "fixture.ttf"
    digest = _font(font_path)
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    doc.styles.new("test-font", dxfattribs={"font": font_path.name})
    line = doc.modelspace().add_lwpolyline([(1, 2), (1.01, 2.01), (10, 8)])
    _identity(line, "path")
    letter = doc.modelspace().add_text(text, dxfattribs={"style": "test-font", "height": 10,
                                                      "width": 2., "insert": (100, 200)})
    _identity(letter, "text")
    path = tmp_path / "saved.dxf"
    doc.saveas(path)
    return path, {font_path.name: digest}


def _read(path, bindings):
    return saved_source_geometries(path, [0, 0, 2000, 2400], 254, font_bindings=bindings)


def _row(report, oid):
    return next(r for r in report["geometries"] if r["object_id"] == oid)


def test_actual_finite_points_and_short_segment_retained_without_producer_truth(tmp_path):
    path, bindings = _drawing(tmp_path)
    report = _read(path, bindings)
    row = _row(report, "path")
    assert len(row["points"]) == 3
    assert row["geometry_supported"] and row["coverage_valid"]
    scale = Fraction(25.4 / 254)
    assert exact_points(row)[1] == (Fraction(1.01) / scale, Fraction(2400) - Fraction(2.01) / scale)
    assert not report["producer_approval_consumed"]
    assert report["source_ownership_verdict"] == "NOT_ESTABLISHED_BY_SAVED_READER"
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE")
    entity.set_points([(1, 2), (1.01, 2.01), (10.000000000000002, 8)])
    doc.saveas(path)
    assert exact_points(_row(_read(path, bindings), "path"))[-1] != exact_points(row)[-1]


def test_font_bound_contains_quadratic_outline_and_only_excludes_proved_distant_text(tmp_path):
    path, bindings = _drawing(tmp_path)
    report = _read(path, bindings)
    row = _row(report, "text")
    assert report["counts"]["certified_text_members"] == 1
    assert row["coverage_valid"] and not row["geometry_supported"]
    proof = row["text_bound_proof"]
    assert proof["font_sha256"] == bindings["fixture.ttf"]
    assert not proof["decoder"]["font_fallback"]
    bounds = [Fraction(*v) for v in row["bbox_xyxy_exact"]]
    scale = Fraction(25.4 / 254)
    # Independently sample the original quadratic in the generated font.
    for offset in (0, 950):
        for i in range(101):
            t = Fraction(i, 100)
            gx = (1 - t) ** 2 * 500 + 2 * t * (1 - t) * 900 + t ** 2 * 500
            gy = 2 * t * (1 - t) * 500 + t ** 2 * 1000
            x = (100 + (offset + gx) * Fraction(1, 50)) / scale
            y = 2400 - (200 + gy * Fraction(1, 100)) / scale
            assert bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
    local = context_for_scope(report, [0, 0, 20, 20], exclude_object_ids=["path"])
    assert local["members"][0]["relation"] == "PROVED_DISJOINT"
    touching = context_for_scope(report, row["bbox_xyxy"], exclude_object_ids=["path"])
    assert touching["members"][0]["relation"] == "POSSIBLY_RELATED"
    assert touching["actual_conflict_count"] == 0


def test_font_missing_or_wrong_hash_never_inherits_bound_or_invents_conflict(tmp_path):
    path, bindings = _drawing(tmp_path)
    for pins, reason in (({}, "FONT_BINDING_MISSING"), ({"fixture.ttf": "0" * 64}, "FONT_SHA256_MISMATCH")):
        report = _read(path, pins)
        row = _row(report, "text")
        assert not row["coverage_valid"]
        assert row["extent_unknown_reason"] == reason
        local = context_for_scope(report, [0, 0, 20, 20], exclude_object_ids=["path"])
        assert local["members"][0]["relation"] == "UNKNOWN_EXTENT_RELEVANCE"
        assert local["actual_conflict_count"] == 0


def test_new_font_bytes_at_same_path_are_decoded_without_stale_path_cache(tmp_path):
    path, bindings = _drawing(tmp_path)
    old = _row(_read(path, bindings), "text")
    bindings["fixture.ttf"] = _font(tmp_path / "fixture.ttf", advance=800)
    new = _row(_read(path, bindings), "text")
    assert new["bbox_xyxy_exact"] != old["bbox_xyxy_exact"]
    assert new["text_bound_proof"]["font_sha256"] != old["text_bound_proof"]["font_sha256"]


def test_matching_digest_does_not_make_malformed_font_decodable(tmp_path):
    path, bindings = _drawing(tmp_path)
    font = tmp_path / "fixture.ttf"
    font.write_bytes(b"This is not an sfnt font.")
    bindings["fixture.ttf"] = sha256(font)
    row = _row(_read(path, bindings), "text")
    assert not row["coverage_valid"]
    assert row["extent_unknown_reason"] == "FONT_OUTLINE_DECODE_UNRESOLVED"


@pytest.mark.parametrize("attribute,value,reason", [
    ("rotation", 0.000000000000001, "TEXT_LAYOUT_OUTSIDE_FROZEN_SUBSET"),
    ("halign", 1, "TEXT_LAYOUT_OUTSIDE_FROZEN_SUBSET"),
    ("oblique", 1., "TEXT_LAYOUT_OUTSIDE_FROZEN_SUBSET"),
    ("text_generation_flag", 2, "TEXT_LAYOUT_OUTSIDE_FROZEN_SUBSET"),
    ("text", "Z", "FONT_CHARACTER_MAP_INCOMPLETE"),
    ("text", "D%%d", "NON_LITERAL_OR_CONTROL_TEXT"),
])
def test_unsupported_text_does_not_get_font_coverage(tmp_path, attribute, value, reason):
    path, bindings = _drawing(tmp_path)
    doc = ezdxf.readfile(path)
    letter = next(e for e in doc.modelspace() if e.dxftype() == "TEXT")
    setattr(letter.dxf, attribute, value)
    doc.saveas(path)
    row = _row(_read(path, bindings), "text")
    assert not row["coverage_valid"] and row["extent_unknown_reason"] == reason


@pytest.mark.parametrize("mutation,reason", [
    ("bulge", "CURVED_SEGMENTS_REQUIRE_EXACT_CURVE_AUDIT"),
    ("width", "FINITE_WIDTH_POLYLINE_REQUIRES_AREA_AUDIT"),
    ("closed", "CLOSED_PATH_OUTSIDE_FINITE_OPEN_MODEL"),
    ("elevation", "NONPLANAR_NATIVE_POLYLINE"),
    ("duplicate_vertex", "DEGENERATE_NATIVE_SEGMENT"),
])
def test_unsupported_polyline_cannot_become_straight_geometry(tmp_path, mutation, reason):
    path, bindings = _drawing(tmp_path)
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE")
    if mutation == "bulge":
        entity.set_points([(1, 2, .5), (10, 8, 0)], format="xyb")
    elif mutation == "width":
        entity.dxf.const_width = 1.
    elif mutation == "closed":
        entity.closed = True
    elif mutation == "elevation":
        entity.dxf.elevation = 1.
    else:
        entity.set_points([(1, 2), (1, 2), (10, 8)])
    doc.saveas(path)
    row = _row(_read(path, bindings), "path")
    assert not row["geometry_supported"]
    assert row["coverage_valid"] is (mutation == "closed")
    assert row["unsupported_reason"] == reason


def test_insert_transform_is_actual_and_multiple_insert_is_not_partially_accepted(tmp_path):
    path, bindings = _drawing(tmp_path)
    doc = ezdxf.readfile(path)
    block = doc.blocks.new("letters")
    block.add_text("D", dxfattribs={"style": "test-font", "height": 10, "insert": (5, 7)})
    insert = doc.modelspace().add_blockref("letters", (20, 30))
    _identity(insert, "block")
    doc.saveas(path)
    row = _row(_read(path, bindings), "block/member:0")
    assert row["coverage_valid"]
    assert row["bbox_xyxy"][0] <= 250 <= row["bbox_xyxy"][2]
    doc = ezdxf.readfile(path)
    insert = next(e for e in doc.modelspace() if e.dxftype() == "INSERT")
    insert.dxf.row_count = 2
    insert.dxf.row_spacing = 10
    doc.saveas(path)
    row = _row(_read(path, bindings), "block/unresolved")
    assert row["unsupported_reason"] == "MULTIPLE_INSERT_REQUIRES_COMPLETE_INSTANCE_AUDIT"
    assert not row["coverage_valid"]


def test_duplicate_and_missing_formal_identity_keep_geometry_and_block_identity(tmp_path):
    path, bindings = _drawing(tmp_path)
    doc = ezdxf.readfile(path)
    _identity(doc.modelspace().add_line((4, 5), (6, 7)), "path")
    doc.modelspace().add_line((8, 9), (10, 11))
    doc.saveas(path)
    report = _read(path, bindings)
    assert len(report["geometries"]) == 4
    assert {r["reason"] for r in report["identity_errors"]} == {"DUPLICATE_FORMAL_ID", "UNIDENTIFIED_FORMAL_ENTITY"}


def test_file_hash_pins_reject_changed_source_or_saved_file(tmp_path):
    path, bindings = _drawing(tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"original source")
    source_hash = hashlib.sha256(b"original source").hexdigest()
    report = saved_source_geometries(path, [0, 0, 2000, 2400], 254, font_bindings=bindings,
                                    expected_dxf_sha256=sha256(path), source_path=source,
                                    expected_source_sha256=source_hash)
    assert report["externally_bound_source_bytes"]
    source.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="ACTUAL_SOURCE_SHA256_MISMATCH"):
        saved_source_geometries(path, [0, 0, 2000, 2400], 254, source_path=source,
                                expected_source_sha256=source_hash)
    with pytest.raises(ValueError, match="ACTUAL_DXF_SHA256_MISMATCH"):
        saved_source_geometries(path, [0, 0, 2000, 2400], 254, expected_dxf_sha256="0" * 64)


def _saved_source_t(tmp_path, *, variant="normal"):
    """An independently rasterized, actually saved finite T; no producer plan."""
    yy, xx = np.indices((128, 128))
    centers = np.stack((xx, yy), axis=-1)
    def capsule(a, b, radius=2):
        a, b = np.asarray(a), np.asarray(b)
        delta = b - a
        times = np.clip((centers - a) @ delta / float(delta @ delta), 0, 1)
        nearest = a + times[..., None] * delta
        return np.sum((centers - nearest) ** 2, axis=-1) <= radius ** 2
    mask = capsule((60, 28), (60, 72)) | capsule((24, 72), (104, 72))
    if variant == "white_hole":
        mask[71, 61] = False
    elif variant == "continuation":
        mask |= capsule((60, 72), (60, 83))
    elif variant == "width_disagreement":
        mask |= capsule((60, 28), (60, 42), radius=5)
    gray = np.where(mask, 0, 255).astype(np.uint8)
    source = tmp_path / "source.png"
    Image.fromarray(gray).save(source)
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    guest = [(60, 100), (60, 99), (60, 56)]
    if variant == "wrong_geometry":
        guest[1] = (69, 84)
    _identity(doc.modelspace().add_lwpolyline(guest), "guest")
    if variant != "missing_host":
        _identity(doc.modelspace().add_line((24, 56), (104, 56)), "host")
    if variant == "duplicate":
        _identity(doc.modelspace().add_line((60, 100), (60, 56)), "duplicate")
    if variant == "unknown_text":
        _identity(doc.modelspace().add_text("D", dxfattribs={"height": 4, "insert": (58, 60)}), "text")
    dxf = tmp_path / "component.dxf"
    doc.saveas(dxf)
    return dxf, source


def _source_audit(dxf, source):
    return audit_saved_source_component(dxf, source, [0, 0, 128, 128], 25.4, ["guest"],
        expected_dxf_sha256=sha256(dxf), expected_source_sha256=sha256(source))


def test_independent_actual_saved_source_positive_can_pass_complete_component(tmp_path):
    dxf, source = _saved_source_t(tmp_path)
    result = _source_audit(dxf, source)
    assert result["status"] == "COMPLETE_SOURCE_PASS", result["failure_reasons"]
    assert result["independent_routes"]["producer_chain_consumed"] is False
    assert result["fresh_graph"]["source_graph_rebuilt_from_unmodified_image"]
    assert result["finite_component_model"]["observation_closed"]
    assert result["finite_component_model"]["coherent_component_model"]["pass"]
    assert len(result["reconstructed_source_bindings"][0]["representation"]["points"]) == 3
    assert all(e["native_short_segment_preserved"] for e in result["finite_component_model"]["endpoints"])


@pytest.mark.parametrize("variant,status", [
    ("wrong_geometry", "HARD_REJECT_SAVED_FINITE_GEOMETRY"),
    ("duplicate", "HARD_REJECT_SAVED_FINITE_GEOMETRY"),
    ("missing_host", "PENDING_INDEPENDENT_SOURCE_EVIDENCE"),
    ("unknown_text", "PENDING_INDEPENDENT_SOURCE_EVIDENCE"),
    ("white_hole", "PENDING_INDEPENDENT_SOURCE_EVIDENCE"),
    ("continuation", "PENDING_INDEPENDENT_SOURCE_EVIDENCE"),
    ("width_disagreement", "MODEL_NOT_APPLICABLE_CONSTANT_WIDTH"),
])
def test_independent_saved_source_falsifiers_cannot_inherit_positive(tmp_path, variant, status):
    dxf, source = _saved_source_t(tmp_path, variant=variant)
    result = _source_audit(dxf, source)
    assert not result["pass"] and result["status"] == status
    assert result["failure_reasons"]
    if variant == "missing_host":
        assert any(i["reason"] == "PENDING_ATTACHMENT_HAS_NO_UNIQUE_COMPLETE_SAVED_HOST"
                   for i in result["independent_routes"]["issues"])
    if variant == "unknown_text":
        assert result["unresolved_relevant_context"]


def test_certified_distant_text_does_not_block_complete_local_source(tmp_path):
    dxf, source = _saved_source_t(tmp_path)
    font = tmp_path / "fixture.ttf"
    digest = _font(font)
    doc = ezdxf.readfile(dxf)
    doc.styles.new("test-font", dxfattribs={"font": font.name})
    _identity(doc.modelspace().add_text("D", dxfattribs={"style": "test-font", "height": 4,
                                                      "insert": (2, 2)}), "distant-text")
    doc.saveas(dxf)
    result = audit_saved_source_component(dxf, source, [0, 0, 128, 128], 25.4, ["guest"],
        font_bindings={font.name: digest}, expected_source_sha256=sha256(source))
    assert result["status"] == "COMPLETE_SOURCE_PASS", result["failure_reasons"]
    text = next(r for r in result["context_relevance"]["members"] if r["object_id"] == "distant-text")
    assert text["relation"] == "PROVED_DISJOINT" and text["actual_conflict_asserted"] is False


def test_v2_dispatch_reconstructs_actual_targets_and_preserves_exact_junction_gate(tmp_path):
    dxf, source = _saved_source_t(tmp_path)
    result = audit_saved_source_component(dxf, source, [0, 0, 128, 128], 25.4, ["guest", "host"],
        source_model="v2", prior_source_bindings=[], circle_source_objects=[],
        expected_dxf_sha256=sha256(dxf), expected_source_sha256=sha256(source))
    assert result["schema"] == "independent-saved-finite-component-source-acceptance-v2"
    assert result["independent_routes"]["pass"], result["independent_routes"]
    assert len(result["reconstructed_source_bindings"]) == 2
    guest = next(r for r in result["reconstructed_source_bindings"] if r["stroke_id"] == "guest")
    terminal = guest["endpoint_evidence"][1]
    assert terminal["independent_exact_finite_contact_squared_distance"]["numerator"] == "0"
    assert terminal["independent_raw_ink_junction_domain"]["pass"]
    assert not result["prior_whole_routes_reconstructed_as_targets"]
    assert "finite_component_model" in result


def test_v2_dispatch_does_not_let_new_source_model_hide_saved_white_geometry(tmp_path):
    dxf, source = _saved_source_t(tmp_path, variant="wrong_geometry")
    result = audit_saved_source_component(dxf, source, [0, 0, 128, 128], 25.4, ["guest", "host"],
        source_model="v2", prior_source_bindings={}, circle_source_objects=[],
        expected_dxf_sha256=sha256(dxf), expected_source_sha256=sha256(source))
    assert not result["pass"] and result["status"] == "HARD_REJECT_SAVED_FINITE_GEOMETRY"
    assert result["finite_component_model"]["status"] == "NOT_RUN_INDEPENDENT_SOURCE_PREREQUISITE_PENDING"
