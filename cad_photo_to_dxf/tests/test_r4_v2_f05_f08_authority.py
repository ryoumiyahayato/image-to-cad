from __future__ import annotations

from dataclasses import replace
import json

import cv2
import numpy as np
import pytest

import app.geometry.source_stroke_reconciliation as reconciliation
from app.geometry.line_detect import LineSegment
from app.geometry.source_stroke_reconciliation import GAP_EXTENT_MEASUREMENT_SLOT, LEGACY_ACCEPTED_HISTORY, ReconciliationLedger


def _masks(page: np.ndarray) -> dict[str, np.ndarray]:
    empty = np.zeros_like(page)
    return {
        "line": np.where(page < 128, 255, 0).astype(np.uint8),
        "text": empty.copy(),
        "logo": empty.copy(),
        "signature": empty.copy(),
        "graphic": empty.copy(),
        "residual": empty.copy(),
    }


def _result(*, accepted: bool = False, scoped: tuple[float, float] | None = None):
    page = np.full((96, 192), 255, dtype=np.uint8)
    line = LineSegment(
        20.0,
        48.0,
        172.0,
        48.0,
        source_ids=("RESTORE",),
        history=(LEGACY_ACCEPTED_HISTORY,),
    )
    cv2.line(page, (20, 48), (172, 48), 0, 1, cv2.LINE_8)
    protected = np.zeros_like(page)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=protected,
        scale=1.0,
    )
    authorizations = ()
    if accepted:
        intervals = None if scoped is None else (scoped,)
        authorizations = (ledger.authorize_restoration(line, intervals=intervals),)
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(line,),
        accepted_restoration_authorizations=authorizations,
        ownership_masks=_masks(page),
    )
    return page, line, result


def _extension(result) -> dict[str, object]:
    payload = result.ledger_payload()
    snapshot = next(
        item
        for item in payload["evidence"]
        if item.get("artifact") == "runtime-route-ledger-snapshot"
    )
    return snapshot["measurements"][GAP_EXTENT_MEASUREMENT_SLOT]


@pytest.mark.parametrize(
    "mutation",
    (
        "gray_replace",
        "binary_replace",
        "gray_inplace_outside_roi",
        "binary_inplace_inside_roi",
        "shape",
        "dtype",
        "source_frame",
    ),
)
def test_f05_closed_commit_rejects_changed_actual_source_bytes(mutation: str) -> None:
    _page, _line, result = _result(accepted=True)
    context = result._validation_context
    gray = context.source_gray
    binary = context.source_binary
    if mutation in {"gray_replace", "gray_inplace_outside_roi"}:
        gray = gray.copy()
        gray.flat[-1 if mutation == "gray_replace" else 0] ^= 1
    elif mutation in {"binary_replace", "binary_inplace_inside_roi"}:
        binary = binary.copy()
        if mutation == "binary_replace":
            binary.flat[-1] ^= 1
        else:
            binary[48, 50] ^= 1
    elif mutation == "shape":
        gray = gray.copy().reshape(48, 384)
    elif mutation == "dtype":
        gray = gray.astype(np.int16)
    changed = replace(context, source_gray=gray, source_binary=binary)
    if mutation == "source_frame":
        changed = replace(
            changed,
            source_gray_authority=replace(
                context.source_gray_authority, source_frame_id="DIFFERENT_FRAME"
            ),
        )
    with pytest.raises(AssertionError, match="source authority|source snapshot changed"):
        replace(result, _validation_context=changed).commit()


def test_f05_ledger_digest_cannot_redefine_trusted_source() -> None:
    _page, _line, result = _result(accepted=True)
    context = result._validation_context
    changed_gray = context.source_gray.copy()
    changed_gray[0, 0] ^= 1
    malicious_hash = reconciliation.hashlib.sha256(changed_gray.tobytes()).hexdigest()
    payload = result.ledger_payload()
    payload["source_image_sha256"] = malicious_hash
    forged_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    forged_digest = reconciliation._digest_payload(payload)
    forged_context = replace(
        context,
        source_gray=changed_gray,
        source_gray_sha256=malicious_hash,
        validated_ledger_digest=forged_digest,
    )
    with pytest.raises(AssertionError):
        replace(
            result,
            ledger_json=forged_json,
            ledger_digest=forged_digest,
            _validation_context=forged_context,
        ).commit()


@pytest.mark.parametrize("field", ("source_gray", "source_binary"))
@pytest.mark.parametrize(
    "variant",
    (
        "exact_copy",
        "c_contiguous_copy",
        "slice_view",
        "read_only_view",
        "writable_view",
        "modified_writable_copy",
    ),
)
def test_f05_construction_evidence_uses_sealed_source_not_working_array(
    field: str,
    variant: str,
) -> None:
    page = np.full((96, 192), 255, dtype=np.uint8)
    line = LineSegment(20.0, 48.0, 172.0, 48.0, source_ids=("SEALED",))
    cv2.line(page, (20, 48), (172, 48), 0, 1, cv2.LINE_8)

    def run(replacement: np.ndarray | None = None):
        ledger = ReconciliationLedger(
            source_gray=page,
            source_binary=page,
            protected_mask=None,
            scale=1.0,
        )
        authorization = ledger.authorize_restoration(line)
        if replacement is not None:
            setattr(ledger, field, replacement)
        return ledger.reconcile(
            main_candidates=(),
            accepted_main=(),
            restoration_candidates=(line,),
            accepted_restoration_authorizations=(authorization,),
            ownership_masks=_masks(page),
        )

    baseline = run()
    if variant in {"exact_copy", "c_contiguous_copy"}:
        replacement = np.ascontiguousarray(page.copy())
    elif variant == "slice_view":
        owner = np.pad(page, 1, constant_values=255)
        replacement = owner[1:-1, 1:-1]
        assert not replacement.flags.c_contiguous
    elif variant == "read_only_view":
        replacement = page.copy().view()
        replacement.setflags(write=False)
    elif variant == "writable_view":
        replacement = page.copy().view()
        assert replacement.flags.writeable
    else:
        replacement = page.copy()
        replacement[48, 80:112] = 255

    changed = run(replacement)
    assert changed.lines == baseline.lines
    assert changed.ledger_digest == baseline.ledger_digest
    assert changed._validation_context.source_scope_digest == (
        baseline._validation_context.source_scope_digest
    )
    assert changed.commit() == baseline.commit()


def test_f08_history_text_alone_has_no_acceptance_authority() -> None:
    _page, _line, result = _result()
    assert all(
        parent["acceptance_status"] == "FRESH_PROPOSAL"
        for parent in _extension(result)["parents"]
    )


@pytest.mark.parametrize(
    "case",
    ("magic", "partial", "full", "unrelated", "lookalike", "copied_identity"),
)
def test_f08_history_attack_matrix_grants_nothing(case: str) -> None:
    page = np.full((96, 192), 255, dtype=np.uint8)
    history = (
        ("source_stroke_legacy_accepte",)
        if case == "lookalike"
        else (LEGACY_ACCEPTED_HISTORY,)
    )
    source_id = "COPIED-TO-DIFFERENT-MEMBER" if case == "copied_identity" else "RESTORE"
    line = LineSegment(
        20.0, 48.0, 172.0, 48.0, source_ids=(source_id,), history=history
    )
    cv2.line(page, (20, 48), (172, 48), 0, 1, cv2.LINE_8)
    protected = np.zeros_like(page)
    if case == "partial":
        protected[46:51, 80:110] = 255
    elif case == "full":
        protected[46:51, 18:175] = 255
    elif case == "unrelated":
        protected[10:15, 10:40] = 255
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=protected,
        scale=1.0,
    )
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(line,),
        ownership_masks=_masks(page),
    )
    assert all(
        parent["acceptance_status"] == "FRESH_PROPOSAL"
        for parent in _extension(result)["parents"]
    )


def test_f08_explicit_authority_does_not_require_history() -> None:
    page = np.full((96, 192), 255, dtype=np.uint8)
    line = LineSegment(20.0, 48.0, 172.0, 48.0, source_ids=("RESTORE",))
    cv2.line(page, (20, 48), (172, 48), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page, source_binary=page, protected_mask=None, scale=1.0
    )
    authorization = ledger.authorize_restoration(line)
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(line,),
        accepted_restoration_authorizations=(authorization,),
        ownership_masks=_masks(page),
    )
    assert any(
        parent["acceptance_status"] == "ALREADY_ACCEPTED"
        for parent in _extension(result)["parents"]
    )


@pytest.mark.parametrize(
    "mutation",
    ("remove_history", "reorder_history", "audit_note", "diagnostic_provenance"),
)
def test_f08_acceptance_identity_is_history_and_audit_independent(
    mutation: str,
) -> None:
    page = np.full((96, 192), 255, dtype=np.uint8)
    line = LineSegment(
        20.0,
        48.0,
        172.0,
        48.0,
        source_ids=("RESTORE",),
        history=(LEGACY_ACCEPTED_HISTORY, "audit:first"),
        classification_reasons=("diagnostic:first",),
    )
    cv2.line(page, (20, 48), (172, 48), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page, source_binary=page, protected_mask=None, scale=1.0
    )
    authorization = ledger.authorize_restoration(line)
    if mutation == "remove_history":
        candidate = line.copy(history=())
    elif mutation == "reorder_history":
        candidate = line.copy(history=tuple(reversed(line.history)))
    elif mutation == "audit_note":
        candidate = line.copy(history=line.history + ("audit:changed",))
    else:
        candidate = line.copy(classification_reasons=("diagnostic:changed",))
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(candidate,),
        accepted_restoration_authorizations=(authorization,),
        ownership_masks=_masks(page),
    )
    assert all(
        parent["acceptance_status"] == "ALREADY_ACCEPTED"
        for parent in _extension(result)["parents"]
    )


@pytest.mark.parametrize(
    "mutation",
    ("endpoint", "orientation", "tiny_geometry", "width", "member", "layer"),
)
def test_f08_acceptance_identity_rejects_semantic_member_changes(
    mutation: str,
) -> None:
    page = np.full((96, 192), 255, dtype=np.uint8)
    line = LineSegment(20.0, 48.0, 172.0, 48.0, source_ids=("RESTORE",))
    cv2.line(page, (20, 48), (172, 48), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page, source_binary=page, protected_mask=None, scale=1.0
    )
    authorization = ledger.authorize_restoration(line)
    if mutation == "endpoint":
        candidate = line.copy(x2=171.0)
    elif mutation == "orientation":
        candidate = line.copy(x1=172.0, x2=20.0)
    elif mutation == "tiny_geometry":
        candidate = line.copy(x2=172.0 + 1e-12)
    elif mutation == "width":
        candidate = line.copy(width=2.0)
    elif mutation == "member":
        candidate = line.copy(source_ids=("OTHER",))
    else:
        candidate = line.copy(layer="OTHER")
    with pytest.raises(AssertionError, match="authorization"):
        ledger.reconcile(
            main_candidates=(),
            accepted_main=(),
            restoration_candidates=(candidate,),
            accepted_restoration_authorizations=(authorization,),
            ownership_masks=_masks(page),
        )


def test_f08_authority_is_identity_source_and_interval_scoped() -> None:
    page, line, _result_unused = _result()
    protected = np.where(page < 128, 255, 0).astype(np.uint8)
    ledger = ReconciliationLedger(
        source_gray=page,
        source_binary=page,
        protected_mask=protected,
        scale=1.0,
    )
    authorization = ledger.authorize_restoration(line, intervals=((40.0, 80.0),))
    result = ledger.reconcile(
        main_candidates=(),
        accepted_main=(),
        restoration_candidates=(line,),
        accepted_restoration_authorizations=(authorization,),
        ownership_masks=_masks(page),
    )
    parents = _extension(result)["parents"]
    accepted = [p for p in parents if p["acceptance_status"] == "ALREADY_ACCEPTED"]
    fresh = [p for p in parents if p["acceptance_status"] == "FRESH_PROPOSAL"]
    assert len(accepted) == 1
    assert accepted[0]["original_geometry"]["start_px"] == pytest.approx([60.0, 48.0])
    assert accepted[0]["original_geometry"]["end_px"] == pytest.approx([100.0, 48.0])
    assert fresh
    other = line.copy(source_ids=("OTHER",))
    with pytest.raises(AssertionError, match="authorization"):
        ledger.reconcile(
            main_candidates=(),
            accepted_main=(),
            restoration_candidates=(other,),
            accepted_restoration_authorizations=(authorization,),
            ownership_masks=_masks(page),
        )


def test_f05_f08_acceptance_rejects_stale_source_scope() -> None:
    page, line, _result_unused = _result()
    first = ReconciliationLedger(
        source_gray=page, source_binary=page, protected_mask=None, scale=1.0
    )
    authorization = first.authorize_restoration(line)
    changed = page.copy()
    changed[0, 0] ^= 1
    second = ReconciliationLedger(
        source_gray=changed, source_binary=page, protected_mask=None, scale=1.0
    )
    with pytest.raises(AssertionError, match="source scope"):
        second.reconcile(
            main_candidates=(),
            accepted_main=(),
            restoration_candidates=(line,),
            accepted_restoration_authorizations=(authorization,),
            ownership_masks=_masks(page),
        )


@pytest.mark.parametrize("with_audit_history", (False, True))
def test_new_explicit_authority_hole_compatibility_control(
    with_audit_history: bool,
) -> None:
    """New explicit-authority compatibility control; not the historical fixture."""

    page = np.full((220, 240), 255, dtype=np.uint8)
    main = LineSegment(20.0, 120.0, 100.0, 120.0, source_ids=("MAIN",))
    restoration = LineSegment(
        80.0,
        120.0,
        180.0,
        120.0,
        source_ids=("RESTORE",),
        history=(LEGACY_ACCEPTED_HISTORY,) if with_audit_history else (),
    )
    cv2.line(page, (20, 120), (114, 120), 0, 1, cv2.LINE_8)
    cv2.line(page, (121, 120), (180, 120), 0, 1, cv2.LINE_8)
    ledger = ReconciliationLedger(
        source_gray=page, source_binary=page, protected_mask=None, scale=1.0
    )
    authorization = ledger.authorize_restoration(
        restoration, authority_source="TRUSTED_LEGACY_ACCEPTED_RECORD_V1"
    )
    result = ledger.reconcile(
        main_candidates=(main,),
        accepted_main=(main,),
        restoration_candidates=(restoration,),
        accepted_restoration_authorizations=(authorization,),
        ownership_masks=_masks(page),
    )
    restored = [line for line in result.lines if line.source_ids == ("RESTORE",)]
    assert len(restored) == 2
    assert restored[0].x1 >= 100.0
    assert restored[0].x2 < restored[1].x1
    assert restored[-1].x2 == pytest.approx(180.0)
    accepted = [
        parent
        for parent in _extension(result)["parents"]
        if parent["acceptance_status"] == "ALREADY_ACCEPTED"
    ]
    assert accepted
    assert any(
        cell["disposition"] == "SOURCE_VISIBLE_GAP"
        for parent in accepted
        for cell in parent["partition"]
    )
    assert any(
        parent["acceptance_status"] == "ALREADY_ACCEPTED"
        for parent in _extension(result)["parents"]
    )


def test_new_explicit_authority_hole_history_variants_share_semantic_identity(
) -> None:
    without_history = LineSegment(
        80.0, 120.0, 180.0, 120.0, source_ids=("RESTORE",)
    )
    with_history = without_history.copy(history=(LEGACY_ACCEPTED_HISTORY,))
    assert reconciliation._acceptance_identity_key(with_history) == (
        reconciliation._acceptance_identity_key(without_history)
    )
