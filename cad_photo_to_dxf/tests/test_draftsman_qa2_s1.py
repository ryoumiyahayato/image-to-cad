from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.draftsman_qa1 import audit_draftsman_qa1
from app.draftsman_qa2_s1 import measure_independent_source_coverage
from app.draftsman_vs3_t1 import run_draftsman_vs3_t1
from app.draftsman_vs3_u1 import preserve_draftsman_vs3_u1


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "tests/real_regression/assets/environment-page-003.png"


@pytest.fixture(scope="module")
def replays():  # type: ignore[no-untyped-def]
    outputs = []
    for _ in range(2):
        t1 = run_draftsman_vs3_t1(
            SOURCE,
            source_document_id="environment-plan-page-003-150dpi",
            source_page=3,
        )
        u1 = preserve_draftsman_vs3_u1(t1)
        qa1 = audit_draftsman_qa1(u1)
        before_u1 = u1.canonical_bytes()
        before_qa1 = qa1.canonical_bytes()
        qa2 = measure_independent_source_coverage(
            SOURCE, u1_result=u1, qa1_audit=qa1
        )
        outputs.append((u1, qa1, qa2, before_u1, before_qa1))
    return tuple(outputs)


def test_runtime_is_reference_free_and_identity_neutral(replays) -> None:  # type: ignore[no-untyped-def]
    runtime = inspect.getsource(measure_independent_source_coverage)
    assert "reference" not in inspect.signature(
        measure_independent_source_coverage
    ).parameters
    assert not any(
        item in runtime
        for item in (
            "FamilyAuditReference",
            "ELEC-150-S01",
            "SMOKE",
            "expected_family",
            "source_center_px ==",
        )
    )
    assert replays[0][2].to_dict()["runtime_contract"] == {
        "reference_available": False,
        "electrical_identity_used": False,
        "existing_glyph_candidate_used_as_detection_seed": False,
        "measurement_only": True,
        "qa1_dispositions_modified": False,
        "production_routing_changed": False,
    }


def test_source_regions_are_deterministic(replays) -> None:  # type: ignore[no-untyped-def]
    first = replays[0][2]
    second = replays[1][2]
    assert first.result_id == second.result_id
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.summary == {
        "source_coverage_regions": 257,
        "regions_seeded_by_existing_evidence": 0,
        "regions_independent_of_existing_evidence": 257,
        "residual_regions": 220,
        "measurement_only_omission_signals": 220,
        "actionable_review_findings": 0,
        "qa1_dispositions_modified": False,
    }


def test_regions_can_be_generated_without_existing_glyph_candidate_seed(replays) -> None:  # type: ignore[no-untyped-def]
    result = replays[0][2]
    independent = [
        item for item in result.source_regions if not item.seeded_by_existing_candidate
    ]
    assert len(independent) == 257
    residual = [item for item in independent if not item.explanation_ids]
    assert len(residual) == 220
    assert all(item.coverage_reason.startswith("INDEPENDENT_RASTER_STRUCTURE") for item in residual)


def test_explained_source_map_uses_narrow_candidate_support(replays) -> None:  # type: ignore[no-untyped-def]
    _, qa1, result, _, _ = replays[0]
    assert len(result.explained_source_map) == len(qa1.ledger) == 154
    by_candidate = {item.candidate_id: item for item in result.explained_source_map}
    for ledger in qa1.ledger:
        item = by_candidate[ledger.candidate_id]
        assert item.source_region == ledger.source_region
        assert item.disposition == ledger.final_disposition.value


def test_duplicate_source_regions_are_suppressed(replays) -> None:  # type: ignore[no-untyped-def]
    regions = replays[0][2].source_regions
    for index, first in enumerate(regions):
        for second in regions[index + 1 :]:
            distance_squared = (
                (first.center_px[0] - second.center_px[0]) ** 2
                + (first.center_px[1] - second.center_px[1]) ** 2
            )
            assert distance_squared > 12.0**2


def test_outputs_are_measurement_only_and_do_not_modify_qa1(replays) -> None:  # type: ignore[no-untyped-def]
    u1, qa1, result, before_u1, before_qa1 = replays[0]
    assert result.residual_regions
    assert all(item.measurement_only for item in result.residual_regions)
    assert result.summary["actionable_review_findings"] == 0
    assert u1.canonical_bytes() == before_u1
    assert qa1.canonical_bytes() == before_qa1


def test_reference_is_loaded_only_after_runtime_in_report_harness() -> None:
    script = (
        PROJECT_ROOT / "scripts/generate_draftsman_qa2_s1.py"
    ).read_text(encoding="utf-8")
    runtime_call = script.index("measure_independent_source_coverage(")
    reference_load = script.index("FamilyAuditReference.load(args.reference)")
    assert reference_load > runtime_call


def test_qa2_is_not_imported_by_production_entrypoints() -> None:
    entrypoints = (
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "app/document_export.py",
        PROJECT_ROOT / "app/dxf_exporter.py",
    )
    assert all(
        "draftsman_qa2_s1" not in path.read_text(encoding="utf-8")
        for path in entrypoints
    )
