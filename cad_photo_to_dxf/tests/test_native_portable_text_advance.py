"""Saved legacy TEXT must use its adjacent font, regardless of host fonts."""

from copy import deepcopy
import json

import ezdxf
from ezdxf.fonts import fonts
from ezdxf.fonts.font_manager import FontManager
import numpy as np
import pytest

from app.native_objects import cad_io


ROI = [0, 0, 320, 200]
DPI = 200
MM = 25.4 / DPI


def _object(kind, text="WIDE-27, A3"):
    geometry = {
        "text": text,
        "x": 42.0,
        "y": 93.0,
        "height_px": 22.0,
        "width_px": 164.0,
        "rotation_deg_image": 0.0,
    }
    if kind == "ROOM_LABEL":
        geometry = {
            "frame_points": [[30, 60], [218, 60], [218, 108], [30, 108]],
            "text_geometry": geometry,
        }
    return {
        "id": "portable-advance-check",
        "kind": kind,
        "layer": "ROOM_LABELS" if kind == "ROOM_LABEL" else "ANNOTATION",
        "geometry": geometry,
    }


def _saved_text(path):
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace() if e.dxf.layer != "REVIEW")
    if entity.dxftype() == "INSERT":
        entity = next(e for e in doc.blocks.get(entity.dxf.name) if e.dxftype() == "TEXT")
    return entity


def _cold(path):
    return cad_io.cold_audit(
        path,
        np.full((200, 320), 255, np.uint8),
        ROI,
        DPI,
        path.parent / "evidence/cold.json",
    )


@pytest.mark.parametrize("kind", ["TEXT", "ROOM_LABEL"])
@pytest.mark.parametrize("literal", ["WIDE-27, A3", "III-308, B2"])
def test_legacy_text_advance_is_identical_without_installed_fonts(
    tmp_path, monkeypatch, kind, literal
):
    obj = _object(kind, literal)
    regular = tmp_path / "regular/result.dxf"
    isolated = tmp_path / "isolated/result.dxf"
    cad_io.export_objects([obj], regular, ROI, DPI, "unchanged-source")
    expected = cad_io.entity_data(_saved_text(regular))

    # The actual portable file remains intact. No system registration or
    # cache mutation is allowed to repair this deliberately empty host.
    manager = FontManager()
    unchanged_manager = manager.dumps()
    monkeypatch.setattr(fonts, "font_manager", manager)

    def host_measurement_is_not_the_saved_font(*args, **kwargs):
        pytest.fail("Legacy TEXT consulted host font measurement")

    monkeypatch.setattr(cad_io, "text_size", host_measurement_is_not_the_saved_font)
    cad_io.export_objects([obj], isolated, ROI, DPI, "unchanged-source")
    actual = _saved_text(isolated)
    assert cad_io.entity_data(actual) == expected
    portable = fonts.sideload_ttf(isolated.parent / "DejaVuSans.ttf", actual.dxf.height)
    geometry = obj["geometry"] if kind == "TEXT" else obj["geometry"]["text_geometry"]
    assert portable.text_width(actual.plain_text()) * actual.dxf.width / MM == pytest.approx(
        geometry["width_px"], abs=1e-9
    )
    assert actual.dxf.height == geometry["height_px"] * MM
    assert actual.dxf.text == literal
    if kind == "TEXT":
        cold = _cold(isolated)
        assert cold["source_gate_pass"]
        assert len(cold["native_text_candidate_checks"]) == 1
        assert cold["native_text_candidate_checks"][0]["pass"]
        assert cold["single_line_text_source_checks"] == []
    assert manager.dumps() == unchanged_manager


@pytest.mark.parametrize("factor", [0.95, 1.035])
def test_coherently_rebound_wrong_font_width_still_fails_saved_candidate(
    tmp_path, monkeypatch, factor
):
    path = tmp_path / "result.dxf"
    cad_io.export_objects([_object("TEXT")], path, ROI, DPI, "unchanged-source")
    metadata_path = path.with_suffix(".objects.json")
    metadata = json.loads(metadata_path.read_text())
    original_candidate = deepcopy(metadata["objects"])
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace() if e.dxftype() == "TEXT")
    entity.dxf.width *= factor
    doc.saveas(path)
    # Simulate the old shared-fallback mistake: the writer's receipt honestly
    # describes the wrong saved width. The source candidate is not changed.
    binding = metadata["written"][0]["text_geometry_binding"]
    binding["actual_text_attributes"]["width"] = float(entity.dxf.width)
    metadata["dxf_sha256"] = cad_io.sha(path)
    metadata_path.write_text(json.dumps(metadata))
    monkeypatch.setattr(fonts, "font_manager", FontManager())
    report = _cold(path)
    check = report["native_text_candidate_checks"][0]
    assert check["saved_candidate_checks"]["written_attributes_match_actual"]
    assert not check["saved_candidate_checks"]["actual_width_matches_candidate"]
    assert not check["pass"]
    assert not report["source_gate_pass"]
    assert json.loads(metadata_path.read_text())["objects"] == original_candidate

