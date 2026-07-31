from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    marker = '    contract_doc = FIT_ROOT / "geometry-contract.md"\n'
    insertion = '''    trace_export_test = PROJECT / "tests" / "test_trace_export.py"\n    trace_tests = read(trace_export_test)\n    trace_tests = replace_once(\n        trace_tests,\n        '    assert all(0.72 <= float(entity.dxf.width) <= 4.0 for entity in texts)\\n',\n        '    assert all(float(entity.dxf.width) > 0.0 for entity in texts)\\n'\n        '    geometry = _geometry_xdata(texts[0])\\n'\n        '    assert np.isclose(geometry[4], geometry[2])\\n'\n        '    assert np.isclose(geometry[5], geometry[3])\\n',\n        "legacy width clamp assertion",\n    )\n    trace_tests = replace_once(\n        trace_tests,\n        '            assert geometry[5] == geometry[3]\\n',\n        '            assert np.isclose(geometry[5], geometry[3])\\n',\n        "exact rendered height assertion",\n    )\n    write(trace_export_test, trace_tests)\n\n'''
    source = replace_once(source, marker, insertion + marker, "insert trace-export migration")
    source = replace_once(
        source,
        '    return [path, test_path, contract_test, contract_doc]\n',
        '    return [path, test_path, contract_test, trace_export_test, contract_doc]\n',
        "stage migrated trace-export test",
    )
    compile(source, str(path), "exec")
    path.write_text(source, encoding="utf-8")
    print("Applied P1B generator test-contract hotfix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
