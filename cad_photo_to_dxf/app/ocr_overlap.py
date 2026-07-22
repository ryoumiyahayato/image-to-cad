from __future__ import annotations

from collections.abc import Iterable

from .auxiliary_recognition import TextCandidate


def _rank(candidate: TextCandidate) -> tuple[int, float, int, int]:
    compact = "".join(candidate.text.split())
    source_bonus = 2 if candidate.source == "rapidocr-tile" else 1
    return int(candidate.reviewed), float(candidate.confidence), len(compact), source_bonus


def _same_printed_region(first: TextCandidate, second: TextCandidate) -> bool:
    ax, ay, aw, ah = first.bbox
    bx, by, bw, bh = second.bbox
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection_width = max(0, right - left)
    intersection_height = max(0, bottom - top)
    if intersection_width <= 0 or intersection_height <= 0:
        return False

    first_area = max(1, aw * ah)
    second_area = max(1, bw * bh)
    coverage = intersection_width * intersection_height / float(min(first_area, second_area))
    vertical = intersection_height / float(max(1, min(ah, bh)))
    horizontal = intersection_width / float(max(1, min(aw, bw)))
    center_y_distance = abs((ay + ah * 0.5) - (by + bh * 0.5))
    same_baseline = center_y_distance <= max(2.0, min(ah, bh) * 0.38)

    first_text = "".join(first.text.split()).casefold()
    second_text = "".join(second.text.split()).casefold()
    text_related = bool(
        first_text
        and second_text
        and (
            first_text == second_text
            or first_text in second_text
            or second_text in first_text
        )
    )
    return bool(
        coverage >= 0.68
        or (
            same_baseline
            and vertical >= 0.78
            and horizontal >= 0.55
            and (text_related or coverage >= 0.48)
        )
    )


def collapse_overlapping_candidates(
    candidates: Iterable[TextCandidate],
) -> tuple[TextCandidate, ...]:
    """Remove shifted overview/tile duplicates before character export.

    OCR engines often return the same printed line twice with slightly different
    boxes or text. Keeping both creates visibly doubled CAD characters. The higher
    confidence and more complete candidate wins; adjacent non-overlapping labels
    remain separate.
    """

    ordered = sorted(candidates, key=_rank, reverse=True)
    kept: list[TextCandidate] = []
    for candidate in ordered:
        if any(_same_printed_region(candidate, existing) for existing in kept):
            continue
        kept.append(candidate)
    kept.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return tuple(kept)
