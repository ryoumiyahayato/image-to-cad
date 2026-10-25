"""Read-only replay of existing source ownership into the six-rule report.

No PDF PATH is assigned by bbox intersection. Component IDs name raster support
at the production threshold, not engineering objects or original CAD handles.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from math import ceil, floor, isclose, isfinite
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from jsonschema import ValidationError

from tools.drafting_rules.cli import read_json, validate_files
from tools.drafting_rules.dxf_adapter import digest, sha256, snapshot

ADAPTER_VERSION = "verified-source-carriers-v1"


class DocumentView:
    """Filter iteration for the existing renderer, without changing the document."""

    def __init__(self, doc, entities):
        self.doc, self.entities = doc, entities

    def __getattr__(self, name):
        return getattr(self.doc, name)

    def modelspace(self):
        return self.entities


def runs(mask):
    """Canonical page-local pixel member intervals [y, x0, x1)."""
    result = []
    for y in np.flatnonzero(np.any(mask, axis=1)):
        row = np.pad(mask[y].astype(np.int8), (1, 1))
        edges = np.flatnonzero(np.diff(row))
        result.extend([int(y), int(a), int(b)] for a, b in zip(edges[::2], edges[1::2]))
    return result


def renderable(entity):
    d, kind = entity.dxf, entity.dxftype()
    if kind == "LINE":
        return d.start.z == d.end.z == 0
    if kind == "LWPOLYLINE":
        return (not d.elevation and tuple(d.extrusion) == (0, 0, 1)
                and not d.const_width and not any(a or b or c for _, _, a, b, c in entity.get_points()))
    return False  # Never let the old preview's local OCS renderer undo WCS safety.


def may_cover(entity, carrier, doc):
    """Conservative segment envelopes prevent a subpixel raster false PASS.

    An envelope overlap without rendered ink is uncertain, never evidence of
    absence. This deliberately sacrifices recall for unsupported fine geometry.
    """
    if entity.dxftype() == "LINE":
        points = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
    else:
        points = list(entity.get_points("xy"))
        if entity.closed and points:
            points.append(points[0])
    width = 1.0
    if entity.has_xdata("P3A_STROKE"):
        tags = entity.get_xdata("P3A_STROKE")
        weight = entity.dxf.lineweight
        if weight == -1:
            weight = doc.layers.get(entity.dxf.layer).dxf.lineweight
        width = max(width, weight / 100 * float(tags[2].value) / 25.4)
    radius = width / 2 + 1  # Include pixel coverage and antialias boundary.
    height, canvas_width = carrier.shape
    for a, b in zip(points, points[1:]):
        if not all(isfinite(v) for v in (*a, *b, radius)):
            return True
        x0, x1 = max(0, floor(min(a[0], b[0]) - radius)), min(canvas_width, ceil(max(a[0], b[0]) + radius))
        y0, y1 = max(0, floor(height - max(a[1], b[1]) - radius)), min(height, ceil(height - min(a[1], b[1]) + radius))
        if x1 > x0 and y1 > y0 and np.any(carrier[y0:y1, x0:x1]):
            return True
    return False


def bind_texts(structure, before, targets):
    from app.export.ocr_outline_export import native_text_placement, native_text_file_content
    from app.ocr.text_output_contract import accepted_ocr_texts

    approved = list(accepted_ocr_texts(structure.texts))
    bindings = {}
    for target in targets:
        entity = before.entitydb.get(target["handle"])
        if entity is None or entity.dxftype() != "TEXT" or not entity.has_xdata("OCR_TEXT_LINE"):
            continue
        tags = entity.get_xdata("OCR_TEXT_LINE")
        index = int(tags[0].value) - 1
        if not 0 <= index < len(approved):
            continue
        candidate = approved[index]
        placement = native_text_placement(candidate, transform=lambda x, y: (x, structure.source_size_px[1] - y))
        g = placement.geometry
        wanted = (*g.insert, g.character_height, g.width_factor, g.rotation)
        actual = (entity.dxf.insert.x, entity.dxf.insert.y, entity.dxf.height, entity.dxf.width, entity.dxf.rotation)
        if (entity.dxf.text != native_text_file_content(candidate.text)
                or tags[1].value != candidate.text
                or not all(isclose(a, b, abs_tol=1e-7, rel_tol=0) for a, b in zip(wanted, actual))
                or before.styles.get(entity.dxf.style).dxf.font != "wqy-unicode.lff"):
            continue
        key = (candidate.text, candidate.bbox)
        if key in bindings:
            raise ValueError("Ambiguous source-to-TEXT binding")
        bindings[key] = dict(target=target, candidate=candidate, handle=entity.dxf.handle, line_index=index + 1)
    return bindings


def validate_with_source(before, after, source, evidence_path, cache, dpi):
    """Consume a real production cache, PDF, and saved CAD. Never write inputs.

    FAIL can be supported by a definite owned fragment; PASS requires the entire
    processed carrier to be bounded, source-owned and represented in cache masks.
    Partial evidence without a definite residue remains ABSTAIN.
    """
    from app.core.cache import load_trace_cache
    from app.core.image_loader import load_image
    from app.core.preview import render_emitted_dxf_preview
    from app.geometry.content_ownership import (
        _candidate_region_mask, complete_verified_text_ownership, partition_content,
    )
    from app.geometry.scan_cleanup import prepare_scan_page
    from app.ocr.ocr_fast import prepare_safe_candidate
    from app.ocr.ocr_layout import constrain_texts_to_table_cells

    report = validate_files(before, after, source, evidence_path)
    evidence = read_json(evidence_path)
    # Old JSON completeness/handle assertions are never authority in this mode.
    glyph_results = [r for r in report["results"] if r["rule"] == "source-glyph-exit"]
    for r in glyph_results:
        r.update(status="ABSTAIN", reason="NO_REPLAYED_SOURCE_PROOF", details={})
    for result in report["results"]:
        if result["rule"] in {"background-protection", "table-line-parity"}:
            result.update(status="ABSTAIN", reason="NO_INDEPENDENT_SOURCE_ROLE_OR_COLLECTION_PROOF",
                          details={"legacy_claims_ignored": True})
    stored = load_trace_cache(cache)
    structure = stored.final_structure
    if structure is None or evidence["source"]["units"] != "source_pixel":
        raise ValueError("Adapter requires a production FinalStructure and source-pixel units")
    candidate_keys = [(c.text, c.bbox) for c in structure.texts]
    if len(set(candidate_keys)) != len(candidate_keys):
        raise ValueError("Ambiguous cache source candidate identity")
    if not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise ValueError("Explicit render DPI must be in 72..600")
    wanted_context = dict(source_sha256=sha256(source), page=evidence["source"]["page"],
                          dpi=dpi, crop=evidence["source"]["region"])
    cache_context_verified = stored.cache_key is not None and all(k in stored.cache_key for k in wanted_context)
    if cache_context_verified and digest({k: stored.cache_key[k] for k in wanted_context}) != digest(wanted_context):
        raise ValueError("SOURCE_CACHE_CONTEXT_IDENTITY_MISMATCH")
    page = load_image(source, page_index=evidence["source"]["page"] - 1, pdf_dpi=dpi, grayscale=True)
    region = evidence["source"]["region"]
    if any(int(v) != v for v in region):
        raise ValueError("Source crop must use integer pixel boundaries")
    left, top, right, bottom = map(int, region)
    if not (0 <= left < right <= page.shape[1] and 0 <= top < bottom <= page.shape[0]):
        raise ValueError("Source region outside rendered PDF")
    gray = page[top:bottom, left:right]
    binary = prepare_scan_page(gray, foreground_threshold=structure.threshold).binary
    if (gray.shape[::-1] != structure.source_size_px or structure.preview_binary is None
            or not np.array_equal(binary, structure.preview_binary)):
        raise ValueError("SOURCE_CACHE_PIXEL_IDENTITY_MISMATCH")
    doc_before, doc_after = ezdxf.readfile(before), ezdxf.readfile(after)
    bindings = bind_texts(structure, doc_before, evidence["texts"])
    proofs = []
    restored = constrain_texts_to_table_cells(gray, structure.texts, verified_sources=proofs)
    owner = partition_content(binary, lines=structure.straight_lines, texts=restored,
                              signatures=structure.signatures, logos=structure.logos)
    owned = complete_verified_text_ownership(binary, gray, restored, proofs, ownership=owner)
    _, labels, stats, _ = cv2.connectedComponentsWithStats((binary < 128).astype(np.uint8), connectivity=8)
    all_cores = {}
    for proof in proofs:
        pl, pt, pr, pb = proof.bounds
        for candidate, core in zip(proof.texts, proof.row_masks, strict=True):
            mask = np.zeros(gray.shape, np.uint8)
            mask[pt:pb, pl:pr] = core
            all_cores[(candidate.text, candidate.bbox)] = mask > 0
    for candidate in structure.texts:
        key = (candidate.text, candidate.bbox)
        if key not in all_cores:
            checked = prepare_safe_candidate(gray, candidate)
            if checked.replacement_safe:
                all_cores[key] = (_candidate_region_mask(checked, gray.shape) > 0) & (gray < 128)

    # Only bound, default-visible native TEXT can be excluded from residual ink.
    after_snapshot = snapshot(after)
    before_snapshot = snapshot(before)
    native_ok = {r["target"] for r in report["results"] if r["rule"] == "editable-text" and r["status"] == "PASS"}
    excluded = {item["handle"] for item in bindings.values() if item["target"]["id"] in native_ok}
    visible = [e for e in doc_after.modelspace() if after_snapshot[e.dxf.handle]["visible"] and e.dxf.handle not in excluded]
    unsupported = [e.dxf.handle for e in visible if not renderable(e)]
    ledger = dict(adapter=ADAPTER_VERSION, cache_sha256=sha256(cache), structure_id=structure.structure_id,
                  source_sha256=sha256(source), source_page=evidence["source"]["page"],
                  render_dpi=dpi, page_size_px=list(page.shape[::-1]), crop=region,
                  source_threshold=structure.threshold,
                  representation="production-threshold raster carriers; not whole native PDF PATH ownership",
                  coordinate_contract="page pixels -> local crop; CAD x=x_local, y=crop_height-y_local; no engineering scale inferred",
                  binary_sha256=digest(runs(binary < 128)), rows=[], unsupported_visible_handles=unsupported,
                  cache_context_verified=cache_context_verified,
                  original_pdf_path_binding="NOT_AVAILABLE; no PATH ownership inferred")
    non_targets = {h: e["fingerprint"] for h, e in before_snapshot.items()
                   if h not in {item["handle"] for item in bindings.values()}}
    ledger["preservation"] = dict(rule="edit-isolation", handles=sorted(non_targets),
                                  fingerprints_sha256=digest(non_targets),
                                  scope="All other modelspace members, including adjacent structure. No semantic logo/table attribution and no automatic edit authorization.")
    geometry_ink = None if unsupported else render_emitted_dxf_preview(
        DocumentView(doc_after, visible), Path(after).parent, structure.source_size_px) < 255
    target_results = {r["target"]: r for r in glyph_results}
    for key, binding in bindings.items():
        result = target_results[binding["target"]["id"]]
        core = all_cores.get(key)
        if core is None:
            continue
        ids = sorted(set(map(int, np.unique(labels[core]))) - {0})
        carrier = np.isin(labels, ids)
        # A connected carrier shared with an unselected row cannot be retired.
        shared = [k for k, c in all_cores.items() if np.any(c & carrier)]
        all_selected = all(k in bindings for k in shared)
        boundary = any(stats[i][0] == 0 or stats[i][1] == 0
                       or stats[i][0] + stats[i][2] == gray.shape[1]
                       or stats[i][1] + stats[i][3] == gray.shape[0] for i in ids)
        cached = structure.editable_text_source_mask
        uncovered = int(np.count_nonzero(carrier & (owned.text == 0)))
        cache_gap = int(np.count_nonzero(carrier & (cached == 0))) if cached is not None else int(carrier.sum())
        known = core & (owned.text > 0)  # Protected line/background pixels are never text witnesses.
        hits = int(np.count_nonzero(known & geometry_ink)) if geometry_ink is not None else None
        witnesses = []
        if hits:
            for entity in visible:
                ink = render_emitted_dxf_preview(DocumentView(doc_after, [entity]), Path(after).parent, structure.source_size_px) < 255
                if np.any(ink & known):
                    witnesses.append(entity.dxf.handle)
        member_runs = runs(carrier)
        envelope_hits = [e.dxf.handle for e in visible if renderable(e) and may_cover(e, carrier, doc_after)]
        row = dict(target=binding["target"]["id"], handle=binding["handle"], recognized_text=key[0],
                   recognition_provenance=binding["candidate"].source,
                   confidence=binding["candidate"].confidence, ocr_line_index=binding["line_index"],
                   cache_candidate_id=digest([key, binding["candidate"].quad, binding["candidate"].source]),
                   expected_edited_text=binding["target"]["expected_text"],
                   current_native_text=after_snapshot.get(binding["handle"], {}).get("text"),
                   original_bbox_page_px=[key[1][0] + left, key[1][1] + top, *key[1][2:]],
                   core_runs=runs(core), source_member_runs=member_runs,
                   source_member_id=digest([ledger["source_sha256"], ledger["source_page"], region, dpi, member_runs]),
                   shared_with=[bindings[k]["target"]["id"] for k in shared if k in bindings],
                   carrier_pixels=int(carrier.sum()), unowned_pixels=uncovered, cache_uncovered_pixels=cache_gap,
                   boundary_truncated=boundary, all_shared_rows_selected=all_selected,
                   residual_owned_core_pixels=hits, residual_handles=witnesses, possible_geometry_handles=envelope_hits)
        ledger["rows"].append(row)
        if not cache_context_verified:
            status, reason = "ABSTAIN", "CACHE_SOURCE_CONTEXT_UNAVAILABLE"
        elif binding["target"]["id"] not in native_ok:
            status, reason = "ABSTAIN", "NATIVE_REPLACEMENT_NOT_VERIFIED"
        elif hits:
            status, reason = "FAIL", "VISIBLE_GEOMETRY_ON_VERIFIED_TEXT_SOURCE"
        elif geometry_ink is None or not ids or boundary or not all_selected or uncovered or cache_gap:
            status, reason = "ABSTAIN", "SOURCE_CARRIER_INCOMPLETE_OR_RENDER_UNSUPPORTED"
        elif np.any(carrier & geometry_ink):
            status, reason = "FAIL", "VISIBLE_SOURCE_CARRIER_REMAINS"
        elif envelope_hits:
            status, reason = "ABSTAIN", "GEOMETRY_ENVELOPE_CANNOT_EXCLUDE_SOURCE_CONTACT"
        else:
            status, reason = "PASS", "VERIFIED_SOURCE_CARRIER_EXITED"
        result.update(status=status, reason=reason, details={k: v for k, v in row.items() if not k.endswith("_runs")})
    report["summary"] = dict(Counter(r["status"] for r in report["results"]))
    report["source_ledger"] = ledger
    report["source_ledger_sha256"] = digest(ledger)
    report["adapter_version"] = ADAPTER_VERSION
    report["adapter_sha256"] = sha256(__file__)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "source", "evidence", "cache", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--dpi", type=int, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new path")
    try:
        result = validate_with_source(args.before, args.after, args.source, args.evidence, args.cache, args.dpi)
        code = int(bool(result["summary"].get("FAIL")))
    except (ValueError, OSError, AssertionError, ezdxf.DXFError, ValidationError) as error:
        result, code = dict(status="INPUT_ERROR", message=str(error)), 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result.get("summary", result), ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
