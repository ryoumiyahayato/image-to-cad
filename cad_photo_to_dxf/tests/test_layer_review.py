from __future__ import annotations

import pytest

from app.layer_review import apply_layer_overrides, layer_counts
from app.line_detect import LineSegment


def _line(layer: str, source: str) -> LineSegment:
    return LineSegment(
        0,
        0,
        100,
        0,
        layer=layer,
        source_ids=(source,),
        history=("classified",),
        classification_confidence=0.55,
        classification_reasons=("heuristic",),
    )


def test_manual_layer_override_preserves_automatic_evidence() -> None:
    original = [_line("DETAIL", "A"), _line("OUTLINE", "B")]
    reviewed, changed = apply_layer_overrides(
        original,
        ["WALL_OR_FRAME", "OUTLINE"],
    )

    assert changed == 1
    assert reviewed[0].layer == "WALL_OR_FRAME"
    assert reviewed[0].classification_confidence == 1.0
    assert "heuristic" in reviewed[0].classification_reasons
    assert "manual_override:DETAIL->WALL_OR_FRAME" in reviewed[0].classification_reasons
    assert "manual_layer_review" in reviewed[0].history
    assert reviewed[0].source_ids == ("A",)
    assert reviewed[1] is original[1]
    assert layer_counts(reviewed) == {"OUTLINE": 1, "WALL_OR_FRAME": 1}


def test_manual_layer_override_rejects_unknown_layer() -> None:
    with pytest.raises(ValueError, match="Unknown layer"):
        apply_layer_overrides([_line("DETAIL", "A")], ["NOT_A_LAYER"])


def test_manual_layer_override_requires_one_choice_per_line() -> None:
    with pytest.raises(ValueError, match="exactly one reviewed layer"):
        apply_layer_overrides([_line("DETAIL", "A")], [])
