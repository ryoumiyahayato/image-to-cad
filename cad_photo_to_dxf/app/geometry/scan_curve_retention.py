"""Retain complete isolated scan rings clipped by a neighbouring LINE claim.

No fitting, closing, endpoint movement or source-mask editing. A qualified
component keeps its two original printed boundaries as complete polylines.
"""

from dataclasses import replace
from time import perf_counter

import cv2
import numpy as np

POLICY = "isolated-scan-curve-source-v1"
RECORD_KEY = "closed_scan_curve_records"
MAX_PAGE_PIXELS = 12_000_000
MAX_CHECKS = 64
MAX_TOTAL_PIXELS = 262144
MAX_POINTS = 256


def _ring_paths(mask):
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or len(contours) != 2 or sorted(hierarchy[0, :, 3]) != [-1, 0]:
        return None
    for contour in contours:
        approx = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        if (
            not 8 <= len(approx) <= 16
            or not cv2.isContourConvex(approx)
            or len(contour) > MAX_POINTS
        ):
            return None
    return contours


def _line_bounds(lines):
    return np.array(
        [
            [
                min(line.x1, line.x2),
                min(line.y1, line.y2),
                max(line.x1, line.x2),
                max(line.y1, line.y2),
            ]
            for line in lines
        ],
        dtype=float,
    ).reshape(-1, 4)


def _centres_enter(box, bounds):
    x, y, w, h = box
    return (
        (bounds[:, 0] <= x + w)
        & (bounds[:, 2] >= x - 1)
        & (bounds[:, 1] <= y + h)
        & (bounds[:, 3] >= y - 1)
    )


def retain_closed_scan_curves(binary, gray, ownership, lines, *, protected_mask=None):
    """Return restricted ownership and bounded, source-only closure proofs."""
    started = perf_counter()
    review = dict(
        policy=POLICY, checks=0, local_pixels=0, proofs=[], rejected=[], label_bytes=0
    )
    if binary.size > MAX_PAGE_PIXELS or not np.any(ownership.line):
        review.update(
            status="SKIPPED_PAGE_BUDGET_OR_NO_LINE_CLAIMS",
            seconds=perf_counter() - started,
        )
        return ownership, review
    ink = (binary < 128).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    review["label_bytes"] = labels.nbytes
    candidates = np.unique(labels[ownership.line > 0])
    bounds = _line_bounds(lines)
    line_owned, graphic_owned = None, None
    for label in candidates:
        if label == 0:
            continue
        x, y, w, h, area = map(int, stats[label])
        if (
            min(w, h) < 20
            or max(w, h) > 128
            or not 0.7 < w / h < 1.4
            or not 0.04 < area / (w * h) < 0.35
        ):
            continue
        if (
            review["checks"] >= MAX_CHECKS
            or review["local_pixels"] + (w + 6) * (h + 6) > MAX_TOTAL_PIXELS
        ):
            review["rejected"].append(
                dict(box=[x, y, w, h], reason="CURVE_PROOF_BUDGET")
            )
            continue
        review["checks"] += 1
        review["local_pixels"] += (w + 6) * (h + 6)
        reason = None
        if x < 3 or y < 3 or x + w + 3 > binary.shape[1] or y + h + 3 > binary.shape[0]:
            reason = "PAGE_EDGE_COMPONENT"
        if reason is None:
            target = labels[y - 3 : y + h + 3, x - 3 : x + w + 3] == label
            local_ink = ink[y - 3 : y + h + 3, x - 3 : x + w + 3]
            # Two paper cells separate this whole source member from other ink.
            near = cv2.dilate(target.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            if np.any((local_ink[1:-1, 1:-1] > 0) & ~target[1:-1, 1:-1]):
                reason = "OTHER_SOURCE_MEMBER_OR_CONTACT"
            elif _ring_paths(target.astype(np.uint8)) is None:
                reason = "NO_COMPLETE_SIMPLE_CURVED_RING"
            elif (
                cv2.distanceTransform(target.astype(np.uint8), cv2.DIST_L2, 5).max()
                > 2.0
            ):
                reason = "BROAD_OR_VARIABLE_FILL"
            elif np.any(_centres_enter((x, y, w, h), bounds)):
                reason = "CAD_LINE_OR_ENDPOINT_ENTERS_CURVE_REGION"
            elif any(
                np.any(target & (m[y - 3 : y + h + 3, x - 3 : x + w + 3] > 0))
                for m in (
                    ownership.text,
                    ownership.logo,
                    ownership.signature,
                    ownership.residual,
                )
            ):
                reason = "OTHER_SOURCE_OWNER"
            elif protected_mask is not None and np.any(
                near & (protected_mask[y - 3 : y + h + 3, x - 3 : x + w + 3] > 0)
            ):
                reason = "TEXT_OR_GRAPHIC_GUARD"
        gray_checks = []
        if reason is None:
            patch = gray[y - 3 : y + h + 3, x - 3 : x + w + 3]
            for cut in (128, 160, 192):
                n, ls, st, _ = cv2.connectedComponentsWithStats(
                    (patch < cut).astype(np.uint8), 8
                )
                ids, counts = np.unique(ls[target], return_counts=True)
                choices = [(int(c), int(i)) for i, c in zip(ids, counts) if i]
                if not choices:
                    reason = "GRAY_CLOSURE_UNRELIABLE"
                    break
                member = ls == max(choices)[1]
                _, hi = cv2.findContours(
                    member.astype(np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
                )
                holes = 0 if hi is None else int((hi[0, :, 3] >= 0).sum())
                edge = bool(
                    member[0].any()
                    or member[-1].any()
                    or member[:, 0].any()
                    or member[:, -1].any()
                )
                gray_checks.append(
                    dict(cut=cut, holes=holes, touches_context_edge=edge)
                )
                if holes != 1 or edge:
                    reason = "GRAY_CLOSURE_OR_ISOLATION_UNRELIABLE"
                    break
        if reason:
            review["rejected"].append(dict(box=[x, y, w, h], reason=reason))
            continue
        component = labels[y : y + h, x : x + w] == label
        removed = component & (ownership.line[y : y + h, x : x + w] > 0)
        if not np.any(removed):
            continue
        if line_owned is None:
            line_owned, graphic_owned = ownership.line.copy(), ownership.graphic.copy()
        line_owned[y : y + h, x : x + w][component] = 0
        graphic_owned[y : y + h, x : x + w][component] = 255
        review["proofs"].append(
            dict(
                policy=POLICY,
                source_id=f"SCAN-CLOSED-CURVE:{x}:{y}:{w}:{h}",
                source_box=[x, y, w, h],
                source_pixels=area,
                released_line_pixels=int(removed.sum()),
                gray_closure=gray_checks,
                endpoint_duty="CLOSED_SOURCE_WITHOUT_EXTERNAL_CONTACTS",
                geometry="ORIGINAL_OUTER_AND_INNER_RASTER_BOUNDARIES; no circle fit or gap filling",
            )
        )
    updated = (
        ownership
        if line_owned is None
        else replace(ownership, line=line_owned, graphic=graphic_owned)
    )
    updated.assert_valid()
    review.update(
        status="RETAINED" if review["proofs"] else "NO_QUALIFIED_SOURCE",
        seconds=perf_counter() - started,
    )
    return updated, review


def bind_closed_curve_contours(paths, binary, source_binary, proofs):
    """Bind only intact final members; Artifact and other owners are not waived."""
    from app.geometry.raster_trace import trace_binary

    records = []
    actual = {tuple(p.points): i for i, p in enumerate(paths)}
    for proof in proofs:
        x, y, w, h = proof["source_box"]
        mask = source_binary[y : y + h, x : x + w] < 128
        if not np.array_equal(binary[y : y + h, x : x + w] < 128, mask):
            continue
        local = trace_binary(np.where(mask, 0, 255).astype(np.uint8))
        if len(local) != 2:
            continue
        members = []
        for p in local:
            points = tuple((a + x, b + y) for a, b in p.points)
            index = actual.get(points)
            if (
                index is None
                or len(points) > MAX_POINTS
                or paths[index].depth != p.depth
            ):
                break
            members.append(dict(index=index, points=points, depth=p.depth))
        if len(members) == 2:
            records.append(dict(proof=proof, members=members))
    return records


def validate_closed_curve_records(structure):
    """Small source patches and exact final members, never coordinate matching."""
    from app.geometry.raster_trace import trace_binary

    records = structure.provenance.get("stroke_presentation", {}).get(RECORD_KEY, ())
    if not records:
        return
    if len(records) > MAX_CHECKS or structure.preview_binary is None:
        raise ValueError("Invalid closed scan curve record count/source")
    used = set()
    bounds = _line_bounds(structure.straight_lines)
    for record in records:
        p = record["proof"]
        x, y, w, h = p["source_box"]
        if (
            any(type(v) is not int for v in (x, y, w, h))
            or p["policy"] != POLICY
            or min(w, h) < 20
            or max(w, h) > 128
            or x < 3
            or y < 3
            or x + w + 3 > structure.source_size_px[0]
            or y + h + 3 > structure.source_size_px[1]
        ):
            raise ValueError("Invalid closed scan curve source region")
        if (
            p["source_id"] != f"SCAN-CLOSED-CURVE:{x}:{y}:{w}:{h}"
            or p["endpoint_duty"] != "CLOSED_SOURCE_WITHOUT_EXTERNAL_CONTACTS"
            or tuple(
                (g["cut"], g["holes"], g["touches_context_edge"])
                for g in p["gray_closure"]
            )
            != ((128, 1, False), (160, 1, False), (192, 1, False))
        ):
            raise ValueError("Closed scan curve needs complete source evidence")
        local = structure.preview_binary[y : y + h, x : x + w]
        context = structure.preview_binary[y - 2 : y + h + 2, x - 2 : x + w + 2]
        if (
            np.any(context[:2] < 128)
            or np.any(context[-2:] < 128)
            or np.any(context[:, :2] < 128)
            or np.any(context[:, -2:] < 128)
            or cv2.distanceTransform(
                np.pad((local < 128).astype(np.uint8), 1), cv2.DIST_L2, 5
            ).max()
            > 2
        ):
            raise ValueError("Closed scan curve has external contacts or broad fill")
        for mask in (
            structure.editable_text_source_mask,
            structure.source_text_outline_mask,
            structure.uncertain_text_outline_mask,
        ):
            if mask is not None and np.any(
                (mask[y : y + h, x : x + w] > 0) & (local < 128)
            ):
                raise ValueError("Closed scan curve cannot replace text source")
        expected = trace_binary(local)
        if (
            len(expected) != 2
            or _ring_paths((local < 128).astype(np.uint8)) is None
            or int((local < 128).sum()) != p["source_pixels"]
            or not 0 < p["released_line_pixels"] <= p["source_pixels"]
            or np.any(_centres_enter((x, y, w, h), bounds))
            or not np.array_equal(local, structure.contour_binary[y : y + h, x : x + w])
        ):
            raise ValueError("Closed scan curve source/topology mismatch")
        if len(record["members"]) != 2:
            raise ValueError("Closed scan curve must retain both boundaries")
        for member, path in zip(record["members"], expected):
            index = member["index"]
            points = tuple((a + x, b + y) for a, b in path.points)
            if (
                index in used
                or not 0 <= index < len(structure.contours)
                or len(points) > MAX_POINTS
                or tuple(tuple(q) for q in member["points"]) != points
                or tuple(structure.contours[index].points) != points
                or member["depth"] != path.depth
                or structure.contours[index].depth != path.depth
            ):
                raise ValueError("Closed scan curve must bind complete final contours")
            used.add(index)
