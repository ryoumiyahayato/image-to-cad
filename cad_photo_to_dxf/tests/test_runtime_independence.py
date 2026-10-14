"""Run the public CPU processing/export path with external dependencies blocked."""
import subprocess
import sys
from pathlib import Path


def test_processing_export_runs_without_git_network_gpu_or_artifact_tree(tmp_path):
    code = r'''
import sys
def guard(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo'):
        raise AssertionError('network is not a processing dependency')
    if event == 'subprocess.Popen' and 'git' in str(args[0]).lower():
        raise AssertionError('Git is not a processing dependency')
    if event == 'open' and 'local-artifacts' in str(args[0]).lower():
        raise AssertionError('local artifact tree is not a processing dependency')
    if event == 'open' and 'historical-verification' in str(args[0]).lower():
        raise AssertionError('historical verification is not a runtime dependency')
    if event == 'open' and any(part in str(args[0]).lower().replace('\\', '/').split('/') for part in ('.git', 'sha-manifest.json', 'hash-manifest.json')):
        raise AssertionError('Git metadata/SHA manifests are not runtime dependencies')
sys.addaudithook(guard)
import cv2
import numpy as np
from app.core.processing import ProductionProcessingConfig, ProductionProcessingService
from app.export.trace_single_export import export_final_structure_dxf
from app.ocr.ocr_recognition import _get_rapidocr_engine
image = np.full((180, 300, 3), 255, np.uint8)
cv2.rectangle(image, (10, 10), (290, 170), (0, 0, 0), 2)
cv2.putText(image, 'A1', (70, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
result = ProductionProcessingService.process_page(image, ProductionProcessingConfig(enable_ocr=True))
assert result.final_structure is not None
assert not any('failed' in warning.lower() or '失败' in warning for warning in result.warnings), result.warnings
engine = _get_rapidocr_engine()
sessions = []
visited = set()
def inspect(value, depth=0):
    if id(value) in visited or depth > 5:
        return
    visited.add(id(value))
    if hasattr(value, 'get_providers'):
        sessions.append(value.get_providers())
        return
    for child in getattr(value, '__dict__', {}).values():
        if hasattr(child, '__dict__'):
            inspect(child, depth + 1)
inspect(engine)
assert sessions, 'must actually verify the installed OCR sessions'
assert all('CPUExecutionProvider' in providers and not any('CUDA' in p or 'Tensorrt' in p for p in providers) for providers in sessions), sessions
exported = export_final_structure_dxf(result.final_structure, 'offline.dxf')
assert exported.path.is_file()
print('OFFLINE CPU PROCESSING + EXPORT OK', sessions)
'''
    project = Path(__file__).resolve().parents[1]
    import os
    env = os.environ.copy()
    env['PYTHONPATH'] = str(project)
    completed = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                               env=env, capture_output=True, text=True, encoding='utf-8')
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert 'OFFLINE CPU PROCESSING + EXPORT OK' in completed.stdout
