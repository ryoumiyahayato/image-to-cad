"""Source conservation assertions independent of the experiment's heuristics.

This checks explicit ownership and retained masks rather than accepting the
algorithm's accounting/status boolean. Candidate geometry is never considered
production adoption merely because this synthetic oracle passes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np

from independent_fixtures import Fixture


@dataclass
class Observation:
    retained: np.ndarray
    owned_masks: list[np.ndarray]
    # Full output ink at input resolution, if the producer actually renders it.
    rendered_ink: np.ndarray | None = None
    rendered_parts: list[np.ndarray] | None = None
    geometric_contact: str = "OBSERVED_ONLY"
    object_identity: str = "NOT_PROVEN"
    electrical_connectivity: str = "NOT_INFERRED"


def masks_from_runs(records: Iterable[Mapping], shape: tuple[int, int],
                    key="source_runs_y_x0_x1") -> list[np.ndarray]:
    masks = []
    for record in records:
        mask = np.zeros(shape, bool)
        for y, x0, x1 in record[key]:
            assert all(isinstance(v, (int, np.integer)) for v in (y, x0, x1)), "noninteger source run"
            assert 0 <= y < shape[0] and 0 <= x0 < x1 <= shape[1], "source run outside original crop"
            assert not mask[y, x0:x1].any(), "duplicate run inside a source record"
            mask[y, x0:x1] = True
        masks.append(mask)
    return masks


def inspect(fixture: Fixture, observed: Observation) -> dict:
    """Return concrete failure evidence; do not trust the producer's verdict."""
    source = fixture.source
    failures = []
    retained = np.asarray(observed.retained, bool)
    if retained.shape != source.shape:
        return {"pass": False, "failures": ["retained_shape_mismatch"]}
    if np.any(retained & ~source):
        failures.append("retained_source_invented_background")
    owner_count = np.zeros(source.shape, np.uint16)
    for idx, owned in enumerate(observed.owned_masks):
        owned = np.asarray(owned, bool)
        if owned.shape != source.shape:
            failures.append(f"owner_{idx}_shape_mismatch")
            continue
        if not owned.any():
            failures.append(f"owner_{idx}_empty")
        if np.any(owned & ~source):
            failures.append(f"owner_{idx}_claims_background")
        if np.any(owned & fixture.protected):
            failures.append(f"owner_{idx}_claims_protected")
        if np.any(owned & fixture.must_retain):
            failures.append(f"owner_{idx}_claims_required_retained")
        owner_count += owned
    if np.any(owner_count > 1):
        failures.append("duplicate_source_ownership")
    claimed = owner_count > 0
    if np.any(claimed & retained):
        failures.append("retired_and_retained_ownership_overlap")
    if np.any(source & ~(retained | claimed)):
        failures.append("original_source_pixels_unaccounted")
    if np.any(fixture.must_retain & ~retained):
        failures.append("required_source_deleted")
    if fixture.expectation == "whole_source_rejection" and observed.owned_masks:
        failures.append("source_that_must_reject_has_owner")
    if observed.rendered_ink is not None:
        rendered = np.asarray(observed.rendered_ink, bool)
        if rendered.shape != source.shape:
            failures.append("rendered_shape_mismatch")
        else:
            if np.any(rendered & fixture.white_fence):
                failures.append("observed_white_fence_bridged")
            if np.any(source & ~rendered):
                failures.append("observed_black_centers_missing")
            if np.any(rendered & ~source):
                failures.append("observed_white_centers_covered")
    if observed.rendered_parts is not None:
        if len(observed.rendered_parts) != len(observed.owned_masks):
            failures.append("rendered_part_ownership_count_mismatch")
        else:
            for idx, (owned, rendered) in enumerate(zip(observed.owned_masks, observed.rendered_parts)):
                if rendered.shape != source.shape:
                    failures.append(f"rendered_part_{idx}_shape_mismatch")
                elif np.any(owned & ~rendered):
                    failures.append(f"rendered_part_{idx}_does_not_cover_own_source")
    if observed.object_identity not in ("NOT_PROVEN", "UNKNOWN"):
        failures.append("object_identity_inferred_from_synthetic_pixels")
    if observed.electrical_connectivity not in ("NOT_INFERRED", "UNKNOWN"):
        failures.append("electrical_connectivity_inferred_from_synthetic_pixels")
    return {"pass": not failures, "failures": failures,
            "source_pixels": int(source.sum()), "retained_pixels": int(retained.sum()),
            "owned_pixels": int(claimed.sum()), "candidate_records": len(observed.owned_masks),
            "required_retained_pixels": int(fixture.must_retain.sum()),
            "white_fence_pixels": int(fixture.white_fence.sum()),
            "rendered_gap_checked": observed.rendered_ink is not None}
