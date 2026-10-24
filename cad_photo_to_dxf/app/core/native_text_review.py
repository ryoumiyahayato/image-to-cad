"""Same-snapshot PDF suggestion bindings. No automatic content authority."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from app.geometry.pdf_text_suggestions import SUGGESTION_KEY, SUGGESTION_VERSION

LAYOUT_VERSION = "source-anchored-review-layout-v1"


def bind_native_suggestions(structure, manifest):
    from app.core.structure import metadata_to_jsonable

    evidence = metadata_to_jsonable(structure.provenance.get(SUGGESTION_KEY))
    if not evidence or not evidence.get("rows"):
        return []
    source = manifest["source"]
    if (
        evidence.get("version") != SUGGESTION_VERSION
        or evidence.get("source_path") != str(Path(source["path"]).resolve())
        or evidence.get("physical_page") != source["physical_page"]
        or evidence.get("dpi") != source["cache_identity"]["dpi"]
        or evidence.get("source_size_px") != list(structure.source_size_px)
    ):
        return []
    # Finite local grid, not string similarity or a quadratic all-page search.
    rows = evidence["rows"]
    if len(rows) > 512:
        return []
    grid = {}
    for n, row in enumerate(rows):
        x0, y0, x1, y1 = row["bounds"]
        if not (
            0 <= x0 < x1 <= structure.source_size_px[0]
            and 0 <= y0 < y1 <= structure.source_size_px[1]
        ):
            continue
        for gx in range(x0 // 256, x1 // 256 + 1):
            for gy in range(y0 // 64, y1 // 64 + 1):
                grid.setdefault((gx, gy), set()).add(n)
    pairs = []
    by_row, by_text = {}, {}
    for binding in manifest["text_bindings"]:
        index = binding["index"]
        candidate = structure.texts[index]
        x, y, w, h = candidate.bbox
        if abs(candidate.rotation_deg) > 1 or w <= 0 or h <= 0:
            continue
        candidates = set()
        for gx in range(int(x) // 256, int(x + w) // 256 + 1):
            for gy in range(int(y) // 64, int(y + h) // 64 + 1):
                candidates.update(grid.get((gx, gy), ()))
        # A font/span fragment cannot masquerade as the complete OCR line.
        # Include unchecked and rejected native rows when looking for a second
        # fully contained fragment; their lack of proof is not blank space.
        if len(candidates) > 32:
            continue
        contained = [
            n
            for n in candidates
            if rows[n]["bounds"][0] >= x - 1
            and rows[n]["bounds"][1] >= y - 1
            and rows[n]["bounds"][2] <= x + w + 1
            and rows[n]["bounds"][3] <= y + h + 1
        ]
        if len(contained) != 1:
            continue
        for n in sorted(candidates):
            if rows[n].get("layout_eligible") is not True:
                continue
            a, b, c, d = rows[n]["bounds"]
            # Entire line containment AND comparable full-line coverage. An
            # overlap with an adjacent line is not a source identity.
            if (
                a >= x - 1
                and b >= y - 1
                and c <= x + w + 1
                and d <= y + h + 1
                and (c - a) / w >= 0.75
                and (d - b) / h >= 0.35
            ):
                pairs.append((index, n, binding))
                by_row[n] = by_row.get(n, 0) + 1
                by_text[index] = by_text.get(index, 0) + 1
    return [
        dict(
            suggestion_uuid=str(uuid4()),
            snapshot_uuid=manifest["snapshot_uuid"],
            text_source_uuid=binding["text_source_uuid"],
            binding=deepcopy(binding),
            snapshot_source=deepcopy(source),
            version=SUGGESTION_VERSION,
            status="NATIVE_SUGGESTED",
            evidence=deepcopy(rows[n]),
        )
        for index, n, binding in pairs
        if by_row[n] == 1 and by_text[index] == 1
    ]
