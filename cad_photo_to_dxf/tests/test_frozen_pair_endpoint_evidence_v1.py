from __future__ import annotations

import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
TRACKED = PACKAGE_ROOT / "validation" / "frozen-pair-endpoint-evidence-v1"
RUNTIME_POOL = (
    REPO_ROOT
    / "local-artifacts"
    / "draftsman"
    / "fresh-dev-candidate-remining-v1"
    / "candidate-set-runtime.json"
)
CURRENT_ELIGIBLE = (
    PACKAGE_ROOT
    / "validation"
    / "current-primitive-eligible-set-v1"
    / "current-primitive-eligible-set-v1.json"
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(name: str) -> dict:
    return _read(TRACKED / name)


def test_frozen_ids_and_original_records_are_preserved() -> None:
    source = _read(RUNTIME_POOL)
    enriched = _artifact("frozen-pair-enriched-records.json")
    current = _read(CURRENT_ELIGIBLE)
    source_records = source["deduplicated_admissible_pool"]
    enriched_records = enriched["records"]

    assert len(source_records) == len(enriched_records) == 147
    assert [item["candidate_id"] for item in source_records] == [
        item["candidate_id"] for item in enriched_records
    ]
    assert {item["candidate_id"] for item in enriched_records} == {
        item["candidate_id"] for item in current["records"]
    }
    for original, actual in zip(source_records, enriched_records):
        for key, value in original.items():
            assert actual[key] == value, (original["candidate_id"], key)
        assert actual["pair_identity_evidence"]["pair_geometry_unchanged"] is True


def test_endpoint_profiles_are_present_and_replay_is_local_and_deterministic() -> None:
    topology = _artifact("endpoint-local-topology-evidence.json")
    records = topology["records"]
    assert topology["endpoint_local_topology_captured_count"] == 147
    assert len(records) == 147
    assert len({item["candidate_id"] for item in records}) == 147
    required_profile_fields = {
        "continuing_ridge_evidence",
        "corner_evidence",
        "t_junction_evidence",
        "crossing_evidence",
        "termination_strength",
        "local_multiplicity",
        "competing_stroke_ids",
        "endpoint_component_id",
    }
    for item in records:
        assert item["capture_status"] == "CAPTURED"
        assert item["endpoint_local_source_crop_coordinates"]["endpoint_a"]
        assert item["endpoint_local_source_crop_coordinates"]["endpoint_b"]
        assert required_profile_fields <= set(item["endpoint_topology_profile_a"])
        assert required_profile_fields <= set(item["endpoint_topology_profile_b"])
        assert item["endpoint_topology_profile_a"]["position_in_endpoint_local_crop"]
        assert item["endpoint_topology_profile_b"]["position_in_endpoint_local_crop"]


def test_source_instance_membership_never_fabricates_from_raw_ancestor_ids() -> None:
    membership = _artifact("source-instance-membership.json")
    enriched = _artifact("frozen-pair-enriched-records.json")
    assert membership["member_slot_count"] == 294
    assert membership["membership_counts"] == {
        "CONFIRMED_INSTANCE": 0,
        "AMBIGUOUS_INSTANCE": 0,
        "UNAVAILABLE_INSTANCE": 294,
    }
    assert membership["no_fabricated_source_identity"] is True
    for item in membership["records"]:
        assert item["no_fabricated_identity"] is True
        for member in item["members"].values():
            assert member["status"] == "UNAVAILABLE_INSTANCE"
            assert member["source_instance_ids"] == []
            assert member["possible_source_instance_ids"] == []
            assert member["fabricated_identity"] is False
            assert member["raw_ancestor_ids_are_source_instance_authority"] is False
    for item in enriched["records"]:
        registry = item["pair_identity_evidence"]["source_stroke_registry_projection"]
        assert all(
            observation["source_instance_id"] is None
            for stroke in registry["strokes"]
            for observation in stroke["observations"]
        )


def test_case15_case16_use_generic_contract_and_v1_membership_is_unchanged() -> None:
    evaluation = _artifact("pair-identity-evaluation.json")
    assert evaluation["current_eligible_set_revision"] == "V1"
    assert evaluation["current_eligible_set_size"] == 122
    assert evaluation["pair_admission_wired"] is False
    assert evaluation["provisional_v2_available"] is False
    assert evaluation["admission_policy"]["SOURCE_IDENTITY_REJECTED"] == (
        "REJECTION_AVAILABLE_BUT_NOT_WIRED"
    )
    for case_name in ("case15", "case16"):
        case = evaluation[case_name]
        assert case["evaluation_path"] == (
            "generic_endpoint_topology_source_identity_contract"
        )
        assert case["identity_status"] in {
            "SOURCE_IDENTITY_SUPPORTED",
            "SOURCE_IDENTITY_REJECTED",
            "SOURCE_IDENTITY_AMBIGUOUS",
        }
        assert case["evidence_completeness"] in {
            "COMPLETE",
            "PARTIAL",
            "INSUFFICIENT",
        }


def test_completeness_distinguishes_incomplete_ambiguity_from_complete_ambiguity() -> None:
    summary = _artifact("evidence-completeness-summary.json")
    assert summary["evidence_counts"] == {
        "COMPLETE": 0,
        "PARTIAL": 147,
        "INSUFFICIENT": 0,
    }
    assert summary["ambiguity_breakdown"]["ambiguous_because_evidence_incomplete"] == 48
    assert summary["ambiguity_breakdown"]["ambiguous_despite_complete_evidence"] == 0


def test_existing_control_suite_remains_safe() -> None:
    evaluation = _artifact("pair-identity-evaluation.json")
    controls = evaluation["controls"]
    assert controls["known_valid_pair_controls"] == {
        "case_ids": ["A", "C", "L"],
        "expected": 3,
        "preserved": 3,
    }
    assert controls["known_invalid_pair_controls"] == {
        "case_ids": ["B", "D", "E"],
        "expected": 3,
        "rejected": 3,
    }
    assert controls["crossing_valid_controls"]["preserved"] == 1
    assert controls["false_pair_rejections"] == 0
    assert set(controls["nested_coincident_multiplicity_controls"]["case_ids"]) == {
        "F",
        "G",
        "H",
        "I",
        "J",
        "L",
    }
