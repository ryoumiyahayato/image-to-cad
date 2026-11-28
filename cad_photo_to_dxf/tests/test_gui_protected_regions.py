"""Check source-pixel selection, actual Qt drag events and scanned-PDF sizing."""
import os
from io import BytesIO

import pymupdf
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core import conversion
from app.gui import window


@pytest.fixture(scope="module")
def application():
    if not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_preview_rectangle_uses_original_pixels_and_clips_edges():
    assert window.protected_source_rect(
        QRectF(-10, 10, 120, 70), QRectF(0, 0, 100, 100), (2400, 1200),
    ) == (0, 120, 2400, 960)
    assert window.protected_source_rect(
        QRectF(200, 200, 10, 10), QRectF(0, 0, 100, 100), (2400, 1200),
    ) is None


def test_pdf_selection_dimensions_match_real_capped_render(tmp_path, monkeypatch):
    source = tmp_path / "fractional-page.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=310.25, height=190.75)
        page.set_rotation(90)
        document.save(source)
    monkeypatch.setattr(conversion, "MAX_RENDER_PIXELS", 100_000)
    monkeypatch.setattr(window, "MAX_RENDER_PIXELS", 100_000)
    image, _ = conversion._render_pdf_page(source, 1, 600)
    with pymupdf.open(source) as document:
        expected = window.pdf_raster_size(document[0].rect, 600)
    assert expected == (image.shape[1], image.shape[0])


def test_drag_survives_zoom_and_selection_clears_on_dpi_page_input(application, tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (2400, 1200), "white").save(source)
    gui = window.MainWindow()
    gui.show()
    gui.load_input(source)
    application.processEvents()
    assert gui.protect_button.isEnabled()
    assert gui.source_view._source_size == (2400, 1200)
    QTest.mouseClick(gui.protect_button, Qt.MouseButton.LeftButton)
    gui.source_view.scale(1.35, 1.35)
    # The PNG preview is 2000x1000, while the source is 2400x1200.
    start = gui.source_view.mapFromScene(QPointF(400, 250))
    end = gui.source_view.mapFromScene(QPointF(900, 600))
    QTest.mousePress(gui.source_view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(gui.source_view.viewport(), end, 20)
    QTest.mouseRelease(gui.source_view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(gui._preserve_regions) == 1
    assert gui._preserve_regions[0] == pytest.approx((480, 300, 1080, 720), abs=5)
    assert not gui.all_pages.isChecked()
    gui._set_busy(True)
    assert not gui.protect_button.isEnabled() and not gui.clear_regions_button.isEnabled()
    gui._set_busy(False)
    gui.dpi_spin.setValue(200)
    assert gui._preserve_regions == []
    # A native page disables drawing regions; a scanned page enables them.
    pdf = tmp_path / "mixed.pdf"
    pixels = BytesIO()
    Image.new("RGB", (120, 90), "white").save(pixels, format="PNG")
    with pymupdf.open() as document:
        page = document.new_page(width=120, height=90)
        page.draw_line((10, 10), (100, 50))
        page = document.new_page(width=120, height=90)
        page.insert_image(page.rect, stream=pixels.getvalue())
        document.save(pdf)
    gui.load_input(pdf)
    assert not gui.protect_button.isEnabled()
    gui.page_spin.setValue(2)
    assert gui.protect_button.isEnabled()
    gui._region_selected((5, 5, 30, 30))
    gui.page_spin.setValue(1)
    assert gui._preserve_regions == [] and not gui.protect_button.isEnabled()
    gui.load_input(source)
    assert gui._preserve_regions == [] and gui.protect_button.isEnabled()
    gui.close()


def test_residual_tab_tracks_scanned_pages_in_a_mixed_document(application, tmp_path):
    source = tmp_path / "mixed.pdf"
    pixels = BytesIO()
    Image.new("RGB", (120, 90), "white").save(pixels, format="PNG")
    with pymupdf.open() as document:
        page = document.new_page(width=120, height=90)
        page.draw_line((10, 10), (100, 50))
        page = document.new_page(width=120, height=90)
        page.insert_image(page.rect, stream=pixels.getvalue())
        document.save(source)
    result = conversion.convert_document(source, tmp_path / "mixed.dxf", dpi=72, enable_ocr=False)

    gui = window.MainWindow()
    gui._completed(result)
    assert not gui.tabs.isTabEnabled(gui.residual_tab)
    gui.result_pages.setCurrentIndex(1)
    assert gui.tabs.isTabEnabled(gui.residual_tab)
    gui.tabs.setCurrentIndex(gui.residual_tab)
    assert gui.tabs.currentWidget() is gui.residual_view
    assert gui.residual_view.sceneRect().size().toTuple() == (120.0, 90.0)
    assert "几何漏画 0 px" in gui.result_log.toPlainText()
    gui.result_pages.setCurrentIndex(0)
    assert gui.tabs.currentWidget() is gui.result_view
    assert not gui.tabs.isTabEnabled(gui.residual_tab)
    assert not gui.residual_view.scene().items()
    gui.close()
