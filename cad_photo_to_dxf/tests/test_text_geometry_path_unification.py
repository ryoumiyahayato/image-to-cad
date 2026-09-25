from __future__ import annotations

from math import isclose

import ezdxf

from app.auxiliary_recognition import TextCandidate
from app.ocr_outline_export import add_ocr_outline_blocks
from app.trace_dxf_entities import add_ocr_text_entities


def _candidate() -> TextCandidate:
    return TextCandidate(
        text="中文 ABC 7600",
        bbox=(10, 20, 120, 24),
        confidence=0.99,
        kind="text_candidate",
        quad=((10.0, 20.0), (130.0, 20.0), (130.0, 44.0), (10.0, 44.0)),
        source="path-unification-test",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )


def _summary(entity) -> tuple[object, ...]:
    return (
        entity.dxftype(),
        entity.dxf.text,
        float(entity.dxf.height),
        float(entity.dxf.width),
        float(entity.dxf.rotation),
        (float(entity.dxf.insert.x), float(entity.dxf.insert.y)),
    )


def test_legacy_trace_entry_delegates_to_canonical_geometry() -> None:
    candidate=_candidate()
    transform=lambda x,y:(x,200.0-y)
    canonical=ezdxf.new("R2010",setup=True)
    legacy=ezdxf.new("R2010",setup=True)
    c_count,c_entities,_=add_ocr_outline_blocks(
        canonical,canonical.modelspace(),(candidate,),transform=transform,minimum_confidence=0.58
    )
    l_count,l_entities,_=add_ocr_text_entities(
        legacy.modelspace(),(candidate,),transform=transform,minimum_confidence=0.58
    )
    assert c_count == l_count == 1
    c=_summary(c_entities[0])
    l=_summary(l_entities[0])
    assert c[:2] == l[:2]
    for left,right in zip(c[2:5],l[2:5],strict=True):
        assert isclose(left,right,rel_tol=1e-12,abs_tol=1e-12)
    assert c[5] == l[5]
    assert not canonical.audit().errors
    assert not legacy.audit().errors


def test_legacy_module_has_no_independent_height_formula() -> None:
    from pathlib import Path
    source=Path('app/trace_dxf_entities.py').read_text(encoding='utf-8')
    assert 'target_height * 0.82' not in source
    assert '_text_width_units' not in source
