"""Real bilingual cell layout through the production path, with source protection."""

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.image_loader import load_image
from app.core.preview import render_emitted_dxf_preview, render_final_structure_preview
from app.core.structure_build import final_structure_from_trace_result
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry import optimized_trace
from app.geometry.content_ownership import (
    complete_verified_text_ownership,
    partition_content,
)
from app.geometry.scan_cleanup import prepare_scan_page
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ocr_fast import prepare_safe_candidate
from app.ocr.ocr_layout import (
    _restore_cell_text_rows,
    constrain_texts_to_table_cells,
    offset_candidate,
)


@lru_cache(maxsize=1)
def source():
    return load_image(
        Path(__file__).parent
        / "real_regression/assets/sources/warehouse-electrical-vector.pdf",
        page_index=1,
        pdf_dpi=136,
        grayscale=True,
    )


def candidates():
    result = []
    # Saved DXF OCR_TEXT_GEOMETRY / OCR_TEXT_LINE metadata, unchanged strings.
    for text, bbox, confidence in (
        ("专业负责人", (4154, 2278, 102, 25), 0.99986),
        ("Discipline", (4178, 2297, 39, 18), 0.9996),
        ("Responsible", (4177, 2311, 40, 10), 0.99962),
    ):
        x, y, w, h = bbox
        result.append(
            TextCandidate(
                text,
                bbox,
                confidence,
                "text_candidate",
                source="rapidocr-tile",
                quad=((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
            )
        )
    return tuple(result)


def local_region():
    gray = source()[2200:2410, 4080:4390]
    texts = tuple(
        offset_candidate(item, offset_x=-4080, offset_y=-2200) for item in candidates()
    )
    return gray, texts


def test_real_cell_recovers_complete_separate_source_rows_without_approving_touching_letters():
    gray, texts = local_region()
    prepared = tuple(prepare_safe_candidate(gray, item) for item in texts)
    assert not any(item.replacement_safe for item in prepared)
    result = constrain_texts_to_table_cells(gray, prepared)
    expected = (
        (4158, 2280, 4253, 2298),
        (4182, 2300, 4229, 2313),
        (4180, 2312, 4231, 2326),
    )
    for old, item, (x, y, right, bottom) in zip(texts, result, expected, strict=True):
        assert item.quad == (
            (x - 4080, y - 2200),
            (right - 4080, y - 2200),
            (right - 4080, bottom - 2200),
            (x - 4080, bottom - 2200),
        )
        assert item.text == old.text and item.confidence == old.confidence
        assert item.source == old.source and not item.reviewed and item.bbox == old.bbox
    assert result[0].replacement_safe and result[1].replacement_safe
    assert not result[2].replacement_safe
    assert result[2].character_boxes == prepared[2].character_boxes
    # Source has two blank rows between Chinese and English, while the two
    # English ink bounds overlap by one pixel (descender/ascender at different X).
    assert result[0].quad[2][1] < result[1].quad[0][1]
    assert result[1].quad[2][1] - result[2].quad[0][1] == 1


@pytest.mark.parametrize(
    "uncertainty", ["reviewed", "rotated", "connected-rows", "missing-rule"]
)
def test_uncertain_cells_do_not_invent_row_positions(uncertainty):
    gray, texts = local_region()
    gray = gray.copy()
    if uncertainty == "reviewed":
        texts = (replace(texts[0], reviewed=True), *texts[1:])
    elif uncertainty == "rotated":
        texts = (replace(texts[0], rotation_deg=3), *texts[1:])
    elif uncertainty == "connected-rows":
        cv2.line(gray, (4199 - 4080, 2286 - 2200), (4199 - 4080, 2320 - 2200), 0, 2)
        # Existing table clipping can see the added vertical stroke as a rule.
        # The new row association must leave the connected source undivided.
        result = _restore_cell_text_rows(gray, texts, (74, 78, 178, 129))
        assert result == texts
        return
    else:
        gray[2268 - 2200 : 2280 - 2200, :] = 255
        gray[2220 - 2200 : 2225 - 2200, :] = 255
    result = constrain_texts_to_table_cells(gray, texts)
    assert all(item.quad == old.quad for item, old in zip(result, texts, strict=True))


def test_normal_processing_export_preview_and_edit_roundtrip(monkeypatch, tmp_path):
    gray, texts = local_region()
    monkeypatch.setattr(
        optimized_trace,
        "recognize_text_candidates_optimized",
        lambda image, **kwargs: (
            tuple(prepare_safe_candidate(image, item) for item in texts),
            (),
        ),
    )
    traced = optimized_trace.trace_image_optimized(
        gray, enable_ocr=True, source_dpi=136, foreground_threshold=254
    )
    structure = final_structure_from_trace_result(traced)
    native = {item.text: item for item in structure.texts}
    assert native["专业负责人"].quad[0] == (78, 80)
    assert native["Discipline"].quad[2] == (149, 113)
    assert native["Responsible"].quad[2] == (151, 126)
    assert native["Responsible"].replacement_safe
    result = export_final_structure_dxf(structure, tmp_path / "cell.dxf")
    doc = ezdxf.readfile(result.path)
    entities = list(doc.modelspace().query("TEXT"))
    assert sorted(item.dxf.text for item in entities) == sorted(
        item.text for item in texts
    )
    assert all(
        doc.styles.get(item.dxf.style).dxf.font == "wqy-unicode.lff"
        for item in entities
    )
    preview = render_final_structure_preview(structure)
    assert np.array_equal(
        preview, render_emitted_dxf_preview(doc, tmp_path, structure.source_size_px)
    )
    entity = next(item for item in entities if item.dxf.text == "Discipline")
    handle = entity.dxf.handle
    entity.dxf.text += "A"
    doc.saveas(tmp_path / "edited.dxf")
    assert (
        ezdxf.readfile(tmp_path / "edited.dxf").entitydb[handle].dxf.text
        == "DisciplineA"
    )


def verified_cell():
    gray, texts = local_region()
    prepared = tuple(prepare_safe_candidate(gray, item) for item in texts)
    proofs = []
    resolved = constrain_texts_to_table_cells(gray, prepared, verified_sources=proofs)
    assert len(proofs) == 1
    # Use the digital-page threshold used by the full W02 page. It keeps faint
    # edges that join the otherwise separate strong-ink English rows.
    binary = prepare_scan_page(gray, foreground_threshold=254).binary
    owner = partition_content(binary, lines=(), texts=resolved, signatures=())
    return gray, binary, resolved, proofs, owner


def test_verified_character_tops_cover_unfiltered_glyph_ink_without_expanding_neighbors():
    from app.geometry.content_ownership import _candidate_region_mask

    gray, binary, texts, proofs, _ = verified_cell()
    legacy = constrain_texts_to_table_cells(
        gray, tuple(prepare_safe_candidate(gray, item) for item in local_region()[1]),
    )
    proof = proofs[0]
    left, top, right, bottom = proof.bounds
    core = np.zeros_like(gray)
    core[top:bottom, left:right] = proof.row_masks[0]
    before = _candidate_region_mask(legacy[0], gray.shape)
    after = _candidate_region_mask(texts[0], gray.shape)
    # The legacy line-removal mask lost strong tips still present in this row proof.
    assert not np.any((core > 0) & (after == 0))
    added = (binary < 128) & (after > 0) & (before == 0)
    assert np.count_nonzero(added) == 14
    assert texts[0].bbox == legacy[0].bbox and texts[0].quad == legacy[0].quad
    assert [(x, w, y + h) for x, y, w, h in texts[0].character_boxes] == [
        (x, w, y + h) for x, y, w, h in legacy[0].character_boxes
    ]
    assert texts[0].character_boxes[:1] == legacy[0].character_boxes[:1]
    assert texts[0].character_boxes[2:] == legacy[0].character_boxes[2:]


@pytest.mark.parametrize("neighbor", [
    None, "detached-weak", "foreign-strong", "foreign-strong-connected",
    "shared-character", "boundary-rule", "no-body-contact", "ascii",
])
def test_verified_character_top_keeps_detached_shared_and_foreign_source(neighbor):
    from app.ocr.ocr_layout import _restore_verified_character_tops

    gray = np.full((64, 72), 255, np.uint8)
    core = np.zeros_like(gray)
    core[12:33, 14:24] = 255
    core[18:33, 42:52] = 255
    item = TextCandidate(
        "中文", (8, 8, 55, 30), 0.99, "text_candidate", source="verified-row",
        approved=True, replacement_safe=True,
        quad=((8, 8), (63, 8), (63, 38), (8, 38)),
        character_boxes=((10, 18, 19, 18), (38, 18, 19, 18)),
    )
    if neighbor == "shared-character":
        core[22:24, 24:43] = 255
    elif neighbor == "boundary-rule":
        core[:13, 18:20] = 255
    elif neighbor == "no-body-contact":
        core[15:33, 14:24] = 0
    elif neighbor == "ascii":
        item = replace(item, text="AB")
    gray[core > 0] = 0
    if neighbor in {"detached-weak", "foreign-strong", "foreign-strong-connected"}:
        gray[13, 28] = 200 if neighbor == "detached-weak" else 0
    if neighbor == "foreign-strong-connected":
        gray[13, 24:28] = 200
    restored = _restore_verified_character_tops(item, gray, core, (0, 0, 72, 64))
    assert restored.bbox == item.bbox and restored.quad == item.quad
    if neighbor is None:
        assert restored.character_boxes == ((10, 12, 19, 24), item.character_boxes[1])
    else:
        assert restored.character_boxes == item.character_boxes


def test_full_line_source_proof_preserves_layout_and_owns_complete_ink_carriers():
    gray, binary, texts, proofs, owner = verified_cell()
    legacy = constrain_texts_to_table_cells(
        gray, tuple(prepare_safe_candidate(gray, item) for item in local_region()[1])
    )
    assert [item.quad for item in texts] == [item.quad for item in legacy]
    assert texts[2].replacement_safe and not legacy[2].replacement_safe
    assert [
        (item.text, item.confidence, item.source, item.reviewed) for item in texts
    ] == [(item.text, item.confidence, item.source, item.reviewed) for item in legacy]
    completed = complete_verified_text_ownership(
        binary, gray, texts, proofs, ownership=owner
    )
    assert np.count_nonzero(completed.text) > np.count_nonzero(owner.text)
    assert np.array_equal(completed.line, owner.line)
    left, top, right, bottom = proofs[0].bounds
    core = proofs[0].mask > 0
    assert np.all(completed.text[top:bottom, left:right][core] > 0)
    assert not np.any(
        completed.text[(binary == 0) & (gray < 128) & (np.indices(gray.shape)[0] < top)]
    )


@pytest.mark.parametrize("blocker", ["structure", "unclaimed-source", "uncertain-text"])
def test_whole_carrier_is_not_suppressed_when_source_or_structure_is_shared(blocker):
    gray, binary, texts, proofs, owner = verified_cell()
    gray, binary = gray.copy(), binary.copy()
    px, py = 4180 - 4080, 2313 - 2200
    if blocker == "structure":
        # An independently committed structure owns part of this same carrier.
        line = owner.line.copy()
        text = owner.text.copy()
        graphic = owner.graphic.copy()
        line[py, px] = 255
        text[py, px] = 0
        graphic[py, px] = 0
        owner = replace(owner, line=line, text=text, graphic=graphic)
        owner.assert_valid()
    elif blocker == "unclaimed-source":
        # A strong source stroke outside the verified row proof joins the word.
        gray[py, px - 1] = 0
        binary[py, px - 1] = 0
        owner = partition_content(binary, lines=(), texts=texts, signatures=())
    else:
        texts = (*texts[:2], replace(texts[2], replacement_safe=False))
    completed = complete_verified_text_ownership(
        binary, gray, texts, proofs, ownership=owner
    )
    count, labels = cv2.connectedComponents(
        (binary < 128).astype(np.uint8), connectivity=8
    )
    component = labels == labels[py, px]
    assert count > 1 and labels[py, px] != 0
    assert np.array_equal(completed.text[component], owner.text[component])
    assert np.array_equal(completed.line, owner.line)


def test_real_cell_exits_owned_members_after_source_arbitration_and_cache_roundtrip(tmp_path):
    from app.core.cache import load_trace_cache
    from tools.drafting_rules.source_adapter import validate_with_source
    from tools.drafting_rules.source_study import make_case

    args = make_case(
        tmp_path / "cell", (4080, 2200, 4390, 2410), candidates(),
        ("专业负责人", "专业负责者"),
    )
    report = validate_with_source(**args)
    row = next(r for r in report["source_ledger"]["rows"]
               if r["recognized_text"] == "专业负责人")
    # The old whole-row downgrade leaves 54 rendered source-core pixels here.
    assert row["residual_owned_core_pixels"] == 0
    assert report["summary"] == {"PASS": 10, "ABSTAIN": 2}
    assert all(r["unowned_pixels"] == r["cache_uncovered_pixels"] == 0
               for r in report["source_ledger"]["rows"])

    structure = load_trace_cache(args["cache"]).final_structure
    chinese = next(c for c in structure.texts if c.text == "专业负责人")
    assert chinese.replacement_safe
    gray, _ = local_region()
    restored = constrain_texts_to_table_cells(gray, structure.texts, verified_sources=(proofs := []))
    owner = partition_content(
        structure.preview_binary, lines=structure.straight_lines, texts=restored,
        logos=structure.logos, signatures=structure.signatures,
    )
    owned = complete_verified_text_ownership(
        structure.preview_binary, gray, restored, proofs, ownership=owner,
    )
    from app.geometry.content_ownership import _rasterize_line_claims

    band = _rasterize_line_claims(structure.straight_lines, shape=gray.shape)
    released = (band > 0) & (structure.preview_binary < 128) & (owner.line == 0)
    # Six disconnected Chinese edges leave line ownership first. Only then
    # can the existing complete-carrier proof absorb the three English edges.
    assert np.count_nonzero(released) == 6
    assert np.all(owned.text[released])
    assert np.count_nonzero((owned.text > 0) & (owner.text == 0)) == 3
    assert np.array_equal(owned.text, structure.editable_text_source_mask)
    owned.assert_valid()
    known = np.zeros(gray.shape, dtype=bool)
    for y, x0, x1 in row["core_runs"]:
        known[y, x0:x1] = True
    known &= owned.text > 0
    assert not np.any(structure.contour_binary[known] < 128)
    assert not np.any(structure.source_text_outline_mask[known])
    assert not np.any(structure.uncertain_text_outline_mask[known])

    cached_dxf = tmp_path / "cached.dxf"
    export_final_structure_dxf(structure, cached_dxf)
    saved = ezdxf.readfile(cached_dxf)
    text = next(e for e in saved.modelspace().query("TEXT") if e.dxf.text == chinese.text)
    text.dxf.text = "专业负责者"
    saved.saveas(tmp_path / "cached-edited.dxf")
    reopened = ezdxf.readfile(tmp_path / "cached-edited.dxf")
    assert reopened.entitydb[text.dxf.handle].dxf.text == "专业负责者"
    assert [e.dxf.text for e in reopened.modelspace().query("TEXT")][1:] == [
        "Discipline", "Responsible",
    ]
    from app.export.trace_dxf_entities import _path_matches_ocr

    independent = [p for p in structure.contours if p.depth % 2 == 0
                   and _path_matches_ocr(p, (chinese,))]
    assert independent  # Nearby rule ink that the old bbox filter would drop.
    exported = [tuple(e.get_points("xy")) for e in reopened.modelspace().query("LWPOLYLINE")]
    for path in independent:
        assert all(not structure.editable_text_source_mask[round(y), round(x)]
                   for x, y in path.points)
        assert tuple((x, gray.shape[0] - y) for x, y in path.points) in exported
    visible_geometry = [e for e in reopened.modelspace() if e.dxftype() != "TEXT"
                        and not reopened.layers.get(e.dxf.layer).is_off()
                        and not reopened.layers.get(e.dxf.layer).is_frozen()]
    from tools.drafting_rules.source_adapter import DocumentView

    ink = render_emitted_dxf_preview(
        DocumentView(reopened, visible_geometry), tmp_path, structure.source_size_px,
    ) < 255
    assert not np.any(ink & known)
