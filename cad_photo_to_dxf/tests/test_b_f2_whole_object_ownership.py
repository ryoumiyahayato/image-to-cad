from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from app.ocr.auxiliary_recognition import TextCandidate
from app.export.document_export import DocumentPage
from app.core.structure import FINAL_STRUCTURE_SCHEMA_VERSION, metadata_to_jsonable
from app.core.structure_build import build_final_structure
from app.geometry.line_detect import LineSegment
from app.ocr.logo_detection import LogoRegion
from app.core.preview import render_final_structure_preview
from app.core.trace_types import TracePath
from app.geometry.raster_trace import RasterTraceResult
from app.ocr.signature_overlay import SignatureRegion
from app.export.trace_single_export import export_final_structure_dxf
from app.export.trace_document_export import export_trace_document_streaming
from app.core.cache import TRACE_CACHE_VERSION, load_trace_cache, save_trace_cache
from app.diagnostics.visual_acceptance import VisualLayerSelection, render_visual_acceptance
from app.core.member_binding import DraftsmanBindingError, cache_binding_admissible, draftsman_cache_identity, resolve_draftsman_output


def _compiled(*, lossy_point=2.0):
    name = 'bound' if lossy_point == 2.0 else 'precise-bound'
    provenance = json.loads((Path(__file__).parent / 'fixtures' / (name+'.json')).read_text())
    return replace(_base_structure(lossy_point=lossy_point), provenance=provenance)

def _base_structure(*, lossy_point: float = 2.0):
    binary = np.full((40, 60), 255, dtype=np.uint8)
    contours = (
        TracePath(((lossy_point, 2.0), (18.0, 2.0), (18.0, 18.0), (2.0, 18.0)), None, 0, 0),
        TracePath(((6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)), 0, 1, 0),
        TracePath(((8.0, 7.0), (12.0, 7.0), (12.0, 13.0), (8.0, 13.0)), None, 0, 2),
        TracePath(((24.0, 3.0), (34.0, 3.0), (34.0, 15.0), (24.0, 15.0)), None, 0, 3),
        TracePath(((5.0, 24.0), (32.0, 26.0), (30.0, 32.0), (7.0, 30.0)), None, 0, 4),
    )
    line = LineSegment(2.0, 27.0, 50.0, 27.0, 1.0, source_ids=("table-rule",))
    text = TextCandidate("R", (38, 4, 8, 10), 0.99, "text_candidate", source="fixture")
    logo = LogoRegion((24, 3, 10, 12), np.full((12, 10), 255, np.uint8), 0.0, 0, 1)
    signature = SignatureRegion((5, 24, 27, 8), np.full((8, 27), 255, np.uint8))
    return build_final_structure(
        source_size_px=(60, 40),
        contour_binary=binary,
        contours=contours,
        straight_lines=(line,),
        texts=(text,),
        logos=(logo,),
        signatures=(signature,),
        preview_binary=binary,
        provenance={"fixture": "b-f2"},
    )


def _swap_circle_logo_closures(object_id: str, closures: list[dict[str, object]]) -> None:
    replacements = {
        "obj-circle-r": "m-logo-s:g1",
        "obj-logo": "m-circle-root:g1",
    }
    if object_id not in replacements:
        return
    foreign_member_id = replacements[object_id]
    closures[0]["final_member_ids"] = [foreign_member_id]
    closures[0]["retained_accepted_member_ids"] = [foreign_member_id]
    closures[0]["replacement_coverage"] = [
        {
            **dict(closures[0]["replacement_coverage"][0]),
            "member_id": foreign_member_id,
        }
    ]


def _cross_object_serialized_structure():
    valid = _compiled()
    raw = metadata_to_jsonable(valid.provenance)
    for object_binding in raw["draftsman_output_v1"]["binding"]["objects"]:
        closures = object_binding["obligation_closures"]
        _swap_circle_logo_closures(object_binding["object_id"], closures)
    return replace(valid, provenance=raw)


def test_cross_object_binding_is_rejected_by_resolver_and_cache_admission() -> None:
    valid = _compiled()
    identity = draftsman_cache_identity(valid)
    assert identity is not None
    invalid = _cross_object_serialized_structure()
    with pytest.raises(DraftsmanBindingError, match="own committed final members"):
        resolve_draftsman_output(invalid, required=True)
    assert not cache_binding_admissible(invalid, identity)


def test_shared_resolver_parity_and_ocr_cannot_remove_protected_members(tmp_path: Path) -> None:
    structure = _compiled()
    resolved = resolve_draftsman_output(structure, required=True)
    preview = render_final_structure_preview(structure)
    source = np.full((40, 60), 255, np.uint8)
    images = render_visual_acceptance(source, structure, layers=VisualLayerSelection(texts=False))
    symbols_only = render_visual_acceptance(
        source,
        structure,
        layers=VisualLayerSelection(
            structure_lines=False,
            texts=False,
            symbols=True,
            unverified_geometry=False,
            review_warnings=False,
        ),
    )
    result = export_final_structure_dxf(structure, tmp_path / "bound.dxf")
    document_result = export_trace_document_streaming(
        [
            DocumentPage(
                1,
                None,
                (60.0, 40.0),
                vector_size_px=structure.source_size_px,
                final_structure=structure,
            )
        ],
        tmp_path / "bound-document.dxf",
    )
    assert preview.shape == images.reconstructed.shape[:2]
    assert np.any(symbols_only.reconstructed < 245)
    assert result.trace_path_count == 5
    assert result.text_count == 1
    assert document_result.text_count == result.text_count
    assert document_result.trace_path_count == result.trace_path_count
    assert resolved is not None and len(resolved.emitted_indices("contours")) == 5


def test_output_identity_is_stable_across_python_hash_seeds() -> None:
    script = """
import json

from app.core.member_binding import draftsman_cache_identity
from tests.test_b_f2_whole_object_ownership import _compiled

identity = draftsman_cache_identity(_compiled())
assert identity is not None
print(json.dumps({
    key: identity[key]
    for key in ("terminal_member_digest", "behavior_digest", "output_id")
}, sort_keys=True))
"""
    identities = []
    for seed in ("1", "2", "3", "4", "5", "random"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
        )
        identities.append(json.loads(completed.stdout))

    assert all(identity == identities[0] for identity in identities[1:])


def test_missing_stale_binding_and_lossy_float32_cache_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(DraftsmanBindingError, match="missing"):
        resolve_draftsman_output(_base_structure(), required=True)
    precise = _compiled(lossy_point=0.1)
    identity = draftsman_cache_identity(precise)
    assert identity is not None
    stale = _base_structure(lossy_point=float(np.float32(0.1)))
    assert not cache_binding_admissible(stale, identity)
    unknown_policy = metadata_to_jsonable(precise.provenance)
    unknown_policy["draftsman_output_v1"]["binding"]["compiled_policy"][
        "consumer_policy"
    ]["version"] = "unknown"
    with pytest.raises(DraftsmanBindingError, match="consumer policy"):
        build_final_structure(
            source_size_px=precise.source_size_px,
            contour_binary=precise.contour_binary,
            contours=precise.contours,
            straight_lines=precise.straight_lines,
            texts=precise.texts,
            logos=precise.logos,
            signatures=precise.signatures,
            preview_binary=precise.preview_binary,
            provenance=unknown_policy,
        )
    trace = RasterTraceResult(binary=precise.contour_binary, stages={}, paths=precise.contours, threshold=128, foreground_pixels=0, vertex_count=sum(len(path.points) for path in precise.contours), texts=precise.texts, signatures=precise.signatures, straight_lines=precise.straight_lines, preview_binary=precise.preview_binary, logos=precise.logos, final_structure=precise)
    cache = save_trace_cache(tmp_path / "lossy.npz", trace)
    # The writer now preserves native enclosure precision. Simulate an older
    # float32 cache explicitly to retain the fail-closed stale-binding check.
    with np.load(cache, allow_pickle=False) as archive:
        payload = {name: archive[name].copy() for name in archive.files}
    payload['points'] = payload['points'].astype(np.float32)
    with cache.open('wb') as handle:
        np.savez(handle, **payload)
    with pytest.raises(DraftsmanBindingError, match="precision|stale"):
        load_trace_cache(cache)


def test_schema_and_cache_versions_follow_d011_arc_contract() -> None:
    assert FINAL_STRUCTURE_SCHEMA_VERSION == 4
    assert TRACE_CACHE_VERSION == 11

