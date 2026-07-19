from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from app import ocr_recognition


class _FakeRapidOcr:
    def __call__(self, image, **_kwargs):
        height, width = image.shape[:2]
        right = min(float(width - 1), 60.0)
        bottom = min(float(height - 1), 40.0)
        return SimpleNamespace(
            word_results=[
                [
                    "火",
                    0.96,
                    [[10.0, 10.0], [right, 10.0], [right, bottom], [10.0, bottom]],
                ]
            ],
            boxes=None,
            txts=(),
            scores=(),
        )


def test_rapidocr_candidates_are_mapped_and_rendered(monkeypatch) -> None:
    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", _FakeRapidOcr())
    image = np.full((100, 200, 3), 255, dtype=np.uint8)

    candidates, warnings = ocr_recognition.recognize_text_candidates(image)

    assert not warnings
    assert candidates
    assert all(candidate.text == "火" for candidate in candidates)
    assert all(candidate.confidence == 0.96 for candidate in candidates)
    assert all(candidate.source == "rapidocr-character" for candidate in candidates)
    assert all(candidate.quad is not None for candidate in candidates)
    overlay = ocr_recognition.render_ocr_overlay(image, candidates)
    assert overlay.shape == image.shape
    assert not np.array_equal(overlay, image)


def test_low_confidence_ocr_is_not_exported(monkeypatch) -> None:
    class LowConfidence:
        def __call__(self, _image, **_kwargs):
            return SimpleNamespace(
                word_results=[
                    [
                        "错误",
                        0.2,
                        [[1.0, 1.0], [20.0, 1.0], [20.0, 10.0], [1.0, 10.0]],
                    ]
                ],
                boxes=None,
                txts=(),
                scores=(),
            )

    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", LowConfidence())
    candidates, warnings = ocr_recognition.recognize_text_candidates(
        np.full((50, 80, 3), 255, dtype=np.uint8)
    )

    assert candidates == ()
    assert warnings


def test_installed_rapidocr_runtime_accepts_character_box_options(monkeypatch) -> None:
    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", None)
    image = np.full((120, 260, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "A1",
        (55, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )

    candidates = ocr_recognition._recognize_rapidocr_pass(image, rotation=0)

    assert isinstance(candidates, list)
    assert ocr_recognition._RAPID_OCR_ENGINE is not None
