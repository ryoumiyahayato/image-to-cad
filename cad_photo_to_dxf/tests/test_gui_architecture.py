from pathlib import Path
from PySide6.QtWidgets import QMainWindow
from app.gui import MainWindow


def test_window_has_one_application_class():
    assert MainWindow.__bases__ == (QMainWindow,)


def test_interfaces_share_production_entry():
    root = Path(__file__).resolve().parents[1]
    cli = (root / 'main.py').read_text(encoding='utf-8')
    gui = (root / 'app/gui/processing.py').read_text(encoding='utf-8')
    assert 'ProductionProcessingService.process_page(' in cli
    assert gui.count('ProductionProcessingService.process_page(') == 2
    assert 'trace_image_optimized(' not in cli + gui


def test_window_export_actions_dispatch(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.gui import page_export
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = []
    window._native_pdf_mode = True
    monkeypatch.setattr(page_export, '_start_single_export', lambda value: calls.append(('current', value)))
    monkeypatch.setattr(page_export, '_start_processed_pages_export', lambda value: calls.append(('processed', value)))
    window.export_file()
    window.export_processed_pages()
    assert calls == [('current', window), ('processed', window)]
    window.close()
    app.processEvents()
