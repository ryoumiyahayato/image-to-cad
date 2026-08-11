from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from editable_text_contract_dispatch import dispatch_contract
from editable_text_regression_contract import (
    EDITABLE_TEXT_CONTRACT,
    require_explicit_contract,
)
from editable_text_v2_contract import (
    V2_CONTRACT,
    V2_PAGE_SCHEMA_VERSION,
    V2_SCHEMA_VERSION,
    V2SchemaError,
    _validate_page,
    validate_v2_manifest_shape,
)
from v2_canonical_structure import (
    canonical_payload,
    content_hash,
    multiset_digest,
    validate_structure_relation,
)


def _line(start: tuple[float, float], end: tuple[float, float], layer: str = "TRACE_STRAIGHT") -> dict[str, object]:
    return {
        "type": "LINE",
        "layer": layer,
        "start": [*start, 0.0],
        "end": [*end, 0.0],
    }


def _polyline() -> dict[str, object]:
    return {
        "type": "LWPOLYLINE",
        "layer": "TRACE_STRAIGHT",
        "closed": False,
        "points": [[0.0, 0.0, 0.0, 0.0, 0.0], [2.0, 0.0, 0.0, 0.0, 0.0]],
    }


def _circle() -> dict[str, object]:
    return {
        "type": "CIRCLE",
        "layer": "TRACE_STRAIGHT",
        "center": [4.0, 4.0, 0.0],
        "radius": 1.0,
    }


def _relation(
    base: list[dict[str, object]],
    candidate: list[dict[str, object]],
    approved: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return validate_structure_relation(
        base,
        candidate,
        page_id="unit-page",
        approved_records=approved or [],
    )


def _approve(relation: dict[str, object]) -> list[dict[str, object]]:
    return [
        {"canonical_entity_id": item["canonical_entity_id"]}
        for item in relation["delta_records"]  # type: ignore[index]
    ]


def _current_page(name: str) -> dict[str, object]:
    candidates = (
        WORKSPACE_ROOT / "local-artifacts/review/p1-v2-implementation/v2-pages" / f"{name}.json",
        PROJECT_ROOT / "validation/baselines/non-destructive-editable-text-v2/pages" / f"{name}.json",
    )
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    pytest.skip(f"current V2 review page is not materialized: {name}")


def test_v2_historical_empty_delta_is_valid() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0)), _polyline(), _circle()]
    result = _relation(base, copy.deepcopy(base))
    assert result["passed"] is True
    assert result["proof"]["base_missing_count"] == 0  # type: ignore[index]
    assert result["delta_records"] == []


def test_v2_single_and_multiple_source_backed_additions_are_exact() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0))]
    candidate = base + [_line((0.0, 1.0), (10.0, 1.0)), _circle()]
    unapproved = _relation(base, candidate)
    assert unapproved["passed"] is False
    approved = _relation(base, candidate, _approve(unapproved))
    assert approved["passed"] is True
    assert len(approved["delta_records"]) == 2


def test_v2_reversed_line_endpoints_share_canonical_identity() -> None:
    forward = _line((1.0, 20.0), (9.0, 2.0))
    reversed_line = _line((9.0, 2.0), (1.0, 20.0))
    assert canonical_payload(forward) == canonical_payload(reversed_line)
    result = _relation([forward], [reversed_line])
    assert result["passed"] is True
    assert result["delta_records"] == []


def test_v2_duplicate_multiplicity_is_counted_one_to_one() -> None:
    duplicate = _line((2.0, 2.0), (8.0, 2.0))
    base = [duplicate, duplicate]
    candidate = [duplicate, duplicate, duplicate]
    unapproved = _relation(base, candidate)
    assert unapproved["passed"] is False
    assert len(unapproved["delta_records"]) == 1
    approved = _relation(base, candidate, _approve(unapproved))
    assert approved["passed"] is True
    assert approved["delta_records"][0]["occurrence"] == 3  # type: ignore[index]


def test_v2_deterministic_ordering_and_digest_ignore_input_order() -> None:
    base = [_line((0.0, 0.0), (1.0, 0.0)), _circle(), _polyline()]
    candidate = base + [_line((4.0, 0.0), (5.0, 0.0)), _line((6.0, 0.0), (7.0, 0.0))]
    first = _relation(base, candidate)
    shuffled = list(candidate)
    random.Random(7).shuffle(shuffled)
    second = _relation(list(reversed(base)), shuffled)
    assert [x["canonical_entity_id"] for x in first["delta_records"]] == [  # type: ignore[index]
        x["canonical_entity_id"] for x in second["delta_records"]  # type: ignore[index]
    ]
    assert multiset_digest(first["delta_records"]) == multiset_digest(second["delta_records"])  # type: ignore[arg-type]


def test_v2_dispatch_is_explicit_and_v1_rejects_v2() -> None:
    with pytest.raises(ValueError):
        require_explicit_contract(V2_CONTRACT)
    kind, module = dispatch_contract(V2_CONTRACT)
    assert kind == "v2"
    assert module.V2_CONTRACT == V2_CONTRACT
    assert dispatch_contract(EDITABLE_TEXT_CONTRACT)[0] == "v1"
    with pytest.raises(ValueError):
        dispatch_contract(None)
    with pytest.raises(ValueError):
        dispatch_contract("v2-by-dpi")


def test_v2_manifest_shape_rejects_v1_and_requires_new_schema() -> None:
    with pytest.raises(V2SchemaError):
        validate_v2_manifest_shape({"contract_version": EDITABLE_TEXT_CONTRACT})
    with pytest.raises(V2SchemaError):
        validate_v2_manifest_shape(
            {
                "contract_version": V2_CONTRACT,
                "schema_version": V2_SCHEMA_VERSION - 1,
                "page_schema_version": V2_PAGE_SCHEMA_VERSION,
                "validator": "editable-text-regression-contract/v2",
                "parent_contract_version": EDITABLE_TEXT_CONTRACT,
                "parent_v1": {},
                "pages": [],
            }
        )


def test_v2_deletion_of_existing_structure_fails_closed() -> None:
    result = _relation([_line((0.0, 0.0), (10.0, 0.0))], [])
    assert result["passed"] is False
    assert result["proof"]["base_missing_count"] == 1  # type: ignore[index]


def test_v2_endpoint_mutation_is_not_swallowed_by_tolerance() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0))]
    moved = [_line((0.0, 0.001), (10.0, 0.0))]
    result = _relation(base, moved, _approve(_relation(base, moved)))
    assert result["passed"] is False
    assert result["proof"]["base_missing_count"] == 1  # type: ignore[index]


def test_v2_split_or_resegment_existing_structure_fails() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0))]
    candidate = [_line((0.0, 0.0), (5.0, 0.0)), _line((5.0, 0.0), (10.0, 0.0))]
    result = _relation(base, candidate, _approve(_relation(base, candidate)))
    assert result["passed"] is False
    assert result["proof"]["base_missing_count"] == 1  # type: ignore[index]


def test_v2_manifest_outside_candidate_delta_fails() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0))]
    candidate = base + [_line((0.0, 1.0), (10.0, 1.0))]
    fake = {"canonical_entity_id": "candidate:not-in-delta:0001"}
    result = _relation(base, candidate, [fake])
    assert result["passed"] is False
    assert result["unapproved_count"] == 1


def test_v2_missing_manifest_record_fails() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0))]
    candidate = base + [_line((0.0, 1.0), (10.0, 1.0))]
    result = _relation(base, candidate, [])
    assert result["passed"] is False
    assert result["missing_approved_count"] == 1


def test_v2_duplicate_manifest_id_fails_even_when_candidate_delta_is_valid() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0))]
    candidate = base + [_line((0.0, 1.0), (10.0, 1.0))]
    delta = _relation(base, candidate)["delta_records"]
    approved = _approve({"delta_records": delta})
    approved = approved + copy.deepcopy(approved)
    result = _relation(base, candidate, approved)
    assert result["passed"] is False
    assert result["duplicate_manifest_id_count"] == 1


def test_v2_full_page_relabeling_cannot_authorize_lost_base() -> None:
    base = [_line((0.0, 0.0), (10.0, 0.0)), _circle()]
    candidate = [_line((0.0, 1.0), (10.0, 1.0)), _circle()]
    result = _relation(base, candidate, _approve(_relation(base, candidate)))
    assert result["passed"] is False
    assert result["proof"]["base_missing_count"] == 1  # type: ignore[index]


def test_v2_current_150_page_is_91_of_91() -> None:
    page = _current_page("environment-plan-page-003-150dpi")
    result = _validate_page(WORKSPACE_ROOT, page, verify_evidence_files=False)
    assert result["passed"] is True
    assert result["restoration_count"] == 91
    assert result["missing_approved_count"] == 0
    assert result["unapproved_additions"] == 0
    assert result["ownership_conflicts"] == 0
    assert result["base_missing_count"] == 0


def test_v2_current_600_page_is_explicit_noop() -> None:
    page = _current_page("warehouse-index-page-001-600dpi")
    result = _validate_page(WORKSPACE_ROOT, page, verify_evidence_files=False)
    assert result["passed"] is True
    assert result["restoration_count"] == 0
    assert result["base_missing_count"] == 0


@pytest.mark.parametrize(
    "partition",
    ["text_symbol_hash", "source_outline_hash", "protected_content_hash", "page_transform_hash"],
)
def test_v2_unrelated_partition_claim_cannot_be_changed(partition: str) -> None:
    page = _current_page("environment-plan-page-003-150dpi")
    mutated = copy.deepcopy(page)
    mutated["partition_hashes"]["candidate"][partition] = "0" * 64  # type: ignore[index]
    result = _validate_page(WORKSPACE_ROOT, mutated, verify_evidence_files=False)
    assert result["passed"] is False
    assert any(partition in error for error in result["errors"])


def test_v2_evidence_hash_substitution_fails() -> None:
    page = _current_page("environment-plan-page-003-150dpi")
    mutated = copy.deepcopy(page)
    mutated["restorations"][0]["evidence_hash"] = content_hash({"substituted": True})  # type: ignore[index]
    result = _validate_page(WORKSPACE_ROOT, mutated, verify_evidence_files=False)
    assert result["passed"] is False
    assert any("aggregate evidence hash" in error for error in result["errors"])


def test_v2_determinism_tamper_fails() -> None:
    page = _current_page("environment-plan-page-003-150dpi")
    mutated = copy.deepcopy(page)
    mutated["determinism"]["runs"][1]["restoration_digest"] = "0" * 64  # type: ignore[index]
    result = _validate_page(WORKSPACE_ROOT, mutated, verify_evidence_files=False)
    assert result["passed"] is False
    assert any("deterministic replay" in error for error in result["errors"])


def test_v2_600_nonempty_policy_is_rejected() -> None:
    page = _current_page("warehouse-index-page-001-600dpi")
    mutated = copy.deepcopy(page)
    mutated["policy"]["expected_delta_count"] = 1  # type: ignore[index]
    result = _validate_page(WORKSPACE_ROOT, mutated, verify_evidence_files=False)
    assert result["passed"] is False
    assert any("expected restoration count" in error for error in result["errors"])
