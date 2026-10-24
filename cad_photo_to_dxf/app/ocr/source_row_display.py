"""Bounded new-conversion display fits; no OCR or source deletion authority."""

from __future__ import annotations
from dataclasses import dataclass, replace
import base64
import cv2
import numpy as np
from app.core.structure import metadata_to_jsonable
from app.export.review_text import ReviewLayoutGuard
from app.geometry.pdf_text_suggestions import SUGGESTION_KEY

VERSION = "source-row-display-v1"
AUTO_VERSION = "source-row-ink-display-v1"


def _complete_display_rows(rows):
    """Collapse only identical source views and their proved prefix views."""
    unique, invalid = {}, set()
    for row in rows:
        fragments = row.get("fragments", ())
        key = tuple(sorted(f["object"] for f in fragments))
        if not key or len(key) != len(set(key)):
            continue
        if key in unique and unique[key] != row:
            invalid.add(key)
        unique.setdefault(key, row)
    output = []
    for key, row in unique.items():
        if key in invalid:
            continue
        parents = [
            (other, full)
            for other, full in unique.items()
            if set(key) < set(other) and other not in invalid
        ]
        covered = False
        for other, full in parents:
            shared = {f["object"]: f for f in full["fragments"]}
            ink = row.get("proof", {}).get("complete_ink_center_bounds")
            full_ink = full.get("proof", {}).get("complete_ink_center_bounds")
            if (
                all(shared[f["object"]] == f for f in row["fragments"])
                and ink
                and full_ink
                and full_ink[0] <= ink[0] <= ink[2] <= full_ink[2]
                and full_ink[1] <= ink[1] <= ink[3] <= full_ink[3]
            ):
                covered = True
            else:
                invalid.add(other)
        if not covered:
            output.append((key, row))
    return [row for key, row in output if key not in invalid]


def _display_obstacle_roles(structure, guard):
    """Read existing formal layer semantics; no source ownership is inferred.

    TRACE_TEXT_SYMBOL is the residual shape heuristic, not a proved engineering
    symbol. Explicit engineering entities and retained rule facts stay protected.
    Every unknown footprint stays visible in its original layer and geometry.
    """
    from pathlib import Path
    from tempfile import TemporaryDirectory
    import ezdxf
    from app.export.trace_single_export import export_final_structure_dxf

    unknown_layers = {
        "SOURCE_TEXT_OUTLINE",
        "TEXT_FALLBACK_OUTLINE",
        "RESIDUAL_GRAPHIC",
        "TRACE_TEXT_SYMBOL",
    }
    roles = []
    with TemporaryDirectory(prefix="image-to-cad-display-roles-") as folder:
        path = Path(folder) / "roles.dxf"
        export_final_structure_dxf(structure, path, allow_empty=True)
        doc = ezdxf.readfile(path)
        for entity in doc.modelspace():
            layer = doc.layers.get(entity.dxf.layer)
            if layer.is_off() or layer.is_frozen():
                continue
            # ReviewLayoutGuard creates one footprint for each supported,
            # nonempty entity. Any mismatch below rejects automatic fitting.
            if entity.dxftype() not in {
                "TEXT",
                "LINE",
                "LWPOLYLINE",
                "CIRCLE",
                "ARC",
                "HATCH",
                "IMAGE",
            }:
                continue
            roles.append(
                entity.dxftype() == "LWPOLYLINE" and entity.dxf.layer in unknown_layers
            )
    if len(roles) != len(guard.obstacles):
        return None
    return roles


def normalize_source_row_displays(structure, *, source_binding):
    """Fit each bound visible PDF row independently; retain every source object.

    This is a new-conversion entry, separate from explicit review transactions.
    Unknown fallback contacts are retained; new independent CAD contacts fail
    closed. PDF Unicode only binds a line and never changes an OCR string.
    """
    from pathlib import Path
    from app.core.native_text_review import bind_native_suggestions
    from app.export.review_text import (
        source_anchored_text_placement,
        glyph_footprint,
        polygon,
        visible_corners,
    )
    from app.export.ocr_outline_export import native_text_placement
    from PySide6.QtGui import QPainterPathStroker

    evidence = metadata_to_jsonable(structure.provenance.get(SUGGESTION_KEY, {}))
    rows = evidence.get("display_rows", ())
    if (
        not source_binding
        or not rows
        or len(rows) > 48
        or structure.provenance.get("review_snapshot_v1")
        or evidence.get("source_path")
        != str(Path(source_binding["document"]).resolve())
        or evidence.get("physical_page") != source_binding["page_number"]
        or evidence.get("dpi") != source_binding["requested_dpi"]
        or evidence.get("source_size_px") != list(structure.source_size_px)
    ):
        return structure
    # Reuse the same page/transform/whole-line/one-to-one binding contract as
    # native review, with the separately derived complete display rows.
    view = replace(
        structure,
        provenance={
            **structure.provenance,
            SUGGESTION_KEY: dict(evidence, rows=_complete_display_rows(rows)),
        },
    )
    manifest = dict(
        snapshot_uuid="NEW_CONVERSION",
        source=dict(
            path=evidence["source_path"],
            physical_page=evidence["physical_page"],
            cache_identity=dict(dpi=evidence["dpi"]),
        ),
        text_bindings=[
            dict(index=i, text_source_uuid=str(i)) for i in range(len(structure.texts))
        ],
    )
    bindings = bind_native_suggestions(view, manifest)
    if not bindings:
        return structure
    guard = ReviewLayoutGuard(structure)
    if guard.unknown:
        return structure
    roles = _display_obstacle_roles(structure, guard)
    if roles is None:
        return structure
    # Explicit source-rule facts take precedence over residual layer heuristics.
    rules = []
    for points in structure.provenance.get("text_rule_contours", ()):
        path = polygon([guard.transform(*p) for p in points])
        stroke = QPainterPathStroker()
        stroke.setWidth(1.0)
        rules.append(stroke.createStroke(path))
    original_paths = {}
    for i in guard.emitted_indices:
        placement = native_text_placement(structure.texts[i], transform=guard.transform)
        if placement is not None and not placement.metrics.fallback_reason:
            original_paths[i] = glyph_footprint(placement)
    proposals = {}
    texts, records = list(structure.texts), []
    for binding in bindings:
        i = binding["binding"]["index"]
        text, row = structure.texts[i], binding["evidence"]
        ink = row.get("proof", {}).get("complete_ink_center_bounds")
        if (
            i not in guard.emitted_indices
            or text.reviewed
            or text.display_quad is not None
            or abs(text.rotation_deg) > 1
            or row.get("rotation_deg") != 0
            or len(text.text.strip()) < 2
            or not text.text.isascii()
            or not any(c.isalpha() for c in text.text)
            or row.get("text") != text.text
            or not ink
            or len(ink) != 4
        ):
            continue
        a, b, c, d = ink
        if not (0 <= a < c < structure.source_size_px[0] and 0 <= b < d < guard.height):
            continue
        quad = ((a, b), (c, b), (c, d), (a, d))
        try:
            placement = source_anchored_text_placement(
                text, text.text, quad, transform=guard.transform
            )
            original = native_text_placement(text, transform=guard.transform)
            if original is None or original.metrics.fallback_reason:
                continue
            proposed = glyph_footprint(placement)
            previous = glyph_footprint(original)
            # Horizontal native rows fit exactly on the legal boundary.
            # Qt path.contains rejects coincident edges at page coordinates;
            # check all formal LFF visible corners with numeric tolerance.
            corners = visible_corners(placement)
            if any(
                not (
                    a - 1e-6 <= x <= c + 1e-6
                    and guard.height - d - 1e-6 <= y <= guard.height - b + 1e-6
                    and 0 <= x <= structure.source_size_px[0]
                    and 0 <= y <= guard.height
                )
                for x, y in corners
            ):
                continue
            new_ink = proposed.subtracted(previous)
            preserved = 0
            blocked = False
            for unknown, (owner, obstacle, bounds) in zip(roles, guard.obstacles):
                if owner is not None or not proposed.boundingRect().intersects(bounds):
                    continue
                if proposed.intersects(obstacle):
                    if not unknown and new_ink.intersects(obstacle):
                        blocked = True
                        break
                    preserved += 1
            if blocked:
                continue
            if any(new_ink.intersects(rule) for rule in rules):
                continue
            proposals[i] = (
                proposed,
                quad,
                dict(
                    index=i,
                    display_quad=quad,
                    geometry=placement.geometry.payload(),
                    retained_existing_contacts=preserved,
                ),
            )
        except (ValueError, RuntimeError, TypeError, IndexError):
            continue
    # Each row is checked once, against both unchanged and proposed neighbors.
    # Thus a rejected neighbor cannot create a new collision on reversion.
    for i, (path, quad, record) in proposals.items():
        if any(
            j != i
            and not original_paths[i].intersects(other)
            and (
                path.intersects(other)
                or (j in proposals and path.intersects(proposals[j][0]))
            )
            for j, other in original_paths.items()
        ):
            continue
        texts[i] = replace(texts[i], display_quad=quad)
        records.append(record)
    if not records:
        return structure
    return replace(
        structure,
        texts=tuple(texts),
        provenance={
            **structure.provenance,
            "source_row_display": dict(
                version=AUTO_VERSION, authority="DISPLAY_ONLY", rows=records
            ),
        },
    )


@dataclass(frozen=True)
class SourceRowTargetSet:
    source_path: str
    physical_page: int
    source_structure_id: str
    source_evidence: dict
    snapshot_texts: tuple
    indices: tuple[int, ...]
    candidates: tuple


def make_source_row_target_set(structure, candidates):
    """Declare one transaction against actual objects in this source snapshot."""
    candidates = tuple(candidates)
    evidence = structure.provenance.get(SUGGESTION_KEY, {})
    if (
        not 2 <= len(candidates) <= 4
        or not evidence.get("source_path")
        or type(evidence.get("physical_page")) is not int
    ):
        raise ValueError(
            "A target group requires a source file, page and two to four rows"
        )
    indices = []
    for candidate in candidates:
        matches = [i for i, text in enumerate(structure.texts) if text is candidate]
        if len(matches) != 1 or sum(text == candidate for text in structure.texts) != 1:
            raise ValueError("Target candidate identity is not unique in this snapshot")
        indices.append(matches[0])
    if len(set(indices)) != len(indices):
        raise ValueError("Repeated source-row target")
    return SourceRowTargetSet(
        str(evidence["source_path"]),
        evidence["physical_page"],
        structure.source_structure_id,
        metadata_to_jsonable(evidence),
        tuple(structure.texts),
        tuple(indices),
        candidates,
    )


def fit_source_row_displays(structure, *, target_set=None):
    """Fit at most four independently proven rows, checking the final group.

    Only an explicitly declared target transaction may call this function.
    Normal conversion and opening caches/projects do not apply it. Original
    candidate facts and all source masks remain unchanged.
    """
    # No implicit whole-page selection. A failed target may never fall through
    # to an unrelated group. The normal-conversion automatic entry is disabled.
    if not isinstance(target_set, SourceRowTargetSet):
        return structure
    evidence = metadata_to_jsonable(structure.provenance.get(SUGGESTION_KEY, {}))
    if (
        target_set.source_path != evidence.get("source_path")
        or target_set.physical_page != evidence.get("physical_page")
        or target_set.source_structure_id != structure.source_structure_id
        or target_set.source_evidence != evidence
        or target_set.snapshot_texts != tuple(structure.texts)
        or not 2 <= len(target_set.indices) <= 4
        or len(set(target_set.indices)) != len(target_set.indices)
        or len(target_set.candidates) != len(target_set.indices)
        or any(
            type(i) is not int or not 0 <= i < len(structure.texts)
            for i in target_set.indices
        )
        or tuple(structure.texts[i] for i in target_set.indices)
        != target_set.candidates
    ):
        return structure
    rows = evidence.get("display_rows", ())
    if (
        not rows
        or len(rows) > 48
        or evidence.get("source_size_px") != list(structure.source_size_px)
        or structure.provenance.get("review_snapshot_v1")
    ):
        return structure
    bound = {}
    for i, text in enumerate(structure.texts):
        if text.reviewed or text.display_quad is not None or abs(text.rotation_deg) > 1:
            continue
        x, y, w, h = text.bbox
        matches = []
        for row in rows:
            a, b, c, d = row["bounds"]
            ink = row.get("proof", {}).get("complete_ink_center_bounds")
            if (
                row.get("layout_eligible")
                and row.get("status") == "NATIVE_TEXT_SUGGESTION"
                and row.get("text") == text.text
                and ink
                and len(ink) == 4
                and x - 1 <= a < c <= x + w + 1
                and y - 1 <= b < d <= y + h + 1
                and w > 0
                and (c - a) / w >= 0.75
            ):
                matches.append(row)
        if len(matches) == 1:
            bound[i] = matches[0]
    # A native source row must bind exactly one emitted candidate.
    bound = {
        i: r
        for i, r in bound.items()
        if sum(other is r for other in bound.values()) == 1
    }
    if len(bound) < 2:
        return structure
    guard = ReviewLayoutGuard(structure)
    bound = {i: r for i, r in bound.items() if i in guard.emitted_indices}
    emitted = sorted(guard.emitted_indices)
    if len(emitted) > 512:
        return structure
    components = [list(target_set.indices)]
    texts = list(structure.texts)
    records = []
    for component in sorted(
        components, key=lambda c: structure.texts[c[-1]].bbox[1], reverse=True
    ):
        group = component
        if any(
            i not in bound
            or structure.texts[i].reviewed
            or structure.texts[i].display_quad is not None
            for i in group
        ):
            continue
        quads, suggestions = {}, {}
        for i in group:
            a, b, c, d = bound[i]["proof"]["complete_ink_center_bounds"]
            quads[i] = ((a, b), (c, b), (c, d), (a, d))
            suggestions[i] = dict(
                evidence=dict(bound[i], quad=quads[i]), suggestion_uuid=f"{VERSION}-{i}"
            )
        contents = {i: structure.texts[i].text for i in group}
        boxes = [bound[i]["proof"]["support_box"] for i in group]
        left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        if (right - left) * (bottom - top) > 600000:
            continue
        union = np.zeros((bottom - top, right - left), np.uint8)
        valid = True
        for i, box in zip(group, boxes):
            data = base64.b64decode(
                bound[i]["proof"]["source_only_support_png"], validate=True
            )
            mask = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            a, b, c, d = box
            if mask is None or mask.shape != (d - b, c - a):
                valid = False
                break
            union[b - top : d - top, a - left : c - left] |= mask
        if not valid:
            continue
        ok, png = cv2.imencode(".png", union)
        if not ok:
            continue
        support = dict(
            suggestion_uuid=f"{VERSION}-group-" + "-".join(map(str, group)),
            evidence=dict(
                proof=dict(
                    support_box=[left, top, right, bottom],
                    source_only_support_png=base64.b64encode(png).decode("ascii"),
                )
            ),
        )
        checks = [
            guard.check_source(
                i,
                contents[i],
                suggestions[i],
                contents,
                quads,
                display_group_support=support,
            )
            for i in group
        ]
        if all(c["state"] == "PASS" for c in checks):
            for i, check in zip(group, checks):
                texts[i] = replace(texts[i], display_quad=quads[i])
                records.append(
                    dict(
                        index=i,
                        display_quad=quads[i],
                        source_bounds=bound[i]["bounds"],
                        geometry=check["geometry"],
                        preserved_source_footprints=check[
                            "preserved_source_footprints"
                        ],
                    )
                )
            # One bounded group per conversion. Other rows stay fixed.
            break
    if (
        not records
        or {record["index"] for record in records} != set(target_set.indices)
        or {
            i
            for i, (before, after) in enumerate(zip(structure.texts, texts))
            if before != after
        }
        != set(target_set.indices)
    ):
        return structure
    return replace(
        structure,
        texts=tuple(texts),
        provenance={
            **structure.provenance,
            "source_row_display": dict(
                version=VERSION, rows=records, authority="DISPLAY_ONLY"
            ),
        },
    )
