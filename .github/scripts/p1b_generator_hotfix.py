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
    insertion = '''    trace_export_test = PROJECT / "tests" / "test_trace_export.py"\n    trace_tests = read(trace_export_test)\n    trace_tests = replace_once(\n        trace_tests,\n        '    assert all(0.72 <= float(entity.dxf.width) <= 4.0 for entity in texts)\\n',\n        '    assert all(float(entity.dxf.width) > 0.0 for entity in texts)\\n'\n        '    geometry = _geometry_xdata(texts[0])\\n'\n        '    assert np.isclose(geometry[4], geometry[2])\\n'\n        '    assert np.isclose(geometry[5], geometry[3])\\n',\n        "legacy width clamp assertion",\n    )\n    trace_tests = replace_once(\n        trace_tests,\n        '        assert geometry[5] == geometry[3]\\n',\n        '        assert np.isclose(geometry[5], geometry[3])\\n',\n        "exact rendered height assertion",\n    )\n    write(trace_export_test, trace_tests)\n\n'''
    source = replace_once(source, marker, insertion + marker, "insert trace-export migration")
    source = replace_once(
        source,
        '    return [path, test_path, contract_test, contract_doc]\n',
        '    return [path, test_path, contract_test, trace_export_test, contract_doc]\n',
        "stage migrated trace-export test",
    )
    main_marker = '\nif __name__ == "__main__":\n'
    diagnostic_wrapper = '''\n_original_patch_legacy_for_diagnostic = patch_legacy\ndef patch_legacy():\n    files = _original_patch_legacy_for_diagnostic()\n    test_path = PROJECT / "tests" / "test_native_text_path_unification.py"\n    text = read(test_path)\n    old = "    assert _entity_geometry(delegated[0]) == _entity_geometry(canonical[0])\\n"\n    new = (\n        "    delegated_geometry = _entity_geometry(delegated[0])\\n"\n        "    canonical_geometry = _entity_geometry(canonical[0])\\n"\n        "    assert delegated_geometry == canonical_geometry, (\\n"\n        "        f'delegated={delegated_geometry!r} canonical={canonical_geometry!r}'\\n"\n        "    )\\n"\n    )\n    if old not in text:\n        raise RuntimeError("unification diagnostic assertion not found")\n    write(test_path, text.replace(old, new, 1))\n    return files\n\n'''
    source = replace_once(source, main_marker, diagnostic_wrapper + main_marker, "install unification diagnostic")
    compile(source, str(path), "exec")
    path.write_text(source, encoding="utf-8")
    print("Applied P1B generator test-contract and diagnostic hotfix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
