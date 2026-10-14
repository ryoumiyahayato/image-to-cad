"""Real source regressions with frozen OCR; OCR domain accuracy is out of scope."""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.cache import _deserialize_texts, save_trace_cache, load_trace_cache
from app.core.image_loader import load_image
from app.core.preview import render_final_structure_preview, render_source_reference
from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.export.trace_document_export import export_trace_document_streaming
from app.export.document_export import DocumentPage
from app.geometry.content_ownership import graphic_source_mask, signature_source_mask
from app.geometry.line_detect import LineSegment
from app.geometry.optimized_trace import _graphic_owns_text
from app.geometry.raster_trace import RasterTraceResult
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.engineering_symbols import resolve_enclosure_relations
from app.ocr.logo_detection import source_logo_objects
from app.ocr.signature_overlay import signature_field_regions, signature_rgba, source_ink_region

HERE = Path(__file__).parent
OBSERVATIONS = json.loads((HERE/'fixtures/product-p2b-ocr-observations.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=4)
def source(uid):
    info = OBSERVATIONS[uid]['input']
    gray = load_image(HERE/'real_regression/assets/sources'/Path(info['SOURCE_FILE']).name,
                      page_index=info['SOURCE_PAGE']-1, pdf_dpi=info['DPI'], grayscale=True)
    return np.where(gray < 128, 0, 255).astype(np.uint8)


def candidates(uid):
    return _deserialize_texts(json.dumps(OBSERVATIONS[uid]['candidates']))


@lru_cache(maxsize=3)
def logos(uid):
    return source_logo_objects(source(uid))


@lru_cache(maxsize=1)
def signatures():
    return signature_field_regions(source('W03'), candidates('W03'))


def object_structure(region, *, signature=False, line=False):
    x, y, w, h = region.bbox
    region = replace(region, bbox=(4, 4, w, h))
    blank = np.full((h+8, w+8), 255, np.uint8)
    return build_final_structure(source_size_px=(w+8, h+8), contour_binary=blank,
        contours=(), logos=() if signature else (region,),
        signatures=(region,) if signature else (), preview_binary=blank,
        straight_lines=(LineSegment(0, h/2+4, w+7, h/2+4),) if line else ())


@pytest.mark.parametrize('content,kind', [('M', 'LWPOLYLINE'), ('SL', 'CIRCLE')])
def test_w02_compound_symbol_actual_dxf(content, kind, tmp_path):
    texts, paths, records, graphics, claimed = resolve_enclosure_relations(source('W02'), candidates('W02')[:5])
    assert not graphics
    assert not any(t.text == 'M2' for t in texts)
    assert sum(t.text == 'M' for t in texts) == 2
    assert sum(t.text == 'SL' for t in texts) == 1
    assert sum(t.text == '2' for t in texts) == 4
    records = tuple(dict(r, contour_index=i) for i, r in enumerate(records))
    height, width = source('W02').shape
    structure = build_final_structure(source_size_px=(width, height),
        contour_binary=np.full((height, width), 255, np.uint8), contours=paths,
        texts=texts, provenance={'engineering_enclosures': records})
    exported = export_final_structure_dxf(structure, tmp_path/'symbols.dxf')
    doc = ezdxf.readfile(exported.path)
    assert not doc.audit().has_errors
    entities = list(doc.modelspace().query(f'{kind}[layer=="ENGINEERING_SYMBOL"]'))
    assert len(entities) == (2 if content == 'M' else 1)
    native = [t for t in doc.modelspace().query('TEXT') if t.dxf.text == content]
    assert len(native) == (2 if content == 'M' else 1)
    # Actual insertion and independent labels remain at source-relative places.
    assert 1648 < native[-1].dxf.insert.x < 1725
    assert all(t.dxf.text != 'M2' for t in doc.modelspace().query('TEXT'))
    assert np.count_nonzero(claimed) > 0


@pytest.mark.parametrize('uid,bbox', [('E01',(3651,83,99,98)),
                                    ('W02',(4240,1489,254,100)),
                                    ('W03',(4338,1204,206,82))])
def test_real_logo_whole_object_and_not_text_s(uid, bbox, tmp_path):
    marks = logos(uid)
    assert len(marks) == 1
    assert marks[0].bbox == bbox
    x, y, w, h = bbox
    assert np.all(source(uid)[y:y+h, x:x+w][marks[0].mask > 0] == 0)
    mask = graphic_source_mask(source(uid), marks)
    assert all(_graphic_owns_text(c, source(uid), mask) for c in candidates(uid) if c.text == 'S')
    result = export_final_structure_dxf(object_structure(marks[0]), tmp_path/'logo.dxf')
    doc = ezdxf.readfile(result.path)
    assert len(doc.modelspace().query('IMAGE')) == 1
    assert not doc.modelspace().query('TEXT')
    assert result.graphic_paths and not doc.audit().has_errors


def test_w03_signatures_and_printed_names_have_separate_ownership(tmp_path):
    regions = signatures()
    assert len(regions) == 7
    mask = signature_source_mask(source('W03'), regions)
    names = [c for c in candidates('W03') if 4370 <= c.bbox[0] < 4430 and 1670 <= c.bbox[1] <= 1950]
    handwriting = [c for c in candidates('W03') if 4440 <= c.bbox[0] < 4520 and 1670 <= c.bbox[1] <= 1950]
    assert len(names) == 7
    assert all(not _graphic_owns_text(c, source('W03'), mask) for c in names)
    assert all(_graphic_owns_text(c, source('W03'), mask) for c in handwriting)
    blank = np.full_like(source('W03'), 255)
    structure = build_final_structure(source_size_px=blank.shape[::-1], contour_binary=blank,
        contours=(), texts=tuple(names), signatures=regions)
    result = export_final_structure_dxf(structure, tmp_path/'signature.dxf')
    doc = ezdxf.readfile(result.path)
    assert len(doc.modelspace().query('IMAGE')) == 7
    assert len(doc.modelspace().query('TEXT')) == 7
    assert all(e.get_xdata('IMAGE_TO_CAD')[0].value == 'SIGNATURE' for e in doc.modelspace().query('IMAGE'))


def test_transparent_foreground_keeps_native_line_visible_and_no_paper(tmp_path):
    region = signatures()[0]
    rgba = signature_rgba(region)
    assert set(np.unique(rgba[:, :, 3])) == {0, 255}
    assert np.all(rgba[:, :, :3][rgba[:, :, 3] > 0] == 0)
    structure = object_structure(region, signature=True, line=True)
    preview = render_final_structure_preview(structure)
    row = round(region.bbox[3]/2+4)
    assert np.all(preview[row, :4] < 128)  # native line outside graphic ink
    assert np.any(preview[4:-4, 4:-4] == 255)
    assert np.all(preview[:3] == 255)


@pytest.mark.parametrize('uid', ['W01', 'W03'])
def test_known_source_1_final_7_preview_parity(uid):
    candidate = next(c for c in candidates(uid) if c.text == '7')
    x, y, w, h = candidate.bbox
    crop = source(uid)[y:y+h, x:x+w]
    blank = np.full((h+12, w+12), 255, np.uint8)
    reference = blank.copy()
    reference[6:6+h, 6:6+w] = crop
    shifted = replace(candidate, bbox=(6,6,w,h), quad=None, character_boxes=())
    structure = build_final_structure(source_size_px=blank.shape[::-1], contour_binary=blank,
        contours=(), texts=(shifted,), preview_binary=reference)
    final = render_final_structure_preview(structure)
    same_without_reference = replace(structure, preview_binary=blank)
    assert np.array_equal(final, render_final_structure_preview(same_without_reference))
    assert not np.array_equal(final, render_source_reference(structure))
    assert np.any(final < 128)
    assert not np.array_equal(final, render_final_structure_preview(
        replace(structure, texts=(replace(shifted, text='1'),))))


def test_logo_preview_parity_includes_final_and_never_missing_source_logo():
    structure = object_structure(logos('E01')[0])
    final = render_final_structure_preview(structure)
    assert np.any(final < 128)
    absent = replace(structure, logos=(), preview_binary=final)
    assert np.all(render_final_structure_preview(absent) == 255)
    assert np.array_equal(render_source_reference(absent), final)


def test_relative_image_move_scale_delete_save_reopen_and_package_relocation(tmp_path):
    structure = object_structure(logos('E01')[0])
    result = export_final_structure_dxf(structure, tmp_path/'drawing.dxf')
    doc = ezdxf.readfile(result.path)
    image = doc.modelspace().query('IMAGE')[0]
    filename = image.image_def.dxf.filename
    assert not Path(filename).is_absolute() and ':' not in filename
    asset = tmp_path/filename
    assert asset.is_file()
    image.translate(10,20,0)
    image.scale_uniform(2)
    expected_insert = image.dxf.insert
    expected_u = image.dxf.u_pixel
    doc.saveas(tmp_path/'edited.dxf')
    reopened = ezdxf.readfile(tmp_path/'edited.dxf')
    image = reopened.modelspace().query('IMAGE')[0]
    assert image.dxf.insert == expected_insert and image.dxf.u_pixel == expected_u
    assert not reopened.audit().has_errors
    package = tmp_path/'relocated'
    package.mkdir()
    (tmp_path/'edited.dxf').replace(package/'edited.dxf')
    asset.replace(package/filename)
    assert (package/ezdxf.readfile(package/'edited.dxf').modelspace().query('IMAGE')[0].image_def.dxf.filename).is_file()
    reopened.modelspace().delete_entity(image)
    reopened.saveas(package/'deleted.dxf')
    assert not ezdxf.readfile(package/'deleted.dxf').modelspace().query('IMAGE')


def test_document_export_reuses_same_graphic_representation(tmp_path):
    structure = object_structure(logos('W02')[0])
    pages = [DocumentPage(i, None, (300,200), final_structure=structure) for i in (1,2)]
    result = export_trace_document_streaming(pages, tmp_path/'pages.dxf', total_pages=2)
    doc = ezdxf.readfile(result.path)
    assert len(doc.modelspace().query('IMAGE')) == 2
    assert len({e.image_def.dxf.filename for e in doc.modelspace().query('IMAGE')}) == 2
    assert len(result.graphic_paths) == 2 and not doc.audit().has_errors


def test_enclosure_decision_and_graphic_class_are_fingerprinted():
    region = logos('E01')[0]
    structure = object_structure(region)
    assert structure.structure_id != replace(structure, logos=(replace(structure.logos[0], visual_kind='engineering_graphic'),)).structure_id


def test_native_enclosure_precision_and_graphic_class_survive_cache(tmp_path):
    structure = object_structure(replace(logos('E01')[0], visual_kind='engineering_graphic'))
    _, paths, records, _, _ = resolve_enclosure_relations(source('W02'), candidates('W02')[:5])
    circle = paths[next(i for i,r in enumerate(records) if r['kind'] == 'circle')]
    path = replace(circle, points=tuple((x-1640,y-745) for x,y in circle.points), root=0)
    structure = replace(structure, contours=(path,),
                        provenance={'engineering_enclosures':({'kind':'circle','contour_index':0},)})
    result = RasterTraceResult(structure.contour_binary,{},structure.contours,128,0,len(path.points),
                                final_structure=structure)
    save_trace_cache(tmp_path/'object.npz', result)
    reopened = load_trace_cache(tmp_path/'object.npz').final_structure
    assert reopened.structure_id == structure.structure_id
    assert reopened.contours == structure.contours
    assert reopened.logos[0].visual_kind == 'engineering_graphic'
    assert reopened.structure_id != replace(reopened, provenance={
        'engineering_enclosures':({'kind':'rectangle','contour_index':0},)}).structure_id


def test_real_logo_source_gray_detail_and_transparent_alpha_survive_cache_and_preview(tmp_path):
    info = OBSERVATIONS['W02']['input']
    gray = load_image(HERE/'real_regression/assets/sources'/info['SOURCE_FILE'],
                      page_index=info['SOURCE_PAGE']-1,pdf_dpi=info['DPI'],grayscale=True)
    region = source_ink_region(logos('W02')[0],gray)
    x,y,w,h = region.bbox
    ink = region.mask > 0
    assert np.any((region.mask > 0) & (region.mask < 255))
    rgba = signature_rgba(region)
    assert np.array_equal(255-rgba[:, :, 3][ink],gray[y:y+h,x:x+w][ink])
    assert np.all(rgba[:, :, 3][~ink] == 0)
    structure = object_structure(region)
    result = RasterTraceResult(structure.contour_binary,{},(),128,0,0,final_structure=structure)
    save_trace_cache(tmp_path/'gray-ink.npz',result)
    restored = load_trace_cache(tmp_path/'gray-ink.npz').final_structure
    assert restored.structure_id == structure.structure_id
    assert np.array_equal(restored.logos[0].mask,region.mask)
    preview = render_final_structure_preview(restored)[4:4+h,4:4+w]
    assert np.max(np.abs(preview[ink].astype(int)-gray[y:y+h,x:x+w][ink])) <= 1


def test_unsupported_enclosure_or_unusable_text_preserves_whole_graphic(tmp_path):
    binary = np.full((1200,1200),255,np.uint8)
    boundary = np.array([(40,40),(67,40),(73,50),(70,72),(45,75),(38,65)],np.int32)
    cv2.polylines(binary,[boundary],True,0,1)
    cv2.putText(binary,'X',(48,64),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    candidate = TextCandidate('X',(47,48,16,20),.99,'text_candidate',
                               character_boxes=((47,48,16,20),))
    texts,paths,records,graphics,_ = resolve_enclosure_relations(binary,(candidate,))
    assert not texts and not paths and not records and len(graphics) == 1
    x,y,w,h = graphics[0].bbox
    assert x <= boundary[:,0].min() and x+w > boundary[:,0].max()
    assert y <= boundary[:,1].min() and y+h > boundary[:,1].max()
    assert np.array_equal(graphics[0].mask, np.where(binary[y:y+h,x:x+w]<128,255,0))
    structure = object_structure(graphics[0])
    result = export_final_structure_dxf(structure,tmp_path/'fallback.dxf')
    image = ezdxf.readfile(result.path).modelspace().query('IMAGE')[0]
    assert image.get_xdata('IMAGE_TO_CAD')[0].value == 'GRAPHIC'
    # A reliable square with unusable OCR must also keep the internal source ink.
    square = np.full_like(binary,255)
    cv2.rectangle(square,(40,40),(70,70),0,1)
    cv2.putText(square,'X',(48,64),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    texts,paths,_,graphics,_ = resolve_enclosure_relations(square,(replace(candidate,approved=False),))
    assert not texts and not paths and graphics


def test_general_relation_does_not_use_letter_dictionary():
    blank = np.full((300,300), 255, np.uint8)
    cv2.rectangle(blank, (40,40), (70,70), 0, 1)
    cv2.putText(blank, 'X', (47,64), cv2.FONT_HERSHEY_SIMPLEX, .5, 0, 1)
    candidate = TextCandidate('X9', (45,44,46,25), .99, 'text_candidate',
        character_boxes=((46,45,19,22),(77,45,13,22)))
    # Page-relative maximum is deliberately scoped to small engineering marks.
    large = np.pad(blank, ((0,900),(0,900)), constant_values=255)
    texts, paths, records, graphics, _ = resolve_enclosure_relations(large, (candidate,))
    assert [c.text for c in texts] == ['X','9']
    assert len(paths) == 1 and records[0]['kind'] == 'rectangle' and not graphics


def test_plain_closed_glyph_is_not_an_enclosure():
    binary = np.full((1200,1200),255,np.uint8)
    cv2.circle(binary,(60,60),18,0,5)
    candidate = TextCandidate('O',(40,40,40,40),.99,'text_candidate')
    texts,paths,records,graphics,mask = resolve_enclosure_relations(binary,(candidate,))
    assert texts == (candidate,)
    assert not paths and not records and not graphics and not np.any(mask)


def test_complex_graphic_keeps_adjacent_label_independent():
    binary = np.full((1200,1200),255,np.uint8)
    boundary = np.array([(40,40),(67,40),(73,50),(70,72),(45,75),(38,65)],np.int32)
    cv2.polylines(binary,[boundary],True,0,1)
    cv2.putText(binary,'X',(48,64),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    cv2.putText(binary,'9',(85,64),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    candidate = TextCandidate('X9',(47,48,54,20),.99,'text_candidate',
                               character_boxes=((47,48,16,20),(84,48,17,20)))
    owned = set()
    texts,paths,records,graphics,_ = resolve_enclosure_relations(binary,(candidate,),claimed_candidates=owned)
    assert [t.text for t in texts] == ['9']
    assert owned == {0} and not paths and not records and len(graphics) == 1
    assert texts[0].bbox[0] >= graphics[0].bbox[0]+graphics[0].bbox[2]
