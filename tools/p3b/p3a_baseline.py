"""Read-only synthetic replay of frozen P3A; returned geometry is discarded.

Real decisions stay tied to captured production provenance. Cropped-context
replays are never presented as production decisions. No CAD is written.
"""

import sys

import cv2
import numpy as np

from common import ROOT


def measure(gray, candidates, cad, scale, affine, dpi):
    sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))
    from app.geometry.line_detect import LineSegment
    from app.geometry.source_presentation import (
        stroke_profile,
        lineweight_record,
        stroke_presentation,
    )

    inputs = [LineSegment(*coords, source_ids=(gid,)) for gid, coords, _ in candidates]
    protection = np.zeros_like(gray)
    for primitive in cad["primitives"]:
        if primitive["type"] == "LINE" and not primitive["id"].startswith("rail-"):
            points = np.array(primitive["xy_mm"]).reshape(2, 2) * scale
            points = np.c_[points, np.ones(2)] @ affine.T
            cv2.line(
                protection,
                tuple(np.rint(points[0]).astype(int)),
                tuple(np.rint(points[1]).astype(int)),
                255,
                3,
            )
            inputs.append(LineSegment(*points.ravel(), source_ids=(primitive["id"],)))
    profiles = []
    for line in inputs[: len(candidates)]:
        profile = stroke_profile(gray, line)
        profiles.append(
            {
                "geometry_id": line.source_ids[0],
                "profile": profile,
                "lineweight": lineweight_record(profile, dpi) if profile else None,
            }
        )
    _, ledger = stroke_presentation(gray, inputs, dpi, protected_mask=protection)
    targeted = any(
        {d["kept_input"], d["removed_input"]} == {0, 1}
        for d in ledger["false_parallel_decisions"]
    )
    return (
        profiles,
        "MERGE_PROPOSED_OFFLINE"
        if len(candidates) == 2 and targeted
        else "PRESERVE_OFFLINE",
        ledger["false_parallel_decisions"],
    )
