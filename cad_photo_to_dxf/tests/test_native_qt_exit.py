"""Native singleton returns and normal interpreter teardown, not drawing evidence."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("singleton", ["None", "True"])
def test_qt_singleton_return_identity_and_process_exits_normally(singleton):
    code = r'''
import gc
import sys
import weakref
import PySide6
from PySide6.QtGui import QPainterPath
path = QPainterPath()
path_ref = weakref.ref(path)
if sys.argv[1] == "None":
    value = None
    operation = lambda: path.moveTo(1.0, 2.0)
else:
    value = True
    operation = path.isEmpty
for _ in range(32):
    assert operation() is value, "Qt returned the wrong singleton"
gc.collect()
before = sys.getrefcount(value)
for _ in range(256):
    assert operation() is value, "Qt returned the wrong singleton"
after = sys.getrefcount(value)
# CPython 3.12 made both tested singletons immortal. Their exposed counters
# are not exact ownership counts; older abi3 extensions can still alter them.
# https://docs.python.org/3.12/library/sys.html#sys.getrefcount
counted_singleton = not (
    sys.implementation.name == "cpython" and sys.version_info >= (3, 12)
)
print(PySide6.__version__, sys.argv[1], before, after,
      "counted_singleton", counted_singleton, flush=True)
if counted_singleton:
    assert after == before, "Qt singleton return reference ownership is unbalanced"
del operation, path
gc.collect()
assert path_ref() is None, "Qt path wrapper survived destruction"
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
