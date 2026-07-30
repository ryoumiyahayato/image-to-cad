from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

from app.auxiliary_recognition import TextCandidate
from app.content_ownership import partition_content
from app.logo_detection import LogoRegion, detect_logo_regions
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


def test_signature_detection_is_structural_and_does_not_reclassify_text() -> None:
    binary, texts = _title_block()
    regions = detect_signature_regions(binary, texts)

    assert len(regions) >= 3
    assert regions[0].bbox[0] < 260
    assert regions[0].bbox[0] + regions[0].bbox[2] > 320
    marked = mark_signature_texts(texts, regions)
    assert marked == texts

    vector_binary = suppress_signature_strokes(binary, regions)
    assert vector_binary[82, 245] == 255
    assert vector_binary[70, 200] == 0
    assert vector_binary[100, 280] == 0


def test_handwriting_detection_does_not_depend_on_ocr_content_or_page_position() -> None:
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

    renamed = tuple(
        TextCandidate(
            text=f"unrelated-{index}",
            bbox=item.bbox,
            confidence=item.confidence,
            kind=item.kind,
            source=item.source,
        )
        for index, item in enumerate(candidates)
    )
    renamed_regions = detect_signature_regions(binary, renamed)

    assert len(regions) == 1
    assert [item.bbox for item in regions] == [item.bbox for item in renamed_regions]
    assert regions[0].bbox[0] < 240
    assert regions[0].bbox[0] + regions[0].bbox[2] > 350
    marked = mark_signature_texts(candidates, regions)
    assert marked == candidates


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
    assert mark_signature_texts((candidate,), regions) == (candidate,)


def test_one_direction_plan_stroke_is_not_forced_to_signature_image() -> None:
    binary = np.full((180, 420), 255, dtype=np.uint8)
    cv2.polylines(
        binary,
        [
            np.asarray(
                [(35, 125), (125, 110), (220, 95), (330, 75)],
                dtype=np.int32,
            )
        ],
        False,
        0,
        4,
        cv2.LINE_8,
    )

    assert detect_signature_regions(binary) == ()
    ownership = partition_content(
        binary,
        lines=(),
        texts=(),
        logos=(),
        signatures=(),
    )
    assert cv2.countNonZero(ownership.signature) == 0
    assert cv2.countNonZero(ownership.graphic) > 0


def test_signature_rgba_keeps_original_stroke_footprint() -> None:
    mask = np.zeros((40, 80), dtype=np.uint8)
    cv2.line(mask, (5, 20), (70, 20), 255, 9, cv2.LINE_8)
    region = SignatureRegion((10, 20, 80, 40), mask)

    rgba = signature_rgba(region)

    assert np.array_equal(rgba[:, :, 3], mask)
    assert np.count_nonzero(rgba[:, :, 3]) == np.count_nonzero(mask)


def test_accepted_text_suppression_removes_the_complete_line_box() -> None:
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


def test_compact_connected_ocr_candidate_is_not_reclassified_as_graphic() -> None:
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

    assert resolved[0].kind == "text_candidate"
    assert resolved[0].approved


def test_split_table_text_is_not_misclassified_as_a_logo() -> None:
    candidate = TextCandidate(
        text="项目名称",
        bbox=(50, 40, 150, 45),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=False,
        character_boxes=(
            (55, 45, 25, 30),
            (85, 45, 25, 30),
            (115, 45, 25, 30),
            (145, 45, 25, 30),
        ),
        review_note="识别框附近仍有未覆盖笔画，保留原图形等待确认",
    )

    resolved = mark_graphic_texts((candidate,), page_shape=(600, 800))

    assert resolved[0].kind == "text_candidate"
    assert resolved[0].approved


def test_logo_words_do_not_reclassify_text_candidates() -> None:
    chinese = TextCandidate(
        text="申都设计",
        bbox=(80, 90, 180, 44),
        confidence=0.98,
        kind="text_candidate",
        source="test",
        replacement_safe=True,
        character_boxes=((80, 90, 40, 44),),
    )
    english = TextCandidate(
        text="SHENDU DESIGN GROUP",
        bbox=(90, 138, 230, 32),
        confidence=0.98,
        kind="text_candidate",
        source="test",
        replacement_safe=True,
        character_boxes=((90, 138, 20, 32),),
    )

    resolved = mark_graphic_texts((chinese, english), page_shape=(600, 800))

    assert resolved == (chinese, english)


def test_logo_semantics_do_not_capture_adjacent_text() -> None:
    logo = TextCandidate(
        text="SHENDU DESIGN GROUP",
        bbox=(80, 180, 360, 55),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=True,
        character_boxes=((80, 180, 20, 55),),
    )
    project_name = TextCandidate(
        text="Project Name",
        bbox=(500, 125, 150, 38),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=False,
        character_boxes=((500, 125, 12, 38),),
    )
    sheet_title = TextCandidate(
        text="Sheet Title",
        bbox=(500, 205, 140, 38),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=False,
        character_boxes=((500, 205, 12, 38),),
    )

    resolved = mark_graphic_texts(
        (logo, project_name, sheet_title),
        page_shape=(800, 1000),
    )

    assert resolved == (logo, project_name, sheet_title)


def test_logo_detector_uses_closed_geometry_instead_of_ocr_words() -> None:
    binary = np.full((220, 320), 255, dtype=np.uint8)
    cv2.circle(binary, (120, 110), 54, 0, 5)
    cv2.circle(binary, (120, 110), 28, 0, 5)
    cv2.circle(binary, (120, 110), 10, 0, 4)
    cv2.line(binary, (120, 56), (120, 164), 0, 4)

    regions = detect_logo_regions(binary)

    assert len(regions) == 1
    assert regions[0].hole_count >= 2
    assert regions[0].structural_score > 0.5
    assert regions[0].visual_kind == "graphic_mark"
    assert regions[0].payload()["evidence_source"] == "source_geometry_only"


@pytest.mark.parametrize(
    ("rendered_text", "ocr_text"),
    (
        ("DESIGN GROUP", "普通正文包含设计集团"),
        ("DESIGN", "标题中含 DESIGN"),
    ),
)
def test_design_words_do_not_create_logo_without_visual_evidence(
    rendered_text: str,
    ocr_text: str,
) -> None:
    binary = np.full((180, 700), 255, dtype=np.uint8)
    cv2.putText(
        binary,
        rendered_text,
        (20, 105),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        2,
        cv2.LINE_8,
    )
    candidate = TextCandidate(
        text=ocr_text,
        bbox=(15, 55, 650, 65),
        confidence=0.99,
        kind="text_candidate",
        source="negative-example",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )

    assert detect_logo_regions(binary) == ()
    assert mark_graphic_texts((candidate,), page_shape=binary.shape) == (
        candidate,
    )


def test_signature_bbox_overlap_does_not_capture_neighboring_body_text() -> None:
    binary = np.full((160, 420), 255, dtype=np.uint8)
    signature_mask = np.zeros((80, 300), dtype=np.uint8)
    cv2.polylines(
        signature_mask,
        [
            np.asarray(
                [(10, 48), (45, 18), (82, 58), (125, 16)],
                dtype=np.int32,
            )
        ],
        False,
        255,
        5,
        cv2.LINE_8,
    )
    binary[40:120, 20:320][signature_mask > 0] = 0
    cv2.putText(
        binary,
        "NORMAL BODY",
        (170, 92),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        0,
        2,
        cv2.LINE_8,
    )
    signature = SignatureRegion(
        bbox=(20, 40, 300, 80),
        mask=signature_mask,
    )
    body = TextCandidate(
        text="normal body",
        bbox=(165, 62, 165, 40),
        confidence=0.99,
        kind="text_candidate",
        source="negative-example",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )

    ownership = partition_content(
        binary,
        lines=(),
        texts=(body,),
        logos=(),
        signatures=(signature,),
    )

    body_x, body_y, body_width, body_height = body.bbox
    body_signature_pixels = cv2.countNonZero(
        ownership.signature[
            body_y : body_y + body_height,
            body_x : body_x + body_width,
        ]
    )
    assert body_signature_pixels == 0
    assert cv2.countNonZero(
        ownership.text[
            body_y : body_y + body_height,
            body_x : body_x + body_width,
        ]
    ) > 0
    assert cv2.countNonZero(ownership.signature) == cv2.countNonZero(
        signature_mask
    )


def test_graphic_logo_mask_does_not_absorb_adjacent_project_name() -> None:
    binary = np.full((220, 620), 255, dtype=np.uint8)
    logo_bbox = (30, 45, 130, 130)
    logo_mask = np.zeros((130, 130), dtype=np.uint8)
    cv2.circle(logo_mask, (65, 65), 52, 255, 5)
    cv2.circle(logo_mask, (65, 65), 25, 255, 5)
    cv2.line(logo_mask, (65, 13), (65, 117), 255, 4)
    binary[45:175, 30:160][logo_mask > 0] = 0
    cv2.putText(
        binary,
        "PROJECT NAME",
        (210, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        0,
        2,
        cv2.LINE_8,
    )
    logo = LogoRegion(
        bbox=logo_bbox,
        mask=logo_mask,
        structural_score=0.9,
        hole_count=2,
        contour_count=3,
        visual_kind="graphic_mark",
    )
    project_name = TextCandidate(
        text="Project Name",
        bbox=(205, 85, 250, 50),
        confidence=0.99,
        kind="text_candidate",
        source="negative-example",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )

    ownership = partition_content(
        binary,
        lines=(),
        texts=(project_name,),
        logos=(logo,),
        signatures=(),
    )

    x, y, width, height = project_name.bbox
    assert cv2.countNonZero(
        ownership.logo[y : y + height, x : x + width]
    ) == 0
    assert cv2.countNonZero(
        ownership.text[y : y + height, x : x + width]
    ) > 0
    assert cv2.countNonZero(ownership.logo) == cv2.countNonZero(logo_mask)


def test_letter_like_engineering_symbol_is_not_forced_to_logo_or_signature() -> None:
    binary = np.full((220, 320), 255, dtype=np.uint8)
    cv2.circle(binary, (120, 110), 40, 0, 3, cv2.LINE_8)
    cv2.putText(
        binary,
        "A",
        (96, 132),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.8,
        0,
        3,
        cv2.LINE_8,
    )

    assert detect_logo_regions(binary) == ()
    assert detect_signature_regions(binary) == ()
    ownership = partition_content(
        binary,
        lines=(),
        texts=(),
        logos=(),
        signatures=(),
    )
    assert cv2.countNonZero(ownership.logo) == 0
    assert cv2.countNonZero(ownership.signature) == 0
    assert cv2.countNonZero(ownership.graphic) > 0
