"""Pure data rule tests: no DXF I/O, font rendering or drawing recognition."""
from copy import deepcopy

import pytest

from tools.drafting_rules.cli import load_pack, compare_reports
from tools.drafting_rules.engine import evaluate, unmatched_segments


def case():
    before = {
        "1": dict(kind="TEXT", text="old", visible=True, fingerprint="old", supported=True, layer="TEXT"),
        "2": dict(kind="LWPOLYLINE", visible=True, fingerprint="outline", supported=True, layer="OLD"),
        "3": dict(kind="CIRCLE", visible=True, fingerprint="logo", supported=True, layer="BACKGROUND"),
        "4": dict(kind="LINE", visible=True, fingerprint="line", supported=True, layer="TABLE", segments=[[0, 0, 10, 0]]),
    }
    after = deepcopy(before)
    after["1"].update(text="水电", fingerprint="new", bounds=[1, 1, 9, 4])
    after["2"].update(visible=False, fingerprint="hidden")
    evidence = dict(schema_version=1, source=dict(sha256="0" * 64, page=1,
                    region=[0, 0, 10, 10], authority="synthetic pure test", units="unitless"),
                    texts=[dict(id="row", handle="1", expected_text="水电", cell=[0, 0, 10, 5],
                                source_outline_handles=["2"], outline_mapping_complete=True,
                                ownership_ref="synthetic fixture complete carrier")],
                    protected=[dict(id="logo", handles=["3"], role="logo", authority="synthetic fixture")],
                    table=dict(id="table", layer="TABLE", mapping_complete=True,
                               source_ref="synthetic fixture", source_segments=[[0, 0, 10, 0]]),
                    edit=dict(allowed_handles=["1", "2"]))
    return evidence, before, after


def run_case(evidence, before, after):
    return evaluate(evidence, before, after, load_pack())


def test_all_six_positive_rules_and_no_mutation():
    evidence, before, after = case()
    saved = deepcopy((evidence, before, after))
    report = run_case(evidence, before, after)
    assert report["summary"] == {"PASS": 6}
    assert (evidence, before, after) == saved
    assert report["cad_editor"] == "NOT_RUN"


@pytest.mark.parametrize("rule", ["editable-text", "cell-fit", "source-glyph-exit",
                                  "background-protection", "table-line-parity", "edit-isolation"])
def test_each_rule_rejects_its_counterexample(rule):
    evidence, before, after = case()
    if rule == "editable-text":
        after["1"]["kind"] = "LWPOLYLINE"
    elif rule == "cell-fit":
        after["1"]["bounds"][2] = 20
    elif rule == "source-glyph-exit":
        after["2"]["visible"] = True
    elif rule == "background-protection":
        after["3"]["fingerprint"] = "altered"
    elif rule == "table-line-parity":
        after["4"]["segments"].append([0, 0, 10, 0])
    else:
        after["4"]["fingerprint"] = "moved"
    result = next(r for r in run_case(evidence, before, after)["results"] if r["rule"] == rule)
    assert result["status"] == "FAIL"


@pytest.mark.parametrize("rule", ["editable-text", "cell-fit", "source-glyph-exit",
                                  "background-protection", "table-line-parity", "edit-isolation"])
def test_each_rule_abstains_without_required_evidence(rule):
    evidence, before, after = case()
    if rule == "editable-text":
        evidence["texts"] = []
    elif rule == "cell-fit":
        after["1"]["bounds"] = None
    elif rule == "source-glyph-exit":
        evidence["texts"][0]["outline_mapping_complete"] = False
    elif rule == "background-protection":
        before["3"]["supported"] = after["3"]["supported"] = False
    elif rule == "table-line-parity":
        evidence["table"]["mapping_complete"] = False
    else:
        del evidence["edit"]
    result = next(r for r in run_case(evidence, before, after)["results"] if r["rule"] == rule)
    assert result["status"] == "ABSTAIN"


def test_table_missing_bridge_and_source_duplicates_have_distinct_evidence():
    assert unmatched_segments([[0, 0, 3, 0], [5, 0, 10, 0]], [[0, 0, 10, 0]], 0) == (
        [[0, 0, 3, 0], [5, 0, 10, 0]], [[0, 0, 10, 0]])
    assert unmatched_segments([[0, 0, 10, 0]] * 2, [[10, 0, 0, 0]] * 2, 0) == ([], [])
    assert unmatched_segments([[0, 0, 10, 0]], [], 0) == ([[0, 0, 10, 0]], [])


def test_matching_is_not_greedy_and_does_not_snap_at_quantization_boundary():
    # First reference can match either actual; second can only match the first.
    assert unmatched_segments([[0, 0, 10, 0], [.2, 0, 10.2, 0]],
                              [[.1, 0, 10.1, 0], [-.1, 0, 9.9, 0]], .11) == ([], [])


def test_reports_compare_reason_details_and_reject_other_scope():
    evidence, before, after = case()
    first = run_case(evidence, before, after)
    second = deepcopy(first)
    second["pack_version"] = "0.1.1"
    second["results"][0]["reason"] = "changed diagnostic"
    assert len(compare_reports(first, second)["changes"]) == 1
    second["source"]["page"] = 2
    with pytest.raises(ValueError):
        compare_reports(first, second)
