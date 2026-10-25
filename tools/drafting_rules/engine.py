"""Pure rules over observations. Evidence assertions are inputs, not discoveries."""
from __future__ import annotations

from collections import Counter
from math import dist


def evaluate(evidence, before, after, pack):
    """Return per-target results without changing entities or accepting repairs.

    Snapshots map stable modelspace handles to kind/visibility/fingerprint/bounds/
    segments. Missing measurements remain unknown. See evidence.schema.json.
    """
    results = []
    rules = {r["id"]: r for r in pack["rules"] if r["state"] == "IMPLEMENTED"}

    def emit(rule, target, status, reason, **details):
        definition = rules[rule]
        results.append(dict(rule=rule, target=target, status=status, reason=reason,
                            classification=definition["classification"],
                            sources=definition["sources"], details=details))

    texts = evidence["texts"]
    for text in texts:
        handle, target = text["handle"], text["id"]
        item = after.get(handle)
        if item is None:
            emit("editable-text", target, "FAIL", "TARGET_MISSING", handle=handle)
        elif item["kind"] not in {"TEXT", "MTEXT"}:
            emit("editable-text", target, "FAIL", "NOT_NATIVE_TEXT", handle=handle)
        elif not item["visible"]:
            emit("editable-text", target, "FAIL", "TEXT_NOT_DEFAULT_VISIBLE", handle=handle)
        elif item.get("text") != text["expected_text"]:
            emit("editable-text", target, "FAIL", "CONTENT_MISMATCH",
                 expected=text["expected_text"], actual=item.get("text"))
        else:
            emit("editable-text", target, "PASS", "NATIVE_CONTENT_PRESENT", handle=handle)

        cell = text.get("cell")
        bounds = item.get("bounds") if item else None
        if cell is None or bounds is None or not item.get("visible"):
            emit("cell-fit", target, "ABSTAIN", "CELL_OR_EXACT_METRICS_UNAVAILABLE")
        else:
            # Axis-aligned cell and exact LFF ink bounds in the SAME CAD units.
            tolerance = pack["parameters"]["cell_tolerance"]
            fits = (bounds[0] >= cell[0] - tolerance and bounds[1] >= cell[1] - tolerance
                    and bounds[2] <= cell[2] + tolerance and bounds[3] <= cell[3] + tolerance)
            emit("cell-fit", target, "PASS" if fits else "FAIL",
                 "INK_INSIDE_CELL" if fits else "INK_OUTSIDE_CELL",
                 bounds=bounds, cell=cell, tolerance=tolerance)

        old = text.get("source_outline_handles", [])
        known = text.get("outline_mapping_complete", False) and text.get("ownership_ref")
        if (not known or not old or any(h not in before for h in old)
                or any(before[h]["kind"] in {"TEXT", "MTEXT"} for h in old)):
            emit("source-glyph-exit", target, "ABSTAIN", "COMPLETE_OUTLINE_MAPPING_UNAVAILABLE")
        else:
            residual = [h for h in old if h in after and after[h]["visible"]]
            emit("source-glyph-exit", target, "FAIL" if residual else "PASS",
                 "VISIBLE_SOURCE_MEMBERS_REMAIN" if residual else "MAPPED_SOURCE_MEMBERS_EXITED",
                 residual_handles=residual, ownership_ref=text["ownership_ref"])

    if not texts:
        for rule in ("editable-text", "cell-fit", "source-glyph-exit"):
            emit(rule, "scope", "ABSTAIN", "NO_TEXT_TARGETS")

    protected = evidence.get("protected", [])
    editable = {t["handle"] for t in texts}
    for group in protected:
        handles = group["handles"]
        if not handles or any(h not in before for h in handles):
            emit("background-protection", group["id"], "ABSTAIN", "BACKGROUND_MAPPING_UNAVAILABLE")
            continue
        changed = [h for h in handles if h not in after
                   or after[h]["fingerprint"] != before[h]["fingerprint"]]
        shared = sorted(editable.intersection(handles))
        unknown = [h for h in handles if not before[h]["supported"]
                   or (h in after and not after[h]["supported"])]
        if changed or shared:
            emit("background-protection", group["id"], "FAIL", "BACKGROUND_CHANGED_OR_SHARED",
                 changed_handles=changed, shared_handles=shared)
        elif unknown:
            emit("background-protection", group["id"], "ABSTAIN", "BACKGROUND_DEPENDENCIES_UNRESOLVED")
        else:
            emit("background-protection", group["id"], "PASS", "INDEPENDENT_MEMBERS_UNCHANGED")
    if not protected:
        emit("background-protection", "scope", "ABSTAIN", "NO_BACKGROUND_MAPPING")

    table = evidence.get("table")
    if table is None or not table.get("mapping_complete"):
        emit("table-line-parity", "scope", "ABSTAIN", "SOURCE_TABLE_MAPPING_UNAVAILABLE")
    else:
        # A complete dedicated layer catches additions as well as missing handles.
        members = [(h, e) for h, e in after.items() if e["layer"] == table["layer"] and e["visible"]]
        unknown = [h for h, e in members if e.get("segments") is None]
        if unknown:
            emit("table-line-parity", table["id"], "ABSTAIN", "UNSUPPORTED_TABLE_MEMBER", handles=unknown)
        else:
            actual = [s for _, e in members for s in e["segments"]]
            expected = table["source_segments"]
            tolerance = pack["parameters"]["line_endpoint_tolerance"]
            missing, extra = unmatched_segments(expected, actual, tolerance)
            emit("table-line-parity", table["id"], "FAIL" if missing or extra else "PASS",
                 "SOURCE_SEGMENT_MULTISET_CHANGED" if missing or extra else "SOURCE_SEGMENTS_RETAINED",
                 missing=missing, unexpected=extra, tolerance=tolerance)

    edit = evidence.get("edit")
    if edit is None:
        emit("edit-isolation", "scope", "ABSTAIN", "NO_EDIT_CONTRACT")
    else:
        allowed = set(edit["allowed_handles"])
        permitted_new = set(edit.get("allowed_new_handles", []))
        if not allowed or not allowed.issubset(before) or permitted_new.intersection(before):
            emit("edit-isolation", "scope", "ABSTAIN", "INVALID_EDIT_SCOPE")
        else:
            changed = [h for h in before if h not in allowed and
                       (h not in after or before[h]["fingerprint"] != after[h]["fingerprint"])]
            added = sorted(set(after) - set(before) - permitted_new)
            unknown = [h for h in before if h not in allowed and
                       (not before[h]["supported"] or (h in after and not after[h]["supported"]))]
            if changed or added:
                emit("edit-isolation", "scope", "FAIL", "UNRELATED_ENTITIES_CHANGED",
                     changed_handles=changed, unexpected_new_handles=added)
            elif unknown:
                emit("edit-isolation", "scope", "ABSTAIN", "UNRESOLVED_ENTITY_DEPENDENCIES", handles=unknown)
            else:
                emit("edit-isolation", "scope", "PASS", "NON_TARGET_MEMBERS_UNCHANGED")

    return dict(schema_version=1, pack_id=pack["id"], pack_version=pack["version"],
                source=evidence["source"], results=results,
                summary=dict(Counter(r["status"] for r in results)),
                cad_editor="NOT_RUN", dwg_roundtrip="NOT_RUN", human_time_saved="NOT_RUN")


def unmatched_segments(expected, actual, tolerance):
    """Maximum bipartite matching preserves multiplicity, gaps and endpoints.

    No snapping/bridging/collinear merge: split-versus-merged representations
    deliberately fail this narrow source contract, rather than imply missing ink.
    """
    def close(a, b):
        return (dist(a[:2], b[:2]) <= tolerance and dist(a[2:], b[2:]) <= tolerance
                or dist(a[:2], b[2:]) <= tolerance and dist(a[2:], b[:2]) <= tolerance)

    matches = {}

    def assign(i, seen):
        for j, segment in enumerate(actual):
            if j in seen or not close(expected[i], segment):
                continue
            seen.add(j)
            if j not in matches or assign(matches[j], seen):
                matches[j] = i
                return True
        return False

    for i in range(len(expected)):
        assign(i, set())
    return ([s for i, s in enumerate(expected) if i not in matches.values()],
            [s for j, s in enumerate(actual) if j not in matches])
