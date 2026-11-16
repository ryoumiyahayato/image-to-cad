"""Experimental display can enlarge a fit, never source or visible contacts."""
from dataclasses import asdict, replace
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2
import numpy as np
import pytest
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from app.ocr.auxiliary_recognition import TextCandidate, TextObservation
from app.ocr.observed_text_display import (
    RECORD_KEY,
    _joint_conflicts,
    _source_fit,
    refine_observed_text_displays,
    refine_unfitted_pdf_labels,
)
from app.core.structure_build import build_final_structure
from app.core.processing import ProductionProcessingConfig
from app.export.ocr_outline_export import native_text_placement
from app.export.review_text import glyph_footprint
from app.geometry.line_detect import LineSegment

APP = QApplication.instance() or QApplication([])


def sample(turns=0, separator=False):
    gray = np.full((100, 180), 255, np.uint8)
    cv2.putText(gray, "ABC", (28, 47), cv2.FONT_HERSHEY_SIMPLEX, .8, 0, 1, cv2.LINE_8)
    if separator:
        cv2.line(gray, (49, 10), (49, 80), 0, 1)
    observed = ((20., 20.), (140., 20.), (140., 55.), (20., 55.))
    current = ((20., 20.), (48., 20.), (48., 55.), (20., 55.))
    h, w = gray.shape
    for _ in range(turns):
        observed = tuple((y, w-1-x) for x, y in observed)
        current = tuple((y, w-1-x) for x, y in current)
        gray = np.ascontiguousarray(np.rot90(gray))
        h, w = w, h
    def bounds(q):
        xs, ys = zip(*q)
        return (int(min(xs)), int(min(ys)), int(max(xs)-min(xs)), int(max(ys)-min(ys)))
    original = TextCandidate("ABC", bounds(observed), .99, "text_candidate",
                             quad=observed, source="rapidocr-line", rotation_deg=-90.*turns)
    observation = replace(TextObservation.capture(original, 7),
                          cell_clip_bbox=bounds(current), cell_clip_quad=current)
    text = replace(original, bbox=bounds(current), quad=current,
                   pre_cell_observation=observation)
    empty = np.full(gray.shape, 255, np.uint8)
    structure = build_final_structure(source_size_px=gray.shape[::-1], contour_binary=empty,
        contours=(), texts=(text,), editable_text_source_mask=np.zeros(gray.shape, np.uint8),
        source_text_outline_mask=np.zeros(gray.shape, np.uint8),
        uncertain_text_outline_mask=np.zeros(gray.shape, np.uint8), preview_binary=gray)
    return gray, structure


@pytest.mark.parametrize("turns", range(4))
def test_complete_source_display_preserves_reading_and_all_source_fields(turns):
    gray, baseline = sample(turns)
    result = refine_observed_text_displays(gray, baseline)
    before, after = baseline.texts[0], result.texts[0]
    assert after.display_quad is not None
    a, b = asdict(before), asdict(after)
    a.pop("display_quad"); b.pop("display_quad")
    assert a == b
    for name in ["contour_binary", "preview_binary", "editable_text_source_mask",
                 "source_text_outline_mask", "uncertain_text_outline_mask"]:
        assert np.array_equal(getattr(baseline, name), getattr(result, name))
    old = native_text_placement(before, transform=lambda x, y: (x, gray.shape[0]-y))
    new = native_text_placement(after, transform=lambda x, y: (x, gray.shape[0]-y))
    assert new.geometry.rotation == pytest.approx(old.geometry.rotation)
    assert new.geometry.target_width > old.geometry.target_width
    assert result.provenance[RECORD_KEY]["source_deletion_authority"] is False


def test_crossing_cell_rule_or_incomplete_component_is_not_display_authority():
    gray, baseline = sample(separator=True)
    result = refine_observed_text_displays(gray, baseline)
    assert result.texts == baseline.texts
    assert result.provenance[RECORD_KEY]["decisions"][0]["decision"] == "REJECTED"
    assert result.provenance[RECORD_KEY]["decisions"][0]["reason"] in {
        "INCOMPLETE_OR_SHARED_SOURCE_COMPONENT", "SOURCE_RULE_BETWEEN_GLYPHS"}


@pytest.mark.parametrize("turns", (0, 1))
def test_padded_pdf_label_uses_complete_ink_and_respects_protection(turns):
    gray, baseline = sample(turns)
    clipped = baseline.texts[0]
    observation = clipped.pre_cell_observation
    label = replace(clipped, bbox=observation.bbox, quad=observation.quad,
                    pre_cell_observation=None)
    fitted, = refine_unfitted_pdf_labels(gray, (label,), protected_source_masks=())
    assert fitted.display_quad is not None
    assert replace(fitted, display_quad=None) == label
    assert refine_unfitted_pdf_labels(gray, (fitted,), protected_source_masks=()) == (fitted,)

    protected = np.zeros_like(gray)
    x, y = map(int, fitted.display_quad[0])
    protected[y, x] = 255
    assert refine_unfitted_pdf_labels(gray, (label,), protected_source_masks=(protected,)) == (label,)
    assert refine_unfitted_pdf_labels(gray, (clipped,), protected_source_masks=()) == (clipped,)


def test_visible_old_outline_or_structure_contact_blocks_enlargement():
    gray, baseline = sample()
    quad, _ = _source_fit(gray, baseline.texts[0].pre_cell_observation)
    fitted = replace(baseline.texts[0], display_quad=quad)
    path = glyph_footprint(native_text_placement(fitted, transform=lambda x, y: (x, gray.shape[0]-y)))
    # Place a real visible CAD stroke on the new rightmost glyph, beyond the
    # original narrow display. Its source authority must stay unchanged.
    x = path.boundingRect().right()-.2
    line = LineSegment(x, 0, x, 99, width=1.)
    baseline = replace(baseline, straight_lines=(line,))
    result = refine_observed_text_displays(gray, baseline)
    assert result.texts == baseline.texts
    assert result.straight_lines == baseline.straight_lines
    assert result.provenance[RECORD_KEY]["decisions"][0]["reason"] == "NEW_VISIBLE_GEOMETRY_OR_OLD_OUTLINE_CONTACT"


def test_joint_expansions_cannot_collide_between_old_texts():
    def rect(a, b):
        p = QPainterPath(); p.addRect(a, 0, b-a, 10); return p
    originals = {0: rect(0, 10), 1: rect(30, 40)}
    proposals = {0: (None, rect(0, 22), None), 1: (None, rect(18, 40), None)}
    assert not proposals[0][1].intersects(originals[1])
    assert not proposals[1][1].intersects(originals[0])
    assert _joint_conflicts(proposals, originals) == {0, 1}


@pytest.mark.parametrize("quad", [((20.,20.),)*4,
    ((float("nan"),20.),(80.,20.),(80.,40.),(20.,40.))])
def test_invalid_observation_keeps_native_text(quad):
    gray, baseline = sample()
    t = baseline.texts[0]
    baseline = replace(baseline, texts=(replace(t, pre_cell_observation=replace(t.pre_cell_observation, quad=quad)),))
    result = refine_observed_text_displays(gray, baseline)
    assert result.texts == baseline.texts
    assert native_text_placement(result.texts[0], transform=lambda x, y: (x, 100-y)) is not None


def test_missing_observation_and_default_config_do_not_enable_recovery():
    gray, baseline = sample()
    baseline = replace(baseline, texts=(replace(baseline.texts[0], pre_cell_observation=None),))
    assert refine_observed_text_displays(gray, baseline) is baseline
    config = ProductionProcessingConfig()
    assert config.experimental_observed_text_display is False
    assert "experimental_observed_text_display" not in config.payload()
    assert ProductionProcessingConfig(experimental_observed_text_display=True).payload()["experimental_observed_text_display"] is True


def test_border_context_outside_body_does_not_veto_complete_source():
    gray, baseline = sample()
    # Both extend outside the actual observation. Their limited intrusion has
    # at least two paper pixels to the complete letters, and changes no mask.
    cv2.line(gray, (86, 0), (86, 20), 0, 1)
    cv2.line(gray, (92, 54), (92, 99), 0, 1)
    result = refine_observed_text_displays(gray, baseline)
    assert result.texts[0].display_quad is not None
    assert np.array_equal(result.contour_binary, baseline.contour_binary)
    assert result.provenance[RECORD_KEY]["decisions"][0]["measured_border_context_components"] == 2


def test_boundary_fragment_into_body_still_rejects_source_fit():
    gray, baseline = sample()
    cv2.line(gray, (36, 0), (36, 38), 0, 1)
    result = refine_observed_text_displays(gray, baseline)
    assert result.texts == baseline.texts
    assert result.provenance[RECORD_KEY]["decisions"][0]["decision"] == "REJECTED"


def test_post_cell_geometry_change_and_missing_marker_keep_baseline():
    gray, baseline = sample()
    t = baseline.texts[0]
    missing = replace(t.pre_cell_observation, cell_clip_bbox=None, cell_clip_quad=None)
    old = replace(baseline, texts=(replace(t, pre_cell_observation=missing),))
    assert refine_observed_text_displays(gray, old) is old
    moved = replace(baseline, texts=(replace(t, bbox=(20, 20, 29, 35)),))
    result = refine_observed_text_displays(gray, moved)
    assert result.texts == moved.texts
    assert result.provenance[RECORD_KEY]["decisions"][0]["reason"] == "SOURCE_FIELDS_CHANGED_AFTER_CELL"


def test_normal_service_flag_applies_after_existing_display(monkeypatch):
    from app.core import processing
    from app.core.review_project import _trace_result
    from app.ocr import proven_row_group_display, observed_text_display
    gray, baseline = sample()
    order = []
    def trace(*args, **kwargs):
        order.append("trace")
        return _trace_result(baseline)
    def legacy(gray, structure):
        order.append("legacy-display")
        return structure
    actual = observed_text_display.refine_observed_text_displays
    def experimental(gray, structure):
        order.append("experimental-display")
        return actual(gray, structure)
    monkeypatch.setattr(processing, "trace_image_optimized", trace)
    monkeypatch.setattr(proven_row_group_display, "refine_proven_row_group_displays", legacy)
    monkeypatch.setattr(observed_text_display, "refine_observed_text_displays", experimental)
    off = processing.ProductionProcessingService.process_page(gray, ProductionProcessingConfig())
    assert order == ["trace", "legacy-display"]
    assert off.final_structure.texts == baseline.texts
    order.clear()
    on = processing.ProductionProcessingService.process_page(gray,
        ProductionProcessingConfig(experimental_observed_text_display=True))
    assert order == ["trace", "legacy-display", "experimental-display"]
    assert on.final_structure.texts[0].display_quad is not None
    assert np.array_equal(on.final_structure.contour_binary, baseline.contour_binary)
