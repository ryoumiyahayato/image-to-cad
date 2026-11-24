"""Bounded recovery of complete single source rows as editable TEXT.

Existing observations locate rows; their strings never become recognizer hints.
Complete source components define a finite row and retain interior punctuation.
Only a separately recorded recognition view may omit proved external graphics.
The immutable original and every raw recognizer input/output remain replayable.
"""

from __future__ import annotations

import copy
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath

import cv2
import numpy as np

from . import independent_recognizer as independent
from . import source_glyph_equivalence as glyph_equivalence
from . import text_regions as base
from . import circle_character_recognition as character
from .circle_character_recognition import (
    _model_integrity,
    _raw_tsv_integrity,
    _tesseract_confident,
)
from .contracts import save_json, validate_text_regions
from .execution import check_cancel


POLICY = {
    "version": "complete-source-single-line-derived-views-v6-terminal-source",
    "source_threshold": 192,
    "minimum_full_height_components": 3,
    "glyph_height_px": [8, 70],
    "glyph_height_ratio": [0.60, 1.45],
    "glyph_width_height_maximum": 1.70,
    "baseline_tolerance_glyph_heights": 0.28,
    "row_join_gap_glyph_heights": 2.0,
    "maximum_row_width_px": 750,
    "maximum_source_components": 64,
    "terminal_punctuation_search_glyph_heights": 0.75,
    "source_context_glyph_heights": 2.0,
    "minimum_external_white_columns": 2,
    "maximum_labels": 48,
    "Tesseract_views": [
        {"scale": 2, "padding": 16, "psm": 7},
        {"scale": 2, "padding": 16, "psm": 13},
    ],
    "PP_OCR_views": [{"scale": 1, "padding": 4}, {"scale": 1, "padding": 0}],
    "maximum_views_per_engine": 2,
    "Tesseract_word_confidence": 85.0,
    "Tesseract_numeric_confidence": 95.0,
    "PP_OCR_mean_confidence": 0.98,
    "PP_OCR_minimum_character_confidence": 0.95,
    "source_bbox_coverage_tolerance_px": 1.0,
    "minimum_source_word_space_glyph_heights": 0.50,
    "canonical_quote_requires_two_original_upper_strokes": True,
    "canonical_dash_requires_one_original_horizontal_stroke": True,
    "model_whitespace_confidence_replaced_by_source_gap_check": True,
    "fragment_maximum_white_gap_px": 2,
    "external_edge_band_fraction": 0.28,
    "old_complete_and_multiline_groups_immutable": True,
    "expected_answers_or_dictionaries": False,
    "original_source_pixels_modified": False,
    "normalization_only_for_recognition": True,
    "new_geometry_ownership_must_be_rechecked": True,
    "contact_transcription_rule": "complete_original_row_and_strict_model_characters_with_raw_Tesseract_literal_corroboration",
    "contact_Tesseract_word_score": "recorded_advisory_aggregate_score_not_a_character_veto",
    "contact_repeated_raw_dash_tokens": "canonicalize_only_one_observed_continuous_midline_source_stroke",
    "complete_row_Tesseract_word_score": "recorded_advisory_aggregate_score_not_a_character_veto",
    "complete_row_transcription_rule": "complete_original_row_and_strict_model_characters_with_raw_Tesseract_literal_corroboration",
    "flat_source_dash": {
        "maximum_centerline_slope": 0.125,
        "maximum_centerline_end_change_source_px": 1.0,
        "maximum_column_center_residual_source_px": 1.0,
        "every_column_supports_one_common_straight_quantized_spine": True,
        "requires_one_continuous_original_component": True,
        "true_wave_or_two_source_marks_not_collapsed": True,
    },
    "raw_character_conflicts": glyph_equivalence.POLICY,
    "known_raw_views": "replay_every_available_finite_plan_view_before_final_decision_no_new_call_after_provisional_acceptance",
    "observed_alphanumeric_suffix": "a_narrower_prefix_cannot_replace_a_wider_original_observation_with_remaining_source_ink",
    "terminal_source_completeness": {
        "original_context_required": True,
        "context_glyph_heights": 2.0,
        "near_glyph_heights": 0.75,
        "maximum_horizontal_thickness_px": 4,
        "maximum_horizontal_thickness_glyph_heights": 0.22,
        "minimum_continuous_horizontal_length_glyph_heights": 1.0,
        "orthogonal_neighbor_requires_continuation_one_glyph_height_outside_row": True,
        "complete_path_source_responsibility_and_remaining_samples_checked_separately": True,
        "crop_boundary_is_not_a_graphic_endpoint_or_exclusion_proof": True,
        "unknown_row_terminal_branches_remain_pending": True,
        "source_or_neighbor_geometry_modified": False,
    },
    "baseline_strip_separation": {
        "maximum_thickness_px": 4,
        "maximum_thickness_glyph_heights": 0.22,
        "minimum_both_end_extensions_glyph_heights": 1.0,
        "minimum_line_length_glyph_heights": 4.0,
        "maximum_baseline_search_glyph_heights": 0.15,
        "minimum_visible_glyph_body_fraction": 0.80,
        "maximum_candidate_strips": 4,
        "actual_source_white_gaps_filled": False,
        "source_pixels_deleted": False,
        "unobserved_glyph_strokes_reconstructed": False,
    },
}

_RECOGNIZER = None


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _box_tuple(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError("SINGLE_LINE_SOURCE_BOX_INVALID")
    if any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(v)
        or int(v) != v
        for v in box
    ):
        raise ValueError("SINGLE_LINE_SOURCE_BOX_NOT_INTEGER")
    return list(map(int, box))


def _catalog(gray, roi):
    a, b, c, d = roi
    raw = np.ascontiguousarray(
        (gray[b:d, a:c] < POLICY["source_threshold"]).astype(np.uint8)
    )
    _, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
    rows = []
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        rows.append(
            {
                "label": label,
                "labels": [label],
                "bbox": [int(x + a), int(y + b), int(x + a + w), int(y + b + h)],
                "width": int(w),
                "height": int(h),
                "area": int(area),
            }
        )
    return labels, rows


def _component_record(row, labels, roi, role):
    x0, y0, x1, y1 = row["bbox"]
    mask = np.isin(
        labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]], row["labels"]
    )
    return {
        "bbox_xyxy_px": row["bbox"],
        "source_area_px": row["area"],
        "source_role": role,
        "source_component_labels": row["labels"],
        "source_runs_y_x0_x1": base._rle(mask, [x0, y0]),
        "source_white_gaps_not_filled": True,
    }


def _terminal_source_completeness(gray, roi, partition):
    """Check source beside both row ends before trusting a cropped transcript.

    A large original component can contain both a neighbor and the missing
    first/last character.  Its size, or its crossing a crop edge, cannot prove
    that the local samples are only graphics.  Connected pieces are therefore
    measured in the wider original context, before inspecting the near end.
    This certificate never changes a source sample or any graphic ownership.
    """
    policy = POLICY["terminal_source_completeness"]
    height = float(partition["glyph_height_px"])
    full = [
        c["bbox_xyxy_px"]
        for c in partition["components"]
        if c["source_role"] == "FULL_HEIGHT_GLYPH"
    ]
    baseline = float(np.median([b[3] for b in full]))
    core = base._box_union(full)
    box = partition["bbox_xyxy_px"]
    reach = math.ceil(policy["context_glyph_heights"] * height)
    near_reach = math.ceil(policy["near_glyph_heights"] * height)
    near_top = max(roi[1], math.floor(core[1] - 0.15 * height))
    near_bottom = min(roi[3], math.ceil(max(core[3], box[3]) + 0.25 * height))
    top = max(roi[1], math.floor(core[1] - height))
    bottom = min(roi[3], math.ceil(max(core[3], box[3]) + height))
    contact = partition.get("text_contact_separation", {})
    proved_runs = [
        run
        for path in contact.get("geometry_plan", {}).get("paths", [])
        for run in path.get("line_runs", [])
    ]
    proved_runs += partition.get("baseline_line_separation", {}).get(
        "original_line_runs_y_x0_x1", []
    )
    certificate = {
        "schema": "original-row-terminal-completeness-v1",
        "policy": policy,
        "source_row_bbox_xyxy_px": box,
        "source_baseline_px": baseline,
        "glyph_height_px": height,
        "terminals": [],
        "original_source_pixels_modified": False,
        "neighbor_geometry_modified": False,
        "pass": True,
    }
    for side in ("left", "right"):
        a, b = (
            (max(roi[0], box[0] - reach), box[0])
            if side == "left"
            else (box[2], min(roi[2], box[2] + reach))
        )
        if a >= b or top >= bottom:
            certificate["pass"] = False
            certificate["terminals"].append({
                "side": side,
                "original_context_bbox_xyxy_px": [a, top, b, bottom],
                "original_context_available": False,
                "reason": "NO_ORIGINAL_ROW_TERMINAL_CONTEXT",
                "source_components": [],
            })
            continue
        source = np.ascontiguousarray(gray[top:bottom, a:b], dtype=np.uint8)
        ink = source < POLICY["source_threshold"]
        near = np.zeros(ink.shape, bool)
        if side == "left":
            near[near_top - top : near_bottom - top, max(0, b - a - near_reach) :] = (
                True
            )
        else:
            near[near_top - top : near_bottom - top, :near_reach] = True
        known = np.zeros(ink.shape, bool)
        for y, x0, x1 in proved_runs:
            if top <= y < bottom and x0 < b and a < x1:
                known[y - top, max(a, x0) - a : min(b, x1) - a] = True
        # A proved complete path may meet a separate underline farther out in
        # this context.  Their union is not one unexplained glyph.  Account for
        # the exact original path samples first and inspect every remaining
        # sample; the full original image and near-source RLE stay unchanged.
        responsibility = ink & known
        _, local, stats, _ = cv2.connectedComponentsWithStats(
            (ink & ~responsibility).astype(np.uint8), connectivity=8
        )
        terminal = {
            "side": side,
            "original_context_available": True,
            "original_context_bbox_xyxy_px": [a, top, b, bottom],
            "original_context_array_sha256": base.source_array_sha256(source),
            "near_source_runs_y_x0_x1": base._rle(ink & near, [a, top]),
            "complete_path_near_source_runs_y_x0_x1": base._rle(
                responsibility & near, [a, top]
            ),
            "remaining_component_basis": "original_samples_outside_separately_proved_complete_path_responsibility",
            "source_components": [],
        }
        for label, (x, y, width, h, area) in enumerate(stats[1:], 1):
            component = local == label
            actual_near = component & near
            if not actual_near.any():
                continue
            yy, xx = np.nonzero(actual_near)
            local_box = [int(a + x), int(top + y), int(a + x + width), int(top + y + h)]
            near_box = [
                int(a + xx.min()),
                int(top + yy.min()),
                int(a + xx.max() + 1),
                int(top + yy.max() + 1),
            ]
            record = {
                "context_component_bbox_xyxy_px": local_box,
                "context_source_area_px": int(area),
                "context_source_runs_y_x0_x1": base._rle(component, [a, top]),
                "near_source_bbox_xyxy_px": near_box,
                "near_source_area_px": int(actual_near.sum()),
                "reason": None,
                "pass": False,
            }
            if (
                local_box[3]
                <= baseline - POLICY["baseline_tolerance_glyph_heights"] * height
            ):
                record["reason"] = "ORIGINAL_COMPONENT_ENDS_ABOVE_ROW_BASELINE_BAND"
            elif local_box[1] >= baseline + max(2, 0.10 * height):
                record["reason"] = "ORIGINAL_COMPONENT_IS_BELOW_ROW"
            else:
                thickness = near_box[3] - near_box[1]
                if thickness <= min(
                    policy["maximum_horizontal_thickness_px"],
                    policy["maximum_horizontal_thickness_glyph_heights"] * height,
                ):
                    strip = component[yy.min() : yy.max() + 1]
                    columns = strip.any(axis=0)
                    intervals = np.flatnonzero(
                        np.diff(np.r_[False, columns, False])
                    ).reshape(-1, 2)
                    for start, end in intervals:
                        if not (start <= xx.min() and end > xx.max()):
                            continue
                        if (
                            end - start
                            >= policy[
                                "minimum_continuous_horizontal_length_glyph_heights"
                            ]
                            * height
                        ):
                            record["reason"] = (
                                "CONTINUOUS_ORIGINAL_THIN_HORIZONTAL_NEIGHBOR"
                            )
                        else:
                            # A short frame shoulder may turn down/up.  Its
                            # actual orthogonal leg must continue a full glyph
                            # height beyond this row; a cropped L-shaped glyph
                            # or an unproved corner cannot use this exception.
                            margin = policy["maximum_horizontal_thickness_px"]
                            for edge in (int(start), int(end) - 1):
                                leg = component[
                                    :,
                                    max(0, edge - margin + 1) : min(
                                        b - a, edge + margin
                                    ),
                                ]
                                leg_rows = leg.any(axis=1)
                                spans = np.flatnonzero(
                                    np.diff(np.r_[False, leg_rows, False])
                                ).reshape(-1, 2)
                                span = next(
                                    (
                                        (int(lo), int(hi))
                                        for lo, hi in spans
                                        if lo <= yy.min()
                                        and hi > yy.max()
                                        and (
                                            top + lo <= core[1] - height
                                            or top + hi >= core[3] + height
                                        )
                                    ),
                                    None,
                                )
                                if span is not None:
                                    record["reason"] = (
                                        "ORIGINAL_ORTHOGONAL_NEIGHBOR_CONTINUES_OUTSIDE_ROW"
                                    )
                                    record["orthogonal_source_leg_rows_px"] = [
                                        top + span[0],
                                        top + span[1],
                                    ]
                                    break
                        if record["reason"] is not None:
                            record["horizontal_source_trace_bbox_xyxy_px"] = [
                                int(a + start),
                                near_box[1],
                                int(a + end),
                                near_box[3],
                            ]
                            break
            record["pass"] = record["reason"] is not None
            if not record["pass"]:
                record["reason"] = "UNPROVED_SOURCE_BRANCH_AT_ROW_TERMINAL"
                certificate["pass"] = False
            terminal["source_components"].append(record)
        terminal["source_components"].sort(
            key=lambda record: (
                record["context_component_bbox_xyxy_px"],
                record["context_source_runs_y_x0_x1"],
            )
        )
        certificate["terminals"].append(terminal)
    return certificate


def _with_terminal_source_completeness(gray, roi, partition):
    certificate = _terminal_source_completeness(gray, roi, partition)
    if not certificate["pass"]:
        return None, "UNPROVED_SOURCE_BRANCH_AT_ROW_TERMINAL"
    partition["terminal_source_completeness"] = certificate
    return partition, None


def _glyph(row, height, baseline):
    lo, hi = POLICY["glyph_height_px"]
    ratio = row["height"] / height
    return (
        lo <= row["height"] <= hi
        and row["area"] >= 8
        and POLICY["glyph_height_ratio"][0] <= ratio <= POLICY["glyph_height_ratio"][1]
        and row["width"] / row["height"] <= POLICY["glyph_width_height_maximum"]
        and abs(row["bbox"][3] - baseline)
        <= POLICY["baseline_tolerance_glyph_heights"] * height
        and 0.025 <= row["area"] / (row["width"] * row["height"]) <= 0.90
    )


def _glyph_units(components, height, baseline):
    """Associate adjacent scan fragments without filling any source gap."""
    rows = [
        copy.deepcopy(r)
        for r in components
        if r["height"] <= 1.45 * height
        and r["width"] <= 1.70 * height
        and r["bbox"][1] < baseline + 0.28 * height
        and r["bbox"][3] > baseline - 1.45 * height
    ]
    for _ in range(POLICY["maximum_source_components"]):
        rows.sort(key=lambda r: (r["bbox"][0], r["bbox"][1]))
        changed = False
        for i, a in enumerate(rows):
            for j in range(i + 1, len(rows)):
                b = rows[j]
                if (
                    b["bbox"][0]
                    > a["bbox"][2] + POLICY["fragment_maximum_white_gap_px"]
                ):
                    break
                if _glyph(a, height, baseline) and _glyph(b, height, baseline):
                    continue
                ab, bb = a["bbox"], b["bbox"]
                x_overlap = max(0, min(ab[2], bb[2]) - max(ab[0], bb[0]))
                y_overlap = max(0, min(ab[3], bb[3]) - max(ab[1], bb[1]))
                x_gap = max(ab[0] - bb[2], bb[0] - ab[2], 0)
                y_gap = max(ab[1] - bb[3], bb[1] - ab[3], 0)
                vertical = (
                    x_overlap >= 0.25 * min(a["width"], b["width"])
                    and y_gap <= POLICY["fragment_maximum_white_gap_px"]
                )
                horizontal = (
                    y_overlap >= 0.50 * min(a["height"], b["height"]) and x_gap <= 1
                )
                separate_dash = any(
                    part["height"] <= 0.22 * height
                    and 0.15 * height <= part["width"] <= 1.40 * height
                    and part["width"] >= 2.5 * part["height"]
                    and baseline - 0.75 * height
                    <= (part["bbox"][1] + part["bbox"][3]) / 2
                    <= baseline - 0.20 * height
                    for part in (a, b)
                )
                if (
                    horizontal
                    and (x_gap >= 1 or separate_dash)
                    and (_glyph(a, height, baseline) or _glyph(b, height, baseline))
                ):
                    # A complete glyph next to a detached mark is not a broken
                    # letter. Keep the real white gap and the independent
                    # short dash/quote/dot; two OCR omissions cannot erase it.
                    horizontal = False
                union = base._box_union([ab, bb])
                if (
                    not (vertical or horizontal)
                    or union[2] - union[0] > 1.70 * height
                    or union[3] - union[1] > 1.45 * height
                ):
                    continue
                # Tiny punctuation components beside one another are not
                # merged into letters. At least one part reaches the glyph's
                # body, or their vertical union has full row height.
                if (
                    max(a["height"], b["height"]) < 0.60 * height
                    and union[3] - union[1] < 0.75 * height
                ):
                    continue
                rows[i] = {
                    "label": min(a["labels"] + b["labels"]),
                    "labels": sorted(a["labels"] + b["labels"]),
                    "bbox": union,
                    "width": union[2] - union[0],
                    "height": union[3] - union[1],
                    "area": a["area"] + b["area"],
                }
                del rows[j]
                changed = True
                break
            if changed:
                break
        if not changed:
            break
    return rows


def _partition_original_row(gray, roi, seed_box, *, catalog=None):
    """A complete component row, including punctuation, independent of text."""
    roi, seed_box = _box_tuple(roi), _box_tuple(seed_box)
    if not base._inside(seed_box, roi):
        return None, "ROW_OBSERVATION_CROSSES_EFFECTIVE_INPUT"
    labels, components = catalog if catalog is not None else _catalog(gray, roi)
    height = seed_box[3] - seed_box[1]
    if not 7 <= height <= 90:
        return None, "ROW_OBSERVATION_HEIGHT_UNSUPPORTED"
    units = _glyph_units(components, height, seed_box[3])
    full = [
        r
        for r in units
        if _glyph(r, height, seed_box[3])
        and base._intersection(r["bbox"], seed_box) / max(1, base._area(r["bbox"]))
        >= 0.5
    ]
    if len(full) < POLICY["minimum_full_height_components"]:
        return None, "INSUFFICIENT_COMPLETE_SOURCE_GLYPH_COMPONENTS"
    h = float(np.median([r["height"] for r in full]))
    baseline = float(np.median([r["bbox"][3] for r in full]))
    full = [r for r in full if _glyph(r, h, baseline)]
    if len(full) < POLICY["minimum_full_height_components"]:
        return None, "NO_UNIQUE_SOURCE_BASELINE"
    # A clipped old word box is only a seed. Walk both ways over the original
    # same-baseline row, so a missing prefix/suffix does not become a label.
    for _ in range(POLICY["maximum_source_components"]):
        core = base._box_union([r["bbox"] for r in full])
        additions = [
            r
            for r in units
            if r not in full
            and _glyph(r, h, baseline)
            and max(core[0] - r["bbox"][2], r["bbox"][0] - core[2], 0)
            <= POLICY["row_join_gap_glyph_heights"] * h
        ]
        if not additions:
            break
        full.extend(additions)
    full.sort(key=lambda r: (r["bbox"][0], r["bbox"][1]))
    core = base._box_union([r["bbox"] for r in full])
    if (
        len(full) > POLICY["maximum_source_components"]
        or core[2] - core[0] > POLICY["maximum_row_width_px"]
    ):
        return None, "SOURCE_ROW_EXCEEDS_FINITE_LABEL_SCOPE"
    if any(a["bbox"][2] > b["bbox"][0] for a, b in zip(full, full[1:])):
        return None, "SOURCE_GLYPH_COLUMNS_NOT_UNIQUE"
    if any(
        r["bbox"][0] <= roi[0]
        or r["bbox"][1] <= roi[1]
        or r["bbox"][2] >= roi[2]
        or r["bbox"][3] >= roi[3]
        for r in full
    ):
        return None, "SOURCE_GLYPH_TOUCHES_EFFECTIVE_INPUT"
    selected_ids = {label for r in full for label in r["labels"]}
    punctuation, external, external_ids = [], [], set()
    side = POLICY["terminal_punctuation_search_glyph_heights"] * h
    band = [
        max(roi[0], int(math.floor(core[0] - side))),
        max(roi[1], int(math.floor(core[1] - 0.15 * h))),
        min(roi[2], int(math.ceil(core[2] + side))),
        min(roi[3], int(math.ceil(core[3] + 0.25 * h))),
    ]
    for row in components:
        box = row["bbox"]
        if row["label"] in selected_ids or not base._intersection(box, band):
            continue
        # Only actual pixels in the row band matter: a neighboring huge circle
        # or wall's bounding rectangle is not itself foreground.
        x0, y0 = max(box[0], band[0]), max(box[1], band[1])
        x1, y1 = min(box[2], band[2]), min(box[3], band[3])
        yy, xx = np.nonzero(
            labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]] == row["label"]
        )
        if not len(xx):
            continue
        actual = [
            int(xx.min() + x0),
            int(yy.min() + y0),
            int(xx.max() + x0 + 1),
            int(yy.max() + y0 + 1),
        ]
        # Marks wholly below the row baseline are preserved as exterior source
        # context. A comma starts within the row and therefore cannot use this.
        below_row = box[1] >= core[3] + max(2, 0.10 * h)
        above_row = box[3] <= core[1] and row["height"] > 0.58 * h
        small = (
            not below_row
            and row["width"] <= 1.40 * h
            and row["height"] <= 0.58 * h
            and row["area"] >= 1
            and base._inside(box, band)
        )
        if small:
            # Never drop a short dash, comma, dot or quote as dust. The raw
            # complete transcript must account for these components later.
            punctuation.append(row)
            selected_ids.add(row["label"])
            continue
        below = (
            box[1] >= core[3] + 1
            and row["width"] >= 3 * h
            and row["width"] >= 10 * max(1, row["height"])
        )
        long_graphic = max(row["width"], row["height"]) > 3 * h
        # A wall/circle/connector network may enter this bounded row in more
        # than one disconnected place. Check every actual local piece, instead
        # of treating the union bounding rectangle as foreground. No connected
        # source glyph can be cut away by this local-piece test.
        local_mask = (
            labels[y0 - roi[1] : y1 - roi[1], x0 - roi[0] : x1 - roi[0]] == row["label"]
        ).astype(np.uint8)
        _, _, local_stats, _ = cv2.connectedComponentsWithStats(
            local_mask, connectivity=8
        )
        local_pieces = []
        for lx, ly, lw, lh, area in local_stats[1:]:
            piece = [int(x0 + lx), int(y0 + ly), int(x0 + lx + lw), int(y0 + ly + lh)]
            outside = (
                max(core[0] - piece[2], piece[0] - core[2])
                >= POLICY["minimum_external_white_columns"]
            )
            above_edge = (
                long_graphic
                and piece[3] <= core[1] + POLICY["external_edge_band_fraction"] * h
                and box[1] < core[1] - h
            )
            # A distinct thin connector continuing outside the terminal
            # search band remains an independent neighbor. A small terminal
            # dash wholly inside that band was retained as punctuation above.
            continuing = (
                outside
                and row["width"] >= 1.25 * h
                and row["width"] >= 8 * max(1, row["height"])
                and (box[0] < band[0] or box[2] > band[2])
            )
            local_pieces.append(
                {
                    "bbox_xyxy_px": piece,
                    "area_px": int(area),
                    "proved_external": bool(
                        below
                        or below_row
                        or above_row
                        or above_edge
                        or (outside and long_graphic)
                        or continuing
                    ),
                }
            )
        if local_pieces and all(p["proved_external"] for p in local_pieces):
            external_ids.add(row["label"])
            external.append(
                {
                    "source_component_label": row["label"],
                    "bbox_xyxy_px": box,
                    "source_area_px": row["area"],
                    "local_ink_bbox_xyxy_px": actual,
                    "local_source_pieces": local_pieces,
                    "reason": "ALL_LOCAL_SOURCE_PIECES_HAVE_EXTERIOR_GEOMETRY",
                    "excluded_only_from_recognition": True,
                }
            )
            continue
        return None, "UNKNOWN_SHORT_OR_SHARED_SOURCE_COMPONENT_RETAINED"
    kept = full + punctuation
    box = base._box_union([r["bbox"] for r in kept])
    # Punctuation may expand the retained row. Recheck every omitted source
    # component against that final box; a word suffix cannot hide in a mask.
    xa, ya, xb, yb = box
    local_labels = labels[ya - roi[1] : yb - roi[1], xa - roi[0] : xb - roi[0]]
    omitted_ids = {
        int(x) for x in np.unique(local_labels) if x and int(x) not in selected_ids
    }
    if omitted_ids - external_ids:
        return None, "UNASSIGNED_INK_INSIDE_COMPLETE_LABEL_BOX"
    support = np.isin(local_labels, list(selected_ids))
    original_crop = np.ascontiguousarray(gray[ya:yb, xa:xb], dtype=np.uint8)
    removed = (original_crop < POLICY["source_threshold"]) & ~support
    context_pad = int(math.ceil(POLICY["source_context_glyph_heights"] * h))
    context = [
        max(roi[0], xa - context_pad),
        max(roi[1], ya - context_pad),
        min(roi[2], xb + context_pad),
        min(roi[3], yb + context_pad),
    ]
    source_records = [
        _component_record(r, labels, roi, "FULL_HEIGHT_GLYPH") for r in full
    ]
    source_records += [
        _component_record(r, labels, roi, "RETAINED_PUNCTUATION") for r in punctuation
    ]
    source_records.sort(key=lambda r: (r["bbox_xyxy_px"][0], r["bbox_xyxy_px"][1]))
    result = {
        "schema": "complete-single-source-row-partition-v1",
        "seed_bbox_xyxy_px": seed_box,
        "roi_xyxy_px": roi,
        "bbox_xyxy_px": box,
        "glyph_height_px": h,
        "full_height_component_count": len(full),
        "punctuation_component_count": len(punctuation),
        "components": source_records,
        "source_support_runs_y_x0_x1": base._rle(support, box[:2]),
        "recognition_excluded_graphic_runs_y_x0_x1": base._rle(removed, box[:2]),
        "recognition_excluded_graphic_pixels": int(removed.sum()),
        "source_crop_array_sha256": base.source_array_sha256(original_crop),
        "context_bbox_xyxy_px": context,
        "context_array_sha256": base.source_array_sha256(
            gray[context[1] : context[3], context[0] : context[2]]
        ),
        "external_graphics": external,
        "source_components_cut": False,
        "original_source_pixels_modified": False,
        "all_label_ink_assigned": True,
    }
    return _with_terminal_source_completeness(gray, roi, result)


def _baseline_strip_candidates(gray, roi, seed):
    """Only a complete straight strip beneath a discovered source row.

    Both observed ends must extend beyond the row. A gap in the strip, a
    second stroke continuing below it, or ink on the outer shoulders stops
    this finite path. No word or expected character is an input.
    """
    policy = POLICY["baseline_strip_separation"]
    h = seed[3] - seed[1]
    if not 7 <= h <= 90 or not base._inside(seed, roi):
        return []
    extension = math.ceil(policy["minimum_both_end_extensions_glyph_heights"] * h)
    search = max(2, math.ceil(policy["maximum_baseline_search_glyph_heights"] * h))
    rows, seen = [], set()
    for y in range(max(roi[1], seed[3] - search), min(roi[3], seed[3] + search + 1)):
        ink = gray[y, roi[0] : roi[2]] < POLICY["source_threshold"]
        starts_ends = np.flatnonzero(np.diff(np.r_[False, ink, False])).reshape(-1, 2)
        for a, b in starts_ends:
            a, b = int(a + roi[0]), int(b + roi[0])
            if not (
                a <= seed[0] - extension
                and b >= seed[2] + extension
                and b - a >= policy["minimum_line_length_glyph_heights"] * h
            ):
                continue
            left, right = (a + seed[0]) // 2, (seed[2] + b) // 2
            top, bottom = y, y + 1
            while (
                top > roi[1]
                and gray[top - 1, left] < 192
                and gray[top - 1, right] < 192
            ):
                top -= 1
            while (
                bottom < roi[3]
                and gray[bottom, left] < 192
                and gray[bottom, right] < 192
            ):
                bottom += 1
            box = [a, top, b, bottom]
            if tuple(box) in seen:
                continue
            seen.add(tuple(box))
            thickness = bottom - top
            if not (
                a > roi[0]
                and b < roi[2]
                and top > roi[1]
                and bottom < roi[3]
                and 1 <= thickness <= policy["maximum_thickness_px"]
                and thickness <= policy["maximum_thickness_glyph_heights"] * h
                and top >= seed[1] + policy["minimum_visible_glyph_body_fraction"] * h
                and bool(np.all(gray[top:bottom, a:b] < 192))
            ):
                continue
            # With no source ink under the strip, a visible comma, descender,
            # branch, curved stroke or another line cannot be silently cut.
            lower = bottom + math.ceil(h)
            upper = top - math.ceil(1.6 * h)
            if lower > roi[3] or upper < roi[1]:
                continue
            if np.any(gray[bottom:lower, a:b] < 192):
                continue
            margin = math.ceil(0.20 * h)
            if np.any(gray[upper:top, a : max(a, seed[0] - margin)] < 192) or np.any(
                gray[upper:top, min(b, seed[2] + margin) : b] < 192
            ):
                continue
            rows.append(
                {
                    "bbox_xyxy_px": box,
                    "source_threshold": POLICY["source_threshold"],
                    "original_strip_pixels": int(thickness * (b - a)),
                    "strip_is_continuous_black_source_rectangle": True,
                    "source_blank_below_bbox_xyxy_px": [a, bottom, b, lower],
                    "outer_shoulders_checked_above_to_y": upper,
                }
            )
            if len(rows) >= policy["maximum_candidate_strips"]:
                return rows
    return rows


def _partition(
    gray, roi, seed_box, *, catalog=None, contact_context=None, contact_seed_box=None
):
    """Original components first; a recorded baseline-strip split is bounded."""
    partition, reason = _partition_original_row(gray, roi, seed_box, catalog=catalog)
    if partition is not None or reason not in {
        "INSUFFICIENT_COMPLETE_SOURCE_GLYPH_COMPONENTS",
        "UNKNOWN_SHORT_OR_SHARED_SOURCE_COMPONENT_RETAINED",
        "UNPROVED_SOURCE_BRANCH_AT_ROW_TERMINAL",
    }:
        return partition, reason
    roi, seed = _box_tuple(roi), _box_tuple(seed_box)
    for line in _baseline_strip_candidates(gray, roi, seed):
        a, top, b, bottom = line["bbox_xyxy_px"]
        # This temporary array partitions the graph only. Original image files
        # and candidate glyph samples are never repaired, filled or erased.
        separated = gray.copy()
        separated[top:bottom, a:b] = 255
        body, error = _partition_original_row(separated, roi, seed)
        if error:
            continue
        box = body["bbox_xyxy_px"]
        full = [
            c for c in body["components"] if c["source_role"] == "FULL_HEIGHT_GLYPH"
        ]
        marks = [
            c for c in body["components"] if c["source_role"] == "RETAINED_PUNCTUATION"
        ]
        height = body["glyph_height_px"]
        if (
            box[3] != top
            or box[0] - a < height
            or b - box[2] < height
            or any(top - c["bbox_xyxy_px"][3] not in (0, 1) for c in full)
            or any(
                c["bbox_xyxy_px"][3] - c["bbox_xyxy_px"][1]
                < POLICY["baseline_strip_separation"][
                    "minimum_visible_glyph_body_fraction"
                ]
                * (seed[3] - seed[1])
                for c in full
            )
            or any(c["bbox_xyxy_px"][3] >= top - 1 for c in marks)
            or not np.array_equal(
                gray[box[1] : box[3], box[0] : box[2]],
                separated[box[1] : box[3], box[0] : box[2]],
            )
        ):
            continue
        # Source labels remain the labels of the ORIGINAL connected graph.
        # Derived subcomponent labels are retained separately, not mislabeled
        # as independent original connected components.
        original_labels, _ = catalog if catalog is not None else _catalog(gray, roi)
        contacts = []
        for component in body["components"]:
            original_ids = set()
            for y, x0, x1 in component["source_runs_y_x0_x1"]:
                original_ids.update(
                    int(v)
                    for v in np.unique(
                        original_labels[y - roi[1], x0 - roi[0] : x1 - roi[0]]
                    )
                    if v
                )
            component["derived_partition_component_labels"] = component[
                "source_component_labels"
            ]
            component["source_component_labels"] = sorted(original_ids)
            adjacent = [
                run for run in component["source_runs_y_x0_x1"] if run[0] == top - 1
            ]
            if adjacent:
                contacts.append(
                    {
                        "component_bbox_xyxy_px": component["bbox_xyxy_px"],
                        "original_glyph_terminal_runs_y_x0_x1": adjacent,
                        "adjacent_original_line_runs_y_x0_x1": [
                            [top, x0, x1] for _, x0, x1 in adjacent
                        ],
                        "original_source_component_labels": sorted(original_ids),
                    }
                )
        if not contacts:
            continue
        context = [
            max(roi[0], a - 1),
            max(roi[1], box[1] - math.ceil(height)),
            min(roi[2], b + 1),
            min(roi[3], bottom + math.ceil(height)),
        ]
        certificate = {
            "schema": "source-baseline-straight-strip-separation-v1",
            **line,
            "original_source_context_bbox_xyxy_px": context,
            "original_source_context_array_sha256": base.source_array_sha256(
                gray[context[1] : context[3], context[0] : context[2]]
            ),
            "original_line_runs_y_x0_x1": [[y, a, b] for y in range(top, bottom)],
            "original_line_component_labels": sorted(
                int(v)
                for v in np.unique(
                    original_labels[
                        top - roi[1] : bottom - roi[1], a - roi[0] : b - roi[0]
                    ]
                )
                if v
            ),
            "recovered_complete_body_bbox_xyxy_px": box,
            "actual_end_extensions_px": [box[0] - a, b - box[2]],
            "glyph_to_line_contacts": contacts,
            "source_body_samples_unchanged": True,
            "source_graph_component_split_recorded": True,
            "contact_strip_not_exclusively_assigned_to_glyphs": True,
            "line_remains_independent_source_responsibility": True,
            "source_erasure_authorized": False,
            "unknown_glyph_strokes_reconstructed": False,
            "actual_source_white_gaps_filled": False,
        }
        body["baseline_line_separation"] = certificate
        body["source_components_cut"] = True
        body["source_component_catalog_basis"] = (
            "original_graph_labels_with_certified_baseline_body_subcomponents"
        )
        body["source_crop_array_sha256"] = base.source_array_sha256(
            gray[box[1] : box[3], box[0] : box[2]]
        )
        cb = body["context_bbox_xyxy_px"]
        body["context_array_sha256"] = base.source_array_sha256(
            gray[cb[1] : cb[3], cb[0] : cb[2]]
        )
        completed, terminal_error = _with_terminal_source_completeness(gray, roi, body)
        if completed is not None:
            return completed, None
    from .text_contact_partition import partition_text_contact_row

    body, contact_reason, _ = partition_text_contact_row(
        gray,
        roi,
        seed if contact_seed_box is None else contact_seed_box,
        catalog=catalog,
        context=contact_context,
    )
    if body is not None:
        return _with_terminal_source_completeness(gray, roi, body)
    if reason == "UNPROVED_SOURCE_BRANCH_AT_ROW_TERMINAL":
        return None, reason
    return None, contact_reason


def _single_baseline_group(group, regions):
    boxes = [
        regions[rid]["bbox_xyxy_px"]
        for rid in group.get("region_ids", [])
        if rid in regions
    ]
    if not boxes:
        return False
    height = float(np.median([b[3] - b[1] for b in boxes]))
    return (
        max(b[3] for b in boxes) - min(b[3] for b in boxes) <= 0.28 * height
        and min(b[3] for b in boxes) - max(b[1] for b in boxes) >= 0.60 * height
    )


def plan_single_line_labels(gray, texts, roi=None):
    """Plan from discovered geometry only; no OCR and no expected strings."""
    roi = list(texts["roi_xyxy_px"] if roi is None else roi)
    validate_text_regions(texts, gray.shape, roi)
    catalog = _catalog(gray, roi)
    contact_context = {}
    protected = {
        r["id"] for r in texts["regions"] if r.get("complete") or r.get("enclosure")
    }
    by_id = {r["id"]: r for r in texts["regions"]}
    for group in texts.get("groups", []):
        if group.get("complete") or not _single_baseline_group(group, by_id):
            protected.update(group.get("region_ids", []))
    protected_boxes = [
        r["bbox_xyxy_px"] for r in texts["regions"] if r["id"] in protected
    ]
    plans, rejected, by_box = [], [], {}
    for row in texts["regions"]:
        if row["id"] in protected:
            continue
        # These strings are used only to reject single-character symbol seeds.
        # They are never sent to a recognition engine or used to select a value.
        if (
            max(
                [sum(c.isalnum() for c in row.get("text", ""))]
                + [
                    sum(c.isalnum() for c in w.get("text", ""))
                    for w in row.get("words", [])
                ]
            )
            < 2
        ):
            continue
        seeds = [
            row.get("discovery_bbox_xyxy_px", row["bbox_xyxy_px"]),
            row["bbox_xyxy_px"],
        ]
        seeds.extend(
            w["bbox_xyxy_px"]
            for w in row.get("words", [])
            if sum(c.isalnum() for c in w.get("text", "")) >= 2
        )
        candidates, errors = [], []
        for seed in {tuple(s) for s in seeds}:
            partition, reason = _partition(
                gray,
                roi,
                list(seed),
                catalog=catalog,
                contact_context=contact_context,
                contact_seed_box=row["bbox_xyxy_px"],
            )
            if partition is None:
                errors.append(reason)
                continue
            if any(
                base._intersection(partition["bbox_xyxy_px"], b) > 0
                for b in protected_boxes
            ):
                errors.append("ROW_TOUCHES_PROTECTED_COMPLETE_OR_MULTILINE_CONTENT")
                continue
            candidates.append(partition)
        if not candidates:
            rejected.append({"region_id": row["id"], "reasons": sorted(set(errors))})
            continue
        partition = max(
            candidates,
            key=lambda p: (
                p["full_height_component_count"],
                base._area(p["bbox_xyxy_px"]),
                tuple(p["seed_bbox_xyxy_px"]),
            ),
        )
        key = tuple(partition["bbox_xyxy_px"])
        if key in by_box:
            by_box[key]["region_ids"].append(row["id"])
            continue
        plan = {
            "id": "SL-"
            + _digest({"source": texts.get("source_array_sha256"), "bbox": key})[:12],
            "region_ids": [row["id"]],
            "source_partition": partition,
        }
        by_box[key] = plan
        plans.append(plan)
    plans.sort(
        key=lambda p: (
            p["source_partition"]["bbox_xyxy_px"][1],
            p["source_partition"]["bbox_xyxy_px"][0],
        )
    )
    contact_plans = {}
    for candidate in contact_context.get("plans", {}).values():
        key = _digest(
            sorted(_digest(path["representation"]) for path in candidate["paths"])
        )
        contact_plans.setdefault(key, candidate)
    return {
        "schema": "bounded-single-line-label-plan-v1",
        "policy": POLICY,
        "plans": plans[: POLICY["maximum_labels"]],
        "deferred_by_budget": plans[POLICY["maximum_labels"] :],
        "rejected": rejected,
        "protected_region_ids": sorted(protected),
        "new_OCR_calls": 0,
        "source_pixels_modified": False,
        "text_contact_geometry_plans": list(contact_plans.values()),
    }


def _producer_identity():
    from . import (
        circular_markers,
        single_line_neighbor_clearance,
        single_line_text_audit,
        single_line_source_layout,
        source_row_font_registry,
        text_contact_audit,
        text_contact_geometry,
        text_contact_partition,
    )

    return {
        "module": __name__,
        "sha256": _sha(Path(__file__).read_bytes()),
        "Tesseract_producer_sha256": _sha(Path(base.__file__).read_bytes()),
        "model_producer_sha256": _sha(Path(independent.__file__).read_bytes()),
        "raw_integrity_producer_sha256": _sha(Path(character.__file__).read_bytes()),
        "contact_geometry_producer_sha256": _sha(
            Path(text_contact_geometry.__file__).read_bytes()
        ),
        "contact_partition_producer_sha256": _sha(
            Path(text_contact_partition.__file__).read_bytes()
        ),
        "source_replay_comparison_producer_sha256": _sha(
            Path(text_contact_audit.__file__).read_bytes()
        ),
        "neighbor_clearance_producer_sha256": _sha(
            Path(single_line_neighbor_clearance.__file__).read_bytes()
        ),
        "text_layout_producer_sha256": _sha(
            Path(single_line_text_audit.__file__).read_bytes()
        ),
        "source_component_layout_producer_sha256": _sha(
            Path(single_line_source_layout.__file__).read_bytes()
        ),
        "source_row_font_registry_sha256": _sha(
            Path(source_row_font_registry.__file__).read_bytes()
        ),
        "source_glyph_equivalence_sha256": _sha(
            Path(glyph_equivalence.__file__).read_bytes()
        ),
        "round_source_producer_sha256": _sha(
            Path(circular_markers.__file__).read_bytes()
        ),
    }


def _adoption_decision(decision, layout_adoption):
    """Retain the raw transcription decision when native layout is pending."""
    if not decision["accepted"]:
        if layout_adoption is not None:
            raise ValueError("SINGLE_LINE_PENDING_TRANSCRIPTION_HAS_LAYOUT_APPROVAL")
        return False, list(decision["reasons"])
    if not isinstance(layout_adoption, dict) or not isinstance(layout_adoption.get("pass"), bool):
        raise ValueError("SINGLE_LINE_LAYOUT_ADOPTION_EVIDENCE_MISSING")
    return layout_adoption["pass"], list(decision["reasons"]) + (
        [] if layout_adoption["pass"] else [layout_adoption["reason"]]
    )


def _file_record(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha(path.read_bytes()),
    }


def _read_record(root, record):
    name = record.get("path")
    if not isinstance(name, str) or "\\" in name:
        raise ValueError("SINGLE_LINE_RAW_EVIDENCE_PATH_INVALID")
    name = PurePosixPath(name)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError("SINGLE_LINE_RAW_EVIDENCE_OUTSIDE_JOB")
    root = Path(root).resolve()
    path = root.joinpath(*name.parts)
    ancestor = root
    for component in name.parts:
        ancestor = ancestor / component
        if ancestor.is_symlink():
            raise ValueError("SINGLE_LINE_RAW_EVIDENCE_SYMLINK")
    if root not in path.resolve().parents or not path.is_file():
        raise ValueError("SINGLE_LINE_RAW_EVIDENCE_MISSING_OR_OUTSIDE_JOB")
    data = path.read_bytes()
    if _sha(data) != record.get("sha256"):
        raise ValueError("SINGLE_LINE_RAW_EVIDENCE_HASH_CHANGED")
    return data


def _view(gray, partition, scale, padding):
    x0, y0, x1, y1 = partition["bbox_xyxy_px"]
    original = np.ascontiguousarray(gray[y0:y1, x0:x1], dtype=np.uint8)
    recognition = original.copy()
    for y, a, b in partition["recognition_excluded_graphic_runs_y_x0_x1"]:
        recognition[y - y0, a - x0 : b - x0] = 255
    normalized = np.repeat(np.repeat(recognition, scale, axis=0), scale, axis=1)
    actual = np.pad(normalized, padding, constant_values=255)
    return normalized, actual


def _mapped_words(words, box, scale):
    result = []
    for word in words:
        a, b, c, d = word["bbox_xyxy_px"]
        result.append(
            {
                **word,
                "bbox_xyxy_px": [
                    box[0] + a / scale,
                    box[1] + b / scale,
                    box[0] + c / scale,
                    box[1] + d / scale,
                ],
            }
        )
    return result


def _flat_source_dash(component, partition, body):
    """Prove a single near-horizontal source stroke before collapsing raw symbols."""
    result = {"pass": False, "source_component_sha256": _digest(component)}
    b = component["bbox_xyxy_px"]
    h = partition["glyph_height_px"]
    w, ph = b[2] - b[0], b[3] - b[1]
    if not (
        component["source_role"] == "RETAINED_PUNCTUATION"
        and len(component["source_component_labels"]) == 1
        and 0.15 * h <= w <= 1.4 * h
        and ph <= 0.22 * h
        and w >= 2.5 * ph
        and body[1] + 0.25 * h <= (b[1] + b[3]) / 2 <= body[1] + 0.8 * h
    ):
        return result
    try:
        stroke, _ = glyph_equivalence.component_samples(component)
    except (KeyError, TypeError, ValueError):
        return result
    if not stroke.any(axis=0).all() or cv2.connectedComponents(stroke, connectivity=8)[0] != 2:
        return result
    x = np.arange(w, dtype=float)
    columns = [np.flatnonzero(stroke[:, i]) for i in range(w)]
    if any(len(v) != v[-1] - v[0] + 1 for v in columns):
        return result
    # Each original sample occupies a one-pixel cell. A straight spine must
    # intersect an occupied cell in every column, under the same slope bound.
    # A real up/down wave cannot pass merely because its overall bbox is thin.
    low = np.array([v[0] - 0.5 for v in columns])
    high = np.array([v[-1] + 0.5 for v in columns])
    limit = min(POLICY["flat_source_dash"]["maximum_centerline_slope"],
                POLICY["flat_source_dash"]["maximum_centerline_end_change_source_px"] / (w - 1))
    lower_slope, upper_slope = -limit, limit
    for i in range(w):
        for j in range(w):
            if i == j:
                continue
            bound = (high[j] - low[i]) / (j - i)
            if j > i:
                upper_slope = min(upper_slope, bound)
            else:
                lower_slope = max(lower_slope, bound)
    if lower_slope > upper_slope + 1e-12:
        return result
    spine_slope = (lower_slope + upper_slope) / 2.0
    spine_low = float(np.max(low - spine_slope * x))
    spine_high = float(np.min(high - spine_slope * x))
    if spine_low > spine_high + 1e-12:
        return result
    y = np.array([v.mean() for v in columns])
    slope, intercept = np.polyfit(x, y, 1)
    residual = float(np.max(np.abs(y - (slope * x + intercept))))
    end_change = float(abs(slope) * (w - 1))
    limits = POLICY["flat_source_dash"]
    result.update(
        centerline_slope=float(slope),
        centerline_end_change_source_px=end_change,
        maximum_column_center_residual_source_px=residual,
        original_component_continuous=True,
        original_quantized_straight_spine={
            "slope": float(spine_slope),
            "intercept_interval_source_px": [spine_low, spine_high],
            "original_pixel_cell_half_width_px": 0.5,
        },
        pass_=abs(slope) <= limits["maximum_centerline_slope"]
        and end_change <= limits["maximum_centerline_end_change_source_px"]
        and residual <= limits["maximum_column_center_residual_source_px"],
    )
    result["pass"] = bool(result.pop("pass_"))
    return result


def _source_canonical_text(text, partition):
    """Bind every character/space to its ordered original source component.

    Only Unicode typography with the *same measured source role* is normalized.
    It cannot invent a digit, drop a dash, turn one quote stroke into two, or
    manufacture a word separator without an original white gap.
    """
    report = {"text": None, "reasons": [], "normalizations": [], "word_spaces": [],
              "component_characters": []}
    if (
        not isinstance(text, str)
        or not text
        or text != text.strip()
        or not any(c.isascii() and c.isalpha() for c in text)
        or any(ord(c) < 32 or ord(c) == 127 for c in text)
    ):
        report["reasons"].append("SINGLE_LINE_REQUIRES_PRINTABLE_ALPHANUMERIC_LABEL")
        return report
    parts = partition["components"]
    full = [p["bbox_xyxy_px"] for p in parts if p["source_role"] == "FULL_HEIGHT_GLYPH"]
    body = base._box_union(full)
    h = partition["glyph_height_px"]
    index, result, skip_raw_until = 0, [], 0
    for char_index, value in enumerate(text):
        if char_index < skip_raw_until:
            continue
        if value == " ":
            if not 0 < index < len(parts) or (result and result[-1] == " "):
                report["reasons"].append("RAW_SPACE_HAS_NO_SOURCE_WORD_BOUNDARY")
                continue
            gap = parts[index]["bbox_xyxy_px"][0] - parts[index - 1]["bbox_xyxy_px"][2]
            if gap < POLICY["minimum_source_word_space_glyph_heights"] * h:
                report["reasons"].append("RAW_SPACE_HAS_NO_SOURCE_WORD_GAP")
            report["word_spaces"].append(
                {
                    "character_index": char_index,
                    "left_component": index - 1,
                    "right_component": index,
                    "original_white_gap_px": gap,
                }
            )
            result.append(" ")
            continue
        quote = value in '"“”'
        dash = value in "-‐‑‒–—−"
        stroke_proof = None
        if (dash or value == "~") and index < len(parts):
            stroke_proof = _flat_source_dash(parts[index], partition, body)
            if value == "~" and stroke_proof["pass"]:
                dash = True
        canonical = '"' if quote else "-" if dash else value
        raw_value = value
        if dash and index < len(parts):
            run_end = char_index + 1
            while run_end < len(text) and text[run_end] in "-‐‑‒–—−~":
                run_end += 1
            next_is_mark = (
                index + 1 < len(parts)
                and parts[index + 1]["source_role"] == "RETAINED_PUNCTUATION"
            )
            if (
                run_end > char_index + 1
                and not next_is_mark
                and stroke_proof["pass"]
            ):
                raw_value = text[char_index:run_end]
                skip_raw_until = run_end
        count = 2 if quote or value in ":;" else 1
        selected = parts[index : index + count]
        if len(selected) != count:
            report["reasons"].append("RAW_TEXT_EXCEEDS_ORDERED_SOURCE_COMPONENTS")
            break
        expected_role = (
            "FULL_HEIGHT_GLYPH"
            if value.isascii() and value.isalnum()
            else "RETAINED_PUNCTUATION"
        )
        if any(p["source_role"] != expected_role for p in selected):
            report["reasons"].append("RAW_CHARACTER_ROLE_DIFFERS_FROM_ORDERED_SOURCE")
        if quote:
            boxes = [p["bbox_xyxy_px"] for p in selected]
            if not (
                all(
                    b[2] - b[0] <= 0.30 * h
                    and b[3] - b[1] >= 1.30 * (b[2] - b[0])
                    and b[3] <= body[1] + 0.40 * h
                    for b in boxes
                )
                and 0 <= boxes[1][0] - boxes[0][2] <= 0.35 * h
            ):
                report["reasons"].append(
                    "DOUBLE_QUOTE_LACKS_TWO_ORIGINAL_UPPER_STROKES"
                )
        elif dash:
            b = selected[0]["bbox_xyxy_px"]
            w, ph = b[2] - b[0], b[3] - b[1]
            if not (
                0.15 * h <= w <= 1.40 * h
                and ph <= 0.22 * h
                and w >= 2.5 * ph
                and body[1] + 0.25 * h <= (b[1] + b[3]) / 2 <= body[1] + 0.80 * h
            ):
                report["reasons"].append("DASH_LACKS_ONE_ORIGINAL_MIDLINE_STROKE")
        elif not value.isascii():
            report["reasons"].append(
                "RAW_UNICODE_CHARACTER_HAS_NO_SOURCE_CANONICAL_RULE"
            )
        if canonical != raw_value:
            report["normalizations"].append(
                {
                    "character_index": char_index,
                    "raw_character": raw_value,
                    "canonical_character": canonical,
                    "source_component_indices": list(range(index, index + count)),
                    "rule": "TWO_ORIGINAL_UPPER_QUOTE_STROKES"
                    if quote
                    else "ONE_ORIGINAL_FLAT_MIDLINE_STROKE_FOR_RAW_WAVE_SYMBOL"
                    if "~" in raw_value
                    else "ONE_ORIGINAL_CONTINUOUS_HORIZONTAL_DASH_COMPONENT"
                    if len(raw_value) > 1
                    else "ONE_ORIGINAL_HORIZONTAL_DASH_COMPONENT",
                }
            )
            if not quote and ("~" in raw_value or len(raw_value) > 1):
                report["normalizations"][-1]["original_stroke_proof"] = stroke_proof
        result.append(canonical)
        report["component_characters"].extend([canonical] * count)
        index += count
    if index != len(parts):
        report["reasons"].append(
            "RAW_TEXT_DOES_NOT_ACCOUNT_FOR_EVERY_ORDERED_SOURCE_COMPONENT"
        )
    report["reasons"] = sorted(set(report["reasons"]))
    if not report["reasons"]:
        report["text"] = "".join(result)
    return report


def _label_model_confident(prediction):
    # Space tokens have no ink shape. Their identity is instead checked above
    # against the original gap. Actual letters/digits/punctuation keep the
    # existing model mean/minimum confidence requirements without relaxation.
    tokens = [
        t for t in prediction.get("raw_CTC_tokens", []) if t.get("character") != " "
    ]
    return (
        _model_integrity(prediction)
        and bool(tokens)
        and min(t["score"] for t in tokens)
        >= POLICY["PP_OCR_minimum_character_confidence"]
        and sum(t["score"] for t in tokens) / len(tokens)
        >= POLICY["PP_OCR_mean_confidence"]
    )


def _whole_source_text(text, words, partition):
    reasons = _source_canonical_text(text, partition)["reasons"]
    if not words:
        reasons.append("NO_COMPLETE_TESSERACT_WORD_GEOMETRY")
        return reasons
    union = base._box_union([w["bbox_xyxy_px"] for w in words])
    box = partition["bbox_xyxy_px"]
    if (
        max(abs(a - b) for a, b in zip(union, box))
        > POLICY["source_bbox_coverage_tolerance_px"]
    ):
        reasons.append("RAW_WORD_BOXES_DO_NOT_COVER_COMPLETE_SOURCE_LABEL")
    if any(
        not base._inside(
            w["bbox_xyxy_px"], [box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1]
        )
        for w in words
    ):
        reasons.append("RAW_WORD_OUTSIDE_COMPLETE_SOURCE_LABEL")
    for component in partition["components"]:
        cb = component["bbox_xyxy_px"]
        if not any(
            base._intersection(cb, w["bbox_xyxy_px"]) / max(1, base._area(cb)) >= 0.5
            for w in words
        ):
            reasons.append("SOURCE_COMPONENT_NOT_COVERED_BY_RAW_WORDS")
    return sorted(set(reasons))


def _observation_spans(gray, roi, partition, binding, evidence_root):
    """Read the actual upstream observations for a veto, never an OCR hint."""
    if binding is None:
        return []
    upstream = json.loads(_read_record(evidence_root, binding["snapshot"]))
    if (
        upstream.get("source_array_sha256") != base.source_array_sha256(gray)
        or upstream.get("roi_xyxy_px") != list(roi)
    ):
        raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATION_SOURCE_CHANGED")
    by_id = {r["id"]: r for r in upstream["regions"]}
    ids = binding["region_ids"]
    if not ids or len(ids) != len(set(ids)) or any(rid not in by_id for rid in ids):
        raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATION_IDS_INVALID")
    box = partition["bbox_xyxy_px"]
    spans = []
    for rid in ids:
        region = by_id[rid]
        for index, observation in enumerate([region, *region.get("words", [])]):
            observed_box = observation["bbox_xyxy_px"]
            if (
                len(observed_box) != 4
                or any(isinstance(v, bool) or not isinstance(v, int) for v in observed_box)
                or not (0 <= observed_box[0] < observed_box[2] <= gray.shape[1])
                or not (0 <= observed_box[1] < observed_box[3] <= gray.shape[0])
            ):
                raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATION_BOX_INVALID")
            x0, x1 = max(box[2], observed_box[0]), observed_box[2]
            y0, y1 = max(box[1], observed_box[1]), min(box[3], observed_box[3])
            ink = int(np.count_nonzero(gray[y0:y1, x0:x1] < POLICY["source_threshold"]))
            spans.append(
                {
                    "region_id": rid,
                    "observation_index": index,
                    "raw_text": observation.get("text", ""),
                    "bbox_xyxy_px": observed_box,
                    "original_ink_past_candidate_px": ink,
                }
            )
    return spans


def _observed_prefix_conflicts(text, partition, spans):
    """A wider literal observation can disprove completeness, not supply letters."""
    candidate = "".join(text.split()).casefold()
    box = partition["bbox_xyxy_px"]
    conflicts = []
    for span in spans:
        raw = "".join(span["raw_text"].split()).casefold()
        observed_box = span["bbox_xyxy_px"]
        vertical_overlap = min(box[3], observed_box[3]) - max(box[1], observed_box[1])
        if (
            raw.startswith(candidate)
            and any(c.isalnum() for c in raw[len(candidate):])
            and observed_box[2] > box[2] + POLICY["source_bbox_coverage_tolerance_px"]
            and vertical_overlap >= 0.5 * min(box[3] - box[1], observed_box[3] - observed_box[1])
            and span["original_ink_past_candidate_px"] > 0
        ):
            conflicts.append(span)
    return conflicts


def _decision(tesseract_views, model_views, partition, source_observations=()):
    tess, model = [], []
    rejected = []
    aggregate_word_scores = []
    for index, view in enumerate(tesseract_views):
        words = view.get("words", [])
        text = " ".join(w["text"] for w in words)
        reasons = _whole_source_text(text, words, partition)
        if not view.get("raw_tsv_integrity"):
            reasons.append("RAW_TSV_HAS_INVALID_NONEMPTY_WORD")
        # A complete source-bound row uses the same evidence rule whether its
        # glyphs touch a graphic or already have a real white gap. Every source
        # component, literal corroboration and strict model character remains.
        aggregate_word_scores.append(
            {
                "view": index,
                "scores": [w.get("confidence") for w in words],
                "strict_legacy_word_gate_met": _tesseract_confident(words),
            }
        )
        if not reasons:
            canonical = _source_canonical_text(text, partition)
            tess.append((index, canonical["text"], words, canonical))
        else:
            rejected.append(
                {
                    "engine": "Tesseract",
                    "view": index,
                    "raw_text": text,
                    "reasons": reasons,
                }
            )
    for index, view in enumerate(model_views):
        prediction = view["prediction"]
        canonical = _source_canonical_text(prediction["raw_text"], partition)
        if _label_model_confident(prediction) and not canonical["reasons"]:
            model.append((index, canonical["text"], canonical))
        else:
            rejected.append(
                {
                    "engine": "PP-OCR",
                    "view": index,
                    "raw_text": prediction.get("raw_text"),
                    "reasons": canonical["reasons"]
                    + (
                        []
                        if _label_model_confident(prediction)
                        else ["PP_OCR_UNCHANGED_CHARACTER_GATE_NOT_MET"]
                    ),
                }
            )
    matches = sorted({t[1] for t in tess} & {p[1] for p in model})
    reasons = []
    if any(v.get("raw_tsv_integrity") is not True for v in tesseract_views):
        reasons.append("INVALID_RAW_TSV_CANNOT_BE_OVERRIDDEN_BY_ANOTHER_VIEW")
    if any(not _model_integrity(v.get("prediction", {})) for v in model_views):
        reasons.append("INVALID_RAW_CTC_CANNOT_BE_OVERRIDDEN_BY_ANOTHER_VIEW")
    if len(matches) != 1:
        reasons.append("NO_UNIQUE_TWO_ENGINE_COMPLETE_RAW_STRING")
    accepted_text = matches[0] if len(matches) == 1 else None
    conflict_evidence = None
    if accepted_text is not None:
        conflict_evidence = glyph_equivalence.verify_raw_character_conflicts(
            partition, accepted_text,
            [{"view_index": t[0], "text": t[1], "component_characters": t[3]["component_characters"]} for t in tess],
            [{"view_index": p[0], "text": p[1], "component_characters": p[2]["component_characters"]} for p in model],
        )
        if not conflict_evidence["pass"]:
            reasons.append("UNRESOLVED_COMPLETE_RAW_CHARACTER_CONFLICT")
    if accepted_text is not None and any(p[1] != accepted_text for p in model):
        reasons.append("CONFLICTING_CONFIDENT_PP_OCR_VIEW")
    prefix_conflicts = (
        _observed_prefix_conflicts(accepted_text, partition, source_observations)
        if accepted_text is not None
        else []
    )
    if prefix_conflicts:
        reasons.append("NARROW_PREFIX_OMITS_OBSERVED_ALPHANUMERIC_SUFFIX")
    winning = next((t for t in tess if t[1] == accepted_text), None)
    return {
        "accepted": not reasons,
        "text": accepted_text if not reasons else None,
        "reasons": reasons,
        "Tesseract_view_index": winning[0] if winning and not reasons else None,
        "PP_OCR_view_indices": [p[0] for p in model if p[1] == accepted_text]
        if not reasons
        else [],
        "Tesseract_canonical_word_texts": winning[1].split(" ")
        if winning and not reasons
        else [],
        "source_text_normalization": winning[3] if winning and not reasons else None,
        "model_whitespace_checked_as_original_source_gap": True,
        "unaccepted_raw_views_retained": rejected,
        "independent_engine_family_count": 2 if not reasons else 0,
        "raw_transcription_rewritten": False,
        "source_glyph_and_punctuation_counts_checked": True,
        "adoption_basis": POLICY["complete_row_transcription_rule"],
        "contact_Tesseract_aggregate_word_scores": aggregate_word_scores,
        "raw_character_conflict_evidence": conflict_evidence,
        "original_observation_prefix_conflicts": prefix_conflicts,
    }


def _preexisting_raw_views(gray, partition, dpi, engine, recognizer, output, root):
    """Freeze the finite existing-raw set before a provisional decision can stop calls."""
    from .observation_cache import (
        configured_cache, model_spec, tesseract_identity, tesseract_spec,
    )

    cache = configured_cache()
    engine_bytes = tesseract_identity(engine) if cache is not None else None
    prior_identity_path = output / "model_identity.json"
    prior_identity = (
        json.loads(prior_identity_path.read_text(encoding="utf-8"))
        if prior_identity_path.exists() else None
    )
    known, slots = {}, []
    box = partition["bbox_xyxy_px"]
    known_dir = output / "known_raw_views"
    known_dir.mkdir(exist_ok=True)
    for index in range(POLICY["maximum_views_per_engine"]):
        for family, spec in [
            ("Tesseract", POLICY["Tesseract_views"][index]),
            ("PP-OCR", POLICY["PP_OCR_views"][index]),
        ]:
            normalized, actual = _view(gray, partition, spec["scale"], spec["padding"])
            payload, receipt, original_meta, cache_record = None, None, None, None
            availability = "ABSENT"
            if cache is not None:
                if family == "Tesseract":
                    request = tesseract_spec(
                        normalized, actual, padding=spec["padding"], psm=spec["psm"],
                        dpi=int(dpi) * spec["scale"], engine=engine_bytes,
                    )
                    hit = cache.lookup_tesseract(request)
                else:
                    original, tensor = independent.prepare_model_input(actual)
                    request = model_spec(original, tensor, recognizer.identity)
                    hit = cache.lookup(request)
                if hit is not None:
                    payload, receipt = hit
                    cache_record = cache.root / "entries" / receipt["kind"] / (receipt["key"] + ".json")
                    availability = "RAW_CACHE"
            if payload is None and family == "Tesseract":
                name = f'line-x{spec["scale"]}-p{spec["psm"]}'
                meta_path, raw_path = output / (name + ".json"), output / (name + ".tsv")
                if meta_path.exists() or raw_path.exists():
                    if not meta_path.exists() or not raw_path.exists():
                        raise ValueError("SINGLE_LINE_PARTIAL_RAW_CHECKPOINT")
                    original_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    payload = raw_path.read_bytes()
                    expected = {
                        "crop_xyxy_px": [0, 0, normalized.shape[1], normalized.shape[0]],
                        "psm": spec["psm"], "crop_array_sha256": base.source_array_sha256(normalized),
                        "pixel_scale": [1, 1], "source_pixels_modified": False,
                        "language": "eng", "recognition_dpi": int(dpi) * spec["scale"],
                        "external_white_padding_px": spec["padding"],
                        "padding_replaces_source_pixels": False,
                    }
                    if (
                        original_meta.get("specification") != expected
                        or original_meta.get("status") != "COMPLETED"
                        or original_meta.get("return_code") != 0
                        or original_meta.get("tsv_sha256") != _sha(payload)
                    ):
                        raise ValueError("SINGLE_LINE_RAW_CHECKPOINT_CHANGED")
                    receipt = original_meta.get("raw_observation_cache")
                    availability = "OUTPUT_CHECKPOINT"
            if payload is None and family == "PP-OCR":
                raw_path, png_path = (
                    output / f"model-view-{index}{suffix}" for suffix in (".json", ".png")
                )
                if raw_path.exists() or png_path.exists():
                    if not raw_path.exists() or not png_path.exists() or prior_identity != recognizer.identity:
                        raise ValueError("SINGLE_LINE_MODEL_CHECKPOINT_IDENTITY_CHANGED")
                    payload = raw_path.read_bytes()
                    prediction = json.loads(payload)
                    original, tensor = independent.prepare_model_input(actual)
                    if (
                        not _model_integrity(prediction)
                        or prediction.get("input_array_sha256") != _sha(original.tobytes())
                        or prediction.get("model_tensor_sha256") != _sha(tensor.tobytes())
                    ):
                        raise ValueError("SINGLE_LINE_MODEL_CHECKPOINT_CHANGED")
                    availability = "OUTPUT_CHECKPOINT"
            slot = {
                "engine": family, "view_index": index, "normalization": spec,
                "input_array_sha256": _sha(actual.tobytes()), "availability": availability,
                "raw_observation_cache": receipt,
            }
            if payload is not None:
                name = f"{'tesseract' if family == 'Tesseract' else 'ppocr'}-{index}"
                raw_copy = known_dir / (name + ".raw")
                raw_copy.write_bytes(payload)
                slot["raw_payload"] = _file_record(raw_copy, root)
                if cache_record is not None:
                    record_copy = known_dir / (name + ".cache-record.json")
                    record_copy.write_bytes(cache_record.read_bytes())
                    slot["cache_record"] = _file_record(record_copy, root)
                if original_meta is not None:
                    meta_copy = known_dir / (name + ".checkpoint-metadata.json")
                    save_json(meta_copy, original_meta)
                    slot["checkpoint_metadata"] = _file_record(meta_copy, root)
                known[(family, index)] = {
                    "payload": payload, "receipt": receipt,
                    "original_metadata": original_meta, "engine_identity": engine_bytes,
                    "availability": availability,
                }
            slots.append(slot)
    inventory = {
        "schema": "single-line-preexisting-raw-view-inventory-v1",
        "source_array_sha256": base.source_array_sha256(gray),
        "source_bbox_xyxy_px": box,
        "recorded_before_any_recognition_or_adoption": True,
        "missing_views_do_not_request_recognition": True,
        "views": slots,
    }
    path = output / "preexisting_raw_view_inventory.json"
    save_json(path, inventory)
    return known, _file_record(path, root)


def _materialize_known_tesseract(hit, normalized, actual, spec, dpi, output, name, engine):
    """Use captured bytes directly: a later cache miss can never launch a process."""
    from PIL import Image

    payload, receipt = hit["payload"], hit["receipt"]
    old = hit["original_metadata"] or (receipt or {}).get("producer", {}).get("metadata") or {}
    raw = payload.decode("utf-8")
    base._check_reused_tsv_encoding(raw, old)
    pad, psm, scale = spec["padding"], spec["psm"], spec["scale"]
    png, tsv, meta_path = (output / (name + suffix) for suffix in (".png", ".tsv", ".json"))
    Image.fromarray(actual).save(png)
    tsv.write_bytes(payload)
    command = old.get("command") or [
        engine["executable"], str(png), "stdout", "-l", "eng", "--oem", "1",
        "--psm", str(psm), "--dpi", str(int(dpi) * scale), "tsv",
    ]
    specification = {
        "crop_xyxy_px": [0, 0, normalized.shape[1], normalized.shape[0]],
        "psm": psm, "crop_array_sha256": base.source_array_sha256(normalized),
        "pixel_scale": [1, 1], "source_pixels_modified": False,
        "language": "eng", "recognition_dpi": int(dpi) * scale,
        "external_white_padding_px": pad, "padding_replaces_source_pixels": False,
    }
    metadata = {
        "status": "COMPLETED", "return_code": 0, "specification": specification,
        "command": command, "command_executed_for_this_request": False,
        "engine_version": engine.get("version", old.get("engine_version")),
        "engine_identity": (receipt or {}).get("producer", {}).get("engine", old.get("engine_identity")),
        "consumer_installed_engine_identity": hit["engine_identity"],
        "recognition_output_encoding": old.get("recognition_output_encoding"),
        "tsv_sha256": _sha(payload), "image_sha256": _sha(png.read_bytes()),
        "raw_observation_cache": receipt,
        "reused_checkpoint": hit["availability"] == "OUTPUT_CHECKPOINT",
        "reused_raw_observation": hit["availability"] == "RAW_CACHE",
        "resource_scope": "Preexisting raw bytes replayed; no recognition child launched",
    }
    save_json(meta_path, metadata)
    words = base._parse_tsv(raw, [-pad, -pad, actual.shape[1] - pad, actual.shape[0] - pad], name, psm)
    return base._bind_ocr_words(words, specification, metadata), metadata


def _verify_preexisting_raw_views(gray, partition, evidence, root):
    """Every known record must be present, even when the other engine has no view."""
    from .observation_cache import (
        SCHEMA as cache_schema,
        digest as cache_digest,
        historical_tesseract_spec,
        model_spec,
        tesseract_spec,
    )

    inventory = json.loads(_read_record(root, evidence["preexisting_raw_view_inventory"]))
    if (
        inventory.get("schema") != "single-line-preexisting-raw-view-inventory-v1"
        or inventory.get("source_array_sha256") != base.source_array_sha256(gray)
        or inventory.get("source_bbox_xyxy_px") != partition["bbox_xyxy_px"]
        or inventory.get("recorded_before_any_recognition_or_adoption") is not True
        or inventory.get("missing_views_do_not_request_recognition") is not True
    ):
        raise ValueError("SINGLE_LINE_KNOWN_RAW_INVENTORY_CHANGED")
    saved = {
        "Tesseract": {v["view_index"]: v for v in evidence["tesseract_views"]},
        "PP-OCR": {v["view_index"]: v for v in evidence["ppocr_views"]},
    }
    expected_keys = {(family, i) for family in saved for i in range(POLICY["maximum_views_per_engine"])}
    rows = inventory["views"]
    keys = [(row["engine"], row["view_index"]) for row in rows]
    if len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise ValueError("SINGLE_LINE_KNOWN_RAW_PLAN_INCOMPLETE")
    for slot in rows:
        family, index = slot["engine"], slot["view_index"]
        spec = POLICY["Tesseract_views" if family == "Tesseract" else "PP_OCR_views"][index]
        normalized, actual = _view(gray, partition, spec["scale"], spec["padding"])
        if slot["normalization"] != spec or slot["input_array_sha256"] != _sha(actual.tobytes()):
            raise ValueError("SINGLE_LINE_KNOWN_RAW_SOURCE_INPUT_CHANGED")
        availability = slot["availability"]
        if availability == "ABSENT":
            if any(k in slot for k in ("raw_payload", "cache_record", "checkpoint_metadata")) or slot["raw_observation_cache"] is not None:
                raise ValueError("SINGLE_LINE_MISSING_RAW_HAS_RECORD")
            continue
        if availability not in {"RAW_CACHE", "OUTPUT_CHECKPOINT"} or index not in saved[family]:
            raise ValueError("SINGLE_LINE_KNOWN_RAW_VIEW_OMITTED")
        payload = _read_record(root, slot["raw_payload"])
        view = saved[family][index]
        if family == "Tesseract":
            if payload != _read_record(root, view["raw_tsv"]) or view["command_executed_for_this_request"]:
                raise ValueError("SINGLE_LINE_KNOWN_TESSERACT_RAW_CHANGED")
        elif json.loads(payload) != view["prediction"] or view["model_inference_executed_for_this_request"]:
            raise ValueError("SINGLE_LINE_KNOWN_MODEL_RAW_CHANGED")
        if availability == "RAW_CACHE":
            record = json.loads(_read_record(root, slot["cache_record"]))
            receipt = slot["raw_observation_cache"]
            if family == "Tesseract":
                metadata = json.loads(_read_record(root, view["metadata"]))
                expected_request = tesseract_spec(
                    normalized, actual, padding=spec["padding"], psm=spec["psm"],
                    dpi=evidence["recognition_dpi"] * spec["scale"],
                    engine=metadata["consumer_installed_engine_identity"],
                )
                if receipt.get("kind") == "historical-tesseract-tsv":
                    # Preserve the explicitly limited historical namespace. Its
                    # input pixels/configuration must still match this exact
                    # source view; this does not manufacture missing engine hashes.
                    expected_request = historical_tesseract_spec(
                        expected_request, record["specification"]["source_sha256"],
                    )
                actual_receipt = metadata.get("raw_observation_cache")
            else:
                identity = json.loads(_read_record(root, evidence["model_identity"]))
                original, tensor = independent.prepare_model_input(actual)
                expected_request = model_spec(original, tensor, identity)
                actual_receipt = view["observation_receipt"].get("raw_observation_cache")
            if record.get("specification") != expected_request:
                raise ValueError("SINGLE_LINE_KNOWN_CACHE_SOURCE_CONFIGURATION_CHANGED")
            if (
                record.get("schema") != cache_schema
                or record.get("key") != cache_digest(expected_request)
                or receipt.get("key") != record["key"]
                or receipt.get("kind") != expected_request["kind"]
                or receipt.get("producer") != record.get("producer")
                or actual_receipt != receipt
                or receipt.get("record_sha256") != slot["cache_record"]["sha256"]
                or record.get("payload_sha256") != _sha(payload)
                or receipt.get("payload_sha256") != _sha(payload)
                or record.get("payload_bytes") != len(payload)
            ):
                raise ValueError("SINGLE_LINE_KNOWN_CACHE_RECORD_CHANGED")
        elif family == "Tesseract":
            original_meta = json.loads(_read_record(root, slot["checkpoint_metadata"]))
            if original_meta.get("tsv_sha256") != _sha(payload):
                raise ValueError("SINGLE_LINE_KNOWN_CHECKPOINT_RAW_CHANGED")
    return {"all_preexisting_views_replayed": True, "known_view_count": sum(r["availability"] != "ABSENT" for r in rows)}


def recognize_single_line_label(
    gray, roi, plan, output_dir, *, dpi=200, recognizer=None, evidence_root=None
):
    """At most two finite image views per existing recognizer; no text hints."""
    global _RECOGNIZER
    from PIL import Image
    from .text_contact_audit import compare_contact_source_replay

    check_cancel("SINGLE_LINE_LABEL_RECOGNITION")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(evidence_root) if evidence_root is not None else output
    partition, error = _partition(
        gray, roi, plan["source_partition"]["seed_bbox_xyxy_px"]
    )
    partition_comparison = compare_contact_source_replay(
        plan["source_partition"], partition, scope="partition"
    )
    if error or not partition_comparison["pass"]:
        raise ValueError("SINGLE_LINE_PLANNED_SOURCE_PARTITION_CHANGED:" + str(error))
    # Retain the already bound original record.  Permitted machine-roundoff
    # in derived round-fit statistics must not rewrite source proof digests.
    partition = copy.deepcopy(plan["source_partition"])
    observation_binding = plan.get("upstream_observations")
    if plan.get("region_ids") and (
        not observation_binding
        or observation_binding.get("region_ids") != plan["region_ids"]
    ):
        raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATIONS_NOT_BOUND")
    source_observations = _observation_spans(
        gray, roi, partition, observation_binding, root
    )
    engine = base._resolve_tesseract(
        os.environ.get("I2CAD_TESSERACT", ""), os.environ.get("TESSDATA_PREFIX")
    )
    save_json(
        output / "policy_frozen_before_recognition.json",
        {"policy": POLICY, "engine": engine},
    )
    if recognizer is None:
        if _RECOGNIZER is None:
            _RECOGNIZER = independent.IndependentRecognizer()
        recognizer = _RECOGNIZER
    known_raw, known_inventory = _preexisting_raw_views(
        gray, partition, dpi, engine, recognizer, output, root
    )
    save_json(output / "model_identity.json", recognizer.identity)
    box = partition["bbox_xyxy_px"]
    original = gray[box[1] : box[3], box[0] : box[2]]
    Image.fromarray(original).save(output / "original_source.png")
    t_views, p_views, decision = [], [], None
    for index, (t_spec, p_spec) in enumerate(
        zip(POLICY["Tesseract_views"], POLICY["PP_OCR_views"])
    ):
        check_cancel("SINGLE_LINE_LABEL_VIEW")
        allow_new = decision is None or not decision["accepted"]
        t_hit = known_raw.get(("Tesseract", index))
        if allow_new or t_hit is not None:
            scale, pad, psm = t_spec["scale"], t_spec["padding"], t_spec["psm"]
            normalized, actual = _view(gray, partition, scale, pad)
            name = f"line-x{scale}-p{psm}"
            if t_hit is not None:
                words, metadata = _materialize_known_tesseract(
                    t_hit, normalized, actual, t_spec, dpi, output, name, engine
                )
            else:
                words, metadata = base._ocr(
                    normalized,
                    [0, 0, normalized.shape[1], normalized.shape[0]],
                    psm,
                    output,
                    name,
                    None,
                    padding_px=pad,
                    dpi=int(dpi) * scale,
                )
            raw_valid = _raw_tsv_integrity((output / (name + ".tsv")).read_bytes())
            t_views.append(
                {
                    "view_index": index,
                    "normalization": {
                        **t_spec,
                        "source_bbox_xyxy_px": box,
                        "resampling": "NEAREST_NEIGHBOR_REPEATED_SOURCE_SAMPLES",
                        "input_array_sha256": _sha(actual.tobytes()),
                        "original_source_pixels_modified": False,
                    },
                    "raw_tsv": _file_record(output / (name + ".tsv"), root),
                    "metadata": _file_record(output / (name + ".json"), root),
                    "recognition_image": _file_record(output / (name + ".png"), root),
                    "words": _mapped_words(words, box, scale),
                    "raw_tsv_integrity": raw_valid,
                    "command_executed_for_this_request": bool(
                        metadata.get("command_executed_for_this_request")
                    ),
                }
            )
        p_hit = known_raw.get(("PP-OCR", index))
        if allow_new or p_hit is not None:
            _, actual_p = _view(gray, partition, p_spec["scale"], p_spec["padding"])
            if p_hit is not None:
                prediction = json.loads(p_hit["payload"])
                receipt = {
                    "raw_observation_cache": p_hit["receipt"],
                    "model_inference_executed_for_this_request": False,
                    "reused_checkpoint": p_hit["availability"] == "OUTPUT_CHECKPOINT",
                }
            else:
                prediction = recognizer.recognize(actual_p)
                receipt = getattr(recognizer, "last_observation", {})
            pname = f"model-view-{index}"
            Image.fromarray(actual_p).save(output / (pname + ".png"))
            save_json(output / (pname + ".json"), prediction)
            p_views.append(
                {
                    "view_index": index,
                    "normalization": {
                        **p_spec,
                        "source_bbox_xyxy_px": box,
                        "input_array_sha256": _sha(actual_p.tobytes()),
                        "original_source_pixels_modified": False,
                    },
                    "prediction_file": _file_record(output / (pname + ".json"), root),
                    "recognition_image": _file_record(output / (pname + ".png"), root),
                    "prediction": prediction,
                    "observation_receipt": receipt,
                    "model_inference_executed_for_this_request": bool(
                        receipt.get("model_inference_executed_for_this_request", True)
                    ),
                }
            )
        decision = _decision(t_views, p_views, partition, source_observations)
    geometry = (
        {
            "text": decision["text"],
            "x": box[0],
            "y": box[3],
            "height_px": box[3] - box[1],
            "width_px": box[2] - box[0],
            "rotation_deg_image": 0.0,
        }
        if decision["accepted"]
        else None
    )
    from .single_line_neighbor_clearance import proposed_text_round_white_gaps

    layout_adoption = (
        proposed_text_round_white_gaps(
            gray,
            roi,
            partition,
            geometry,
            dpi,
        )
        if geometry is not None
        else None
    )
    adopted, adoption_reasons = _adoption_decision(decision, layout_adoption)
    evidence = {
        "schema": "native-single-line-label-evidence-v1",
        "policy": POLICY,
        "source_partition": partition,
        "planned_source_partition_replay_comparison": partition_comparison,
        "original_source": _file_record(output / "original_source.png", root),
        "source_bbox_xyxy_px": box,
        "roi_xyxy_px": list(roi),
        "recognition_dpi": int(dpi),
        "source_array_sha256": base.source_array_sha256(gray),
        "tesseract_views": t_views,
        "ppocr_views": p_views,
        "preexisting_raw_view_inventory": known_inventory,
        "model_identity": _file_record(output / "model_identity.json", root),
        "producer": _producer_identity(),
        "upstream_observations": observation_binding,
        "planned_region_ids": plan.get("region_ids", []),
        "decision": decision,
        "text_geometry": geometry,
        "layout_adoption": layout_adoption,
        "expected_answers_provided": False,
        "original_source_pixels_modified": False,
        "raw_transcription_rewritten": False,
        "new_Tesseract_calls": sum(
            v["command_executed_for_this_request"] for v in t_views
        ),
        "new_model_calls": sum(
            v["model_inference_executed_for_this_request"] for v in p_views
        ),
    }
    result = {
        "accepted": adopted,
        "transcription_accepted": decision["accepted"],
        "text": decision["text"],
        "geometry": geometry,
        "bbox_xyxy_px": box,
        "evidence": evidence,
        "reasons": adoption_reasons,
        "new_Tesseract_calls": evidence["new_Tesseract_calls"],
        "new_model_calls": evidence["new_model_calls"],
    }
    save_json(output / "label_result.json", result)
    return result


def verify_single_line_label_evidence(gray, roi, evidence, evidence_root):
    """Recompute source separation, image transforms, raw text and adoption."""
    from PIL import Image
    from .text_contact_audit import compare_contact_source_replay

    result = {"pass": False, "new_OCR_calls": 0, "new_model_calls": 0}
    try:
        if (
            evidence.get("schema") != "native-single-line-label-evidence-v1"
            or evidence.get("policy") != POLICY
        ):
            raise ValueError("SINGLE_LINE_POLICY_CHANGED")
        if evidence.get("producer") != _producer_identity():
            raise ValueError("SINGLE_LINE_PRODUCER_CHANGED")
        if (
            evidence.get("roi_xyxy_px") != list(roi)
            or evidence.get("source_array_sha256") != base.source_array_sha256(gray)
            or evidence.get("original_source_pixels_modified") is not False
            or evidence.get("expected_answers_provided") is not False
            or evidence.get("raw_transcription_rewritten") is not False
        ):
            raise ValueError("SINGLE_LINE_ORIGINAL_SOURCE_BINDING_CHANGED")
        partition, error = _partition(
            gray, roi, evidence["source_partition"]["seed_bbox_xyxy_px"]
        )
        partition_comparison = compare_contact_source_replay(
            evidence["source_partition"], partition, scope="partition"
        )
        result["source_partition_replay_comparison"] = partition_comparison
        if error or not partition_comparison["pass"]:
            raise ValueError("SINGLE_LINE_SOURCE_PARTITION_CHANGED:" + str(error))
        partition = copy.deepcopy(evidence["source_partition"])
        box = partition["bbox_xyxy_px"]
        if evidence.get("source_bbox_xyxy_px") != box:
            raise ValueError("SINGLE_LINE_SOURCE_BBOX_CHANGED")
        if "upstream_observations" not in evidence:
            raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATION_BINDING_MISSING")
        binding = evidence["upstream_observations"]
        if evidence.get("planned_region_ids") and (
            not binding or binding.get("region_ids") != evidence["planned_region_ids"]
        ):
            raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATION_BINDING_CHANGED")
        source_observations = _observation_spans(
            gray, roi, partition, binding, evidence_root
        )
        original_png = _read_record(evidence_root, evidence["original_source"])
        if not np.array_equal(
            np.asarray(Image.open(BytesIO(original_png)).convert("L")),
            gray[box[1] : box[3], box[0] : box[2]],
        ):
            raise ValueError("SINGLE_LINE_ORIGINAL_IMAGE_CHANGED")
        saved_t, saved_p = evidence["tesseract_views"], evidence["ppocr_views"]
        if (
            not 1 <= len(saved_t) <= POLICY["maximum_views_per_engine"]
            or not 1 <= len(saved_p) <= POLICY["maximum_views_per_engine"]
            or [v["view_index"] for v in saved_t] != list(range(len(saved_t)))
            or [v["view_index"] for v in saved_p] != list(range(len(saved_p)))
        ):
            raise ValueError("SINGLE_LINE_FINITE_VIEW_COUNT_CHANGED")
        dpi = evidence.get("recognition_dpi")
        if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
            raise ValueError("SINGLE_LINE_DPI_INVALID")
        t_views, p_views = [], []
        for index, (view, expected) in enumerate(
            zip(saved_t, POLICY["Tesseract_views"])
        ):
            scale, pad, psm = expected["scale"], expected["padding"], expected["psm"]
            normalized, actual = _view(gray, partition, scale, pad)
            norm = {
                **expected,
                "source_bbox_xyxy_px": box,
                "resampling": "NEAREST_NEIGHBOR_REPEATED_SOURCE_SAMPLES",
                "input_array_sha256": _sha(actual.tobytes()),
                "original_source_pixels_modified": False,
            }
            if view.get("view_index") != index or view.get("normalization") != norm:
                raise ValueError("SINGLE_LINE_TESSERACT_VIEW_CHANGED")
            raw = _read_record(evidence_root, view["raw_tsv"])
            if not _raw_tsv_integrity(raw) or view.get("raw_tsv_integrity") is not True:
                raise ValueError("SINGLE_LINE_RAW_TSV_INVALID")
            meta = json.loads(_read_record(evidence_root, view["metadata"]))
            png = _read_record(evidence_root, view["recognition_image"])
            spec = meta["specification"]
            if (
                meta.get("status") != "COMPLETED"
                or meta.get("return_code") != 0
                or meta.get("tsv_sha256") != _sha(raw)
                or meta.get("image_sha256") != _sha(png)
                or spec.get("crop_xyxy_px")
                != [0, 0, normalized.shape[1], normalized.shape[0]]
                or spec.get("crop_array_sha256") != base.source_array_sha256(normalized)
                or spec.get("psm") != psm
                or spec.get("external_white_padding_px") != pad
                or spec.get("recognition_dpi") != dpi * scale
                or spec.get("language") != "eng"
                or spec.get("pixel_scale") != [1, 1]
                or spec.get("source_pixels_modified") is not False
                or spec.get("padding_replaces_source_pixels") is not False
                or not np.array_equal(
                    actual, np.asarray(Image.open(BytesIO(png)).convert("L"))
                )
            ):
                raise ValueError("SINGLE_LINE_TESSERACT_SOURCE_TRANSFORM_CHANGED")
            command = meta.get("command", [])
            for flag, value in [
                ("--psm", str(psm)),
                ("--dpi", str(dpi * scale)),
                ("-l", "eng"),
                ("--oem", "1"),
            ]:
                if flag not in command or command[command.index(flag) + 1] != value:
                    raise ValueError("SINGLE_LINE_TESSERACT_ENGINE_COMMAND_CHANGED")
            if not str(meta.get("engine_version", "")).startswith("tesseract "):
                raise ValueError("SINGLE_LINE_TESSERACT_IDENTITY_MISSING")
            words = base._parse_tsv(
                raw.decode("utf-8"),
                [-pad, -pad, actual.shape[1] - pad, actual.shape[0] - pad],
                f"line-x{scale}-p{psm}",
                psm,
            )
            mapped = _mapped_words(words, box, scale)
            fields = (
                "text",
                "confidence",
                "bbox_xyxy_px",
                "context_id",
                "psm",
                "line_key",
                "word_num",
            )
            if [{k: w.get(k) for k in fields} for w in mapped] != [
                {k: w.get(k) for k in fields} for w in view.get("words", [])
            ]:
                raise ValueError("SINGLE_LINE_SAVED_WORDS_DIFFER_FROM_RAW_TSV")
            if not isinstance(
                view.get("command_executed_for_this_request"), bool
            ) or view["command_executed_for_this_request"] != meta.get(
                "command_executed_for_this_request"
            ):
                raise ValueError("SINGLE_LINE_TESSERACT_EXECUTION_RECEIPT_CHANGED")
            # The permissive common parser cannot hide invalid raw word rows;
            # it is used only after the strict raw integrity check above.
            t_views.append({"words": mapped, "raw_tsv_integrity": True})
        identity = json.loads(_read_record(evidence_root, evidence["model_identity"]))
        if (
            identity.get("model_sha256") != independent.MODEL_SHA256
            or identity.get("policy") != independent.POLICY
        ):
            raise ValueError("SINGLE_LINE_MODEL_IDENTITY_CHANGED")
        for index, (view, expected) in enumerate(zip(saved_p, POLICY["PP_OCR_views"])):
            _, actual = _view(gray, partition, expected["scale"], expected["padding"])
            norm = {
                **expected,
                "source_bbox_xyxy_px": box,
                "input_array_sha256": _sha(actual.tobytes()),
                "original_source_pixels_modified": False,
            }
            if view.get("view_index") != index or view.get("normalization") != norm:
                raise ValueError("SINGLE_LINE_MODEL_VIEW_CHANGED")
            png = _read_record(evidence_root, view["recognition_image"])
            prediction = json.loads(
                _read_record(evidence_root, view["prediction_file"])
            )
            _, tensor = independent.prepare_model_input(actual)
            if (
                not _model_integrity(prediction)
                or prediction != view.get("prediction")
                or prediction.get("input_array_sha256") != _sha(actual.tobytes())
                or prediction.get("input_shape_px") != list(actual.shape)
                or prediction.get("model_tensor_shape") != list(tensor.shape)
                or prediction.get("model_tensor_sha256") != _sha(tensor.tobytes())
                or prediction.get("source_geometry_modified") is not False
                or prediction.get("raw_transcription_rewritten") is not False
                or not np.array_equal(
                    actual, np.asarray(Image.open(BytesIO(png)).convert("L"))
                )
            ):
                raise ValueError("SINGLE_LINE_MODEL_SOURCE_TRANSFORM_CHANGED")
            receipt = view.get("observation_receipt", {})
            if (
                not isinstance(
                    view.get("model_inference_executed_for_this_request"), bool
                )
                or receipt.get("model_inference_executed_for_this_request")
                != view["model_inference_executed_for_this_request"]
            ):
                raise ValueError("SINGLE_LINE_MODEL_EXECUTION_RECEIPT_CHANGED")
            p_views.append({"prediction": prediction})
        known_views = _verify_preexisting_raw_views(
            gray, partition, evidence, evidence_root
        )
        decision = _decision(t_views, p_views, partition, source_observations)
        if decision != evidence.get("decision") or not decision["accepted"]:
            raise ValueError("SINGLE_LINE_RAW_DECISION_NOT_APPROVED")
        geometry = {
            "text": decision["text"],
            "x": box[0],
            "y": box[3],
            "height_px": box[3] - box[1],
            "width_px": box[2] - box[0],
            "rotation_deg_image": 0.0,
        }
        if geometry != evidence.get("text_geometry"):
            raise ValueError("SINGLE_LINE_SOURCE_LAYOUT_OR_TEXT_CHANGED")
        if evidence.get("new_Tesseract_calls") != sum(
            v["command_executed_for_this_request"] for v in saved_t
        ) or evidence.get("new_model_calls") != sum(
            v["model_inference_executed_for_this_request"] for v in saved_p
        ):
            raise ValueError("SINGLE_LINE_EXECUTION_COUNTS_CHANGED")
        from .single_line_neighbor_clearance import proposed_text_round_white_gaps

        layout_adoption = proposed_text_round_white_gaps(
            gray,
            roi,
            partition,
            geometry,
            dpi,
        )
        if layout_adoption != evidence.get("layout_adoption"):
            raise ValueError("SINGLE_LINE_LAYOUT_ADOPTION_EVIDENCE_CHANGED")
        result.update(transcription_source_pass=True, layout_adoption=layout_adoption)
        if not layout_adoption["pass"]:
            raise ValueError("SINGLE_LINE_SOURCE_WHITE_GAP_LAYOUT_REJECTED")
        result.update(
            {
                "pass": True,
                "text": decision["text"],
                "bbox_xyxy_px": box,
                "geometry": geometry,
                "source_component_count": len(partition["components"]),
                "source_punctuation_count": partition["punctuation_component_count"],
                "source_text_normalization": decision["source_text_normalization"],
                "Tesseract_canonical_word_texts": decision[
                    "Tesseract_canonical_word_texts"
                ],
                "Tesseract_views_replayed": len(saved_t),
                "PP_OCR_views_replayed": len(saved_p),
                "all_raw_artifacts_read_and_hashed": True,
                "original_pixels_derived_views_model_tensors_and_adoption_recomputed": True,
                **known_views,
            }
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        OSError,
        UnicodeError,
        OverflowError,
    ) as exc:
        result["reason"] = str(exc)
    return result


def refine_single_line_labels(
    gray,
    texts,
    output_dir,
    *,
    roi=None,
    dpi=200,
    source_sha256=None,
    recognizer=None,
    progress_callback=None,
    evidence_root=None,
):
    """Ordinary text-contract refinement, preserving all prior source records."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(evidence_root) if evidence_root is not None else output.parent
    roi = list(texts["roi_xyxy_px"] if roi is None else roi)
    if texts.get("single_line_label_recovery", {}).get("version") == POLICY["version"]:
        # The ordinary resume importer must bind producer and raw files first.
        # Still replay every adopted record here: a sidecar success bit is not
        # permission to omit the actual source/recognizer checks.
        for row in texts["regions"]:
            if row.get("single_line_recovery"):
                check = verify_single_line_label_evidence(
                    gray, roi, row["single_line_recovery"], root
                )
                if not check["pass"]:
                    raise ValueError(
                        "SINGLE_LINE_RESUME_EVIDENCE_FAILED:" + check.get("reason", "")
                    )
        return copy.deepcopy(texts)
    plan = plan_single_line_labels(gray, texts, roi)
    upstream_path = output / "upstream_completed_text.json"
    if not upstream_path.exists():
        save_json(upstream_path, texts)
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    # Ordinary pipeline snapshots the completed raw stage before ownership is
    # rewritten. Bind that exact snapshot, rather than copying a chosen string.
    observed_keys = ("id", "text", "bbox_xyxy_px", "words")
    if [
        {key: row.get(key) for key in observed_keys} for row in upstream["regions"]
    ] != [
        {key: row.get(key) for key in observed_keys} for row in texts["regions"]
    ]:
        raise ValueError("SINGLE_LINE_UPSTREAM_OBSERVATIONS_DIFFER_FROM_PLAN_INPUT")
    upstream_record = _file_record(upstream_path, root)
    for row_plan in plan["plans"]:
        row_plan["upstream_observations"] = {
            "snapshot": upstream_record,
            "region_ids": row_plan["region_ids"],
        }
    save_json(output / "plan.json", plan)
    result = copy.deepcopy(texts)
    result["text_contact_geometry_plans"] = plan.get("text_contact_geometry_plans", [])
    prior_by_id = {row["id"]: row for row in texts["regions"]}
    recovered, attempts, removed_groups = [], [], []
    for index, row_plan in enumerate(plan["plans"]):
        check_cancel("SINGLE_LINE_LABEL_QUEUE")
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "SINGLE_LINE_LABEL",
                    "completed": index + 1,
                    "total": len(plan["plans"]),
                    "id": row_plan["id"],
                }
            )
        observation = recognize_single_line_label(
            gray,
            roi,
            row_plan,
            output / "labels" / row_plan["id"],
            dpi=dpi,
            recognizer=recognizer,
            evidence_root=root,
        )
        attempt = {
            "id": row_plan["id"],
            "region_ids": row_plan["region_ids"],
            "bbox_xyxy_px": observation["bbox_xyxy_px"],
            "accepted": observation["accepted"],
            "text": observation["text"],
            "reasons": observation["reasons"],
            "new_Tesseract_calls": observation["new_Tesseract_calls"],
            "new_model_calls": observation["new_model_calls"],
        }
        attempts.append(attempt)
        if not observation["accepted"]:
            save_json(
                output / "progress.json",
                {
                    "completed_plans": index + 1,
                    "recovered_labels": recovered,
                    "attempts": attempts,
                    "source_sha256": source_sha256,
                },
            )
            continue
        evidence = observation["evidence"]
        cold = verify_single_line_label_evidence(gray, roi, evidence, root)
        if not cold["pass"]:
            raise ValueError(
                "SINGLE_LINE_FRESH_RAW_REPLAY_FAILED:" + cold.get("reason", "")
            )
        region_id, group_id = "SLR-" + row_plan["id"][3:], "SLG-" + row_plan["id"][3:]
        partition = evidence["source_partition"]
        box, text = observation["bbox_xyxy_px"], observation["text"]
        chosen = evidence["tesseract_views"][
            evidence["decision"]["Tesseract_view_index"]
        ]
        # Derived raw observations have their own source/transform contract.
        # Do not fabricate old unmodified-crop provenance for these words.
        canonical_words = evidence["decision"]["Tesseract_canonical_word_texts"]
        words = [
            {
                "id": f"{region_id}-W{wi + 1:02d}",
                "text": canonical_words[wi],
                "raw_text": word["text"],
                "bbox_xyxy_px": word["bbox_xyxy_px"],
                "confidence": word["confidence"],
                "required_confidence": POLICY["Tesseract_numeric_confidence"]
                if word["text"].isdigit()
                else POLICY["Tesseract_word_confidence"],
                "agreement_pass": True,
                "agreement_basis": "single_line_complete_source_and_independent_raw_engines",
                "Tesseract_aggregate_score_is_advisory": bool(
                    partition.get("text_contact_separation")
                ),
                "source_acceptance_basis": evidence["decision"]["adoption_basis"],
                "raw_text_unchanged": canonical_words[wi] == word["text"],
                "source_canonicalization_recorded": canonical_words[wi] != word["text"],
                "single_line_evidence_id": row_plan["id"],
            }
            for wi, word in enumerate(chosen["words"])
        ]
        superseded = [
            {
                "region_id": rid,
                "previous_record_sha256": _digest(prior_by_id[rid]),
                "previous_record_retained": True,
            }
            for rid in row_plan["region_ids"]
        ]
        new_region = {
            "id": region_id,
            "bbox_xyxy_px": box,
            "text": text,
            "words": words,
            "discovery_bbox_xyxy_px": partition["seed_bbox_xyxy_px"],
            "inspection_bbox_xyxy_px": partition["context_bbox_xyxy_px"],
            "complete": True,
            "accepted": False,
            "source_review_required": True,
            "status": "TEXT_PROPOSAL_PENDING_SOURCE_REVIEW",
            "unresolved_reasons": [],
            "enclosure": None,
            "single_line_recovery": evidence,
            "supersedes_pending_regions": superseded,
            "compact_source_ink_mask": {
                "runs_y_x0_x1": partition["source_support_runs_y_x0_x1"],
                "component_labels": sorted(
                    {
                        label
                        for c in partition["components"]
                        for label in c["source_component_labels"]
                    }
                ),
                "source_erasure_authorized": False,
            },
            "completeness_evidence": {
                "producer": __name__,
                "single_line_recovery": evidence,
                "legacy_unmodified_crop_alternatives_not_fabricated": True,
            },
        }
        result["regions"].append(new_region)
        old_ids = set(row_plan["region_ids"])
        keep = []
        for group in result["groups"]:
            if (
                group.get("region_ids")
                and set(group["region_ids"]) <= old_ids
                and not group.get("complete")
            ):
                if not _single_baseline_group(group, prior_by_id):
                    raise ValueError("SINGLE_LINE_CANNOT_SUPERSEDE_MULTILINE_GROUP")
                removed_groups.append(copy.deepcopy(group))
            else:
                keep.append(group)
        new_group = {
            "id": group_id,
            "geometry_type": "TEXT",
            "kind": "single_line",
            "bbox_xyxy_px": box,
            "region_ids": [region_id],
            "text": text,
            "complete": True,
            "source_review_required": True,
            "unresolved_reasons": [],
            "enclosure": None,
            "numeric_label": False,
            "grouping_is_semantic_proof": False,
            "automatic_formal_adoption": False,
            "single_line_recovery": evidence,
            "lines": [
                {
                    "region_id": region_id,
                    "text": text,
                    "bbox_xyxy_px": box,
                    "complete": True,
                    "word_ids": [w["id"] for w in words],
                }
            ],
        }
        result["groups"] = keep + [new_group]
        result.setdefault("region_evidence_roots", {})[region_id] = "."
        recovered.append(
            {
                **attempt,
                "region_id": region_id,
                "group_id": group_id,
                "supersedes_pending_region_ids": row_plan["region_ids"],
                "source_replay_pass": True,
            }
        )
        save_json(
            output / "progress.json",
            {
                "completed_plans": index + 1,
                "recovered_labels": recovered,
                "attempts": attempts,
                "source_sha256": source_sha256,
            },
        )
    # The existing geometry ownership stage must actually run on the changed
    # text contract; retaining its old no-op cache would bypass that review.
    if "source_text_ownership" in result:
        result["prior_source_text_ownership"] = result.pop("source_text_ownership")
    if removed_groups:
        save_json(output / "superseded_pending_groups.json", removed_groups)
    raw_files = [
        _file_record(path, root)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name
        not in {"summary.json", "completed_text.json", "completed_stages.json"}
    ]
    summary = {
        "schema": "single-line-label-recovery-summary-v1",
        "version": POLICY["version"],
        "plan_count": len(plan["plans"]),
        "accepted_labels": len(recovered),
        "pending_labels": len(attempts) - len(recovered),
        "recovered_labels": recovered,
        "attempts": attempts,
        "geometrically_unresolved_regions": len(plan["rejected"]),
        "deferred_by_budget": len(plan["deferred_by_budget"]),
        "new_Tesseract_calls": sum(a["new_Tesseract_calls"] for a in attempts),
        "new_model_calls": sum(a["new_model_calls"] for a in attempts),
        "accepted_region_ids": [r["region_id"] for r in recovered],
        "protected_region_ids": plan["protected_region_ids"],
        "old_complete_regions_unchanged": all(
            prior_by_id[rid] == next(r for r in result["regions"] if r["id"] == rid)
            for rid in plan["protected_region_ids"]
        ),
        "superseded_pending_groups": len(removed_groups),
        "raw_evidence_files": raw_files,
        "source_sha256": source_sha256,
        "source_array_sha256": base.source_array_sha256(gray),
        "original_source_pixels_modified": False,
        "only_recognition_inputs_derived": True,
    }
    result["single_line_label_recovery"] = summary
    validate_text_regions(result, gray.shape, roi)
    save_json(output / "summary.json", summary)
    save_json(output / "completed_text.json", result)
    return result
