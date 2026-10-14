import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ezdxf
from PySide6.QtWidgets import QApplication, QDialog
from app.gui import MainWindow
from app.gui import review_actions as gui_review_actions
from app.core.processing import ProductionProcessingConfig, ProductionProcessingService
from app.core.arc_types import ArcSegment, PdfPathReference
from app.core.structure import FinalStructure
from app.core.cancellation import CancellationToken
import numpy as np
from app.export.trace_single_export import export_final_structure_dxf
from tests.test_processing_contract import _page


def test_unchanged_review_preserves_final_structure_lines_and_export(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    result = ProductionProcessingService.process_page(
        _page(), ProductionProcessingConfig(enable_ocr=False)
    )
    window = MainWindow()
    window._refresh_visual_acceptance = lambda: None
    window._final_structure = result.final_structure
    window.binary_image = result.binary
    before = window._final_structure
    assert before.straight_lines

    class UnchangedDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def edited_binary(self):
            return window.binary_image.copy()

    monkeypatch.setattr(gui_review_actions, "TracePaintDialog", UnchangedDialog)
    window._start_processing = lambda *args: (_ for _ in ()).throw(
        AssertionError("unchanged save must not retrace")
    )
    window.review_layers()
    assert window._final_structure is before
    exported = export_final_structure_dxf(before, tmp_path / "saved.dxf")
    assert len(ezdxf.readfile(exported.path).modelspace().query("LINE")) == len(
        before.straight_lines
    )
    window.close()
    app.processEvents()


def test_residual_review_keeps_independent_native_arc(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    arc = ArcSegment(
        "contract:residual-review",
        (40, 40),
        20,
        0,
        90,
        source=PdfPathReference("artificial.pdf", 1, 0),
        replaced_members=("contour:old",),
        acceptance_reason="artificial contract",
    )
    binary = np.full((80, 80), 255, np.uint8)
    structure = FinalStructure(
        (80, 80),
        binary,
        (),
        arcs=(arc,),
        provenance={
            "native_arc_replacements": [
                {"object_id": arc.object_id, "replaced_members": ["contour:old"]}
            ]
        },
    )
    edited = binary.copy()
    edited[65:68, 65:68] = 0
    captured = []

    class EditedDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def edited_binary(self):
            return edited

    monkeypatch.setattr(gui_review_actions, "TracePaintDialog", EditedDialog)
    window = SimpleNamespace(
        binary_image=binary,
        _final_structure=structure,
        _state_revision=0,
        _trace_threshold=128,
        _ocr_texts=(),
        _signature_regions=(),
        _native_pdf_mode=False,
        _apply_trace_result=lambda value, **kw: captured.append(value),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _: None),
        _start_processing=lambda operation, completed, label: completed(
            operation(CancellationToken(), lambda *args: None)
        ),
    )
    gui_review_actions.review_layers(window)
    (result,) = captured
    assert result.final_structure.arcs == (arc,)
    assert (
        result.final_structure.provenance["native_arc_replacements"]
        == structure.provenance["native_arc_replacements"]
    )
    assert len(result.final_structure.contours) == 1
    exported = export_final_structure_dxf(
        result.final_structure, tmp_path / "residual-review.dxf"
    )
    assert len(ezdxf.readfile(exported.path).modelspace().query("ARC")) == 1
    app.processEvents()


def test_text_review_rebuild_preserves_formal_arc_and_replacement_relation():
    app = QApplication.instance() or QApplication([])
    arc = ArcSegment(
        "contract:review-arc",
        (40, 40),
        20,
        0,
        90,
        source=PdfPathReference("artificial.pdf", 1, 0),
        replaced_members=("contour:old",),
        acceptance_reason="artificial contract",
    )
    structure = FinalStructure(
        (80, 80),
        np.full((80, 80), 255, np.uint8),
        (),
        arcs=(arc,),
        provenance={
            "native_arc_replacements": [
                {"object_id": arc.object_id, "replaced_members": ["contour:old"]}
            ]
        },
    )
    window = SimpleNamespace(
        _final_structure=structure,
        detected_canvas=SimpleNamespace(set_image=lambda _: None),
        _dirty_trace_keys=set(),
        _current_trace_key=lambda: "contract",
        _refresh_visual_acceptance=lambda: None,
    )
    updated = gui_review_actions._replace_final_structure_texts(window, ())
    assert updated.arcs == (arc,)
    assert (
        updated.provenance["native_arc_replacements"]
        == structure.provenance["native_arc_replacements"]
    )
    assert window._cad_preview_binary[20:22, 39:42].min() < 128
    app.processEvents()
