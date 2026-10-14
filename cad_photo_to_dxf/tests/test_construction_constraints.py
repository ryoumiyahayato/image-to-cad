from dataclasses import replace
import numpy as np
import pytest
from app.geometry.line_detect import LineSegment
from app.core.processing import ProductionProcessingConfig, build_processing_cache_key
from app.core.structure import FinalStructure


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True])
def test_line_rejects_invalid_coordinates_on_creation(value):
    with pytest.raises(ValueError):
        LineSegment(value, 0, 10, 0)


def test_cache_deserialization_cannot_bypass_identifier_validation():
    key = build_processing_cache_key(input_content_sha256='A'*64, page_index=0, config=ProductionProcessingConfig())
    assert key.input_content_sha256 == 'a'*64
    with pytest.raises(ValueError):
        replace(key, input_content_sha256='bad')
    with pytest.raises(ValueError):
        replace(key, page_number=0)


def test_direct_final_structure_construction_detaches_masks_and_metadata():
    mask = np.full((10, 20),255,np.uint8)
    provenance = {'nested': [1]}
    structure = FinalStructure((20,10),mask,(),provenance=provenance)
    mask[:] = 0
    provenance['nested'].append(2)
    assert np.all(structure.contour_binary == 255)
    assert structure.provenance['nested'] == (1,)
    with pytest.raises(ValueError):
        replace(structure, preview_binary=np.zeros((2,2),np.uint8))
