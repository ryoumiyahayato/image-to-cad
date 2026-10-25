"""Real retained PDF through production export; not a synthetic CAD fixture."""
from tools.drafting_rules.study import run


def test_real_bilingual_cell_edit_detects_overflow_and_collateral_change(tmp_path):
    report = run(tmp_path / "real-cell")
    assert report["positive"].get("FAIL", 0) == 0
    assert report["positive"]["PASS"] == 7  # Three native strings + three cells + edit isolation.
    assert report["positive"]["ABSTAIN"] == 5  # Three glyph maps + background + source lines.
    assert report["overflow"]["FAIL"] == 1
    assert report["collateral"]["FAIL"] == 2
    assert report["editor"] == "NOT_RUN"
