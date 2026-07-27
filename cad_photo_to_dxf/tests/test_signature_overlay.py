from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.raster_trace import trace_binary
from app.signature_overlay import (
    SignatureRegion,
    detect_signature_regions,
    mark_graphic_texts,
    mark_signature_texts,
    signature_rgba,
    suppress_signature_strokes,
    suppress_text_strokes,
)
from app.trace_single_export import export_exact_trace_dxf


def _title_block() -> tuple[np.ndarray, tuple[TextCandidate, ...]]:
    binary = np.full((300, 400), 255, dtype=np.uint8)
    for x in (200, 260, 320, 380):
        cv2.line(binary, (x, 20), (x, 280), 0, 2)
    for y in (20, 60, 100, 140, 180, 220, 260, 280):
        cv2.line(binary, (200, y), (380, y), 0, 2)
    for y in (78, 118, 158):
        points = np.asarray(
            [(245, y + 4), (275, y - 8), (300, y + 6), (335, y - 5)],
            dtype=np.int32,
        )
        cv2.polylines(binary, [points], False, 0, 3, cv2.LINE_8)
    texts = (
        TextCandidate(
            text="签字",
            bbox=(270, 30, 40, 20),
            confidence=1.0,
            kind="text_candidate",
            source="test",
        ),
        TextCandidate(
            text="wrong-signature-ocr",
            bbox=(270, 66, 55, 25),
            confidence=0.99,
            kind="text_candidate",
            source="test",
        ),
    )
    return binary, texts


def test_signature_crossing_border_is_one_region_and_not_text() -> None:
    binary, texts = _title_block()
    regions = detect_signature_regions(binary, texts)

    assert len(regions) >= 3
    assert regions[0].bbox[0] < 260
    assert regions[0].bbox[0] + regions[0].bbox[2] > 320
    marked = mark_signature_texts(texts, regions)
    assert marked[1].kind == "signature_candidate"
    assert not marked[1].approved

    vector_binary = suppress_signature_strokes(binary, regions)
    assert vector_binary[82, 245] == 255
    assert vector_binary[70, 200] == 0
    assert vector_binary[100, 280] == 0


def test_blurred_lower_right_large_handwriting_uses_restricted_fallback() -> None:
    binary = np.full((300, 400), 255, dtype=np.uint8)
    for x in (320, 360, 390):
        cv2.line(binary, (x, 190), (x, 280), 0, 2)
    for y in (190, 220, 250, 280):
        cv2.line(binary, (320, y), (390, y), 0, 2)
    cv2.polylines(
        binary,
        [
            np.asarray(
                [(225, 245), (265, 225), (310, 250), (365, 230)],
                dtype=np.int32,
            )
        ],
        False,
        0,
        3,
    )
    candidates = (
        TextCandidate(
            text="普通文字",
            bbox=(325, 195, 50, 18),
            confidence=0.85,
            kind="text_candidate",
            source="test",
            replacement_safe=False,
            review_note="疑似签名或手写体",
        ),
        TextCandidate(
            text="手写签名",
            bbox=(225, 220, 145, 45),
            confidence=0.80,
            kind="text_candidate",
            source="test",
            replacement_safe=False,
            review_note="笔画连笔，疑似签名或手写体",
        ),
    )

    regions = detect_signature_regions(binary, candidates)

    assert len(regions) == 1
    assert regions[0].bbox[0] < 240
    assert regions[0].bbox[0] + regions[0].bbox[2] > 350
    marked = mark_signature_texts(candidates, regions)
    assert marked[0].kind != "signature_candidate"
    assert marked[1].kind == "signature_candidate"


def test_text_suppression_keeps_table_rules() -> None:
    binary, _texts = _title_block()
    cv2.putText(binary, "ABC", (215, 248), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 0, 2)
    candidate = TextCandidate(
        text="ABC",
        bbox=(213, 228, 45, 25),
        confidence=1.0,
        kind="text_candidate",
        source="test",
    )

    cleaned = suppress_text_strokes(binary, (candidate,))

    assert cleaned[245, 225] == 255
    assert cleaned[240, 200] == 0
    assert cleaned[260, 230] == 0


def test_signature_is_exported_as_transparent_top_image(tmp_path: Path) -> None:
    binary, texts = _title_block()
    regions = detect_signature_regions(binary, texts)[:1]
    vector_binary = suppress_signature_strokes(binary, regions)
    paths = trace_binary(vector_binary)
    stale_path = tmp_path / "signature.signature-999.png"
    stale_path.write_bytes(b"stale")

    result = export_exact_trace_dxf(
        paths,
        tmp_path / "signature.dxf",
        binary.shape[0],
        image_width=binary.shape[1],
        signatures=regions,
    )

    assert len(result.signature_paths) == 1
    assert not stale_path.exists()
    rgba = cv2.imread(str(result.signature_paths[0]), cv2.IMREAD_UNCHANGED)
    assert rgba is not None and rgba.shape[2] == 4
    assert 0 < np.count_nonzero(rgba[:, :, 3]) < rgba.shape[0] * rgba.shape[1]
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    images = list(modelspace.query("IMAGE"))
    assert len(images) == 1
    assert images[0].dxf.layer == "SIGNATURE_OVERLAY"
    assert int(images[0].dxf.flags) & 8
    redraw_order = dict(modelspace.get_redraw_order())
    assert redraw_order[images[0].dxf.handle] == "0"
    assert not document.audit().errors


def test_freeform_signature_beside_long_label_is_preserved() -> None:
    binary = np.full((260, 520), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        "SIGNATURE:",
        (80, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        0,
        2,
        cv2.LINE_8,
    )
    cv2.polylines(
        binary,
        [
            np.asarray(
                [(270, 155), (305, 125), (330, 165), (365, 120), (430, 150)],
                np.int32,
            )
        ],
        False,
        0,
        7,
        cv2.LINE_8,
    )
    candidate = TextCandidate(
        text="委托人签名或盖章：",
        bbox=(80, 105, 360, 70),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=False,
        review_note="识别框附近有未覆盖笔画",
    )

    regions = detect_signature_regions(binary, (candidate,))

    assert len(regions) == 1
    assert regions[0].bbox[0] < 285
    assert regions[0].bbox[0] + regions[0].bbox[2] > 420
    assert cv2.countNonZero(regions[0].mask) > 300
    assert mark_signature_texts((candidate,), regions)[0].kind == "signature_candidate"


def test_signature_rgba_keeps_original_stroke_footprint() -> None:
    mask = np.zeros((40, 80), dtype=np.uint8)
    cv2.line(mask, (5, 20), (70, 20), 255, 9, cv2.LINE_8)
    region = SignatureRegion((10, 20, 80, 40), mask)

    rgba = signature_rgba(region)

    assert np.array_equal(rgba[:, :, 3], mask)
    assert np.count_nonzero(rgba[:, :, 3]) == np.count_nonzero(mask)


def test_unsafe_text_suppression_does_not_erase_graphic_between_characters() -> None:
    binary = np.full((120, 240), 255, dtype=np.uint8)
    cv2.circle(binary, (32, 55), 9, 0, -1)
    cv2.circle(binary, (120, 55), 22, 0, 4)
    cv2.circle(binary, (202, 55), 9, 0, -1)
    candidate = TextCandidate(
        text="AB",
        bbox=(15, 30, 205, 50),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=False,
        character_boxes=((15, 30, 35, 50), (185, 30, 35, 50)),
    )

    cleaned = suppress_text_strokes(binary, (candidate,))

    assert cleaned[55, 32] == 255
    assert cleaned[55, 98] == 0


def test_compact_connected_ocr_candidate_is_kept_as_graphic() -> None:
    candidate = TextCandidate(
        text="SDD",
        bbox=(50, 40, 150, 45),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=False,
        review_note="笔画跨越多个字符格，疑似签名、手写体或图形，保留原轮廓",
    )

    resolved = mark_graphic_texts((candidate,), page_shape=(600, 800))

    assert resolved[0].kind == "graphic_candidate"
    assert not resolved[0].approved
