"""Preview geometry/font checks; target-CAD inspection remains separate."""
from copy import deepcopy
from pathlib import Path
import sys
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ezdxf
import pytest
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.addons.drawing.pyqt import CorrespondingDXFEntity
from PySide6.QtWidgets import QApplication, QGraphicsScene

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"cad_photo_to_dxf"))
import cad_preview
from app.ocr.librecad_lff import librecad_text_metrics

APP = QApplication.instance() or QApplication([])


def test_real_cad_uses_lff_and_keeps_leader_and_document():
    path = Path(r"D:\programs\Image-to-CAD\g2728-followup-20261027\b\dev08-second-librecad.dxf")
    doc = ezdxf.readfile(path)
    before = [TagCollector.dxftags(e) for e in doc.modelspace()]
    styles = [deepcopy(e.dxfattribs()) for e in doc.styles]
    scene = QGraphicsScene()
    context = cad_preview.draw_current_cad(doc, scene)
    assert context.resolve_all(doc.entitydb["6D6"]).font.filename == "wqy-unicode.lff"
    items = {i.data(CorrespondingDXFEntity).dxf.handle: i for i in scene.items() if i.data(CorrespondingDXFEntity)}
    assert "12F" in items and "6D6" in items
    line = items["12F"].line()
    assert line.x1() == pytest.approx(doc.entitydb["12F"].dxf.start.x)
    assert line.y1() == pytest.approx(doc.entitydb["12F"].dxf.start.y)
    assert items["12F"].pen().widthF() >= 1.
    # Phi/@ descend beneath the insertion baseline, toward this near leader.
    assert items["6D6"].path().boundingRect().top() < doc.entitydb["6D6"].dxf.insert.y
    assert [TagCollector.dxftags(e) for e in doc.modelspace()] == before
    assert [e.dxfattribs() for e in doc.styles] == styles


def test_rotated_native_path_has_correct_coordinates():
    doc = ezdxf.new("R2010"); doc.styles.new("lff", dxfattribs={"font": "wqy-unicode"})
    e = doc.modelspace().add_text("A1", dxfattribs={"insert": (10,20), "rotation":90, "height":2, "width":.8,"style":"lff"})
    scene = QGraphicsScene();cad_preview.draw_current_cad(doc,scene)
    item = next(i for i in scene.items() if i.data(CorrespondingDXFEntity).dxf.handle==e.dxf.handle)
    box = item.path().boundingRect(); m = librecad_text_metrics("A1")
    assert box.left() == pytest.approx(10-m.max_y*2/9)
    assert box.right() == pytest.approx(10-m.min_y*2/9)
    assert box.top() == pytest.approx(20+m.min_x*2/9*.8)
    assert box.bottom() == pytest.approx(20+m.max_x*2/9*.8)


def test_missing_lff_rejects_untrusted_preview(monkeypatch):
    monkeypatch.setattr(cad_preview,"librecad_font_available",lambda:False)
    with pytest.raises(ValueError,match="LFF"):
        cad_preview.preview_context(ezdxf.new())


def test_unverified_font_does_not_silently_become_trusted_preview():
    doc = ezdxf.new(); doc.modelspace().add_text("unverified")
    with pytest.raises(ValueError, match="字体"):
        cad_preview.draw_current_cad(doc, QGraphicsScene())


def test_mtext_is_rejected_before_using_unverified_font_parser():
    doc = ezdxf.new();doc.styles.new("lff",dxfattribs={"font":"wqy-unicode"})
    doc.modelspace().add_mtext("note",dxfattribs={"style":"lff"})
    with pytest.raises(ValueError,match="MTEXT"):
        cad_preview.draw_current_cad(doc,QGraphicsScene())
