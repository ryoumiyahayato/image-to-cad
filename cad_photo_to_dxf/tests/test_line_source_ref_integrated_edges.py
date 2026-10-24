"""Focused integrated edge checks; source variants are DESIGN_PROBE."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ezdxf
import pytest



from tests import test_line_source_ref as source_ref_tests
from app.export.line_source_ref import (
    make_line_source_refs,
    read_line_source_ref,
    expected_line_source_records,
    validate_line_source_refs,
)
from app.export.trace_entity_writer import write_page_entities
from app.export.trace_single_export import export_final_structure_dxf
from app.export.trace_dxf_entities import add_straight_line_entities

ROOT = Path(__file__).resolve().parents[2]
tiny = source_ref_tests.tiny


def emitted(doc):
    return list(doc.modelspace().query("LINE"))


def expected(structure):
    return expected_line_source_records(structure, lambda x, y: (x, 165 - y))


def produce(structure, path):
    export_final_structure_dxf(structure, path)
    return ezdxf.readfile(path)


def test_shared_writer_filter_and_degenerate_retain_original_indices(tiny, tmp_path):
    original = tiny.straight_lines
    dead = replace(
        original[0],
        x2=original[0].x1,
        y2=original[0].y1,
        source_ids=("DESIGN-PROBE-DEGENERATE",),
    )
    structure = replace(
        tiny, straight_lines=(original[0], dead, original[2], original[3])
    )
    refs = make_line_source_refs(structure)
    doc = ezdxf.new("R2010")
    selected = (1, 2, 3)
    resolved = SimpleNamespace(
        members=(),
        emitted_indices=lambda name: selected if name == "straight_lines" else (),
    )
    write_page_entities(
        doc,
        doc.modelspace(),
        trace_paths=(),
        straight_lines=structure.straight_lines,
        texts=(),
        signatures=(),
        transform=lambda x, y: (x, 165 - y),
        output_path=tmp_path / "filtered.dxf",
        source_size=structure.source_size_px,
        resolved_output=resolved,
        line_source_refs=refs,
    )
    entities = emitted(doc)
    assert [read_line_source_ref(e)["source"]["member_index"] for e in entities] == [
        2,
        3,
    ]
    wanted = expected_line_source_records(
        structure, lambda x, y: (x, 165 - y), emitted_indices=selected
    )
    assert (
        validate_line_source_refs(entities, expected=wanted)["status"]
        == "SNAPSHOT_VERIFIED"
    )


def test_transform_degenerate_creates_no_shifted_reference(tiny):
    doc = ezdxf.new("R2010")
    count, entities, _ = add_straight_line_entities(
        doc.modelspace(),
        tiny.straight_lines,
        transform=lambda x, y: (0, 0),
        line_source_refs=make_line_source_refs(tiny),
    )
    assert count == 0 and entities == []
    assert expected_line_source_records(tiny, lambda x, y: (0, 0)) == ()


def test_endpoint_reverse_and_tuple_reorder_recompute_expected_binding(tiny, tmp_path):
    backwards = tuple(
        replace(line, x1=line.x2, y1=line.y2, x2=line.x1, y2=line.y1)
        for line in reversed(tiny.straight_lines)
    )
    changed = replace(tiny, straight_lines=backwards)
    doc = produce(changed, tmp_path / "reversed.dxf")
    assert (
        validate_line_source_refs(emitted(doc), expected=expected(changed))["status"]
        == "SNAPSHOT_VERIFIED"
    )
    assert [read_line_source_ref(e)["source"]["source_ids"] for e in emitted(doc)] == [
        list(line.source_ids) for line in backwards
    ]
    with pytest.raises(ValueError):
        validate_line_source_refs(emitted(doc), expected=expected(tiny))


def test_repeated_formal_export_has_same_member_records(tiny, tmp_path):
    first = produce(tiny, tmp_path / "first.dxf")
    second = produce(tiny, tmp_path / "second.dxf")
    assert [read_line_source_ref(e) for e in emitted(first)] == [
        read_line_source_ref(e) for e in emitted(second)
    ]
    assert (
        validate_line_source_refs(emitted(second), expected=expected(tiny))["status"]
        == "SNAPSHOT_VERIFIED"
    )


def test_overflow_does_not_replace_existing_complete_dxf(tiny, tmp_path):
    path = tmp_path / "prior.dxf"
    produce(tiny, path)
    before = path.read_bytes()
    changed = replace(
        tiny,
        straight_lines=(
            replace(
                tiny.straight_lines[0],
                source_ids=tuple(f"DESIGN-PROBE-{i}" for i in range(129)),
            ),
        )
        + tiny.straight_lines[1:],
    )
    with pytest.raises(ValueError, match="overflow"):
        export_final_structure_dxf(changed, path)
    assert path.read_bytes() == before


def test_literal_two_member_attribute_swap_rejected(tiny, tmp_path):
    # Construct unequal display attrs, rebind each legitimately, then swap attrs.
    # This is a diagnostic parser fault, not a production lineweight benefit.
    from app.export.line_source_ref import attach_line_source_ref

    doc = produce(tiny, tmp_path / "before.dxf")
    entities = emitted(doc)
    sources = [read_line_source_ref(e)["source"] for e in entities[:2]]
    entities[0].dxf.lineweight = 0
    entities[1].dxf.lineweight = 13
    for entity, source in zip(entities[:2], sources):
        attach_line_source_ref(entity, source)
    assert validate_line_source_refs(entities)["status"] == "SELF_CONSISTENTONLY"
    entities[0].dxf.lineweight, entities[1].dxf.lineweight = (
        entities[1].dxf.lineweight,
        entities[0].dxf.lineweight,
    )
    after = tmp_path / "DESIGN_PROBE-attribute-swap.dxf"
    doc.saveas(after)
    with pytest.raises(ValueError, match="geometry or attributes"):
        validate_line_source_refs(emitted(ezdxf.readfile(after)))


def test_expected_reader_handles_real_mixed_presentation_none(tiny):
    # Current Zhongshan cache has line_records with None entries; writer supports this.
    lines = tiny.straight_lines[:2]
    weights = (
        None,
        dict(
            cad_lineweight=13,
            category="DESIGN_PROBE",
            source_width_px=1.91,
            source_dpi=240,
        ),
    )
    snapshot = SimpleNamespace(
        structure_id=tiny.structure_id,
        source_structure_id=tiny.source_structure_id,
        straight_lines=lines,
        provenance={"stroke_presentation": {"line_records": weights}},
    )
    doc = ezdxf.new("R2010")
    _, entities, _ = add_straight_line_entities(
        doc.modelspace(),
        lines,
        transform=lambda x, y: (x, 165 - y),
        line_records=weights,
        line_source_refs=make_line_source_refs(snapshot),
    )
    expected_records = expected_line_source_records(snapshot, lambda x, y: (x, 165 - y))
    assert [item["entity"]["lineweight"] for item in expected_records] == [-1, 13]
    assert (
        validate_line_source_refs(entities, expected=expected_records)["status"]
        == "SNAPSHOT_VERIFIED"
    )
