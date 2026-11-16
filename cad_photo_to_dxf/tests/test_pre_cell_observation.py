"""Recovery metadata must not gain placement or source authority."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

from app.ocr.auxiliary_recognition import TextCandidate, TextObservation
from app.ocr.ocr_layout import constrain_texts_to_table_cells
from app.ocr.ocr_overlap import collapse_overlapping_candidates
from app.core.cache import _serialize_texts, _deserialize_texts, save_trace_cache, load_trace_cache
from app.core.structure_build import build_final_structure
from app.core.review_project import ReviewProject, _candidate_fact, _trace_result
from app.core.processing import ProductionProcessingConfig, build_processing_cache_key, file_content_sha256
from app.export.ocr_outline_export import native_text_placement

APP = QApplication.instance() or QApplication([])


def sample():
    gray = np.full((100, 160), 255, np.uint8)
    candidate = TextCandidate("ROOM 12", (15, 20, 95, 20), .99, "text_candidate",
        quad=((15., 20.), (110., 20.), (110., 40.), (15., 40.)), source="rapidocr-tile")
    return gray, candidate


def test_observation_follows_winner_after_reorder_copy_and_cache():
    gray, c = sample()
    loser = replace(c, confidence=.7)
    other = replace(c, text="ROOM 34", bbox=(15, 65, 95, 20),
                    quad=((15., 65.), (110., 65.), (110., 85.), (15., 85.)))
    captured = constrain_texts_to_table_cells(gray, (loser, other, c))
    output = collapse_overlapping_candidates(captured)
    assert [t.pre_cell_observation.candidate_index for t in output] == [2, 1]
    assert output[0].pre_cell_observation.bbox == c.bbox
    copied = deepcopy(replace(output[0], review_note="copied"))
    recovered = _deserialize_texts(_serialize_texts((copied,)))[0]
    assert recovered.pre_cell_observation == copied.pre_cell_observation
    assert recovered.pre_cell_observation.text == copied.text
    assert constrain_texts_to_table_cells(gray, (recovered,))[0].pre_cell_observation.candidate_index == 2


def test_observation_error_does_not_change_cell_business_or_native_placement(monkeypatch):
    gray, c = sample()
    for x in (10, 80, 150):
        cv2.line(gray, (x, 10), (x, 90), 0, 1)
    for y in (10, 55, 90):
        cv2.line(gray, (10, y), (150, y), 0, 1)
    observed = constrain_texts_to_table_cells(gray, (c,))[0]
    def fail(*args):
        raise ValueError("observation unavailable")
    monkeypatch.setattr(TextObservation, "capture", fail)
    fallback = constrain_texts_to_table_cells(gray, (c,))[0]
    assert fallback.pre_cell_observation is None
    assert observed.pre_cell_observation.bbox == c.bbox
    assert observed.pre_cell_observation.cell_clip_bbox == observed.bbox
    assert observed.pre_cell_observation.cell_clip_quad == observed.quad
    a, b = asdict(observed), asdict(fallback)
    a.pop("pre_cell_observation"); b.pop("pre_cell_observation")
    assert a == b
    assert observed == fallback
    transform = lambda x, y: (x, 100-y)
    assert native_text_placement(observed, transform=transform) == native_text_placement(fallback, transform=transform)


def test_old_or_invalid_observation_does_not_invent_source_or_drop_text():
    _, c = sample()
    legacy = _serialize_texts((c,))
    assert "pre_cell_observation" not in legacy
    assert "pre_cell_observation" not in _candidate_fact(c)
    assert _deserialize_texts(legacy)[0].pre_cell_observation is None
    payload = json.loads(legacy)
    payload[0]["pre_cell_observation"] = {"stage": "pre-table-cell-v1", "bbox": [1]}
    restored = _deserialize_texts(json.dumps(payload))
    assert len(restored) == 1 and restored[0] == c
    assert restored[0].pre_cell_observation is None


def test_nonfinite_observation_cannot_break_project_fact_serialization():
    _, c = sample()
    payload = dict(TextObservation.capture(c, 0).payload(), rotation_deg=float("nan"))
    serialized = json.loads(_serialize_texts((c,)))
    serialized[0]["pre_cell_observation"] = payload
    recovered = _deserialize_texts(json.dumps(serialized))[0]
    assert recovered.pre_cell_observation is None
    assert _candidate_fact(recovered)["text"] == c.text


def test_actual_cache_and_review_project_restore_the_same_observation(tmp_path):
    gray, c = sample()
    for x in (10, 80, 150):
        cv2.line(gray, (x, 10), (x, 90), 0, 1)
    for y in (10, 55, 90):
        cv2.line(gray, (10, y), (150, y), 0, 1)
    observed = constrain_texts_to_table_cells(gray, (c,))[0]
    assert observed.pre_cell_observation.cell_clip_bbox == observed.bbox != c.bbox
    structure = build_final_structure(source_size_px=(160, 100), contour_binary=gray,
                                     contours=(), texts=(observed,), preview_binary=gray)
    cache = tmp_path / "observed.npz"
    save_trace_cache(cache, _trace_result(structure))
    restored = load_trace_cache(cache).final_structure
    assert restored.texts[0].pre_cell_observation == observed.pre_cell_observation
    source = tmp_path / "source.png"
    cv2.imwrite(str(source), gray)
    # Existing project creation requires its own source-integrity binding.
    # No separate digest list, new integrity mechanism or result metric.
    key = build_processing_cache_key(input_content_sha256=file_content_sha256(source),
                                    page_index=None, config=ProductionProcessingConfig())
    project = ReviewProject.create(structure, source_path=source, cache_key=key.payload())
    path = tmp_path / "observed.icreview"
    project.save(path)
    project.close()
    reopened = ReviewProject.open(path)
    try:
        assert reopened.baseline.texts[0].pre_cell_observation == observed.pre_cell_observation
        assert reopened.bindings[0]["original_candidate"]["pre_cell_observation"] == observed.pre_cell_observation.payload()
    finally:
        reopened.close()
