"""Finalize already committed real models through the existing representation code.

W01/W02/W03 use production P2B runs. E01 replays the SAME production stage
on the captured UAT FinalStructure. Structural LINE tuples are frozen in both.
This also refreshes source-opacity assets after the gray-detail correction.
"""
from pathlib import Path
from dataclasses import replace
import json
import sys

import cv2
import ezdxf
import numpy as np

from app.core.cache import load_trace_cache, save_trace_cache, _deserialize_texts
from app.core.image_loader import load_image, save_image
from app.core.preview import render_final_structure_preview
from app.core.scale_calibrator import ScaleCalibration
from app.core.trace_types import TracePath
from app.geometry.raster_trace import RasterTraceResult, trace_binary
from app.geometry.content_ownership import TextSemanticOwnership
from app.geometry.optimized_trace import commit_source_objects
from app.ocr.signature_overlay import source_ink_region
from app.export.trace_single_export import export_final_structure_dxf


def run(uat, output):
    report = {}
    for uid in ('W01','W02','W03','E01'):
        folder = output/uid
        folder.mkdir(exist_ok=True,parents=True)
        input_info = json.loads((uat/uid/'input.json').read_text(encoding='utf-8'))
        gray = load_image(Path('tests/real_regression/assets/sources')/Path(input_info['SOURCE_FILE']).name,
            page_index=input_info['SOURCE_PAGE']-1,pdf_dpi=input_info['DPI'],grayscale=True)
        seed = load_trace_cache((uat/uid if uid == 'E01' else folder)/'processing-result.npz').final_structure
        lines = seed.straight_lines
        if uid == 'E01':
            candidates = _deserialize_texts((uat/uid/'texts.json').read_text(encoding='utf-8'))
            def mask(value):
                return np.zeros_like(gray) if value is None else value
            semantics = TextSemanticOwnership(mask(seed.editable_text_source_mask),
                mask(seed.source_text_outline_mask),mask(seed.uncertain_text_outline_mask),())
            binary,texts,logos,signatures,semantics,enclosures,records = commit_source_objects(
                source_gray=gray,contour_binary=seed.contour_binary.copy(),source_candidates=candidates,
                texts=seed.texts,logos=seed.logos,signatures=seed.signatures,text_semantics=semantics)
            paths = tuple(trace_binary(binary))
            records = tuple(dict(r,contour_index=len(paths)+i) for i,r in enumerate(records))
            paths += tuple(replace(p,root=len(paths)+i) for i,p in enumerate(enclosures))
            structure = replace(seed,contour_binary=binary,contours=paths,texts=texts,
                logos=logos,signatures=signatures,editable_text_source_mask=semantics.editable_source,
                source_text_outline_mask=semantics.source_outline,uncertain_text_outline_mask=semantics.uncertain_outline,
                provenance={**dict(seed.provenance),'engineering_enclosures':records})
        else:
            structure = replace(seed,logos=tuple(source_ink_region(r,gray) for r in seed.logos),
                signatures=tuple(source_ink_region(r,gray) for r in seed.signatures))
        assert structure.straight_lines == lines
        trace = RasterTraceResult(structure.contour_binary,{},structure.contours,structure.threshold,
            int(np.count_nonzero(structure.contour_binary < 128)),sum(len(p.points) for p in structure.contours),
            final_structure=structure)
        save_trace_cache(folder/'processing-result.npz',trace)
        assert load_trace_cache(folder/'processing-result.npz').final_structure.structure_id == structure.structure_id
        save_image(folder/'source.png',gray)
        scale = input_info['PAGE_SIZE_MM'][0]/gray.shape[1]
        result = export_final_structure_dxf(structure,folder/'drawing.dxf',ScaleCalibration((0,0),(1,0),scale))
        doc = ezdxf.readfile(result.path)
        assert not doc.audit().has_errors
        images = list(doc.modelspace().query('IMAGE'))
        assets = []
        for entity in images:
            name = entity.image_def.dxf.filename
            assert not Path(name).is_absolute() and ':' not in name
            assert (folder/name).is_file()
            rgba = cv2.imdecode(np.fromfile(folder/name,np.uint8),cv2.IMREAD_UNCHANGED)
            assert rgba.shape[2] == 4 and np.any(rgba[:,:,3] == 0)
            assets.append(dict(filename=name,object_class=entity.get_xdata('IMAGE_TO_CAD')[0].value,
                transparent_pixels=int(np.count_nonzero(rgba[:,:,3] == 0)),
                partial_ink_pixels=int(np.count_nonzero((rgba[:,:,3]>0)&(rgba[:,:,3]<255))),
                insert=list(entity.dxf.insert),u_pixel=list(entity.dxf.u_pixel),v_pixel=list(entity.dxf.v_pixel)))
        for entity in images:
            entity.translate(2,3,0)
            entity.scale_uniform(1.25)
        doc.saveas(folder/'move-scale-save-reopen.dxf')
        reopened = ezdxf.readfile(folder/'move-scale-save-reopen.dxf')
        assert not reopened.audit().has_errors
        assert len(reopened.modelspace().query('IMAGE')) == len(images)
        assert len(reopened.modelspace().query('LINE')) == len(doc.modelspace().query('LINE'))
        for entity in reopened.modelspace().query('IMAGE'):
            assert (folder/entity.image_def.dxf.filename).is_file()
        if images:
            reopened.modelspace().delete_entity(reopened.modelspace().query('IMAGE')[0])
            reopened.saveas(folder/'delete-save-reopen.dxf')
            assert len(ezdxf.readfile(folder/'delete-save-reopen.dxf').modelspace().query('IMAGE')) == len(images)-1
        save_image(folder/'final-preview.png',render_final_structure_preview(structure))
        report[uid] = dict(structure_id=structure.structure_id,lines=len(lines),line_tuple_unchanged=True,
            evidence_scope='committed UAT model + production representation stage' if uid=='E01' else
                           'production P2B run + production source-opacity encode',
            logos=[list(r.bbox) for r in structure.logos if r.visual_kind!='engineering_graphic'],
            signatures=[list(r.bbox) for r in structure.signatures],images=assets,audit_errors=0,
            graphic_move_scale_delete_save_reopen='PASS',preview='actual DXF entities and relative IMAGE assets')
        (output/'final-measurements.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(uid,'PASS',len(images),'IMAGE',flush=True)
    return report


if __name__ == '__main__':
    run(Path(sys.argv[1]),Path(sys.argv[2]))
