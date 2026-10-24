"""TEST_ONLY faults exercise both atomic native TEXT consumers."""

import ezdxf
import pytest

from app.core.review_project import ReviewProject, ReviewProjectError
from app.export.document_export import DocumentPage
from app.export.trace_document_export import export_trace_document_streaming
from app.export.trace_single_export import export_final_structure_dxf
from app.export.text_consistency import TextConsistencyError
from tests import test_persistent_text_review as persistent_tests
from tests.test_persistent_text_review import _confirm

project = persistent_tests.project


def _export(project, path, mode, *, review=True):
    if mode == "single":
        return (
            project.export_dxf(path)
            if review
            else export_final_structure_dxf(project.baseline, path)
        )
    return export_trace_document_streaming(
        (
            DocumentPage(
                page_number=1,
                raster=None,
                page_size_mm=(320, 150),
                final_structure=project.baseline,
                text_review=project.validated_review() if review else None,
            ),
        ),
        path,
    )


@pytest.mark.parametrize("mode", ["single", "document"])
@pytest.mark.parametrize("mutate_record", [False, True])
def test_wrong_text_rejected_even_when_output_record_copies_it(
    project, tmp_path, monkeypatch, mode, mutate_record
):
    from app.export import ocr_outline_export

    _confirm(project)
    path = tmp_path / "valid.dxf"
    _export(project, path, mode)
    previous = path.read_bytes()
    original = ocr_outline_export._add_text_entity

    def fault(*args, **kwargs):
        entity = original(*args, **kwargs)
        entity.dxf.text = "TEST_ONLY_WRONG"
        if mutate_record:
            tags = list(entity.get_xdata("OCR_TEXT_LINE"))
            tags[1] = (1000, entity.dxf.text)
            entity.set_xdata("OCR_TEXT_LINE", tags)
        return entity

    monkeypatch.setattr(ocr_outline_export, "_add_text_entity", fault)
    with pytest.raises(TextConsistencyError, match="effective text"):
        _export(project, path, mode)
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".valid.dxf.*.tmp.dxf"))


@pytest.mark.parametrize("mode", ["single", "document"])
def test_original_applied_held_withdrawn_and_saved_history(project, tmp_path, mode):
    path = tmp_path / "history.dxf"
    uuid = project.bindings[0]["text_source_uuid"]
    _export(project, path, mode)
    assert [e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")] == [
        "ALPHA",
        "ALPHA",
    ]
    applied = _confirm(project)
    _confirm(project, "TEST_ONLY A PROPOSAL TOO LONG FOR THE SOURCE")
    assert project.current_text(uuid) == "ALP"
    _export(project, path, mode)
    assert [e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")] == [
        "ALP",
        "ALPHA",
    ]
    _confirm(project, withdraw=True)
    saved = tmp_path / "history.icreview"
    project.save(saved)
    reopened = ReviewProject.open(saved)
    try:
        _export(reopened, path, mode)
        doc = ezdxf.readfile(path)
        entities = list(doc.modelspace().query("TEXT"))
        assert [e.dxf.text for e in entities] == ["ALPHA", "ALPHA"]
        assert entities[0].get_xdata("OCR_TEXT_LINE")[1].value == "ALPHA"
        assert "WITHDRAWN" in [
            tag.value for tag in entities[0].get_xdata("TEXT_REVIEW")
        ]
        assert reopened.records[0] == applied and len(reopened.records) == 3
        assert len(doc.modelspace().query("LINE")) == 1
    finally:
        reopened.close()


def test_serialized_fault_is_rejected_before_atomic_replace(
    project, tmp_path, monkeypatch
):
    from ezdxf.document import Drawing

    path = tmp_path / "serialized.dxf"
    project.export_dxf(path)
    previous = path.read_bytes()
    original = Drawing.saveas

    def fault(doc, filename, *args, **kwargs):
        result = original(doc, filename, *args, **kwargs)
        data = __import__("pathlib").Path(filename)
        data.write_text(
            data.read_text(encoding="utf8").replace("ALPHA", "OMEGA"), encoding="utf8"
        )
        return result

    monkeypatch.setattr(Drawing, "saveas", fault)
    with pytest.raises(TextConsistencyError):
        project.export_dxf(path)
    assert path.read_bytes() == previous


def test_stale_review_cannot_export_a_later_journal(project, tmp_path):
    review = project.validated_review()
    _confirm(project)
    with pytest.raises(ReviewProjectError, match="review changed"):
        export_final_structure_dxf(
            project.baseline, tmp_path / "stale.dxf", text_review=review
        )
    assert not (tmp_path / "stale.dxf").exists()


def test_generic_snapshot_without_review_works_in_both_consumers(project, tmp_path):
    for mode in ("single", "document"):
        path = tmp_path / (mode + ".dxf")
        _export(project, path, mode, review=False)
        assert [
            e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")
        ] == ["ALPHA", "ALPHA"]


@pytest.mark.parametrize("mode", ["single", "document"])
def test_same_string_objects_cannot_exchange_complete_output_identity(
    project, tmp_path, monkeypatch, mode
):
    from app.export import trace_single_export, trace_document_export

    path = tmp_path / "identity.dxf"
    _export(project, path, mode)
    previous = path.read_bytes()
    module = trace_single_export if mode == "single" else trace_document_export
    original = module.write_page_entities

    def fault(doc, modelspace, **kwargs):
        result = original(doc, modelspace, **kwargs)
        first, second = list(modelspace.query("TEXT"))
        for appid in ("OCR_TEXT_LINE", "TEXT_REVIEW", "TEXT_OUTPUT_CONTRACT"):
            one, two = list(first.get_xdata(appid)), list(second.get_xdata(appid))
            first.set_xdata(appid, two)
            second.set_xdata(appid, one)
        return result

    monkeypatch.setattr(module, "write_page_entities", fault)
    with pytest.raises(
        TextConsistencyError, match="source placement/target identity"
    ) as caught:
        _export(project, path, mode)
    assert all(
        key in str(caught.value)
        for key in ("layer=", "handle=", "line_index=", "source_uuid=")
    )
    assert path.read_bytes() == previous


@pytest.mark.parametrize("mode", ["single", "document"])
def test_current_output_missing_record_rejected_with_location(
    project, tmp_path, monkeypatch, mode
):
    from app.export import ocr_outline_export

    original = ocr_outline_export._add_text_entity
    path = tmp_path / "missing-record.dxf"
    _export(project, path, mode)
    previous = path.read_bytes()

    def fault(*args, **kwargs):
        entity = original(*args, **kwargs)
        entity.discard_xdata("OCR_TEXT_LINE")
        return entity

    monkeypatch.setattr(ocr_outline_export, "_add_text_entity", fault)
    with pytest.raises(TextConsistencyError) as caught:
        _export(project, path, mode)
    assert all(
        key in str(caught.value) for key in ("layer=", "handle=", "line_index=missing")
    )
    assert path.read_bytes() == previous
