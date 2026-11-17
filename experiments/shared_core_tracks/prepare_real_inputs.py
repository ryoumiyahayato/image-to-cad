"""Freeze existing page-stage source tiles without running OCR or recovery.

All paths are caller-supplied.  Existing inputs and outputs are read only.
The saved stage is evidence of current ownership, not a new page conversion.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def array_digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def prepare(evidence: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    target = json.loads((evidence / 'continuation_native/real_cohort_v4/summary.json').read_text())
    target_by_bbox = {tuple(row['bbox']): row for row in target['rows'] if row['mode'] == 'physical'}
    pages = [
        ('A2', 'input_gate/inputs/A2-SG-008.tiff'),
        ('HABS', 'inputs_extra/图像转cad/HABS-DC-579-sheet-1.tif'),
        ('ENV', None),
    ]
    manifest = dict(schema='shared-core-real-inputs-v1', source_exposure='PREVIOUSLY_EXPOSED_NOT_BLIND',
                    stage_scope='REUSED_FROZEN_OWNERSHIP_STATE_NOT_A_NEW_FULL_PAGE_CONVERSION',
                    source_rule='All whole working components meeting unchanged r13 resource filters',
                    rows=[], pages=[], observed_original_25=[], input_files={})
    for page_name, native_name in pages:
        stage_path = evidence / f'continuation_integration/accuracy_main_merge/whole_pages/{page_name}-candidate/compound_stage.npz'
        manifest['input_files'][str(stage_path)] = dict(sha256=digest(stage_path), bytes=stage_path.stat().st_size)
        with np.load(stage_path, allow_pickle=False) as archive:
            stage = {key: archive[key].copy() for key in archive.files}
        gray, binary, visible, protected = (stage[key] for key in ('gray', 'binary', 'visible_before', 'protected'))
        dpi = float(stage['dpi'])
        native = None
        scale = None
        if native_name:
            native_path = evidence / native_name
            image = Image.open(native_path)
            native = np.asarray(image.convert('L'))
            native_dpi = tuple(float(x) for x in image.info['dpi'])
            scale_y, rem_y = divmod(native.shape[0], gray.shape[0])
            scale_x, rem_x = divmod(native.shape[1], gray.shape[1])
            assert rem_x == rem_y == 0 and scale_x == scale_y
            scale = scale_x
            assert native_dpi == (dpi * scale, dpi * scale)
            assert np.isin(native, [0, 255]).all()
            manifest['input_files'][str(native_path)] = dict(sha256=digest(native_path), bytes=native_path.stat().st_size)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(gray < 254), connectivity=8)
        page = dict(page=page_name, dpi=dpi, native_scale=scale, shape=list(gray.shape),
                    connected_components=count-1, filter_rejections={}, selected=0,
                    original_scan_available=native is not None, stage_sha256=digest(stage_path))
        filters = Counter()
        pad = max(6, int(np.ceil(4*dpi/100.)) + 1)
        budget = 4_000_000
        page_dir = destination / page_name
        page_dir.mkdir()
        for label in range(1, count):
            x, y, w, h, area = map(int, stats[label])
            if max(w, h) < 10*dpi/25.4*.9 or area < 10*dpi/25.4*.9:
                filters['PARENT_BELOW_EXISTING_RESOURCE_SPAN'] += 1
                continue
            size = (w+2*pad)*(h+2*pad)
            if area > 8192 or size > 100_000 or (scale is not None and size*scale*scale > 1_000_000):
                filters['EXISTING_PARENT_RESOURCE_LIMIT'] += 1
                continue
            if page['selected'] >= 512 or budget < size:
                filters['EXISTING_PAGE_BUDGET'] += 1
                continue
            budget -= size
            if x < pad or y < pad or x+w+pad > gray.shape[1] or y+h+pad > gray.shape[0]:
                filters['PAGE_EDGE_COMPONENT'] += 1
                continue
            sl = np.s_[y-pad:y+h+pad, x-pad:x+w+pad]
            component = labels[sl] == label
            row_arrays = dict(gray=gray[sl].copy(), component=component,
                              binary=binary[sl].copy(), visible_binary=visible[sl].copy(),
                              protected=protected[sl].copy(),
                              foreign=((gray[sl] < 254) & ~component) | (protected[sl] > 0))
            if native is not None:
                row_arrays['native_gray'] = native[(y-pad)*scale:(y+h+pad)*scale,
                                                   (x-pad)*scale:(x+w+pad)*scale].copy()
            name = f'component-{label:06d}'
            npz_path = page_dir / f'{name}.npz'
            np.savez_compressed(npz_path, **row_arrays)
            row = dict(page=page_name, name=name, component_id=label, bbox=[x,y,w,h],
                       origin_work_px=[x-pad,y-pad], source_pixels=area, dpi=dpi,
                       native_scale=scale, input=npz_path.relative_to(destination).as_posix(),
                       input_sha256=digest(npz_path),
                       arrays={key:dict(sha256=array_digest(value), shape=list(value.shape),dtype=str(value.dtype))
                               for key,value in row_arrays.items()},
                       production_guards=dict(protected_source_pixels=int((component & (protected[sl]>0)).sum()),
                           noncurrent_source_pixels=int((component & (binary[sl]>=128)).sum()),
                           previously_claimed_source_pixels=int((component & (visible[sl]>=128)).sum())),
                       original_cohort_index=None)
            if page_name == 'A2' and (x,y,w,h) in target_by_bbox:
                previous = target_by_bbox[(x,y,w,h)]
                index = previous['index']
                original = evidence / f'continuation_native/real_cohort_v4/parent-{index:02d}/source.npz'
                with np.load(original, allow_pickle=False) as z:
                    for key in ('gray','component','foreign','native_gray','protected'):
                        assert np.array_equal(row_arrays[key], z[key]), (index,key)
                row.update(original_cohort_index=index, original_cohort_source_sha256=digest(original))
                manifest['observed_original_25'].append(index)
            manifest['rows'].append(row)
            page['selected'] += 1
        page['filter_rejections'] = dict(filters)
        manifest['pages'].append(page)
    assert sorted(manifest['observed_original_25']) == list(range(1,26))
    for path, item in manifest['input_files'].items():
        assert digest(path) == item['sha256']
    manifest['input_originals_unchanged'] = True
    path = destination / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(dict(pages=manifest['pages'], original_25_verified=True,
                         total_rows=len(manifest['rows']), manifest_sha256=digest(path)), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.evidence_root, args.out)
