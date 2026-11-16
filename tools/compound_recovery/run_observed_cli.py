"""Run the unchanged CLI while recording the open-stroke boundary for research.

The observation wrapper returns the original result unchanged. It supplies no
coordinates, text answers, protection overrides, blank-paper regions, or cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    args, cli_args = parser.parse_known_args()
    if cli_args[:1] == ['--']:
        cli_args = cli_args[1:]
    root = args.repo.resolve()
    from offline_runtime import enforce_offline_runtime
    offline = enforce_offline_runtime()
    app_root = root / 'cad_photo_to_dxf'
    sys.path.insert(0, str(app_root))
    cv2.setNumThreads(2)
    args.capture.mkdir(parents=True, exist_ok=True)
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(app_root.rglob('*.py')) if '__pycache__' not in p.parts}
    launch = {'cli_args': cli_args, 'repo': str(root), 'python': sys.executable,
              'source_sha256': sources, 'observer_only': True, 'offline_policy': offline,
              'versions': {'numpy': np.__version__, 'opencv': cv2.__version__}}
    (args.capture / 'launch.json').write_text(json.dumps(launch, indent=2), encoding='utf-8')
    from app.geometry import observed_open_strokes as module
    original = module.recover_observed_open_strokes

    def observed(gray, binary, visible_binary, **kwargs):
        result = original(gray, binary, visible_binary, **kwargs)
        protected = np.zeros(gray.shape, dtype=np.uint8)
        for mask in kwargs.get('protected_masks', ()):
            if mask is not None:
                protected |= np.uint8(mask > 0)
        np.savez_compressed(args.capture / 'stage.npz', gray=gray, binary=binary,
                            visible_before=visible_binary, visible_after=result[0],
                            protected=protected, dpi=np.asarray(kwargs['dpi']))
        (args.capture / 'open_stroke_review.json').write_text(
            json.dumps(result[3], indent=2), encoding='utf-8')
        return result

    module.recover_observed_open_strokes = observed
    compound_stage = app_root / 'app' / 'geometry' / 'observed_compound_strokes.py'
    if compound_stage.exists():
        from app.geometry import observed_compound_strokes as compound_module
        original_compound = compound_module.recover_observed_compound_strokes

        def observed_compound(gray, binary, visible_binary, **kwargs):
            result = original_compound(gray, binary, visible_binary, **kwargs)
            protected = np.zeros(gray.shape, dtype=np.uint8)
            for mask in kwargs.get('protected_masks', ()):
                if mask is not None:
                    protected |= np.uint8(mask > 0)
            np.savez_compressed(args.capture / 'compound_stage.npz', gray=gray, binary=binary,
                visible_before=visible_binary, visible_after=result[0], protected=protected,
                dpi=np.asarray(kwargs['dpi']))
            for filename, value in (('compound_review.json', result[3]),
                                    ('compound_records.json', result[2])):
                (args.capture / filename).write_text(json.dumps(value, indent=2), encoding='utf-8')
            return result

        compound_module.recover_observed_compound_strokes = observed_compound
    start = time.monotonic()
    sys.argv = [str(app_root / 'main.py'), *cli_args]
    status = 0
    try:
        runpy.run_path(str(app_root / 'main.py'), run_name='__main__')
    except SystemExit as exc:
        status = int(exc.code or 0)
        raise
    except BaseException:
        status = 1
        raise
    finally:
        final_sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(app_root.rglob('*.py')) if '__pycache__' not in p.parts}
        (args.capture / 'execution.json').write_text(json.dumps({
            'exit_code': status, 'elapsed_s': time.monotonic() - start,
            'production_sources_unchanged': sources == final_sources,
            'observed_stage_exists': (args.capture / 'stage.npz').exists(),
            'compound_stage_exists': (args.capture / 'compound_stage.npz').exists(),
            'CAD_GUI': 'NOT_RUN'}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
