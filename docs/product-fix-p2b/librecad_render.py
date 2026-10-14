"""Native installed LibreCAD render, with identical no-IMAGE controls.

The diagnostic crops translate whole committed objects to a small drawing.
Fixed page borders keep IMAGE and no-IMAGE viewports identical. No fonts change.
"""
from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys

import cv2
import ezdxf
import numpy as np

from app.core.image_loader import save_image, load_image
from app.core.scale_calibrator import ScaleCalibration
from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.line_detect import LineSegment
from app.ocr.engineering_symbols import resolve_enclosure_relations
from app.ocr.signature_overlay import source_ink_region
from tests.test_product_p2b_representation import logos, signatures, source, candidates, OBSERVATIONS

LC = Path('C:/Users/agcrf/Desktop/LibreCAD/LibreCAD.exe')
NATIVE_ENV = dict(os.environ)
# The project's Qt6 offscreen setting is for tests; LibreCAD uses its own Qt5.
NATIVE_ENV.pop('QT_QPA_PLATFORM', None)


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    objects = {uid: (logos(uid)[0], False) for uid in ('E01','W02','W03')}
    objects['W03-signature'] = (signatures()[0], True)
    for uid, (region, signature) in objects.items():
        info = OBSERVATIONS['W03' if signature else uid]['input']
        gray = load_image(Path('tests/real_regression/assets/sources')/info['SOURCE_FILE'],
                         page_index=info['SOURCE_PAGE']-1,pdf_dpi=info['DPI'],grayscale=True)
        region = source_ink_region(region,gray)
        x,y,w,h = region.bbox
        shifted = replace(region, bbox=(10,10,w,h))
        width, height = w+20,h+20
        blank = np.full((height,width), 255, np.uint8)
        frame = tuple(LineSegment(*p) for p in [(0,0,width,0),(0,0,0,height),
                                               (0,height,width,height),(width,0,width,height)])
        structure = build_final_structure(source_size_px=(width,height), contour_binary=blank,
            contours=(), straight_lines=frame, logos=() if signature else (shifted,),
            signatures=(shifted,) if signature else ())
        path = output/f'{uid}.dxf'
        export_final_structure_dxf(structure, path, ScaleCalibration((0,0),(1,0),.2))
        doc = ezdxf.readfile(path)
        for entity in doc.modelspace().query('LINE'):
            entity.dxf.true_color=0
            entity.dxf.lineweight=13
        doc.saveas(path)
        for entity in list(doc.modelspace().query('IMAGE')):
            doc.modelspace().delete_entity(entity)
        control = output/f'{uid}-without-image.dxf'
        doc.saveas(control)
        raster = []
        failures = []
        for drawing in (path,control):
            pdf = drawing.with_suffix('.pdf')
            command = [str(LC), 'dxf2pdf', '-p','130x150','-s','1','-c','-m','-o',str(pdf.resolve()),str(drawing.resolve())]
            try:
                result = subprocess.run(command, cwd=output, capture_output=True, timeout=45, env=NATIVE_ENV)
            except subprocess.TimeoutExpired as error:
                drawing.with_suffix('.render.log').write_bytes((error.stdout or b'')+(error.stderr or b'')+b'\nTIMEOUT 45s')
                failures.append('Native IMAGE render timed out after 45s')
                raster.append(None)
                continue
            drawing.with_suffix('.render.log').write_bytes(result.stdout+result.stderr)
            if result.returncode != 0:
                failures.append(f'Native render exit={result.returncode}; PDF exists={pdf.is_file()}')
            if not pdf.is_file():
                raster.append(None)
                continue
            result = subprocess.run(['pdftoppm','-r','180','-singlefile','-png', str(pdf.resolve()),str(drawing.resolve().with_suffix(''))], capture_output=True, timeout=60)
            if result.returncode != 0:
                failures.append('Poppler could not reopen the native PDF')
                raster.append(None)
                continue
            raster.append(cv2.imdecode(np.fromfile(drawing.with_suffix('.png'),np.uint8),cv2.IMREAD_GRAYSCALE))
        assert raster[1] is not None, 'No-IMAGE native control must render successfully'
        delta = None
        if raster[0] is not None:
            assert raster[0].shape == raster[1].shape
            delta = int(np.count_nonzero(np.abs(raster[0].astype(int)-raster[1]) > 32))
            ys,xs = np.where(raster[0] < 200)
            save_image(output/f'{uid}-crop.png', raster[0][ys.min():ys.max()+1,xs.min():xs.max()+1])
        report[uid] = dict(native_render='PASS' if delta is not None and delta > 20 else 'UNSUPPORTED',
                           image_control_pixel_difference=delta, command=command,
                           failures=failures, without_image_control='PASS',
                           diagnostic_native_lines_black=True, foreground_rgb=[0,0,0])
        print(uid, report[uid]['native_render'], delta, flush=True)

    texts, paths, records, _, _ = resolve_enclosure_relations(source('W02'), candidates('W02')[:5])
    x,y,width,height = 1635,700,145,125
    paths = tuple(replace(p, points=tuple((a-x,b-y) for a,b in p.points)) for p in paths)
    texts = tuple(replace(t,bbox=(t.bbox[0]-x,t.bbox[1]-y,*t.bbox[2:]),quad=None,character_boxes=()) for t in texts)
    structure = build_final_structure(source_size_px=(width,height),contour_binary=np.full((height,width),255,np.uint8),
        contours=paths,texts=texts, provenance={'engineering_enclosures':tuple(dict(r,contour_index=i) for i,r in enumerate(records))})
    path = output/'W02-engineering.dxf'
    export_final_structure_dxf(structure,path,ScaleCalibration((0,0),(1,0),.5))
    doc = ezdxf.readfile(path)
    for entity in doc.modelspace():
        entity.dxf.true_color=0
        entity.dxf.lineweight=13
    doc.saveas(path)
    pdf = path.with_suffix('.pdf')
    result = subprocess.run([str(LC),'dxf2pdf','-p','130x150','-s','1','-c','-m','-o',str(pdf.resolve()),str(path.resolve())],cwd=output,capture_output=True,timeout=60,env=NATIVE_ENV)
    path.with_suffix('.render.log').write_bytes(result.stdout+result.stderr)
    assert result.returncode == 0 and pdf.is_file()
    subprocess.run(['pdftoppm','-r','180','-singlefile','-png',str(pdf.resolve()),str(path.resolve().with_suffix(''))],check=True,capture_output=True,timeout=60)
    raster = cv2.imdecode(np.fromfile(path.with_suffix('.png'),np.uint8),cv2.IMREAD_GRAYSCALE)
    ys,xs = np.where(raster < 200)
    save_image(output/'W02-engineering-crop.png',raster[ys.min():ys.max()+1,xs.min():xs.max()+1])
    report['W02-engineering'] = dict(native_render='PASS',
                                    text_contents=[t.dxf.text for t in doc.modelspace().query('TEXT')])
    (output/'librecad-image-render.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__ == '__main__':
    render(Path(sys.argv[1]).resolve())
