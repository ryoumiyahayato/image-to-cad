"""Failed visual acceptance stays disabled; this is not a source/GUI proof."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
import project_entry as entry

APP = QApplication.instance() or QApplication([])


def test_visual_proposal_cannot_enable_or_bypass_direct_accept(monkeypatch):
    window = entry.ProjectWindow()
    window.member.addItem("test", "member")
    window.source.addItem("test", "source")
    window.project = object()
    monkeypatch.setattr(entry, "preview_repair", lambda *a: ({"member":"member", "before":{"text":"old"},"after":{"text":"new"},"source_evidence":{}},{}))
    monkeypatch.setattr(window,"display_source",lambda *a:None)
    monkeypatch.setattr(window,"render",lambda *a:None)
    window.make_preview()
    assert not window.confirm.isEnabled()
    with pytest.raises(ValueError,match="停用"):
        window.accept()
    window.close()
