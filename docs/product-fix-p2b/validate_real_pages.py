"""P2B evidence runner. Frozen UAT OCR content; real production geometry/export.

Run from cad_photo_to_dxf. The original UAT directory is supplied explicitly;
PNG/NPZ/DXF/PDF artifacts stay in ignored local-artifacts/product-fix-p2b.
"""
from pathlib import Path
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from dataclasses import asdict

import cv2
import ezdxf
import numpy as np

from app.core.cache import _deserialize_texts, _deserialize_lines, save_trace_cache, load_trace_cache
from app.core.image_loader import load_image, save_image
from app.core.preview import render_final_structure_preview
from app.core.scale_calibrator import ScaleCalibration
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.optimized_trace import trace_image_optimized


def run(uat, output):
    output.mkdir(parents=True, exist_ok=True)
    # Read-only execution of the CLOSED P1 implementation, using exactly the
    # same current structural modules and frozen OCR observations as P2B.
    previous = subprocess.check_output(['git', 'show',
        '2aa8345:cad_photo_to_dxf/app/geometry/optimized_trace.py'], text=True, encoding='utf-8')
    baseline = ModuleType('p2b_p1_baseline')
    exec(compile(previous, 'closed-p1-optimized_trace.py', 'exec'), baseline.__dict__)
    summary = {}
    for uid in ('W01', 'W02', 'W03', 'E01'):
        target = output / uid
        target.mkdir(exist_ok=True)
        info = json.loads((uat/uid/'input.json').read_text(encoding='utf-8'))
        source = load_image(Path('tests/real_regression/assets/sources')/Path(info['SOURCE_FILE']).name,
            page_index=info['SOURCE_PAGE']-1, pdf_dpi=info['DPI'], grayscale=True)
        candidates = _deserialize_texts((uat/uid/'texts.json').read_text(encoding='utf-8'))
        print(uid, 'baseline', flush=True)
        verified = output.parent/'product-fix-p1/verified'/uid/'processing-result.npz'
        line_reference = target/'closed-p1-lines-reference.json'
        if verified.is_file():
            before = load_trace_cache(verified)
        elif line_reference.is_file():
            # W02: the initial closed-P1 vs P2B assertion passed before the old
            # float32 cache failed. This snapshot contains ONLY that unchanged
            # line tuple; subsequent representation validation is transitive.
            before = SimpleNamespace(straight_lines=_deserialize_lines(line_reference.read_text(encoding='utf-8')))
        else:
            baseline.recognize_text_candidates_optimized = lambda *a, **kw: (candidates, ())
            before = baseline.trace_image_optimized(source, enable_ocr=True, source_dpi=info['DPI'])
        print(uid, 'final', flush=True)
        if uid == 'W01' and (target/'processing-result.npz').is_file():
            result = load_trace_cache(target/'processing-result.npz')
        else:
            with patch('app.geometry.optimized_trace.recognize_text_candidates_optimized',
                       return_value=(candidates, ())):
                result = trace_image_optimized(source, enable_ocr=True, source_dpi=info['DPI'])
        structure = result.final_structure
        assert result.straight_lines == before.straight_lines, 'P2B changed structural geometry: STOP'
        (target/'structural-comparison.json').write_text(json.dumps(dict(
            lines=len(result.straight_lines), exact_tuple_equal=True,
            reference='closed-P1 verified cache' if verified.is_file() else
                      'initial closed-P1 equality assertion line snapshot' if line_reference.is_file() else
                      'closed-P1 implementation rerun')),encoding='utf-8')
        if uid != 'W01':
            save_trace_cache(target/'processing-result.npz', result)
        assert load_trace_cache(target/'processing-result.npz').final_structure.structure_id == structure.structure_id
        save_image(target/'source.png', source)
        paper_scale = info['PAGE_SIZE_MM'][0]/source.shape[1]
        calibration = ScaleCalibration((0, 0), (1, 0), paper_scale)
        exported = export_final_structure_dxf(structure, target/'drawing.dxf', calibration)
        doc = ezdxf.readfile(exported.path)
        assert not doc.audit().has_errors
        images = list(doc.modelspace().query('IMAGE'))
        asset_records = []
        for entity in images:
            filename = entity.image_def.dxf.filename
            assert not Path(filename).is_absolute() and ':' not in filename
            asset = target/filename
            assert asset.is_file()
            rgba = cv2.imdecode(np.fromfile(asset, np.uint8), cv2.IMREAD_UNCHANGED)
            assert rgba.shape[2] == 4 and np.any(rgba[:, :, 3] == 0)
            asset_records.append(dict(filename=filename, object_class=entity.get_xdata('IMAGE_TO_CAD')[0].value,
                insert=list(entity.dxf.insert), u_pixel=list(entity.dxf.u_pixel), v_pixel=list(entity.dxf.v_pixel),
                transparent_pixels=int(np.count_nonzero(rgba[:, :, 3] == 0))))
        if images:
            edited = images[0]
            edited.translate(2, 3, 0)
            edited.scale_uniform(1.25)
            doc.saveas(target/'move-scale-save-reopen.dxf')
            reopened = ezdxf.readfile(target/'move-scale-save-reopen.dxf')
            assert len(reopened.modelspace().query('IMAGE')) == len(images)
            assert not reopened.audit().has_errors
            for image in reopened.modelspace().query('IMAGE'):
                assert (target/image.image_def.dxf.filename).is_file()
            reopened.modelspace().delete_entity(reopened.modelspace().query('IMAGE')[0])
            reopened.saveas(target/'delete-save-reopen.dxf')
            assert len(ezdxf.readfile(target/'delete-save-reopen.dxf').modelspace().query('IMAGE')) == len(images)-1
        preview = render_final_structure_preview(structure)
        save_image(target/'final-preview.png', preview)
        text_data = [asdict(c) for c in structure.texts]
        (target/'texts.json').write_text(json.dumps(text_data, ensure_ascii=False, indent=2), encoding='utf-8')
        records = dict(structure_id=structure.structure_id, lines=len(structure.straight_lines),
            straight_geometry_exactly_unchanged=True, logos=[list(g.bbox) for g in structure.logos],
            signatures=[list(g.bbox) for g in structure.signatures], images=asset_records,
            enclosures=[dict(r) for r in structure.provenance.get('engineering_enclosures', ())],
            audit_errors=0, move_scale_save_reopen='PASS' if images else 'N/A')
        # Frozen tuples in provenance are JSON serializable after dict conversion.
        summary[uid] = records
        (output/'measurements.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(uid, len(structure.logos), 'logos', len(structure.signatures), 'signatures',
              len(records['enclosures']), 'enclosures', len(images), 'IMAGE', flush=True)
    return summary


if __name__ == '__main__':
    run(Path(sys.argv[1]), Path(sys.argv[2]))
