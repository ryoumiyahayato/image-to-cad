"""Validate the bounded input record before coordinate transport or tie breaking."""

import json
import numpy as np


def bound_digit_record(candidate):
    if (
        candidate.reviewed
        or len(candidate.text) != 1
        or candidate.text not in "0123456789"
        or not candidate.recognition_input
        or candidate.quad is None
    ):
        return None
    try:
        record = json.loads(candidate.recognition_input)
        if record["version"] != "orientation-bound-digit-v1":
            return None
        selected, context = record["selected"], record["context"]
        scores = np.asarray(selected["scores"], float)
        if (
            selected["text"] != candidate.text
            or scores.shape != (2,)
            or not np.isfinite(scores).all()
            or min(scores) < 0.55
            or abs(float(min(scores)) - candidate.confidence) > 1e-8
            or context["direction"] != 0
        ):
            return None
        anchors = context["anchors"]
        if not 2 <= len(anchors) <= 32:
            return None
        boxes = []
        for anchor in anchors:
            x, y, w, h = np.asarray(anchor["bbox"], float)
            direction, score = anchor["direction"]
            if (
                len("".join(anchor["text"].split())) < 2
                or str(direction) != "0"
                or not np.isfinite(float(score))
                or float(score) < 0.95
                or not np.isfinite((x, y, w, h)).all()
                or min(w, h) <= 0
            ):
                return None
            if any(
                x < ax + aw and x + w > ax and y < ay + ah and y + h > ay
                for ax, ay, aw, ah in boxes
            ):
                return None
            boxes.append((x, y, w, h))
        transform = np.asarray(record["frame_to_page"], float)
        crop_transform = np.asarray(record["source_to_crop"], float)
        if any(
            m.shape != (3, 3)
            or not np.isfinite(m).all()
            or abs(np.linalg.det(m)) < 1e-12
            for m in (transform, crop_transform)
        ):
            return None
        h, w = selected["crop_size"]
        corners = np.asarray(((0, 0, 1), (w, 0, 1), (w, h, 1), (0, h, 1)), float).T
        mapped = transform @ np.linalg.solve(crop_transform, corners)
        quad = (mapped[:2] / mapped[2]).T
        if not np.allclose(quad, candidate.quad, atol=1e-4, rtol=0):
            return None
        return record
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        np.linalg.LinAlgError,
    ):
        return None


def prefer_bound_digit(first, second):
    """Input evidence can beat confidence only for the same single-digit region."""
    if (
        second.reviewed
        or len(second.text) != 1
        or second.text not in "0123456789"
        or first.quad is None
        or second.quad is None
    ):
        return False
    return (
        bound_digit_record(first) is not None
        and bound_digit_record(second) is None
        and np.allclose(first.bbox, second.bbox, atol=1, rtol=0)
        and np.allclose(first.quad, second.quad, atol=1, rtol=0)
    )


def transport_bound_digit(candidate, matrix):
    record = bound_digit_record(candidate)
    if record is None:
        return candidate.recognition_input
    record["frame_to_page"] = (
        np.asarray(matrix, float) @ np.asarray(record["frame_to_page"], float)
    ).tolist()
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))
