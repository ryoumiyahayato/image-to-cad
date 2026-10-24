"""Preserve supported PDF paint paths without OCR or a model/API key.

Derived from the S0 ARM-B experiment, with page-specific values removed.
This is an opt-in CLI, not a replacement for ProductionProcessingService.
Unsupported visible content prevents export; it is never silently discarded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

import ezdxf
import pymupdf as fitz

PT_MM = 25.4 / 72.0
WEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70,
           80, 90, 100, 106, 120, 140, 158, 200, 211)


def chains(path: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Keep source order/subpaths. No snapping, extension or deduplication."""
    result: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def flush() -> None:
        if current:
            result.append(current.copy())
            current.clear()

    for item in path['items']:
        kind = item[0]
        if kind == 'l':
            start, end = tuple(item[1]), tuple(item[2])
            if current and current[-1] == start:
                current.append(end)
            else:
                flush()
                current.extend((start, end))
        elif kind == 're':
            flush()
            r = item[1]
            points = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
            if item[2] < 0:
                points.reverse()
            result.append(points + points[:1])
        elif kind == 'qu':
            flush()
            q = item[1]
            points = [tuple(q.ul), tuple(q.ur), tuple(q.lr), tuple(q.ll)]
            result.append(points + points[:1])
        else:
            raise ValueError(f'Unsupported path command: {kind}')
    flush()
    if path.get('closePath') and result and result[-1][0] != result[-1][-1]:
        result[-1].append(result[-1][0])
    return result


def inspect_page(source: Path, page_number: int = 1) -> dict[str, Any]:
    source = Path(source)
    with fitz.open(source) as pdf:
        if pdf.needs_pass:
            raise ValueError('Encrypted PDF requires an explicitly decrypted input')
        if not 1 <= page_number <= len(pdf):
            raise ValueError('Page number is 1-based and must exist')
        page = pdf[page_number - 1]
        issues: list[str] = []
        if page.rotation or page.cropbox != page.mediabox or page.rect.x0 or page.rect.y0:
            issues.append('Rotated or cropped page is outside this initial importer')
        if pdf.get_ocgs():
            issues.append('Optional-content layers require explicit visibility handling')
        if list(page.annots() or []) or list(page.widgets() or []):
            issues.append('Annotation/widget appearance is not supported')
        paints = Counter(item[0] for item in page.get_bboxlog())
        unsupported = sorted(set(paints) - {'fill-path', 'stroke-path', 'ignore-text'})
        if unsupported:
            issues.append('Unsupported visible paint types: ' + ', '.join(unsupported))
        drawings = page.get_drawings(extended=True)
        if not drawings:
            issues.append('No supported native drawing paths')
        for index, path in enumerate(drawings):
            if path['type'] not in {'s', 'f', 'fs'}:
                issues.append(f'Path {index}: clip/group visibility is unsupported')
                continue
            if any(item[0] not in {'l', 're', 'qu'} for item in path['items']):
                issues.append(f'Path {index}: curved/unknown path command')
                continue
            for mode in ('stroke', 'fill'):
                opacity = path.get(mode + '_opacity')
                if opacity is not None and not math.isclose(float(opacity), 1.0):
                    issues.append(f'Path {index}: transparency is unsupported')
            if 's' in path['type'] and str(path.get('dashes', '[] 0')).replace(' ', '') != '[]0':
                issues.append(f'Path {index}: dashed stroke is unsupported')
            if 'f' in path['type'] and not path.get('even_odd') and len(chains(path)) > 1:
                issues.append(f'Path {index}: multi-loop nonzero-winding fill is unsupported')
            if not (page.rect + (-0.001, -0.001, 0.001, 0.001)).contains(path['rect']):
                issues.append(f'Path {index}: page-edge clipping requires verification')
        return {
            'schema': 1, 'mode': 'NATIVE_FIRST_PREVIEW', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'page_number': page_number, 'page_points': list(page.rect),
            'paint_counts': dict(paints), 'drawing_paths': len(drawings),
            'supported': not issues, 'unsupported': sorted(set(issues)),
            'geometry_origin': 'PDF_NATIVE_PATHS', 'ocr_calls': 0, 'model_calls': 0,
            'semantic_text_recovered': 0, 'gui_roundtrip': 'NOT_RUN',
            'warnings': ['Font-outline shapes are geometry, not semantic TEXT.',
                         'Standard CAD lineweight is discrete; caps/joins and printing need GUI verification.',
                         'Source duplicates are preserved, not automatically deleted.'],
        }


def export_page(source: Path, output: Path, page_number: int = 1,
                canvas: tuple[int, int] | None = None,
                units_per_pixel: float | None = None) -> dict[str, Any]:
    """Export a supported full page. Refuse overwrite and partial-page success."""
    source, output = Path(source), Path(output)
    report_path = output.with_suffix('.manifest.json')
    if output.exists() or report_path.exists():
        raise FileExistsError('Use a new output path; existing results are preserved')
    if (canvas is None) != (units_per_pixel is None):
        raise ValueError('Canvas and units_per_pixel must be supplied together')
    if canvas is not None and (len(canvas) != 2 or any(v <= 0 for v in canvas)):
        raise ValueError('Canvas dimensions must be positive')
    if units_per_pixel is not None and (not math.isfinite(units_per_pixel) or units_per_pixel <= 0):
        raise ValueError('units_per_pixel must be positive and finite')
    report = inspect_page(source, page_number)
    if not report['supported']:
        raise ValueError('Unsupported page; run --inspect for details: ' + '; '.join(report['unsupported'][:8]))
    with fitz.open(source) as pdf:
        page = pdf[page_number - 1]
        width, height = page.rect.width, page.rect.height
        kx = ky = PT_MM
        if canvas is not None:
            kx = canvas[0] / width * units_per_pixel
            ky = canvas[1] / height * units_per_pixel
        def world(point: tuple[float, float]) -> tuple[float, float]:
            return point[0] * kx, (height - point[1]) * ky
        doc = ezdxf.new('R2013')
        doc.units = ezdxf.units.MM
        doc.header['$LWDISPLAY'] = True
        doc.layers.new('SOURCE_NATIVE', dxfattribs={'color': 7})
        doc.appids.new('NATIVE_FIRST_SOURCE')
        doc.appids.new('P3A_STROKE')
        msp = doc.modelspace()
        registry = []
        for index, path in enumerate(page.get_drawings()):
            subpaths = chains(path)
            handles: list[str] = []
            def record(entity: Any) -> Any:
                entity.set_xdata('NATIVE_FIRST_SOURCE', [(1000, report['source_sha256']),
                                  (1071, page_number), (1071, index), (1071, path['seqno'])])
                handles.append(entity.dxf.handle)
                return entity
            def attributes(rgb: Any) -> dict[str, Any]:
                color = tuple(max(0, min(255, round(float(c) * 255))) for c in (rgb or (0, 0, 0)))
                return {'layer': 'SOURCE_NATIVE', 'color': 7, 'true_color': ezdxf.colors.rgb2int(color)}
            if 'f' in path['type']:
                loops = [points for points in subpaths if len(points) >= 3]
                if loops:
                    hatch = record(msp.add_hatch(dxfattribs=attributes(path.get('fill'))))
                    for points in loops:
                        hatch.paths.add_polyline_path([world(p) for p in points], is_closed=True, flags=0)
            if 's' in path['type']:
                source_width = float(path['width'])
                width_px = source_width * ((canvas[0] / width + canvas[1] / height) / 2.0 if canvas else 240.0 / 72.0)
                width_mm = source_width * (kx + ky) / 2.0
                lineweight = min(WEIGHTS, key=lambda v: abs(v / 100.0 - width_mm))
                for points in subpaths:
                    if len(points) < 2 or len(set(points)) < 2:
                        continue
                    closed = len(points) > 2 and points[0] == points[-1]
                    vertices = [world(p) for p in (points[:-1] if closed else points)]
                    attrs = dict(attributes(path.get('color')), lineweight=lineweight)
                    if len(vertices) == 2 and not closed:
                        entity = record(msp.add_line(vertices[0], vertices[1], dxfattribs=attrs))
                    else:
                        entity = record(msp.add_lwpolyline(vertices, close=closed, dxfattribs=attrs))
                    # Existing preview convention; standard CAD still uses approximate lineweight.
                    if width_mm > 0 and lineweight > 0:
                        entity.set_xdata('P3A_STROKE', [(1000, 'NATIVE_FIRST_PDF_WIDTH'),
                            (1040, width_px), (1040, width_px * 25.4 / (lineweight / 100.0))])
            if handles:
                group = doc.groups.new(name=f'PDF_PATH_{index:06d}', description='Source paint operation; not an engineering object')
                group.extend(doc.entitydb[handle] for handle in handles)
            registry.append({'path': index, 'seqno': path['seqno'], 'handles': handles,
                             'width_pt': path.get('width'), 'line_cap': path.get('lineCap'),
                             'line_join': path.get('lineJoin'), 'fill_even_odd': path.get('even_odd')})
        doc.set_modelspace_vport(height=height * ky, center=(width * kx / 2, height * ky / 2))
        report.update({'entities': dict(Counter(e.dxftype() for e in msp)), 'groups': len(doc.groups),
                       'coordinate_scale_mm_per_pt_xy': [kx, ky], 'paths': registry,
                       'unrepresented_path_indices': [r['path'] for r in registry if not r['handles']]})
        if report['unrepresented_path_indices']:
            raise ValueError('Some source operations have no representation; no DXF written')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent) as temp:
            temp_dxf = Path(temp) / output.name
            doc.saveas(temp_dxf)
            restored = ezdxf.readfile(temp_dxf)
            audit = restored.audit()
            if audit.errors or audit.fixes or len(restored.modelspace()) != len(msp):
                raise RuntimeError('Saved-DXF validation failed; no output promoted')
            report['dxf_sha256'] = hashlib.sha256(temp_dxf.read_bytes()).hexdigest()
            report['saved_readback'] = 'PASS'
            # Exclusive creation also protects against another process writing this path.
            with output.open('xb') as dest:
                dest.write(temp_dxf.read_bytes())
            with report_path.open('x', encoding='utf-8') as dest:
                json.dump(report, dest, ensure_ascii=False, indent=2)
                dest.write('\n')
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--page', type=int, default=1, help='1-based page number')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--canvas', nargs=2, type=int)
    parser.add_argument('--units-per-pixel', type=float)
    args = parser.parse_args()
    if args.inspect:
        result = inspect_page(args.source, args.page)
    elif args.output:
        result = export_page(args.source, args.output, args.page,
                             tuple(args.canvas) if args.canvas else None, args.units_per_pixel)
        result = {key: value for key, value in result.items() if key != 'paths'}
    else:
        parser.error('Specify --inspect or --output')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
