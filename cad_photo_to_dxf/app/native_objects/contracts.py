"""Coordinates and required text-to-geometry fields; no silent empty fallback."""

from pathlib import Path
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import numpy as np

COORDINATES = "source_pixels_top_left"
TOLERANCES = {
    "line_perpendicular_px": 2.0,
    "line_endpoint_px": 3.0,
    "arc_radial_px": 2.5,
    "max_unexplained_line_gap_px": 5.0,
    "max_direction_adjustment_deg": 0.5,
    "opening_minimum_preserved_px": 6.0,
}


def plain(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(type(o).__name__)


def _replace_checkpoint(source, destination):
    """Retain atomic checkpoint writes across a bounded Windows sharing delay.

    The writer has closed and synced its own temporary handle. A different
    reader can still deny replacement on Windows; its identity is not assumed.
    Persistent permissions and all other failures remain failures, with the
    previous checkpoint intact. Never delete the destination before replacing.
    """
    started = time.monotonic()
    deadline = started + 2.0
    attempts = 0
    prior_error = None
    while True:
        if prior_error is not None:
            from .execution import check_cancel, current_context

            check_cancel("CHECKPOINT_ATOMIC_REPLACE")
            context = current_context()
            now = time.monotonic()
            if now >= deadline:
                if context is not None:
                    context.event(
                        "checkpoint_replace_retry_exhausted",
                        path=str(destination), replace_attempts=attempts,
                        winerror=prior_error.winerror, elapsed_seconds=now - started,
                        previous_checkpoint_preserved=True,
                    )
                raise prior_error
        attempts += 1
        try:
            os.replace(source, destination)
        except OSError as exc:
            if sys.platform != "win32" or getattr(exc, "winerror", None) not in {5, 32, 33}:
                raise
            from .execution import check_cancel, current_context

            prior_error = exc
            now = time.monotonic()
            delay = min(0.05, max(0.0, deadline - now))
            context = current_context()
            if context is not None:
                context.event(
                    "checkpoint_replace_retry", path=str(destination),
                    replace_attempts=attempts, winerror=exc.winerror,
                    elapsed_seconds=now - started, delay_seconds=delay,
                    previous_checkpoint_preserved=True,
                )
            check_cancel("CHECKPOINT_ATOMIC_REPLACE")
            if delay:
                time.sleep(delay)
        else:
            if prior_error is not None and context is not None:
                context.event(
                    "checkpoint_replace_recovered", path=str(destination),
                    replace_attempts=attempts,
                    elapsed_seconds=time.monotonic() - started,
                    atomic_replacement=True,
                )
            return


def save_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Serialize before touching the checkpoint. A killed/cancelled worker may
    # leave an uncommitted temporary file, never a half-valid stage manifest.
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=plain)
        + "\n"
    )
    name = None
    failure = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=p.parent,
            prefix=p.name + ".pending-",
            delete=False,
        ) as f:
            name = f.name
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _replace_checkpoint(name, p)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if name is not None and os.path.exists(name):
            try:
                os.unlink(name)
            except OSError as cleanup_error:
                if failure is None:
                    raise
                # A locked temporary file must not hide the failed commit or
                # cancellation. Leave that owned file for recovery inspection.
                failure.add_note(
                    f"Owned checkpoint temporary retained: {name}; cleanup failed: {cleanup_error}"
                )


def stable_id(prefix, geometry):
    return (
        prefix
        + "-"
        + hashlib.sha256(
            json.dumps(geometry, sort_keys=True, default=plain).encode()
        ).hexdigest()[:12]
    )


def validate_text_regions(data, shape, roi):
    if not isinstance(data, dict):
        raise ValueError("TEXT_REGION_CONTRACT_MISSING")
    if data.get("coordinate_system") != COORDINATES:
        raise ValueError("TEXT_REGION_COORDINATE_SYSTEM_MISMATCH")
    if list(data.get("source_size_px", [])) != [shape[1], shape[0]]:
        raise ValueError("TEXT_REGION_SOURCE_SIZE_MISMATCH")
    if list(data.get("roi_xyxy_px", [])) != list(roi):
        raise ValueError("TEXT_REGION_ROI_MISMATCH")
    if "regions" not in data or not isinstance(data["regions"], list):
        raise ValueError("TEXT_REGIONS_LIST_MISSING")
    boxes = []
    ids = set()
    group_roles = {}
    for group in data.get("groups", []):
        for rid in group.get("region_ids", []):
            group_roles.setdefault(rid, []).append({
                "group_id": group.get("id"),
                "complete": bool(group.get("complete")),
                "source_review_accepted": bool(group.get("source_review", {}).get("accepted")),
            })
    for row in data["regions"]:
        if "bbox_xyxy_px" not in row:
            raise ValueError("TEXT_REGION_BBOX_XYXY_PX_MISSING:" + str(row.get("id")))
        box = row["bbox_xyxy_px"]
        if len(box) != 4 or not all(math.isfinite(float(x)) for x in box):
            raise ValueError("TEXT_REGION_BBOX_INVALID")
        x0, y0, x1, y1 = map(float, box)
        if not (0 <= x0 < x1 <= shape[1] and 0 <= y0 < y1 <= shape[0]):
            raise ValueError("TEXT_REGION_BBOX_OUTSIDE_SOURCE")
        oid = row.get("id")
        if not oid or oid in ids:
            raise ValueError("TEXT_REGION_ID_MISSING_OR_DUPLICATE")
        ids.add(oid)
        support_role = {
            "mask_role": "COMPACT_CANDIDATE_INK_NOT_EXCLUSIVE_GLYPH_OWNERSHIP",
            "region_complete": bool(row.get("complete")),
            "region_accepted": bool(row.get("accepted")),
            "source_review_accepted": bool(row.get("source_review", {}).get("accepted")),
            "groups": group_roles.get(oid, []),
            "shared_text_graphic_source_permitted_with_evidence": True,
        }
        # A region is a text localization, not an eraser. Line classification
        # receives the narrow word boxes wherever available, never whole crops.
        words = row.get("words", [])
        if words:
            for w in words:
                b = w.get("bbox_xyxy_px")
                if b is None or len(b) != 4:
                    raise ValueError("TEXT_WORD_BBOX_MISSING:" + oid)
                if not (
                    x0 - 1 <= b[0] < b[2] <= x1 + 1 and y0 - 1 <= b[1] < b[3] <= y1 + 1
                ):
                    raise ValueError("TEXT_WORD_NOT_IN_REGION:" + oid)
                boxes.append(
                    {
                        "region_id": oid,
                        "bbox_xyxy_px": list(map(float, b)),
                        "text": w.get("text"),
                        "confirmed": bool(row.get("accepted", False)),
                        "support_role": support_role,
                        "glyph_source_runs": row.get("compact_source_ink_mask", {}).get(
                            "runs_y_x0_x1"
                        ),
                    }
                )
        else:
            boxes.append(
                {
                    "region_id": oid,
                    "bbox_xyxy_px": list(map(float, box)),
                    "text": row.get("text"),
                    "confirmed": False,
                    "support_role": support_role,
                    "glyph_source_runs": row.get("compact_source_ink_mask", {}).get(
                        "runs_y_x0_x1"
                    ),
                }
            )
    return boxes
