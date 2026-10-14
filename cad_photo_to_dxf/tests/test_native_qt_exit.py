"""Native return ownership and normal interpreter teardown, not drawing evidence."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("singleton", ["None", "True"])
def test_qt_singleton_return_owns_reference_and_process_exits_normally(singleton):
    code = r'''
import gc
import sys
import PySide6
from PySide6.QtGui import QPainterPath
path = QPainterPath()
if sys.argv[1] == "None":
    value = None
    operation = lambda: path.moveTo(1.0, 2.0)
else:
    value = True
    operation = path.isEmpty
for _ in range(32):
    operation()
gc.collect()
before = sys.getrefcount(value)
for _ in range(256):
    operation()
after = sys.getrefcount(value)
print(PySide6.__version__, sys.argv[1], before, after, flush=True)
assert after == before, "Qt singleton return reference ownership is unbalanced"
del operation, path
gc.collect()
'''
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code, singleton],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
