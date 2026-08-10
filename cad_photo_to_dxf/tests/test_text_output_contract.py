from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.final_structure import build_final_structure
from app.raster_trace import trace_binary
from app.text_output_contract import (
    TextOutputState,
    accepted_ocr_texts,
    decide_text_output,
    text_output_summary,
)
from app.trace_single_export import (
    export_exact_trace_dxf,
    export_final_structure_dxf,
)


def _candidate(**changes: object) -> TextCandidate:
    values: dict[str, object] = {
        "text": "ROOM",
        "bbox": (20, 20, 80, 30),
        "confidence": 0.95,
        "kind": "text_candidate",
        "source": "contract-test",
        "approved": True,
        "reviewed": False,
        "replacement_safe": True,
    }
    values.update(changes)
    return TextCandidate(**values)  # type: ignore[arg-type]


def test_text_output_states_are_mutually_exclusive_and_reasoned() -> None:
    editable = decide_text_output(_candidate())
    unsafe_editable = decide_text_output(
        _candidate(replacement_safe=False)
    )
    residual = decide_text_output(
        _candidate(confidence=0.10)
    )

    assert editable.state is TextOutputState.EDITABLE_TEXT
    assert editable.output_layer == "OCR_TEXT"
    assert editable.editable
    assert editable.downgrade_reason is None
    assert editable.text_emit_eligible
    assert editable.source_outline_suppressible
    assert editable.hard_reject_reason is None

    assert unsafe_editable.state is TextOutputState.EDITABLE_TEXT
    assert unsafe_editable.output_layer == "OCR_TEXT"
    assert unsafe_editable.editable
    assert unsafe_editable.text_emit_eligible
    assert not unsafe_editable.source_outline_suppressible
    assert unsafe_editable.downgrade_reason is None
    assert unsafe_editable.hard_reject_reason is None

    assert residual.state is TextOutputState.TEXT_FALLBACK_OUTLINE
    assert residual.output_layer == "TEXT_FALLBACK_OUTLINE"
    assert not residual.editable
    assert residual.downgrade_reason == "confidence_below_contract"
    assert not residual.text_emit_eligible
    assert residual.hard_reject_reason == "confidence_below_contract"


def test_review_and_source_safety_do_not_block_text_emission() -> None:
    reviewed_unsafe = _candidate(
        confidence=0.10,
        reviewed=True,
        replacement_safe=False,
    )

    decision = decide_text_output(reviewed_unsafe)

    assert decision.state is TextOutputState.EDITABLE_TEXT
    assert decision.text_emit_eligible
    assert not decision.source_outline_suppressible
    assert accepted_ocr_texts((reviewed_unsafe,)) == (
        reviewed_unsafe,
    )


def test_invalid_geometry_is_an_explicit_text_hard_reject() -> None:
    invalid = _candidate(
        bbox=(20, 20, 0, 30),
        quad=None,
    )

    decision = decide_text_output(invalid)

    assert not decision.text_emit_eligible
    assert decision.state is TextOutputState.TEXT_FALLBACK_OUTLINE
    assert decision.hard_reject_reason == "invalid_text_geometry"


def test_font_choice_does_not_change_text_editability() -> None:
    evidence = _candidate()
    ttf = replace(
        evidence,
        font_family="Example TTF",
        font_file="example.ttf",
    )
    lff = replace(
        evidence,
        font_family="Example LFF",
        font_file="example.lff",
    )

    assert decide_text_output(ttf).state is TextOutputState.EDITABLE_TEXT
    assert decide_text_output(lff).state is TextOutputState.EDITABLE_TEXT


def test_summary_reports_every_required_text_count_and_reason() -> None:
    texts = (
        _candidate(),
        _candidate(
            bbox=(120, 20, 80, 30),
            replacement_safe=False,
        ),
        _candidate(
            bbox=(220, 20, 80, 30),
            approved=False,
        ),
    )

    summary = text_output_summary(texts)

    assert summary.payload() == {
        "ocr_candidate_count": 3,
        "text_count": 2,
        "fallback_count": 1,
        "residual_count": 0,
        "text_emit_eligible_count": 2,
        "source_outline_suppressible_count": 1,
        "source_outline_backup_count": 1,
        "confidence_hard_reject_count": 0,
        "invalid_geometry_count": 0,
        "downgrade_reasons": {
            "candidate_not_approved": 1,
        },
    }


def test_dxf_emits_native_text_independently_from_outline_safety(
    tmp_path: Path,
) -> None:
    binary = np.full((140, 360), 255, dtype=np.uint8)
    boxes = (
        (20, 50, 70, 30),
        (140, 50, 70, 30),
        (260, 50, 70, 30),
    )
    for x, y, width, height in boxes:
        cv2.rectangle(
            binary,
            (x, y),
            (x + width, y + height),
            0,
            -1,
        )
    texts = (
        _candidate(text="SAFE", bbox=boxes[0]),
        _candidate(
            text="UNSAFE",
            bbox=boxes[1],
            replacement_safe=False,
        ),
        _candidate(
            text="UNKNOWN",
            bbox=boxes[2],
            approved=False,
        ),
    )

    result = export_exact_trace_dxf(
        trace_binary(binary),
        tmp_path / "text-contract.dxf",
        binary.shape[0],
        image_width=binary.shape[1],
        texts=texts,
    )

    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()
    native_texts = list(modelspace.query("TEXT"))
    outline_layers = {
        str(entity.dxf.layer)
        for entity in modelspace.query("LWPOLYLINE")
    }
    assert [entity.dxf.text for entity in native_texts] == [
        "SAFE",
        "UNSAFE",
    ]
    assert "SOURCE_TEXT_OUTLINE" in outline_layers
    assert "TEXT_FALLBACK_OUTLINE" in outline_layers
    assert "RESIDUAL_GRAPHIC" not in outline_layers
    assert document.layers.get("SOURCE_TEXT_OUTLINE").is_off()
    assert document.layers.get("SOURCE_TEXT_OUTLINE").is_frozen()
    assert not document.layers.get("TEXT_FALLBACK_OUTLINE").is_off()
    assert result.ocr_candidate_count == 3
    assert result.text_count == 2
    assert result.fallback_text_count == 1
    assert result.source_text_outline_count == 1
    assert result.residual_graphic_count == 0
    assert dict(result.text_downgrade_reasons) == {
        "candidate_not_approved": 1,
    }

    for entity in native_texts:
        contract_xdata = entity.get_xdata(
            "TEXT_OUTPUT_CONTRACT"
        )
        string_values = [
            tag.value for tag in contract_xdata if tag.code == 1000
        ]
        assert string_values[0] == "editable_text"
        assert "contract-test" in string_values
    assert not document.audit().errors


def test_small_unreliable_ocr_segment_marks_long_owner_as_residual(
    tmp_path: Path,
) -> None:
    binary = np.full((220, 100), 255, dtype=np.uint8)
    cv2.rectangle(binary, (40, 20), (52, 200), 0, -1)
    residual = _candidate(
        text="S",
        bbox=(41, 100, 8, 12),
        confidence=0.10,
        replacement_safe=False,
    )

    result = export_exact_trace_dxf(
        trace_binary(binary),
        tmp_path / "long-residual-owner.dxf",
        binary.shape[0],
        image_width=binary.shape[1],
        texts=(residual,),
    )

    document = ezdxf.readfile(result.path)
    layers = {
        str(entity.dxf.layer)
        for entity in document.modelspace().query("LWPOLYLINE")
    }
    assert layers == {"TEXT_FALLBACK_OUTLINE"}
    assert result.fallback_text_count == 1
    assert result.residual_graphic_count == 0
    assert not document.audit().errors


def test_final_structure_masks_prevent_editable_text_symbol_conflict(
    tmp_path: Path,
) -> None:
    main_binary = np.full((140, 360), 255, dtype=np.uint8)
    cv2.circle(main_binary, (300, 70), 12, 0, 2)
    source_outline = np.zeros_like(main_binary)
    cv2.rectangle(source_outline, (20, 50), (90, 80), 255, -1)
    candidate = _candidate(
        text="UNSAFE",
        bbox=(20, 50, 70, 30),
        replacement_safe=False,
    )
    structure = build_final_structure(
        source_size_px=(360, 140),
        contour_binary=main_binary,
        contours=tuple(trace_binary(main_binary)),
        texts=(candidate,),
        editable_text_source_mask=source_outline,
        source_text_outline_mask=source_outline,
        uncertain_text_outline_mask=np.zeros_like(main_binary),
    )

    result = export_final_structure_dxf(
        structure,
        tmp_path / "semantic-owner.dxf",
    )
    document = ezdxf.readfile(result.path)
    modelspace = document.modelspace()

    assert result.text_count == 1
    assert result.source_text_outline_count == 1
    assert result.fallback_text_count == 0
    assert [entity.dxf.text for entity in modelspace.query("TEXT")] == [
        "UNSAFE"
    ]
    assert modelspace.query(
        'LWPOLYLINE[layer=="SOURCE_TEXT_OUTLINE"]'
    )
    assert not modelspace.query(
        'LWPOLYLINE[layer=="TEXT_FALLBACK_OUTLINE"]'
    )
    assert document.layers.get("SOURCE_TEXT_OUTLINE").is_off()
    assert document.layers.get("SOURCE_TEXT_OUTLINE").is_frozen()
    assert not document.audit().errors
