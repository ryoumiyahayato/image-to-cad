"""Contradictory accepted proof children cannot borrow their parent's PASS.

These are synthetic receipt-consistency probes, not reconstruction samples.
Rejected layout alternatives deliberately remain in the successful receipts.
"""
from copy import deepcopy

import pytest

from app.native_objects import independent_source_proof_binding as independent
from app.native_objects import source_proof_continuation as continuation


def _clearance():
    return {"pass": True, "schema": "source-separated-round-native-text-clearance-v1",
            "policy": {}, "source_partition_sha256": "synthetic-partition", "actual_text_attributes_sha256": "synthetic-text",
            "font_sha256": "synthetic-font", "source_pixels_modified": False, "font_or_text_geometry_modified": False,
            "relations": [{"pass": True, "original_white_gap_proved": True}]}


def _single_line():
    layout = {"pass": True, "source_fit": {"pass": True, "checks": {"component_fit": True}},
              "source_neighbor_clearance": {"pass": True, "checks": [{"pass": True}],
                  "all_original_neighbors_preserved": True, "source_pixels_modified": False},
              "actual_attributes_used": True,
              "actual_saved_LFF_literal_equivalence": {"pass": True, "scope": "synthetic literal equivalence"}}
    adopted_layout = {**_clearance(), "selected_layout": {"synthetic": True},
                      "source_fit": deepcopy(layout["source_fit"]),
                      "source_neighbor_clearance": deepcopy(layout["source_neighbor_clearance"]),
                      "default_layout_rejection": {"pass": False, "reason": "source white gap closes"}}
    return {"id": "synthetic-text", "type": "SINGLE_LINE_TEXT_SOURCE_BINDING", "pass": True,
            "saved_candidate_checks": {"saved_text_bound": True}, "saved_candidate_pass": True,
            "source_text_matches_candidate": True, "source_bbox_matches_candidate": True,
            "source_rotation_is_supported": True, "actual_saved_text_round_clearance": _clearance(),
            "actual_saved_source_component_layout": layout,
            "source_replay": {"pass": True, "text": "AB", "bbox_xyxy_px": [1, 2, 9, 6], "geometry": {},
                "layout_adoption": adopted_layout, "all_raw_artifacts_read_and_hashed": True,
                "transcription_source_pass": True, "Tesseract_views_replayed": 1, "PP_OCR_views_replayed": 1,
                "source_partition_replay_comparison": {"pass": True, "all_non_whitelisted_fields_exact": True,
                    "errors": [], "original_records_modified": False}}}


def _short_group():
    members = [{"pass": True, "checks": {"literal_component_fit": True}, "geometry": {"text": character}}
               for character in "AB"]
    return {"id": "synthetic-group", "type": "SHORT_CONTACT_SAVED_SOURCE_AND_EDITING_RESPONSIBILITY", "pass": True,
            "text": "AB", "kind": "TEXT_GROUP", "actual_native_TEXT_members": 2, "independent_graphic_owner_ids": [],
            "original_glyph_and_shared_core_samples_replayed": True, "original_and_partition_raw_conflicts_replayed": True,
            "minimum_complete_editing_group_verified": True,
            "source_replay": {"pass": True, "text": "AB", "complete_original_components_replayed": True,
                "original_and_derived_raw_replayed": True, "all_competing_readings_retained_and_rechecked": True,
                "layout": {"pass": True, "kind": "TEXT_GROUP", "minimum_native_member_count": 2,
                    "one_TEXT_attempt": {"pass": False, "checks": {"component_positions_match": False}},
                    "members": members}}}


def _path():
    return {"id": "synthetic-path", "type": "SAVED_TEXT_CONTACT_PATH_SOURCE", "pass": True,
            "checks": {"actual_start_contacts_required_circle": True},
            "actual_structural_endpoint_contacts": {"actual_start_contacts_required_circle": True,
                                                    "actual_end_contacts_required_finite_carrier": True},
            "original_source_plan_replay": {"pass": True, "checks": {"source_bound": True}, "reason": None},
            "actual_source_geometry": {"pass": True, "checks": {"whole_path_support": True},
                "actual_source_support": {"pass": True, "samples": 20, "max_distance_px": 0.0,
                                          "source_fraction": 1.0, "maximum_white_gap_px": 0.0}},
            "shared_neighbor_source_checks": [{"prior_object_id": "synthetic-neighbor", "pass": True}]}


def _accepts(row):
    try:
        continuation._validate_historical_check(row)
        producer_accepts = True
    except (ValueError, KeyError, TypeError):
        producer_accepts = False
    return producer_accepts, independent._historical_detail_valid(row, {})


@pytest.mark.parametrize("factory", [_single_line, _short_group, _path])
def test_complete_accepted_branches_keep_rejected_layout_alternatives(factory):
    row = factory()
    before = deepcopy(row)
    assert _accepts(row) == (True, True)
    assert row == before


@pytest.mark.parametrize("factory,branch,replacement", [
    (_single_line, ("source_replay", "transcription_source_pass"), False),
    (_single_line, ("source_replay", "all_raw_artifacts_read_and_hashed"), False),
    (_single_line, ("source_replay", "source_partition_replay_comparison", "pass"), False),
    (_single_line, ("source_replay", "layout_adoption", "pass"), False),
    (_single_line, ("actual_saved_source_component_layout",), {"pass": True, "required": True}),
    (_single_line, ("actual_saved_source_component_layout", "source_fit", "checks", "component_fit"), False),
    (_single_line, ("actual_saved_text_round_clearance", "relations"), [{"pass": False}]),
    (_short_group, ("source_replay", "original_and_derived_raw_replayed"), False),
    (_short_group, ("source_replay", "layout", "pass"), False),
    (_short_group, ("source_replay", "layout", "members"), [{"pass": False, "checks": {"component_fit": True}, "geometry": {}}]),
    (_path, ("actual_source_geometry", "actual_source_support", "pass"), False),
    (_path, ("shared_neighbor_source_checks",), [{"prior_object_id": "synthetic-neighbor", "pass": False}]),
    (_path, ("actual_structural_endpoint_contacts", "actual_start_contacts_required_circle"), False),
])
def test_outer_pass_cannot_hide_missing_or_failed_selected_child(factory, branch, replacement):
    row = factory()
    target = row
    for key in branch[:-1]:
        target = target[key]
    target[branch[-1]] = replacement
    assert row["pass"] is True
    assert _accepts(row) == (False, False)


def test_single_text_success_and_explicit_unused_component_layout_are_allowed():
    single = _single_line()
    single["actual_saved_source_component_layout"] = {"pass": True, "required": False}
    assert _accepts(single) == (True, True)
    short = _short_group()
    short.update(kind="TEXT", text="A", actual_native_TEXT_members=1)
    short["source_replay"]["text"] = "A"
    layout = short["source_replay"]["layout"]
    layout["kind"] = "TEXT"
    layout["members"] = [layout["members"][0]]
    layout["one_TEXT_attempt"] = deepcopy(layout["members"][0])
    layout["minimum_native_member_count"] = 1
    assert _accepts(short) == (True, True)
