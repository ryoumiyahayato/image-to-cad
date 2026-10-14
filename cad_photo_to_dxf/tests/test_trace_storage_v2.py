from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from tests.trace_fixtures import contour_result

import cv2
import numpy as np
import pytest

from app.ocr.auxiliary_recognition import TextCandidate
from app.core.structure import metadata_to_jsonable
from app.core.structure_build import build_final_structure
from app.geometry.raster_trace import RasterTraceResult
from app.ocr.signature_overlay import SignatureRegion
from app.core.cache import load_trace_cache, save_trace_cache


def test_packed_cache_preserves_character_layout_and_signature_safety(tmp_path: Path) -> None:
    image = np.full((120, 180), 255, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (170, 110), 0, 2)
    result = contour_result(image)
    candidate = TextCandidate(
        text="签名",
        bbox=(40, 40, 80, 30),
        confidence=0.97,
        kind="text_candidate",
        source="rapidocr-tile",
        character_boxes=((42, 42, 30, 26), (78, 42, 34, 26)),
        replacement_safe=False,
        review_note="疑似签名，保留原图形等待确认",
    )
    signature = SignatureRegion(
        bbox=(55, 65, 20, 12),
        mask=np.where(np.indices((12, 20)).sum(axis=0) % 3 == 0, 255, 0).astype(
            np.uint8
        ),
    )
    preview = np.ascontiguousarray(result.binary.copy())
    preview[5:10, 5:10] = 0
    result = replace(
        result,
        texts=(candidate,),
        signatures=(signature,),
        preview_binary=preview,
    )

    path = save_trace_cache(tmp_path / "packed.npz", result)
    with np.load(path, allow_pickle=False) as archive:
        assert "binary_packed" in archive.files
        assert "binary" not in archive.files

    stored = load_trace_cache(path)

    assert np.array_equal(stored.binary, result.binary)
    assert stored.texts == (candidate,)
    assert not stored.texts[0].replacement_safe
    assert stored.texts[0].character_boxes == candidate.character_boxes
    assert len(stored.signatures) == 1
    assert stored.signatures[0].bbox == signature.bbox
    assert np.array_equal(stored.signatures[0].mask, signature.mask)
    assert stored.preview_binary is not None
    assert np.array_equal(stored.preview_binary, preview)


def _text_cache_result(text: TextCandidate) -> RasterTraceResult:
    binary = np.full((100, 160), 255, dtype=np.uint8)
    structure = build_final_structure(
        source_size_px=(160, 100),
        contour_binary=binary,
        contours=(),
        texts=(text,),
        preview_binary=binary,
        provenance={"nested": {"source_ids": ["one"]}},
        observations=({"event": "contract", "details": {"count": 1}},),
    )
    return RasterTraceResult(
        binary=binary,
        stages={},
        paths=(),
        threshold=128,
        foreground_pixels=0,
        vertex_count=0,
        texts=(text,),
        preview_binary=binary,
        final_structure=structure,
    )


def test_current_cache_roundtrips_nested_metadata_and_identity(tmp_path: Path) -> None:
    text = TextCandidate(
        "ABC",
        (10, 20, 100, 20),
        0.99,
        "text_candidate",
        quad=((10.0, 20.0), (110.0, 20.0), (110.0, 40.0), (10.0, 40.0)),
        reviewed=True,
    )
    result = _text_cache_result(text)
    path = save_trace_cache(tmp_path / "current.npz", result)

    stored = load_trace_cache(path)

    assert stored.final_structure is not None
    assert stored.final_structure.structure_id == result.final_structure.structure_id
    assert metadata_to_jsonable(stored.final_structure.provenance) == {
        "nested": {"source_ids": ["one"]}
    }
    assert metadata_to_jsonable(stored.final_structure.observations) == [
        {"details": {"count": 1}, "event": "contract"}
    ]


def test_quad_only_cache_tampering_is_rejected(tmp_path: Path) -> None:
    text = TextCandidate(
        "ABC",
        (10, 20, 100, 20),
        0.99,
        "text_candidate",
        quad=((10.0, 20.0), (110.0, 20.0), (110.0, 40.0), (10.0, 40.0)),
        reviewed=True,
    )
    path = save_trace_cache(tmp_path / "original.npz", _text_cache_result(text))
    with np.load(path, allow_pickle=False) as archive:
        values = {name: archive[name].copy() for name in archive.files}
    texts = json.loads(str(values["texts_json"].reshape(-1)[0]))
    texts[0]["quad"] = [[10.0, 20.0], [110.0, 30.0], [110.0, 40.0], [10.0, 30.0]]
    values["texts_json"] = np.asarray(
        [json.dumps(texts, ensure_ascii=False)],
        dtype=np.str_,
    )
    tampered = tmp_path / "quad-only.npz"
    np.savez(tampered, **values)

    with pytest.raises(ValueError, match="fingerprint"):
        load_trace_cache(tampered)


def test_legacy_cache_identity_is_explicitly_invalidated(tmp_path: Path) -> None:
    text = TextCandidate("ABC", (10, 20, 100, 20), 0.99, "text_candidate")
    path = save_trace_cache(tmp_path / "current.npz", _text_cache_result(text))
    with np.load(path, allow_pickle=False) as archive:
        values = {name: archive[name].copy() for name in archive.files}
    values["cache_version"] = np.asarray([9], dtype=np.int32)
    legacy = tmp_path / "legacy.npz"
    np.savez(legacy, **values)

    with pytest.raises(ValueError, match="legacy identity schema"):
        load_trace_cache(legacy)
