"""Reconcile detector endpoint excess with a measured, closed source frame.

Only already-owned frame LINE remainders are eligible. A short length alone
never authorizes removal. Every actual ink pixel supporting the remainder
must be supported by the complete frame at the unchanged source tolerance,
and every such connected component must extend along a frame side. The
source pixels, frame vertices and numeric text are never changed.
"""

from __future__ import annotations
import copy
import hashlib
import math
import cv2
import numpy as np
from .contracts import TOLERANCES


def _distance(points, first, last):
    vector = last - first
    length2 = float(vector @ vector)
    if length2 <= 0:
        raise ValueError("INVALID_FRAME_SEGMENT")
    t = np.clip(((points - first) @ vector) / length2, 0.0, 1.0)
    return np.linalg.norm(points - (first + t[:, None] * vector), axis=1)


def reconcile_frame_endpoints(result, image, roi):
    resolved = copy.deepcopy(result)
    tolerance = float(TOLERANCES["line_perpendicular_px"])
    end_bound = float(TOLERANCES["line_endpoint_px"])
    events = []
    for obj in resolved["objects"]:
        if obj["kind"] != "ROOM_LABEL":
            continue
        geometry = obj["geometry"]
        corners = np.asarray(geometry["frame_points"], dtype=float)
        members = geometry.get("frame_source_remainders", [])
        if not members:
            continue
        pad = int(math.ceil(end_bound + tolerance + 4))
        lo = np.floor(corners.min(axis=0)).astype(int) - pad
        hi = np.ceil(corners.max(axis=0)).astype(int) + pad + 1
        lo = np.maximum(lo, np.asarray(roi[:2], dtype=int))
        hi = np.minimum(hi, np.asarray(roi[2:], dtype=int))
        x0, y0 = map(int, lo)
        x1, y1 = map(int, hi)
        crop = np.asarray(image[y0:y1, x0:x1], dtype=np.uint8)
        black = crop < 128
        _, labels = cv2.connectedComponents(black.astype(np.uint8), connectivity=8)
        yy, xx = np.nonzero(black)
        points = np.column_stack((xx + x0, yy + y0)).astype(float)
        component_ids = labels[yy, xx]
        frame_distance = np.min(
            [_distance(points, corners[i], corners[(i + 1) % 4]) for i in range(4)],
            axis=0,
        )
        corner_distance = np.min(
            np.linalg.norm(points[:, None, :] - corners[None, :, :], axis=2), axis=1
        )
        side_interior = (frame_distance <= tolerance) & (
            corner_distance > end_bound + tolerance
        )
        side_components = set(map(int, component_ids[side_interior]))
        kept, absorbed = [], []
        for member in members:
            a = np.asarray(member["geometry"]["start"], dtype=float)
            b = np.asarray(member["geometry"]["end"], dtype=float)
            length = float(np.linalg.norm(b - a))
            support = _distance(points, a, b) <= tolerance
            support_components = set(map(int, component_ids[support]))
            unique = support & (frame_distance > tolerance)
            nearest_corner = np.min(
                np.linalg.norm(
                    np.array([a, b])[:, None, :] - corners[None, :, :], axis=2
                ),
                axis=1,
            )
            checks = {
                "previously_owned_frame_endpoint": member.get("role")
                == "retained_original_frame_endpoint",
                "parent_is_consumed_frame_line": member.get("parent_line_id")
                in obj["source_evidence"]["consumed_frame_line_ids"],
                "not_marked_shared_or_foreign": not any(
                    member.get(k)
                    for k in (
                        "shared_source_ids",
                        "foreign_source_ids",
                        "protected_source_ids",
                        "ambiguous_ownership",
                    )
                ),
                "source_neighborhood_not_clipped_by_ROI": bool(
                    np.all(corners.min(axis=0) - pad >= np.asarray(roi[:2]))
                    and np.all(corners.max(axis=0) + pad < np.asarray(roi[2:]))
                ),
                "within_original_endpoint_bound": length <= end_bound,
                "both_endpoints_local_to_source_corner": bool(
                    np.all(nearest_corner <= end_bound + tolerance)
                ),
                "has_actual_source_ink": bool(np.any(support)),
                "no_ink_supported_only_by_tail": not bool(np.any(unique)),
                "all_support_components_extend_along_frame": bool(support_components)
                and support_components <= side_components,
            }
            accepted = all(checks.values())
            event = {
                "object_id": obj["id"],
                "member_id": member["id"],
                "parent_line_id": member.get("parent_line_id"),
                "original_geometry": member["geometry"],
                "source_interval_px": member["source_interval_px"],
                "length_px": length,
                "checks": checks,
                "decision": "REPLACED_BY_SOURCE_SUPPORTED_CLOSED_FRAME"
                if accepted
                else "RETAIN_EXPLICIT_ENDPOINT",
                "source_crop_xyxy_px": [x0, y0, x1, y1],
                "source_crop_array_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
                "source_support_pixels": points[support].tolist(),
                "source_pixels_not_supported_by_frame": points[unique].tolist(),
                "source_component_ids": sorted(support_components),
                "frame_support_distance_max_px": float(frame_distance[support].max())
                if np.any(support)
                else None,
                "source_tolerance_px_unchanged": tolerance,
                "source_pixels_removed": 0,
                "frame_vertices_changed": False,
                "meaning": "Geometric source-support equivalence, not engineering stroke identity.",
            }
            events.append(event)
            (absorbed if accepted else kept).append(member)
        geometry["frame_source_remainders"] = kept
        obj["source_evidence"]["endpoint_source_reconciliation"] = {
            "version": "source-supported-frame-endpoint-replacement-v1",
            "original_endpoint_members": members,
            "replaced_member_ids": [m["id"] for m in absorbed],
            "retained_member_ids": [m["id"] for m in kept],
            "frame_geometry_unchanged": True,
            "text_unchanged": True,
        }
        obj["source_evidence"]["retained_endpoint_child_ids"] = [m["id"] for m in kept]
        obj["expected_native_block_member_counts"] = {
            "closed_LWPOLYLINE": 1,
            "TEXT": 1,
            "retained_LINE": len(kept),
            "total": 2 + len(kept),
        }
        obj["editing_scope"] = (
            "complete measured frame and unchanged numeric TEXT, with only unsupported endpoint differences retained"
        )
    resolved["endpoint_source_reconciliation"] = {
        "version": "source-supported-frame-endpoint-replacement-v1",
        "events": events,
        "replaced_endpoint_entity_count": sum(
            e["decision"].startswith("REPLACED") for e in events
        ),
        "source_mask_modified": False,
        "tolerances_changed": False,
        "original_interval_partition_retained_as_history": True,
        "unrelated_lines_and_unknown_objects_modified": False,
    }
    resolved["counts"]["retained_endpoint_LINE_members_in_ROOM_blocks"] = sum(
        len(o["geometry"].get("frame_source_remainders", []))
        for o in resolved["objects"]
    )
    resolved["counts"]["expected_ROOM_native_member_count"] = sum(
        o.get("expected_native_block_member_counts", {}).get("total", 0)
        for o in resolved["objects"]
    )
    return resolved
