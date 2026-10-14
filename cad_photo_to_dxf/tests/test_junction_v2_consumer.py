from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import ezdxf
import numpy as np
import pytest

from app.geometry import junction_v2_consumer as junction_consumer_module
from app.ocr.auxiliary_recognition import TextCandidate
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION
from app.core.structure_build import build_final_structure
from app.geometry.junction_v2_consumer import BoundedR4JunctionAuthority, EndpointSelector, JunctionAction, JunctionAlreadyConsumedError, JunctionBlockedError, JunctionContract, JunctionObligation, _lines_digest, bounded_r4_authority_from_reconciliation_results, consume_junction_contract, load_junction_v2_trusted_authority, load_verified_junction_v2_r4_replay
from app.geometry.line_detect import LineSegment
from app.core.processing import ProductionProcessingConfig, build_processing_cache_key, cache_key_matches
from app.geometry.raster_trace import RasterTraceResult
from app.geometry.source_stroke_reconciliation import ReconciliationLedger, RouteOrigin
from app.export.trace_single_export import export_final_structure_dxf
from app.core.cache import TRACE_CACHE_VERSION, load_trace_cache, save_trace_cache

FIXTURE = (
    Path(__file__).parent / "fixtures" / "junction-v2-consumer-contract-d2cecc.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _contract(payload: dict[str, object] | None = None) -> JunctionContract:
    value = dict(_fixture() if payload is None else payload)
    return JunctionContract.from_payload(value)


def _authority() -> BoundedR4JunctionAuthority:
    return load_verified_junction_v2_r4_replay()


def _line_by_id(result, member_id: str) -> LineSegment:
    return result.lines[result.final_piece_ids.index(member_id)]


def _point(value: list[float]) -> tuple[float, float]:
    return (float(value[0]), float(value[1]))


def test_all_eight_frozen_nodes_have_exact_shared_incidence_and_lineage() -> None:
    contract = _contract()
    source = _authority()
    result = consume_junction_contract(source, contract)

    assert len(contract.obligations) == 20
    assert len(result.consumed_obligation_ids) == 20
    assert len(result.lineage) == 20
    assert [item["node_id"] for item in result.node_incidence] == [
        "ENV-3",
        "WH-1",
        "WH-2",
        "WH-3",
        "WH-4",
        "WH-5",
        "WH-6",
        "WH-7",
    ]
    assert [item["actual_arms"] for item in result.node_incidence] == [
        2,
        2,
        2,
        2,
        4,
        4,
        4,
        4,
    ]
    assert all(item["status"] == "PASS" for item in result.node_incidence)
    assert len(result.lines) == len(source.lines) + 4
    result.assert_complete(result.lines)


@pytest.mark.parametrize("node_id", ["ENV-3", "WH-1", "WH-2", "WH-3"])
def test_corner_actions_replace_only_designated_endpoints(node_id: str) -> None:
    payload = _fixture()
    contract = _contract(payload)
    source = _authority()
    result = consume_junction_contract(source, contract)
    obligations = [item for item in contract.obligations if item.node_id == node_id]

    assert len(obligations) == 2
    for obligation in obligations:
        record = next(
            item
            for item in result.lineage
            if item.obligation_id == obligation.obligation_id
        )
        original = source.lines[
            source.final_piece_ids.index(obligation.input_member_id)
        ]
        before = record.input_geometries[0]
        after = record.output_geometries[0]
        assert obligation.action is JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE
        if obligation.endpoint_selector is EndpointSelector.START:
            assert after[:2] == obligation.canonical_point
            assert after[2:] == before[2:]
        else:
            assert after[2:] == obligation.canonical_point
            assert after[:2] == before[:2]
        final_members = [
            line
            for member_id, line in zip(
                result.final_piece_ids, result.lines, strict=True
            )
            if member_id.startswith(obligation.input_member_id)
        ]
        assert final_members
        assert all(line.width == original.width for line in final_members)
        assert all(line.layer == original.layer for line in final_members)
        assert all(line.source_ids == original.source_ids for line in final_members)
        assert all(line.confidence == original.confidence for line in final_members)
        assert all(
            line.classification_confidence == original.classification_confidence
            for line in final_members
        )


@pytest.mark.parametrize("node_id", ["WH-4", "WH-5", "WH-6", "WH-7"])
def test_warehouse_crossing_has_two_split_and_two_endpoint_arms(node_id: str) -> None:
    contract = _contract()
    source = _authority()
    result = consume_junction_contract(source, contract)
    obligations = [item for item in contract.obligations if item.node_id == node_id]
    point = obligations[0].canonical_point

    assert [item.action for item in obligations] == [
        JunctionAction.SPLIT_AT_CANONICAL_NODE,
        JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE,
        JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE,
    ]
    incident = next(
        item for item in result.node_incidence if item["node_id"] == node_id
    )
    assert incident["actual_arms"] == 4
    assert len(incident["incident_output_member_ids"]) == 4
    for member_id in incident["incident_output_member_ids"]:
        line = _line_by_id(result, member_id)
        assert (line.x1, line.y1) == point or (line.x2, line.y2) == point


def test_nonparticipants_crossings_and_near_parallel_members_cannot_enter_authority() -> None:
    crossing_a = LineSegment(0.0, 50.0, 100.0, 50.0, source_ids=("NONPARTICIPANT-A",))
    crossing_b = LineSegment(50.0, 0.0, 50.0, 100.0, source_ids=("NONPARTICIPANT-B",))
    near_parallel = LineSegment(
        0.0, 50.25, 100.0, 50.25, source_ids=("SAME-STROKE-DUPLICATE",)
    )
    extras = (
        ("extra-crossing-a", crossing_a),
        ("extra-crossing-b", crossing_b),
        ("extra-near-parallel", near_parallel),
    )
    source = _authority()
    lines = (*source.lines, *(line for _, line in extras))
    forged = replace(
        source,
        lines=lines,
        final_piece_ids=(*source.final_piece_ids, *(member_id for member_id, _ in extras)),
        final_set_digest=_lines_digest(lines),
    )
    with pytest.raises(JunctionBlockedError):
        consume_junction_contract(forged, _contract())


def test_extension_requires_saved_support_and_clear_protection() -> None:
    contract = _contract()
    lower = next(
        item
        for item in contract.obligations
        if item.action is JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE
    )
    unsupported = replace(lower, source_support_to_node="UNKNOWN")
    vetoed = replace(lower, protection_clear=False)

    with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
        consume_junction_contract(
            _authority(),
            replace(contract, obligations=(unsupported,)),
        )
    with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
        consume_junction_contract(
            _authority(),
            replace(contract, obligations=(vetoed,)),
        )


def test_explicit_block_action_is_transactionally_rejected() -> None:
    contract = _contract()
    original = contract.obligations[0]
    blocked = replace(
        original,
        action=JunctionAction.BLOCK_AND_REVIEW,
        endpoint_selector=EndpointSelector.NONE,
    )
    with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
        consume_junction_contract(
            _authority(), replace(contract, obligations=(blocked,))
        )


def test_exactly_once_rejects_reapplication() -> None:
    result = consume_junction_contract(_authority(), _contract())
    with pytest.raises(JunctionAlreadyConsumedError):
        consume_junction_contract(result, _contract())


def test_empty_explicit_contract_performs_no_discovery_or_mutation() -> None:
    source = _authority()
    contract = JunctionContract("explicit-empty-contract", ())

    with pytest.raises(JunctionBlockedError, match="contract ID is not trusted"):
        consume_junction_contract(source, contract)


def test_finalstructure_cache_and_export_consume_exact_junction_geometry(
    tmp_path: Path,
) -> None:
    source = _authority()
    result = consume_junction_contract(source, _contract())
    binary = np.full((1800, 1300), 255, dtype=np.uint8)
    text = TextCandidate(
        text="ROOM",
        bbox=(20, 20, 80, 30),
        confidence=0.99,
        kind="text_candidate",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )
    before = build_final_structure(
        source_size_px=(1300, 1800),
        contour_binary=binary,
        contours=(),
        straight_lines=source.lines,
        texts=(text,),
    )
    after = build_final_structure(
        source_size_px=(1300, 1800),
        contour_binary=binary,
        contours=(),
        straight_lines=result.commit(),
        texts=(text,),
        provenance={"junction_v2_ledger_digest": result.ledger_digest},
        observations=(result.ledger_payload(),),
    )

    assert FINAL_STRUCTURE_SCHEMA_VERSION == 3
    assert TRACE_CACHE_VERSION == 10
    assert after.straight_lines is result.lines
    assert after.texts == before.texts == (text,)
    assert after.structure_id != before.structure_id

    trace = RasterTraceResult(
        binary=binary,
        stages={},
        paths=(),
        threshold=128,
        foreground_pixels=0,
        vertex_count=0,
        straight_lines=result.lines,
        final_structure=after,
    )
    cache = save_trace_cache(tmp_path / "junction.npz", trace)
    restored = load_trace_cache(cache)
    assert restored.final_structure is not None
    assert restored.final_structure.structure_id == after.structure_id
    assert restored.final_structure.straight_lines == result.lines

    export_path = tmp_path / "junction.dxf"
    exported = export_final_structure_dxf(after, export_path)
    assert exported.structure_id == after.structure_id
    document = ezdxf.readfile(export_path)
    entities = list(document.modelspace().query("LINE[layer=='TRACE_STRAIGHT']"))
    assert len(entities) == len(result.lines)
    expected = {
        (
            (float(line.x1), float(1800.0 - line.y1)),
            (float(line.x2), float(1800.0 - line.y2)),
        )
        for line in result.lines
    }
    actual = {
        (
            (float(entity.dxf.start.x), float(entity.dxf.start.y)),
            (float(entity.dxf.end.x), float(entity.dxf.end.y)),
        )
        for entity in entities
    }
    assert actual == expected


def test_processing_cache_identity_binds_only_explicit_junction_contract() -> None:
    source_hash = "a" * 64
    baseline_config = ProductionProcessingConfig(enable_ocr=False)
    junction_config = ProductionProcessingConfig(
        enable_ocr=False,
        junction_contract=_contract(),
    )
    baseline = build_processing_cache_key(
        input_content_sha256=source_hash,
        page_index=0,
        config=baseline_config,
    )
    junction = build_processing_cache_key(
        input_content_sha256=source_hash,
        page_index=0,
        config=junction_config,
    )

    assert "junction_contract_digest" not in baseline_config.payload()
    assert junction_config.payload()["junction_contract_digest"] == _contract().digest
    assert baseline.digest != junction.digest
    repeated = build_processing_cache_key(
        input_content_sha256=source_hash,
        page_index=0,
        config=ProductionProcessingConfig(
            enable_ocr=False,
            junction_contract=_contract(),
        ),
    )
    assert repeated == junction
    assert not cache_key_matches(baseline.payload(), junction)
    assert cache_key_matches(junction.payload(), repeated)


def _replace_contract_obligation(
    contract: JunctionContract,
    index: int,
    obligation: JunctionObligation,
) -> JunctionContract:
    obligations = list(contract.obligations)
    obligations[index] = obligation
    return replace(contract, obligations=tuple(obligations))


@pytest.mark.parametrize(
    ("name", "mutator"),
    [
        (
            "changed-node-id",
            lambda item: replace(item, node_id="FORGED-NODE"),
        ),
        (
            "forged-900-900-point",
            lambda item: replace(item, canonical_point=(900.0, 900.0)),
        ),
        (
            "changed-participant",
            lambda item: replace(item, participant_id="FORGED-PARTICIPANT"),
        ),
        (
            "changed-action",
            lambda item: replace(
                item,
                action=JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE,
            ),
        ),
        (
            "invalid-role-action-pair",
            lambda item: replace(item, frozen_role="FORGED-ROLE"),
        ),
        (
            "foreign-evidence-scope",
            lambda item: replace(
                item, source_evidence_refs=("foreign-page://untrusted",)
            ),
        ),
        (
            "missing-evidence",
            lambda item: replace(item, source_evidence_refs=()),
        ),
        (
            "protection-veto",
            lambda item: replace(item, protection_clear=False),
        ),
    ],
)
def test_mutated_contract_fields_fail_before_geometry_mutation(name, mutator) -> None:
    del name
    source = _authority()
    before = source.lines
    contract = _contract()
    index = next(
        index
        for index, item in enumerate(contract.obligations)
        if item.action is JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE
    )
    forged = _replace_contract_obligation(
        contract,
        index,
        mutator(contract.obligations[index]),
    )

    with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
        consume_junction_contract(source, forged)
    with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
        ProductionProcessingConfig(enable_ocr=False, junction_contract=forged)
    assert source.lines is before
    assert all(
        (line.x1, line.y1) != (900.0, 900.0)
        and (line.x2, line.y2) != (900.0, 900.0)
        for line in source.lines
    )


def test_changed_contract_id_and_self_digest_cannot_self_authorize() -> None:
    contract = replace(_contract(), contract_id="caller-generated-authority")
    assert contract.digest != load_junction_v2_trusted_authority().trusted_contract_digest
    with pytest.raises(JunctionBlockedError, match="contract ID is not trusted"):
        consume_junction_contract(_authority(), contract)
    with pytest.raises(JunctionBlockedError, match="contract ID is not trusted"):
        ProductionProcessingConfig(enable_ocr=False, junction_contract=contract)


def test_complete_set_rejects_incomplete_extra_and_duplicate_obligations() -> None:
    contract = _contract()
    incomplete = replace(contract, obligations=(contract.obligations[0],))
    extra_item = replace(
        contract.obligations[0],
        obligation_id="UNAUTHORIZED-EXTRA-OBLIGATION",
        participant_id="UNAUTHORIZED-EXTRA-PARTICIPANT",
    )
    extra = replace(contract, obligations=(*contract.obligations, extra_item))

    for forged in (incomplete, extra):
        with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
            consume_junction_contract(_authority(), forged)
        with pytest.raises(JunctionBlockedError, match="digest is not trusted"):
            ProductionProcessingConfig(enable_ocr=False, junction_contract=forged)
    with pytest.raises(ValueError, match="identities must be unique"):
        replace(
            contract,
            obligations=(*contract.obligations, contract.obligations[0]),
        )


def test_source_page_and_r4_transaction_binding_fail_closed() -> None:
    source = _authority()
    foreign_scope = replace(source, source_scope_digests=("foreign-scope",))
    stale = replace(source, final_set_digest="0" * 64)
    wrong_member_ids = list(source.final_piece_ids)
    wrong_member_ids[0] = "FORGED-CURRENT-MEMBER"
    wrong_member = replace(source, final_piece_ids=tuple(wrong_member_ids))
    wrong_line = source.lines[0].copy(source_ids=("FORGED-SOURCE",))
    wrong_source_lines = (wrong_line, *source.lines[1:])
    wrong_source = replace(
        source,
        lines=wrong_source_lines,
        final_set_digest=_lines_digest(wrong_source_lines),
    )

    controls = (foreign_scope, stale, wrong_member, wrong_source)
    for forged in controls:
        with pytest.raises(JunctionBlockedError):
            consume_junction_contract(forged, _contract())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("layer", "FOREIGN_CALLER_LAYER"),
        ("confidence", 0.01),
        ("history", ("caller-fabricated:not-r4-reconciled",)),
        ("classification_confidence", 0.02),
        ("classification_reasons", ("caller-fabricated",)),
    ],
)
def test_output_significant_r4_metadata_change_rejects(field, value) -> None:
    source = _authority()
    changed = source.lines[0].copy(**{field: value})
    lines = (changed, *source.lines[1:])
    forged = replace(source, lines=lines, final_set_digest=_lines_digest(lines))

    with pytest.raises(JunctionBlockedError):
        consume_junction_contract(forged, _contract())


def test_caller_lines_cannot_mint_bounded_r4_authority() -> None:
    source = _authority()
    changed = source.lines[0].copy(layer="FOREIGN_CALLER_LAYER")
    lines = (changed, *source.lines[1:])
    authority = load_junction_v2_trusted_authority()

    assert not hasattr(BoundedR4JunctionAuthority, "from_trusted_replay")
    forged = BoundedR4JunctionAuthority(
        lines=lines,
        final_piece_ids=source.final_piece_ids,
        final_set_digest=_lines_digest(lines),
        source_scope_digests=authority.page_scope_digests,
        authority_origin="VERIFIED_SAVED_REPLAY",
        provenance_digest=authority.trusted_r4_replay_resource_sha256,
        _provenance_token=object(),
        _seal=object(),
    )
    with pytest.raises(JunctionBlockedError, match="seal changed"):
        consume_junction_contract(forged, _contract())


def test_modified_saved_replay_resource_cannot_mint_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = junction_consumer_module._TRUSTED_R4_REPLAY_RESOURCE
    payload = json.loads(original.read_text(encoding="utf-8"))
    payload["members"][0]["layer"] = "FOREIGN_CALLER_LAYER"
    changed = tmp_path / "changed-r4-replay.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        junction_consumer_module, "_TRUSTED_R4_REPLAY_RESOURCE", changed
    )
    load_verified_junction_v2_r4_replay.cache_clear()
    try:
        with pytest.raises(JunctionBlockedError, match="integrity failed"):
            load_verified_junction_v2_r4_replay()
    finally:
        load_verified_junction_v2_r4_replay.cache_clear()


def test_missing_extra_and_duplicate_r4_members_reject() -> None:
    source = _authority()
    missing_lines = source.lines[:-1]
    missing = replace(
        source,
        lines=missing_lines,
        final_piece_ids=source.final_piece_ids[:-1],
        final_set_digest=_lines_digest(missing_lines),
    )
    extra_line = LineSegment(0.0, 0.0, 1.0, 1.0, source_ids=("EXTRA",))
    extra_lines = (*source.lines, extra_line)
    extra = replace(
        source,
        lines=extra_lines,
        final_piece_ids=(*source.final_piece_ids, "EXTRA"),
        final_set_digest=_lines_digest(extra_lines),
    )
    duplicate = replace(
        source,
        final_piece_ids=(*source.final_piece_ids[:-1], source.final_piece_ids[0]),
    )

    for forged in (missing, extra, duplicate):
        with pytest.raises(JunctionBlockedError):
            consume_junction_contract(forged, _contract())


def test_equal_value_line_copies_cannot_reuse_verified_replay_provenance() -> None:
    source = _authority()
    copied_lines = tuple(line.copy() for line in source.lines)
    assert copied_lines == source.lines
    assert copied_lines is not source.lines
    forged = replace(source, lines=copied_lines)

    with pytest.raises(JunctionBlockedError, match="tuple provenance changed"):
        consume_junction_contract(forged, _contract())


@pytest.mark.parametrize(
    "lines",
    [
        lambda source: tuple(line.copy() for line in source.lines),
        lambda source: (
            source.lines[0].copy(layer="FOREIGN_CALLER_LAYER"),
            *source.lines[1:],
        ),
        lambda source: (
            source.lines[0].copy(confidence=0.01),
            *source.lines[1:],
        ),
        lambda source: (
            source.lines[0].copy(history=("caller-created",)),
            *source.lines[1:],
        ),
        lambda source: (
            source.lines[0].copy(classification_confidence=0.02),
            *source.lines[1:],
        ),
        lambda source: (
            source.lines[0].copy(classification_reasons=("caller-created",)),
            *source.lines[1:],
        ),
        lambda source: (source.lines[0].copy(x1=-123.0), *source.lines[1:]),
        lambda source: (source.lines[0].copy(width=9.0), *source.lines[1:]),
        lambda source: (
            source.lines[0].copy(source_ids=("CALLER-SOURCE",)),
            *source.lines[1:],
        ),
        lambda source: source.lines[:-1],
        lambda source: (*source.lines, source.lines[0].copy()),
        lambda source: (*source.lines[:-1], source.lines[0]),
    ],
)
def test_loose_line_tuples_have_no_authority_creation_path(lines) -> None:
    source = _authority()
    loose_lines = tuple(lines(source))

    assert not hasattr(junction_consumer_module, "_create_bounded_r4_authority")
    with pytest.raises((JunctionBlockedError, TypeError)):
        bounded_r4_authority_from_reconciliation_results(
            loose_lines,  # type: ignore[arg-type]
            _contract(),
        )
    with pytest.raises(TypeError, match="validated R4 line authority"):
        consume_junction_contract(loose_lines, _contract())  # type: ignore[arg-type]


def test_trusted_authority_origin_and_complete_identity_are_fixed() -> None:
    authority = load_junction_v2_trusted_authority()
    contract = _contract()

    assert authority.authority_id == "junction-v2-eight-node-r4-d2cecc"
    assert authority.authority_version == "1"
    assert authority.trusted_contract_digest == contract.digest
    assert authority.node_ids == (
        "ENV-3",
        "WH-1",
        "WH-2",
        "WH-3",
        "WH-4",
        "WH-5",
        "WH-6",
        "WH-7",
    )
    assert len(authority.obligation_ids) == 20
    assert len(set(authority.obligation_ids)) == 20
    assert len(authority.page_scope_digests) == 2
    assert len(load_verified_junction_v2_r4_replay().lines) == 18


def test_valid_transaction_records_trusted_authority_and_r4_binding() -> None:
    result = consume_junction_contract(_authority(), _contract())
    authority = load_junction_v2_trusted_authority()
    ledger = result.ledger_payload()

    assert result.trusted_authority_id == authority.authority_id
    assert result.trusted_authority_resource_sha256 == authority.resource_sha256
    assert (
        result.trusted_r4_transaction_binding_digest
        == authority.r4_transaction_binding_digest
    )
    assert ledger["trusted_authority_id"] == authority.authority_id
    assert len(result.consumed_obligation_ids) == 20
    assert len(result.node_incidence) == 8


def test_real_r4_result_stays_sealed_beneath_junction_authority() -> None:
    page = np.full((120, 140), 255, dtype=np.uint8)
    page[50, 20:101] = 0
    line = LineSegment(
        20.0,
        50.0,
        100.0,
        50.0,
        source_ids=("R4-SEALED",),
        history=("detected:test",),
    )
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=np.zeros_like(page),
        scale=1.0,
    )
    ledger.observe_route((line,), route=RouteOrigin.MAIN, producer="junction-test")
    r4 = ledger.reconcile(
        main_candidates=(line,),
        accepted_main=(line,),
        restoration_candidates=(),
        ownership_masks={"line": np.where(page < 128, 255, 0).astype(np.uint8)},
    )
    obligation = JunctionObligation(
        obligation_id="TEST-NODE::R4-SEALED::CANONICALIZE_ENDPOINT_TO_NODE",
        node_id="TEST-NODE",
        participant_id="R4-SEALED-PARTICIPANT",
        input_member_id=r4.final_piece_ids[0],
        action=JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE,
        canonical_point=(90.0, 50.0),
        endpoint_selector=EndpointSelector.END,
        source_ids=("R4-SEALED",),
        frozen_role="TERMINATES_AT_NODE_WITH_FITTED_OVERSHOOT",
        source_support_to_node="YES_DIRECT_SOURCE_CONTACT",
        source_evidence_refs=("test://explicit-frozen-node",),
        protection_clear=True,
    )

    r4.assert_complete()
    with pytest.raises(JunctionBlockedError, match="contract ID is not trusted"):
        consume_junction_contract(
            r4,
            JunctionContract("sealed-r4-test", (obligation,)),
        )
    assert r4.lines[0].x2 == 100.0
    assert r4.lines[0].y2 == 50.0
