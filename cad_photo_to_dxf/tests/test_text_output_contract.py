from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import ezdxf
import numpy as np

from app.auxiliary_recognition import TextCandidate
from app.raster_trace import trace_binary
from app.text_output_contract import (
    TextOutputState,
    accepted_ocr_texts,
    decide_text_output,
    text_output_summary,
)
from app.trace_single_export import export_exact_trace_dxf


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
    fallback = decide_text_output(
        _candidate(replacement_safe=False)
    )
    residual = decide_text_output(
        _candidate(confidence=0.10)
    )

    assert editable.state is TextOutputState.EDITABLE_TEXT
    assert editable.output_layer == "OCR_TEXT"
    assert editable.editable
    assert editable.downgrade_reason is None

    assert fallback.state is TextOutputState.TEXT_FALLBACK_OUTLINE
    assert fallback.output_layer == "TEXT_FALLBACK_OUTLINE"
    assert not fallback.editable
    assert fallback.downgrade_reason == "replacement_unsafe"

    assert residual.state is TextOutputState.RESIDUAL_GRAPHIC
    assert residual.output_layer == "RESIDUAL_GRAPHIC"
    assert not residual.editable
    assert residual.downgrade_reason == "confidence_below_contract"


def test_review_cannot_override_replacement_safety() -> None:
    reviewed_unsafe = _candidate(
        confidence=0.10,
        reviewed=True,
        replacement_safe=False,
    )

    decision = decide_text_output(reviewed_unsafe)

    assert decision.state is TextOutputState.TEXT_FALLBACK_OUTLINE
    assert accepted_ocr_texts((reviewed_unsafe,)) == ()


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
        "text_count": 1,
        "fallback_count": 1,
        "residual_count": 1,
        "downgrade_reasons": {
            "candidate_not_approved": 1,
            "replacement_unsafe": 1,
        },
    }


def test_dxf_uses_native_text_and_explicit_fallback_layers(
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
    assert [entity.dxf.text for entity in native_texts] == ["SAFE"]
    assert "TEXT_FALLBACK_OUTLINE" in outline_layers
    assert "RESIDUAL_GRAPHIC" in outline_layers
    assert result.ocr_candidate_count == 3
    assert result.text_count == 1
    assert result.fallback_text_count == 1
    assert result.residual_graphic_count == 1
    assert dict(result.text_downgrade_reasons) == {
        "candidate_not_approved": 1,
        "replacement_unsafe": 1,
    }

    contract_xdata = native_texts[0].get_xdata(
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
    assert layers == {"RESIDUAL_GRAPHIC"}
    assert result.residual_graphic_count == 1
    assert not document.audit().errors
