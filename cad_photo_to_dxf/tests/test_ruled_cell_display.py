"""Content-independent display-only proof and source immutability checks."""
from dataclasses import asdict, replace

import cv2
import numpy as np
import pytest

from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ruled_cell_display import refine_ruled_cell_row_displays


def sample(offset=(0, 0), scale=1):
    image = np.full((110, 150), 255, np.uint8)
    for x in (28, 83):
        cv2.rectangle(image, (x, 25), (x+14, 43), 0, 1)
        cv2.line(image, (x, 34), (x+14, 34), 0, 1)
    cv2.putText(image, 'Sample', (43, 64), cv2.FONT_HERSHEY_SIMPLEX, .4, 0, 1)
    texts = (
        TextCandidate('中文', (22, 18, 85, 36), .99, 'text_candidate',
                      rotation_deg=2, quad=((22,18),(107,21),(107,54),(22,51)),
                      source='rapidocr-test', replacement_safe=False),
        TextCandidate('Sample', (38, 48, 60, 23), .99, 'text_candidate',
                      source='rapidocr-test', replacement_safe=False),
    )
    dx, dy = offset
    output = np.full((110*scale+dy+10, 150*scale+dx+10), 255, np.uint8)
    output[dy:dy+110*scale, dx:dx+150*scale] = cv2.resize(
        image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    def point(p): return (p[0]*scale+dx, p[1]*scale+dy)
    texts = tuple(replace(t,
        bbox=(t.bbox[0]*scale+dx,t.bbox[1]*scale+dy,t.bbox[2]*scale,t.bbox[3]*scale),
        quad=tuple(point(p) for p in t.quad) if t.quad else None) for t in texts)
    cell = (10*scale+dx,10*scale+dy,130*scale+dx,90*scale+dy)
    cells = {cell:tuple((t.text,t.bbox) for t in texts)}
    return output, texts, cells


@pytest.mark.parametrize('offset,scale', [((0,0),1),((37,21),1),((13,19),2)])
def test_only_display_changes_with_translation_and_scale(offset, scale):
    image, texts, cells = sample(offset, scale)
    result, proofs = refine_ruled_cell_row_displays(image,texts,cells)
    assert len(proofs) == 2
    for old, new in zip(texts,result,strict=True):
        a,b=asdict(old),asdict(new)
        assert b.pop('display_quad') is not None
        a.pop('display_quad')
        assert a == b
    assert result[0].display_quad[2][1] < result[1].display_quad[0][1]
    assert refine_ruled_cell_row_displays(image,result,cells) == (result,())
    from app.core.cache import _deserialize_texts, _serialize_texts
    assert _deserialize_texts(_serialize_texts(result)) == result


@pytest.mark.parametrize('unsafe', ['connected','tilted-source','numeric','manual','rotated',
                                     'existing-display','protected','missing-member'])
def test_uncertain_source_or_existing_contract_is_untouched(unsafe):
    image,texts,cells=sample()
    if unsafe == 'connected':
        cv2.line(image,(40,40),(50,60),0,2)
    elif unsafe == 'tilted-source':
        image[25:44,83:98]=255
        cv2.rectangle(image,(83,29),(97,47),0,1)
        cv2.line(image,(83,38),(97,38),0,1)
    elif unsafe in {'numeric','manual','rotated','existing-display'}:
        changes = {'numeric':dict(text='123'), 'manual':dict(reviewed=True),
                   'rotated':dict(rotation_deg=90),
                   'existing-display':dict(display_quad=((22,18),(107,18),(107,54),(22,54)))}
        texts=(replace(texts[0],**changes[unsafe]),texts[1])
        cell=next(iter(cells));cells={cell:tuple((t.text,t.bbox) for t in texts)}
    elif unsafe == 'missing-member':
        texts=texts[:1]
    masks=[]
    if unsafe == 'protected':
        mask=np.zeros_like(image);mask[25:44,28:43]=255;masks=[mask]
    result,proofs=refine_ruled_cell_row_displays(image,texts,cells,protected_source_masks=masks)
    assert result == texts and not proofs


def test_substituted_glyph_does_not_touch_protected_source_paper():
    from PySide6.QtCore import QPointF
    from app.export.ocr_outline_export import native_text_placement
    from app.export.review_text import glyph_footprint

    image, texts, cells = sample()
    proposed, proofs = refine_ruled_cell_row_displays(image, texts, cells)
    assert len(proofs) == 2
    transform = lambda x, y: (x, image.shape[0] - y)
    new = glyph_footprint(native_text_placement(proposed[0], transform=transform))
    old = glyph_footprint(native_text_placement(texts[0], transform=transform))
    pixel = next((x, y) for y in range(20, 50) for x in range(25, 105)
                 if image[y, x] == 255
                 and new.contains(QPointF(x + .5, image.shape[0] - y - .5))
                 and not old.contains(QPointF(x + .5, image.shape[0] - y - .5)))
    x, y = pixel
    image[y, x] = 200  # outside the strong source-component proof, still protected
    protection = np.zeros_like(image)
    protection[y, x] = 255
    assert refine_ruled_cell_row_displays(
        image, texts, cells, protected_source_masks=(protection,)
    ) == (texts, ())

def test_observation_sidechannel_does_not_change_source_recovery_or_singleton_map():
    from app.ocr.ocr_layout import constrain_texts_to_table_cells

    image, texts, _ = sample()
    for y in (10, 90):
        cv2.line(image, (0, y), (image.shape[1]-1, y), 0, 1)
    for x in (10, 130):
        cv2.line(image, (x, 0), (x, image.shape[0]-1), 0, 1)
    old_singletons, new_singletons, groups = {}, {}, {}
    expected = constrain_texts_to_table_cells(image, texts, display_cells=old_singletons)
    actual = constrain_texts_to_table_cells(
        image, texts, display_cells=new_singletons, display_row_cells=groups)
    assert expected == actual
    assert new_singletons == old_singletons
    assert any(len(members) == 2 for members in groups.values())
