"""Bound candidate roles preserve raw ink, text negatives and complete paths."""

import copy
import hashlib
import time

import cv2
import numpy as np
import pytest

from app.native_objects.connections import _SourceGraph, extract_connections
from app.native_objects.contracts import validate_text_regions
from app.native_objects.text_graph_support import _source_adjacencies, prove_shared_core_overlap
from app.native_objects.text_graph_support import unlocalized_compact_path_protection


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def fixture(*, raw_words=("NO", "Nvv"), left=True, right=True):
    ink = np.zeros((260, 380), np.uint8)
    main = np.array([[150, 90], [168, 97], [187, 108], [204, 120], [225, 138]], np.int32)
    candidate = np.zeros_like(ink)
    cv2.polylines(candidate, [main], False, 1, 1)
    ink |= candidate
    if left:
        cv2.polylines(ink, [np.array([[65, 64], [85, 68], [110, 73], [126, 79]], np.int32)], False, 1, 1)
    if right:
        cv2.polylines(ink, [np.array([[249, 161], [267, 185], [284, 212]], np.int32)], False, 1, 1)
    # A retained formal text reference with actual compact source ink.
    for x in [90, 105, 120]:
        ink[35:55, x] = 1
        ink[35, x:x + 10] = 1
        ink[45, x:x + 8] = 1
        ink[54, x:x + 10] = 1
    gray = np.where(ink, 0, 255).astype(np.uint8)
    yy, xx = np.nonzero(candidate)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    region = {"id": "unconfirmed-row", "bbox_xyxy_px": box,
              "text": raw_words[0], "accepted": False, "complete": False,
              "compact_source_ink_mask": {"runs_y_x0_x1": [[int(y), int(x), int(x + 1)] for y, x in zip(yy, xx)]},
              "unresolved_reasons": ["word_missing_two_confident_contexts_with_current_local_OCR"]}
    observations, alternatives = [], []
    for index, text in enumerate(raw_words):
        pad = 2 + 2 * index
        crop = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]
        psm = 7 if index == 0 else 13
        word = {"text": text, "confidence": 40.0, "bbox_xyxy_px": box}
        spec = {"crop_xyxy_px": crop, "crop_array_sha256": digest(gray[crop[1]:crop[3], crop[0]:crop[2]]), "psm": psm}
        observations.append({"region_id": region["id"], "key": f"verified-raw-{index}",
                             "specification": spec, "words": [word],
                             "raw_tsv_sha256": hashlib.sha256(text.encode()).hexdigest(),
                             "metadata_sha256": hashlib.sha256(str(spec).encode()).hexdigest(),
                             "input_png_sha256": hashlib.sha256(gray[crop[1]:crop[3], crop[0]:crop[2]].tobytes()).hexdigest()})
        alternatives.append({"context_id": f"different-import-wrapper-{index}", "crop_xyxy_px": crop,
                             "psm": psm, "words": [copy.deepcopy(word)]})
    region["words"] = copy.deepcopy(alternatives[0]["words"])
    region["completeness_evidence"] = {"alternatives": alternatives}
    roi = [0, 0, gray.shape[1], gray.shape[0]]
    data = {"coordinate_system": "source_pixels_top_left", "source_size_px": [gray.shape[1], gray.shape[0]],
            "roi_xyxy_px": roi, "source_array_sha256": digest(gray), "regions": [region], "groups": []}
    token = {"validated": True, "source_array_sha256": digest(gray), "source_sha256": "a" * 64,
             "observations": observations}
    formal = [{"id": "reference-label", "kind": "TEXT", "geometry": {"text": "EEE", "x": 90,
                "y": 55, "height_px": 20, "width_px": 40}, "source_evidence": {"region_ids": ["retained-label"]}}]
    return gray, roi, data, token, formal, box


def extract(item, output, *, verified=True):
    gray, roi, data, token, formal, _ = item
    original, raw = gray.copy(), copy.deepcopy(data)
    result = extract_connections(gray, roi, formal, output, text_regions=data,
                                 verified_text_observations=token if verified else None)
    assert np.array_equal(gray, original)
    assert data == raw
    return result


def crossing_fixture(*, raw_words=("NO", "Nvv"), missing_bar=False, stroke_width=2):
    """Public synthetic ink: one long stroke crossing two complete short bars."""
    item = fixture(raw_words=raw_words)
    ink = np.zeros_like(item[0], np.uint8)
    candidate = np.zeros_like(ink)
    cv2.polylines(candidate, [np.array([[80, 100], [124, 113], [165, 129], [210, 145]], np.int32)], False, 1, stroke_width)
    cv2.line(candidate, (135, 93), (110, 133), 1, stroke_width)
    if not missing_bar:
        cv2.line(candidate, (171, 109), (146, 149), 1, stroke_width)
    ink |= candidate
    for x in [90, 105, 120]:
        ink[35:55, x] = 1
        ink[35, x:x + 10] = 1
        ink[45, x:x + 8] = 1
        ink[54, x:x + 10] = 1
    gray = np.where(ink, 0, 255).astype(np.uint8)
    yy, xx = np.nonzero(candidate)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    data, token = copy.deepcopy(item[2]), copy.deepcopy(item[3])
    data["source_array_sha256"] = token["source_array_sha256"] = digest(gray)
    region = data["regions"][0]
    region["bbox_xyxy_px"] = box
    region["compact_source_ink_mask"]["runs_y_x0_x1"] = [[int(y), int(x), int(x + 1)] for y, x in zip(yy, xx)]
    for index, (row, alt) in enumerate(zip(token["observations"], region["completeness_evidence"]["alternatives"])):
        pad = 2 + 2 * index
        crop = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]
        row["specification"]["crop_xyxy_px"] = crop
        row["specification"]["crop_array_sha256"] = digest(gray[crop[1]:crop[3], crop[0]:crop[2]])
        row["words"][0]["bbox_xyxy_px"] = box
        alt["crop_xyxy_px"] = crop
        alt["words"][0]["bbox_xyxy_px"] = box
    region["words"][0]["bbox_xyxy_px"] = box
    return gray, item[1], data, token, item[4], box


def target_paths(result, box):
    return [obj for obj in result["objects"] if all(
        box[0] <= point[0] < box[2] and box[1] <= point[1] < box[3]
        for point in obj["geometry"]["points"])]


def test_verified_two_sided_graphic_support_recovers_one_whole_path_without_bridging_gaps(tmp_path):
    item = fixture()
    result = extract(item, tmp_path)
    target = target_paths(result, item[-1])
    assert len(target) == 1
    evidence = target[0]["source_evidence"]
    relation = evidence["text_graphic_support"]
    assert relation["decision"] == "SOURCE_SUPPORTED_GRAPHIC"
    assert relation["positive_evidence_kind"] == "TWO_SIDED_SEPARATE_SOURCE_STROKE_CONTINUATION"
    assert evidence["whole_simple_source_chain"]["pass"]
    assert evidence["whole_simple_source_chain_fit"]["pass"]
    assert evidence["source_support"]["pass"]
    assert not relation["raw_candidate_masks_modified"]
    assert not relation["source_pixels_uniquely_partitioned"]
    assert not evidence["source_morphological_gap_closing"]
    assert target[0]["geometry"]["points"][0] == [150.0, 90.0]
    assert target[0]["geometry"]["points"][-1] == [225.0, 138.0]


def test_raw_reference_json_alone_does_not_authorize_releasing_old_glyph_veto(tmp_path):
    item = fixture()
    item[2]["validated"] = True  # Input JSON cannot supply the runtime token.
    result = extract(item, tmp_path, verified=False)
    assert not target_paths(result, item[-1])
    assert any(row["reason"] == "CURRENT_SOURCE_GLYPH_OWNERSHIP_CONTACT" for row in result["uncertainties"])


@pytest.mark.parametrize("raw_words", [("1", "I"), ("/", "/"), ("(", "("), ("-", "-"), ("+", "+")])
def test_single_character_and_punctuation_remain_protected_even_with_graphic_like_context(tmp_path, raw_words):
    item = fixture(raw_words=raw_words)
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])
    assert any("SINGLE_CHARACTER_OR_PUNCTUATION_INTERPRETATION_RETAINED" in str(row)
               for row in result["uncertainties"])


@pytest.mark.parametrize("change", ["complete", "source_review", "group_complete", "reliable_word", "source_hash", "crop_hash", "parsed_words"])
def test_real_text_or_invalid_observation_binding_cannot_be_overruled(tmp_path, change):
    item = fixture()
    region, token = item[2]["regions"][0], item[3]
    if change == "complete":
        region["complete"] = True
    elif change == "source_review":
        region["source_review"] = {"accepted": True}
    elif change == "group_complete":
        item[2]["groups"] = [{"id": "complete-group", "region_ids": [region["id"]], "complete": True}]
    elif change == "reliable_word":
        token["observations"][0]["words"][0]["confidence"] = 98
        region["completeness_evidence"]["alternatives"][0]["words"][0]["confidence"] = 98
    elif change == "source_hash":
        token["source_array_sha256"] = "0" * 64
    elif change == "crop_hash":
        token["observations"][0]["specification"]["crop_array_sha256"] = "0" * 64
    else:
        token["observations"][0]["words"][0]["text"] = "DIFFERENT"
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])


@pytest.mark.parametrize("missing", ["left", "right"])
def test_one_sided_neighbor_does_not_turn_an_unresolved_curve_into_a_confirmed_graphic(tmp_path, missing):
    item = fixture(**{missing: False})
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])


def test_contract_preserves_candidate_mask_and_reports_group_role_separately():
    gray, roi, data, _, _, _ = fixture()
    data["groups"] = [{"id": "reviewed", "region_ids": ["unconfirmed-row"], "source_review": {"accepted": True}}]
    box = validate_text_regions(data, gray.shape, roi)[0]
    assert not box["confirmed"]
    assert box["support_role"]["groups"][0]["source_review_accepted"]
    assert box["glyph_source_runs"] == data["regions"][0]["compact_source_ink_mask"]["runs_y_x0_x1"]


def test_complete_multi_crossing_group_emits_all_three_paths_including_sub50_short_strokes(tmp_path):
    item = crossing_fixture()
    result = extract(item, tmp_path)
    target = target_paths(result, item[-1])
    assert len(target) == 3
    assert sum(obj["source_evidence"]["source_path_length_px"] < 50 for obj in target) == 2
    assert all(len(obj["source_evidence"]["graphic_group_path_responsibility"]) == 3 for obj in target)
    for obj in target:
        source = obj["source_evidence"]
        assert source["whole_simple_source_chain_fit"]["pass"]
        assert all(endpoint["kind"] == "OBSERVED_FREE_SOURCE_ENDPOINT" for endpoint in source["endpoint_evidence"])
    shared_pairs = [(a, b) for i, a in enumerate(target) for b in target[i + 1:]
                    if _source_adjacencies(a) & _source_adjacencies(b)]
    assert len(shared_pairs) == 2
    for a, b in shared_pairs:
        proof = prove_shared_core_overlap(item[0], a, b)
        assert proof["pass"]
        assert all(row["source_recomputed"] for row in proof["current_core_proofs"])


def test_large_parent_crop_rechecks_same_small_core_and_keeps_all_short_ports(tmp_path):
    local = crossing_fixture()
    local_paths = target_paths(extract(local, tmp_path / "local"), local[-1])
    full = list(copy.deepcopy(local))
    full[0] = np.pad(full[0], ((0, 1240), (0, 1120)), constant_values=255)
    full[1] = [0, 0, full[0].shape[1], full[0].shape[0]]
    full[2]["roi_xyxy_px"] = full[1]
    full[2]["source_size_px"] = full[1][2:]
    _rebind_changed_source(full)
    full_paths = target_paths(extract(full, tmp_path / "full"), full[-1])
    assert len(local_paths) == len(full_paths) == 3
    assert {o["id"]: o["geometry"] for o in local_paths} == {
        o["id"]: o["geometry"] for o in full_paths
    }
    assert sum(o["source_evidence"]["source_path_length_px"] < 50 for o in full_paths) == 2
    pairs = [(a, b) for i, a in enumerate(full_paths) for b in full_paths[i + 1:]
             if _source_adjacencies(a) & _source_adjacencies(b)]
    assert len(pairs) == 2
    for a, b in pairs:
        proof = prove_shared_core_overlap(full[0], a, b)
        assert proof["pass"]
        for core in proof["current_core_proofs"]:
            x0, y0, x1, y1 = core["original_bound_source_crop_xyxy_px"]
            assert (x1 - x0) * (y1 - y0) > 2_000_000
            x0, y0, x1, y1 = core["current_core_replay_crop_xyxy_px"]
            assert (x1 - x0) * (y1 - y0) < 2_000_000
            assert core["original_bound_source_crop_reverified"]
            assert len(core["independent_four_port_pairings"]) == 2
            assert len({tuple(port) for pair in core["independent_four_port_pairings"]
                        for port in pair}) == 4
    a, b = pairs[0]
    changed_source = full[0].copy()
    changed_source[-10, -10] = 0  # Outside replay crop, inside original binding.
    assert not prove_shared_core_overlap(changed_source, a, b)["pass"]
    altered = copy.deepcopy(a)
    for row in altered["source_evidence"]["crossing_evidence"]:
        if row.get("bounded_shared_source_core"):
            row["bounded_shared_source_core"]["source_core_points"][0][0] += 1
    assert not prove_shared_core_overlap(full[0], altered, b)["pass"]


def test_one_crossing_or_an_unrepresented_short_member_does_not_claim_a_complete_graphic_group(tmp_path):
    item = crossing_fixture(missing_bar=True)
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])


def test_real_dot_above_source_stroke_keeps_fragmented_character_protected_with_wrong_multiletter_ocr(tmp_path):
    # Actual extra ink, not merely changing the OCR answer of an unchanged
    # positive. The dot overlaps the stem's x range and leaves a real 2 px gap.
    item = fixture()
    gray, _, data, token, _, box = item
    gray[box[1] - 4:box[1] - 2, box[0]:box[0] + 2] = 0
    data["source_array_sha256"] = token["source_array_sha256"] = digest(gray)
    for observation in token["observations"]:
        x0, y0, x1, y1 = observation["specification"]["crop_xyxy_px"]
        observation["specification"]["crop_array_sha256"] = digest(gray[y0:y1, x0:x1])
    result = extract(item, tmp_path)
    assert not target_paths(result, box)
    assert any("POSSIBLE_FRAGMENTED_CHARACTER_RETAINED" in str(row) for row in result["uncertainties"])


def _rebind_changed_source(item):
    gray, _, data, token, _, _ = item
    data["source_array_sha256"] = token["source_array_sha256"] = digest(gray)
    for observation in token["observations"]:
        x0, y0, x1, y1 = observation["specification"]["crop_xyxy_px"]
        observation["specification"]["crop_array_sha256"] = digest(gray[y0:y1, x0:x1])


def test_large_enclosing_component_box_without_local_ink_is_not_a_fragment_witness(tmp_path):
    item = fixture()
    cv2.rectangle(item[0], (1, 1), (378, 258), 0, 1)
    _rebind_changed_source(item)
    result = extract(item, tmp_path)
    target = target_paths(result, item[-1])
    assert len(target) == 1
    protection = target[0]["source_evidence"]["text_graphic_support"]["candidate_relations"][0]["text_protection_checks"]
    assert not protection["fragmented_character_witnesses"]
    assert protection["nonlocal_component_bbox_contacts"]
    assert all(row["local_source_pixel_count"] == 0
               for row in protection["nonlocal_component_bbox_contacts"])


def test_enclosing_frame_in_full_roi_does_not_change_a_complete_local_path(tmp_path):
    full = fixture()
    cv2.rectangle(full[0], (1, 1), (378, 258), 0, 1)
    _rebind_changed_source(full)
    local = list(copy.deepcopy(full))
    local[1] = [40, 30, 310, 225]
    local[2]["roi_xyxy_px"] = local[1]
    a = target_paths(extract(full, tmp_path / "full"), full[-1])
    b = target_paths(extract(local, tmp_path / "local"), local[-1])
    assert len(a) == len(b) == 1
    assert a[0]["geometry"] == b[0]["geometry"]
    assert a[0]["source_evidence"]["source_path_points"] == b[0]["source_evidence"]["source_path_points"]


def test_real_fragment_at_lower_two_pixel_gap_remains_protected(tmp_path):
    item = fixture()
    box = item[-1]
    item[0][box[3] + 2:box[3] + 4, box[2] - 2:box[2]] = 0
    _rebind_changed_source(item)
    result = extract(item, tmp_path)
    assert not target_paths(result, box)
    protections = [relation["text_protection_checks"]
                   for row in result["uncertainties"]
                   for relation in row.get("text_graphic_support", {}).get("candidate_relations", [])]
    assert any("POSSIBLE_FRAGMENTED_CHARACTER_RETAINED" in row["blocking_reasons"]
               and any(fragment["local_source_pixel_count"] > 0
                       for fragment in row["fragmented_character_witnesses"])
               for row in protections)


def test_unlocalized_small_curved_ink_stays_pending_using_current_page_text_scale(tmp_path):
    item = list(fixture())
    # No OCR candidate covers this disconnected turning stroke. Its continuity
    # and >50 px length alone must not reinterpret a possible label as a line.
    item[0] = np.pad(item[0], ((0, 400), (0, 400)), constant_values=255)
    curve = np.array([[500, 400], [489, 400], [486, 406], [489, 410],
                      [499, 414], [499, 420], [494, 426], [486, 424]], np.int32)
    cv2.polylines(item[0], [curve], False, 0, 1)
    item[1] = [0, 0, item[0].shape[1], item[0].shape[0]]
    item[2]["source_size_px"] = [item[0].shape[1], item[0].shape[0]]
    item[2]["roi_xyxy_px"] = item[1]
    _rebind_changed_source(item)
    result = extract(item, tmp_path)
    box = [486, 400, 501, 427]
    assert not target_paths(result, box)
    rejected = [row for row in result["uncertainties"]
                if row["reason"] == "UNLOCALIZED_COMPACT_CURVED_INK_MAY_BE_GLYPH"]
    assert len(rejected) == 1
    proof = rejected[0]["unlocalized_text_scale_check"]
    assert proof["reference_scope"] == "SAME_PAGE_FORMAL_TEXT"
    assert proof["formal_text_references"][0]["object_id"] == "reference-label"
    assert proof["reference_glyph_height_px"] == 20
    assert not proof["near_straight_source_stroke"]["pass"]


def test_short_monotone_slanted_stroke_is_not_rejected_at_compact_glyph_scale():
    context = {"references": [{"object_id": "source-verified-reference",
                "bbox_xyxy_px": [0, 0, 50, 28], "glyph_height_px": 28}]}
    points = np.array([[150, 100], [154, 108], [159, 115], [162, 123],
                       [166, 130], [170, 137], [174, 143]], float)
    proof = unlocalized_compact_path_protection(context, points, straight_tolerance_px=2)
    assert proof["maximum_source_path_extent_px"] <= proof["current_glyph_scale_extent_limit_px"]
    assert proof["near_straight_source_stroke"]["pass"]
    assert not proof["pending"]


def test_unlocalized_guard_does_not_invent_a_scale_without_formal_text():
    proof = unlocalized_compact_path_protection(
        {"references": []}, np.array([[10, 10], [25, 10], [10, 25]], float),
        straight_tolerance_px=2,
    )
    assert proof["reason"] == "NO_CURRENT_FORMAL_TEXT_SCALE_REFERENCE"
    assert not proof["pending"]


@pytest.mark.parametrize("restore_caps", [False, True])
def test_source_cap_repair_is_required_before_complete_group_adoption(tmp_path, monkeypatch, restore_caps):
    # Keep the former failure as a negative: disabling the new observation
    # repair must still fail the unchanged 3 px cap gate, never just bypass it.
    if not restore_caps:
        monkeypatch.setattr("app.native_objects.source_endpoint_caps.restore_source_endpoint_caps",
                            lambda skel, *_: (skel, {"restored": [], "rejected": []}))
    item = crossing_fixture(stroke_width=3)
    result = extract(item, tmp_path)
    if restore_caps:
        target = target_paths(result, item[-1])
        assert len(target) == 3
        assert all(obj["source_evidence"]["source_endpoint_cap_restorations"] for obj in target)
        assert all(cap["pass"] for obj in target
                   for cap in obj["source_evidence"]["original_source_endpoint_cap_checks"])
    else:
        assert not target_paths(result, item[-1])
        assert any(row["reason"] == "SOURCE_TERMINAL_CAP_NOT_EXPLAINED_WITHIN_ENDPOINT_BOUND"
                   for row in result["uncertainties"])


@pytest.mark.parametrize("white_gap", [False, True])
def test_two_actual_offset_t_junctions_are_not_merged_into_a_crossing(white_gap):
    ink = np.zeros((140, 160), np.uint8)
    ink[70, 20:141] = 1
    ink[30:71, 70] = 1
    ink[70:111, 74] = 1
    if white_gap:
        ink[70, 72] = 0
    original = ink.copy()
    graph = _SourceGraph(ink.astype(bool), [0, 0], [], [0, 0, 160, 140], time.process_time(),
                         source_ink=ink.astype(bool), aggregate_core_boxes=[[0, 0, 160, 140]])
    assert not graph.bounded_aggregate_cores
    assert np.array_equal(graph.skel, original)
    assert np.array_equal(graph.source_ink, original)
    assert sum(len(node["edges"]) == 3 for node in graph.nodes.values()) >= (0 if white_gap else 2)
