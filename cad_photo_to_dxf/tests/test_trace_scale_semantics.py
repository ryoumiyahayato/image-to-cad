from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from app.gui_trace_release import MainWindow
from app.scale_calibrator import ScaleCalibration


_APP = QApplication.instance() or QApplication([])


def test_known_length_calibration_is_not_multiplied_by_drawing_ratio() -> None:
    window = MainWindow()
    window._native_pdf_mode = False
    window.original_image = np.full((100, 200, 3), 255, dtype=np.uint8)
    window.corrected_image = window.original_image.copy()
    window.paper_size_combo.setCurrentIndex(0)
    window.calibration = ScaleCalibration((10.0, 10.0), (110.0, 10.0), 5000.0)
    window.drawing_scale_spin.setValue(100)

    assert window._has_explicit_model_calibration()
    assert window._export_drawing_multiplier() == 1.0
    window._update_scale_label()
    assert "不会再叠加图纸比例" in window.scale_result_label.text()
    window.close()


def test_pdf_paper_coordinates_use_selected_drawing_ratio() -> None:
    window = MainWindow()
    window._native_pdf_mode = True
    window.original_image = np.full((100, 200, 3), 255, dtype=np.uint8)
    window.corrected_image = window.original_image.copy()
    window.calibration = ScaleCalibration((0.0, 0.0), (199.0, 0.0), 420.0)
    window.drawing_scale_spin.setValue(50)

    assert not window._has_explicit_model_calibration()
    assert window._export_drawing_multiplier() == 50.0
    window._update_scale_label()
    assert "输出比例 1:50" in window.scale_result_label.text()
    window.close()
