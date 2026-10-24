"""Focused production LINE provenance export and readback regressions."""

import json
import runpy
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import ezdxf
import numpy as np
import pytest



from app.export import line_source_ref as ref
from app.core.structure import FinalStructure
from app.export.trace_single_export import export_final_structure_dxf
from app.export.trace_document_export import export_trace_document_streaming
from app.export.document_export import DocumentPage
from app.geometry.source_stroke_reconciliation import ReconciliationLedger

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tiny():
    """Current real safe-alias consumer, physical p9 LOCAL_CONTEXT at 240 dpi."""
    module = runpy.run_path(
        str(ROOT / "cad_photo_to_dxf/tests/test_source_stroke_reconciliation_v1.py")
    )
    captured = []
    original = ReconciliationLedger.reconcile

    def capture(self, **kwargs):
        result = original(self, **kwargs)
        captured.append(result)
        return result

    ReconciliationLedger.reconcile = capture
    try:
        module["test_real_tiny_house_white_edge_alias_keeps_source_window_boundaries"](
            False
        )
    finally:
        ReconciliationLedger.reconcile = original
    lines = tuple(captured[-1].lines)
    assert len(lines) == 9
    assert any(set(line.source_ids) == {"HOUGH-000012", "LSD-001004"} for line in lines)
    return FinalStructure(
        (150, 165), np.full((165, 150), 255, dtype=np.uint8), (), straight_lines=lines
    )


def _single(tiny, path):
    export_final_structure_dxf(tiny, path)
    return ezdxf.readfile(path)


def _validated_entities(doc, structure):
    entities = list(doc.modelspace().query("LINE"))
    assert len(entities) == len(structure.straight_lines)
    ref.validate_line_source_refs(entities, expected=_expected(structure))
    return entities


def _expected(tiny):
    return ref.expected_line_source_records(tiny, lambda x, y: (x, 165 - y))


@pytest.mark.parametrize("exporter", ["single", "document"])
def test_formal_exporter_carries_sources(tiny, tmp_path, exporter):
    """Both formal exporters retain the accepted member source facts."""
    if exporter == "single":
        doc = _single(tiny, tmp_path / "formal-single.dxf")
        expected = _expected(tiny)
    else:
        path = tmp_path / "formal-document.dxf"
        export_trace_document_streaming(
            (DocumentPage(9, None, (150, 165), final_structure=tiny),),
            path,
            total_pages=1,
        )
        doc = ezdxf.readfile(path)
        expected = ref.expected_line_source_records(
            tiny,
            lambda x, y: (x, 165 - y),
            layer_name="PAGE_001_TRACE_STRAIGHT",
            page_slot=1,
            physical_page=9,
        )
    assert (
        ref.validate_line_source_refs(
            doc.modelspace().query("LINE"), expected=expected
        )["status"]
        == "SNAPSHOT_VERIFIED"
    )


def test_real_alias_fresh_process(tiny, tmp_path):
    doc = _single(tiny, tmp_path / "base.dxf")
    _validated_entities(doc, tiny)
    candidate = tmp_path / "QA_TEST_ONLY-attached.dxf"
    doc.saveas(candidate)
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(_expected(tiny)), encoding="utf-8")
    code = (
        "import sys,json,ezdxf;"
        "sys.path.insert(0,sys.argv[1]);"
        "from app.export import line_source_ref as r;"
        "d=ezdxf.readfile(sys.argv[2]); e=list(d.modelspace().query('LINE'));"
        "expected=json.load(open(sys.argv[3],encoding='utf-8'));"
        "a=r.validate_line_source_refs(e); b=r.validate_line_source_refs(e,expected=expected);"
        "print(json.dumps({'standalone':a,'snapshot':b}));"
        "assert a['status']=='SELF_CONSISTENTONLY'; assert b['status']=='SNAPSHOT_VERIFIED'"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(ROOT / "cad_photo_to_dxf"),
            str(candidate),
            str(expected_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())


@pytest.mark.parametrize(
    "fault",
    [
        "swapped_refs",
        "attribute",
        "source_claim",
        "member_index",
        "missing",
        "duplicate",
    ],
)
def test_refuses_same_count_faults(tiny, tmp_path, fault):
    doc = _single(tiny, tmp_path / "base.dxf")
    entities = _validated_entities(doc, tiny)
    if fault == "swapped_refs":
        first, second = (
            entities[0].get_xdata(ref.APPID),
            entities[1].get_xdata(ref.APPID),
        )
        entities[0].set_xdata(ref.APPID, second)
        entities[1].set_xdata(ref.APPID, first)
    elif fault == "attribute":
        entities[0].dxf.color = 6
    elif fault in ("source_claim", "member_index"):
        source = dict(ref.read_line_source_ref(entities[0])["source"])
        if fault == "source_claim":
            source["source_ids"] = ["WRONG-OBSERVATION"]
        else:
            source["member_index"] = 999
        ref.attach_line_source_ref(entities[0], source)
        # A coherent self claim is not source authentication.
        assert (
            ref.validate_line_source_refs(entities)["status"] == "SELF_CONSISTENTONLY"
        )
    elif fault == "missing":
        entities[0].discard_xdata(ref.APPID)
        assert ref.validate_line_source_refs(entities)["status"] == "PARTIAL"
    else:
        source = ref.read_line_source_ref(entities[0])["source"]
        ref.attach_line_source_ref(entities[1], source)
    with pytest.raises(ValueError):
        ref.validate_line_source_refs(entities, expected=_expected(tiny))
    assert len(entities) == len(tiny.straight_lines)


@pytest.mark.parametrize(
    "fault",
    [
        "too_many_ids",
        "long_id",
        "total_budget",
        "bad_header",
        "bad_json",
        "nan",
        "repeated_key",
    ],
)
def test_bounds_and_format(tiny, tmp_path, fault):
    doc = _single(tiny, tmp_path / "base.dxf")
    entity = _validated_entities(doc, tiny)[0]
    source = dict(ref.read_line_source_ref(entity)["source"])
    if fault in ("too_many_ids", "long_id", "total_budget"):
        source["source_ids"] = (
            [str(i) for i in range(129)]
            if fault == "too_many_ids"
            else ["X" * 256]
            if fault == "long_id"
            else [str(i) + "X" * 200 for i in range(100)]
        )
        with pytest.raises(ValueError):
            ref.attach_line_source_ref(entity, source)
        return
    payload = json.dumps(ref.read_line_source_ref(entity), separators=(",", ":"))
    if fault == "bad_header":
        entity.set_xdata(ref.APPID, [(1070, 99), (1000, "{}")])
    else:
        if fault == "bad_json":
            payload = "{"
        elif fault == "nan":
            payload = payload.replace(
                '"source_width":1.909999966621399', '"source_width":NaN'
            )
            if "NaN" not in payload:
                raw = ref.read_line_source_ref(entity)
                raw["source"]["source_width"] = float("nan")
                payload = json.dumps(raw)
        else:
            payload = payload.replace('"version":1', '"version":1,"version":1')
        entity.set_xdata(
            ref.APPID,
            [(1070, 1)]
            + [(1000, payload[i : i + 240]) for i in range(0, len(payload), 240)],
        )
    with pytest.raises(ValueError):
        ref.read_line_source_ref(entity)


def test_old_empty_sources_remain_unavailable(tiny, tmp_path):
    old = replace(
        tiny,
        straight_lines=tuple(
            replace(line, source_ids=()) for line in tiny.straight_lines
        ),
    )
    doc = _single(old, tmp_path / "legacy.dxf")
    assert all(source is None for source in ref.make_line_source_refs(old))
    assert (
        ref.validate_line_source_refs(doc.modelspace().query("LINE"))["status"]
        == "UNAVAILABLE"
    )
    assert (
        ref.validate_line_source_refs(
            doc.modelspace().query("LINE"), expected=_expected(old)
        )["status"]
        == "UNAVAILABLE"
    )


def test_source_change_same_structure_identity_is_rejected(tiny, tmp_path):
    changed = replace(
        tiny,
        straight_lines=(replace(tiny.straight_lines[0], source_ids=("OTHER",)),)
        + tiny.straight_lines[1:],
    )
    assert changed.structure_id == tiny.structure_id
    doc = _single(tiny, tmp_path / "base.dxf")
    entities = _validated_entities(doc, tiny)
    with pytest.raises(ValueError, match="trusted snapshot"):
        ref.validate_line_source_refs(entities, expected=_expected(changed))


def test_filtered_indices_keep_original_member(tiny, tmp_path):
    from app.export.trace_dxf_entities import add_straight_line_entities

    doc = ezdxf.new("R2010")
    chosen = (2, 5)
    _, entities, _ = add_straight_line_entities(
        doc.modelspace(),
        tuple(tiny.straight_lines[i] for i in chosen),
        transform=lambda x, y: (x, 165 - y),
    )
    refs = ref.make_line_source_refs(tiny)
    for i, entity in zip(chosen, entities):
        ref.attach_line_source_ref(entity, refs[i])
    expected = ref.expected_line_source_records(
        tiny, lambda x, y: (x, 165 - y), emitted_indices=chosen
    )
    assert (
        ref.validate_line_source_refs(entities, expected=expected)["status"]
        == "SNAPSHOT_VERIFIED"
    )
    assert [
        ref.read_line_source_ref(e)["source"]["member_index"] for e in entities
    ] == [2, 5]


def test_existing_atomic_save_preserves_prior_complete_file(
    tiny, tmp_path, monkeypatch
):
    path = tmp_path / "prior.dxf"
    _single(tiny, path)
    prior = path.read_bytes()

    def interrupted(self, filename, **kwargs):
        Path(filename).write_text("INTERRUPTED", encoding="ascii")
        raise OSError("injected save interruption")

    monkeypatch.setattr(ezdxf.document.Drawing, "saveas", interrupted)
    with pytest.raises(OSError, match="injected"):
        export_final_structure_dxf(tiny, path)
    assert path.read_bytes() == prior
    assert not list(tmp_path.glob(".prior.dxf.*.tmp.dxf"))


@pytest.mark.parametrize(
    "fault", ["none", "known_wrong", "known_missing", "unknown_geometry"]
)
def test_partial_legacy_still_checks_every_known_member(tiny, tmp_path, fault):
    mixed = replace(
        tiny,
        straight_lines=(replace(tiny.straight_lines[0], source_ids=()),)
        + tiny.straight_lines[1:],
    )
    doc = _single(mixed, tmp_path / "mixed.dxf")
    entities = _validated_entities(doc, mixed)
    if fault == "known_wrong":
        source = dict(ref.read_line_source_ref(entities[1])["source"])
        source["source_ids"] = ["WRONG"]
        ref.attach_line_source_ref(entities[1], source)
    elif fault == "known_missing":
        entities[1].discard_xdata(ref.APPID)
    elif fault == "unknown_geometry":
        entities[0].dxf.start = (999, 999, 0)
    if fault == "none":
        assert (
            ref.validate_line_source_refs(entities, expected=_expected(mixed))["status"]
            == "UNAVAILABLE"
        )
    else:
        with pytest.raises(ValueError):
            ref.validate_line_source_refs(entities, expected=_expected(mixed))


def test_swap_rejected_after_fresh_reopen(tiny, tmp_path):
    doc = _single(tiny, tmp_path / "base.dxf")
    entities = _validated_entities(doc, tiny)
    first, second = entities[0].get_xdata(ref.APPID), entities[1].get_xdata(ref.APPID)
    entities[0].set_xdata(ref.APPID, second)
    entities[1].set_xdata(ref.APPID, first)
    tampered = tmp_path / "QA_TEST_ONLY-wrong-line.dxf"
    doc.saveas(tampered)
    code = (
        "import sys,ezdxf;sys.path.insert(0,sys.argv[1]);"
        "from app.export import line_source_ref as r;"
        "d=ezdxf.readfile(sys.argv[2]);"
        "r.validate_line_source_refs(d.modelspace().query('LINE'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "cad_photo_to_dxf"), str(tampered)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "different geometry or attributes" in result.stderr
    print(
        "fresh process rejected swapped reference: "
        + result.stderr.strip().splitlines()[-1]
    )
