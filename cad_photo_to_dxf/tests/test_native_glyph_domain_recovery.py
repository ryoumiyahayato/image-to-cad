"""Source-domain regressions: nearby rules, true suffixes and truncation."""

import copy
import json
import numpy as np
from scipy.ndimage import find_objects

from app.native_objects import text_line_domains as domains, text_regions as text


def source_fixture(with_suffix=False):
    image = np.full((180, 180), 255, np.uint8)
    image[:, 42] = 0
    image[:, 104] = 0
    for x in (50, 66, 82):
        image[70:94, x : x + 2] = 0
        image[70:72, x : x + 11] = 0
        image[81:83, x : x + 9] = 0
    if with_suffix:
        image[81:84, 96:100] = 0
    roi = [0, 0, 180, 180]
    _, labels, glyphs = text._component_evidence(image, roi)
    support = [g for g in glyphs if 50 <= g["bbox_xyxy_px"][0] < 93]
    line = {
        "bbox_xyxy_px": text._box_union([g["bbox_xyxy_px"] for g in support]),
        "glyph_height_px": 24,
        "baseline_y_px": 94,
        "source_component_labels": [g["label"] for g in support],
    }
    return image, roi, labels, line


def test_external_rules_leave_only_the_original_glyph_crop():
    image, roi, labels, line = source_fixture()
    before = image.copy()
    old = domains._line_domain(image, line, roi)
    new = domains._line_domain(
        image, line, roi, labels=labels, component_slices=find_objects(labels)
    )
    assert old["bbox_xyxy_px"][0] < new["bbox_xyxy_px"][0]
    assert old["bbox_xyxy_px"][2] > new["bbox_xyxy_px"][2]
    assert new["bbox_xyxy_px"] == [48, 68, 95, 96]
    assert {r["side"] for r in new["glyph_neighbor_separation"]["side_decisions"]} == {
        "left",
        "right",
    }
    assert domains.inspect_source_domain(labels, roi, new["bbox_xyxy_px"])[
        "source_domain_complete"
    ]
    assert np.array_equal(image, before)


def test_unknown_short_suffix_is_not_removed_with_a_neighbor_rule():
    image, roi, labels, line = source_fixture(with_suffix=True)
    new = domains._line_domain(image, line, roi, labels=labels)
    decisions = new["glyph_neighbor_separation"]["side_decisions"]
    assert [r["side"] for r in decisions] == ["left"]
    assert new["bbox_xyxy_px"][2] > 104
    assert not domains.inspect_source_domain(labels, roi, new["bbox_xyxy_px"])[
        "source_domain_complete"
    ]
    assert int((image[81:84, 96:100] < 128).sum()) == 12


def test_mixed_scope_words_are_preserved_as_raw_evidence_not_trimmed():
    image, roi, labels, line = source_fixture()
    domain = domains._line_domain(image, line, roi, labels=labels)
    words = [
        {"text": "BOX", "bbox_xyxy_px": [50, 70, 93, 94], "confidence": 91},
        {"text": "IBOX", "bbox_xyxy_px": [42, 68, 105, 96], "confidence": 95},
    ]
    original = copy.deepcopy(words)
    kept, rejected = domains.scope_words_to_source_domain(words, domain, labels, roi)
    assert [w["text"] for w in kept] == ["BOX"]
    assert rejected[0]["raw_word"]["text"] == "IBOX"
    assert rejected[0]["external_component_ids_in_word_box"]
    assert words == original


def test_clean_discovery_does_not_hide_polluted_current_scope():
    _, _, _, line = source_fixture()
    row = {
        "bbox_xyxy_px": [42, 68, 105, 96],
        "discovery_bbox_xyxy_px": line["bbox_xyxy_px"],
        "inspection_bbox_xyxy_px": [40, 68, 107, 96],
        "completeness_evidence": {"alternatives": []},
    }
    assert domains._pollution(row, line)["eligible"]


def test_true_effective_input_contact_still_blocks_two_plausible_reads():
    image, roi, labels, line = source_fixture()
    clipped = image[70:94, 50:93].copy()
    new_roi = [0, 0, 43, 24]
    _, local, glyphs = text._component_evidence(clipped, new_roi)
    words = [
        {
            "text": "BOX",
            "confidence": 95,
            "bbox_xyxy_px": new_roi,
            "context_id": "a",
            "psm": 7,
        }
    ]
    alternatives = [
        {
            "context_id": n,
            "psm": psm,
            "words": [dict(words[0], context_id=n)],
            "crop_xyxy_px": new_roi,
            "status": "COMPLETED",
            "evidence_role": "current_candidate",
        }
        for n, psm in [("a", 7), ("b", 13)]
    ]
    boundary = text._current_boundary_assessment(
        alternatives, words, clipped, new_roi, local, ["a", "b"]
    )
    assert boundary["actual_source_component_contacts_effective_input"]
    assert boundary["clean_current_full_line_witness_count"] == 0


def test_i_upper_i_and_one_are_exposed_at_exact_positions_without_rewrite():
    from app.native_objects.text_confirmation import similar_character_conflicts

    strings = ["iST FLOOR", "IST FLOOR", "1ST FLOOR", "OTHER"]
    conflicts = similar_character_conflicts(strings)
    assert len(conflicts) == 1
    assert conflicts[0]["character_index_zero_based"] == 0
    assert conflicts[0]["alternatives"] == ["1", "I", "i"]
    assert strings == ["iST FLOOR", "IST FLOOR", "1ST FLOOR", "OTHER"]


def test_neighbor_scope_refinement_preserves_selected_region_ledger(
    tmp_path, monkeypatch
):
    """Run the refinement driver with canned observations and no OCR engine.

    The glyph/neighbor partition is real; unrelated recognition, grouping and
    contract validation are stubbed so this checks the selected-region ledger
    after the branch that filters words, not recognition acceptance.
    """
    image, roi, labels, line = source_fixture()
    original_image = image.copy()
    region = {
        "id": "TR-SYNTHETIC",
        "text": "UNRESOLVED",
        "complete": False,
        "bbox_xyxy_px": [42, 68, 105, 96],
        "discovery_bbox_xyxy_px": line["bbox_xyxy_px"],
        "inspection_bbox_xyxy_px": [42, 68, 105, 96],
        "unresolved_reasons": ["SYNTHETIC_PENDING_OBSERVATION"],
        "compact_source_ink_mask": {"runs_y_x0_x1": []},
    }
    text_data = {
        "regions": [region],
        "groups": [],
        "roi_xyxy_px": roi,
        "source_size_px": [180, 180],
    }
    original_text = copy.deepcopy(text_data)
    upstream = tmp_path / "upstream.json"
    text._dump(upstream, text_data)
    provenance = {
        "source_sha256": "synthetic-source",
        "text_path": str(upstream),
        "text_sha256": text._sha(upstream),
    }
    words = [
        {"text": "FFF", "bbox_xyxy_px": [50, 70, 93, 94], "confidence": 95},
        {"text": "IFFF", "bbox_xyxy_px": [42, 68, 105, 96], "confidence": 95},
    ]
    original_words = copy.deepcopy(words)
    line.update(
        context_support=2,
        anchors=[
            {"all_observation_ids": ["synthetic"], "raw_text_alternatives": ["FFF"]}
        ],
    )
    monkeypatch.setattr(domains, "_verify_inputs", lambda *args: roi)
    monkeypatch.setattr(
        domains,
        "_collect_current_observations",
        lambda *args: (
            copy.deepcopy(words),
            {"cache": {}, "source_identity": {"source_sha256": "synthetic-source"}},
        ),
    )
    monkeypatch.setattr(domains, "_anchors", lambda *args: [])
    monkeypatch.setattr(domains, "_anchor_line", lambda *args: (line, None))
    monkeypatch.setattr(domains, "_unread_boundary_ink", lambda *args: ([], []))
    monkeypatch.setattr(domains, "_regroup", lambda *args: [])
    monkeypatch.setattr(domains, "validate_text_regions", lambda *args: None)
    monkeypatch.setattr(text, "_overlay", lambda *args: {})
    canned_calls = []

    def canned_observation(image, box, psm, *args, **kwargs):
        canned_calls.append(psm)
        return copy.deepcopy(words), {
            "status": "COMPLETED",
            "specification": {"crop_xyxy_px": box, "psm": psm},
            "tsv_sha256": "synthetic-no-engine",
            "child_cpu_seconds": 0.0,
        }

    def keep_pending(seed, alternatives, *args):
        result = copy.deepcopy(region)
        result["completeness_evidence"] = {"alternatives": alternatives}
        return result

    monkeypatch.setattr(text, "_ocr", canned_observation)
    monkeypatch.setattr(text, "_complete_region", keep_pending)
    output = tmp_path / "refinement"
    result = domains.refine_text_line_domains(
        image,
        text_data,
        output,
        cache_dir=None,
        upstream_provenance=provenance,
    )
    selection = json.loads((output / "selection.json").read_text())
    summary = json.loads((output / "recovery_summary.json").read_text())
    assert result["line_domain_recovery"]["selected_region_ids"] == [region["id"]]
    assert selection["selected_region_ids"] == [region["id"]]
    assert summary["selected_regions"] == 1
    assert summary["resources"]["selected_regions"] == 1
    assert len(canned_calls) == 2
    refined = result["regions"][0]
    assert refined["line_domain_refinement"]["new_domain"]["glyph_neighbor_separation"]
    for alternative in refined["completeness_evidence"]["alternatives"]:
        assert [word["text"] for word in alternative["words"]] == ["FFF"]
        assert alternative["all_words"] == original_words
    assert words == original_words
    assert text_data == original_text
    assert np.array_equal(image, original_image)
