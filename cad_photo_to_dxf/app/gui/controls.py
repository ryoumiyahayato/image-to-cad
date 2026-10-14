"""Build the current desktop controls once, with their final labels and defaults."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def build_controls(self):
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.addWidget(self._button("导入图片 / 扫描 PDF", self.import_image))
    layout.addWidget(self._button("图片校正", self.correct_image))

    pages = QGroupBox("当前 PDF 页面", container)
    page_layout = QVBoxLayout(pages)
    row = QHBoxLayout()
    self.previous_page_button = self._button("上一页", self._previous_pdf_page)
    self.next_page_button = self._button("下一页", self._next_pdf_page)
    self.page_combo = QComboBox(pages)
    self.page_combo.addItem("单页图片", 0)
    self.page_combo.currentIndexChanged.connect(self._on_pdf_page_changed)
    row.addWidget(self.previous_page_button)
    row.addWidget(self.page_combo, 1)
    row.addWidget(self.next_page_button)
    page_layout.addLayout(row)
    self.page_summary_label = QLabel(
        "当前页处理完成后可立即导出；也可批量导出所有已处理页面。", pages
    )
    self.page_summary_label.setWordWrap(True)
    page_layout.addWidget(self.page_summary_label)
    layout.addWidget(pages)

    generation = QGroupBox("生成 CAD", container)
    generation_layout = QVBoxLayout(generation)
    generation_layout.addWidget(self._button("处理当前页", self.detect_and_clean))
    self.batch_pdf_button = self._button("处理全部页面", self.batch_vectorize_pdf)
    generation_layout.addWidget(self.batch_pdf_button)
    layout.addWidget(generation)

    review = QGroupBox("检查与修改", container)
    review_layout = QVBoxLayout(review)
    review_layout.addWidget(self._button("检查并修改当前页", self.review_layers))
    layout.addWidget(review)

    ocr = QGroupBox("文字识别", container)
    ocr_layout = QVBoxLayout(ocr)
    self.ocr_before_trace_checkbox = QCheckBox("识别文字并生成可编辑文字", ocr)
    self.ocr_before_trace_checkbox.setChecked(True)
    ocr_layout.addWidget(self.ocr_before_trace_checkbox)
    note = QLabel(
        "识别文字默认显示为单行可编辑 TEXT；已识别字形不再重复生成空心轮廓。", ocr
    )
    note.setWordWrap(True)
    ocr_layout.addWidget(note)
    ocr_layout.addWidget(self._button("检查文字识别结果", self.review_ocr_texts))
    layout.addWidget(ocr)

    scale = QGroupBox("输出设置", container)
    form = QFormLayout(scale)
    self.drawing_scale_spin = QSpinBox(scale)
    self.drawing_scale_spin.setRange(1, 10000)
    self.drawing_scale_spin.setValue(1)
    self.drawing_scale_spin.setToolTip(
        "默认按 1:1 输出。只有明确需要按图纸比例还原模型尺寸时才修改。"
    )
    self.drawing_scale_spin.valueChanged.connect(self._scale_changed)
    form.addRow("图纸比例 1:", self.drawing_scale_spin)
    self.scale_result_label = QLabel(scale)
    self.scale_result_label.setWordWrap(True)
    form.addRow("模型坐标", self.scale_result_label)
    palette = QLabel("不同内容使用不同颜色，便于检查。", scale)
    palette.setWordWrap(True)
    form.addRow("自动分层颜色", palette)
    layout.addWidget(scale)

    export = QGroupBox("导出选项", container)
    export_layout = QVBoxLayout(export)
    self.include_underlay_checkbox = QCheckBox(
        "附加原扫描底图（仅需在 CAD 中对照时开启；会增加文件和导出时间）", export
    )
    export_layout.addWidget(self.include_underlay_checkbox)
    self.dwg_version_combo = QComboBox(export)
    for label, value in [
        ("AutoCAD 2018", "R2018"),
        ("AutoCAD 2013", "R2013"),
        ("AutoCAD 2010", "R2010"),
    ]:
        self.dwg_version_combo.addItem(label, value)
    export_layout.addWidget(self.dwg_version_combo)
    layout.addWidget(export)
    layout.addWidget(self._button("导出当前页 CAD", self.export_file))
    self.export_processed_pages_button = self._button(
        "导出已处理页面（每页独立文件）", self.export_processed_pages
    )
    layout.addWidget(self.export_processed_pages_button)

    self.cancel_button = self._button("取消当前处理", self.cancel_processing)
    self.cancel_button.setEnabled(False)
    layout.addWidget(self.cancel_button)
    self.progress_bar = QProgressBar(container)
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setFormat("空闲")
    layout.addWidget(self.progress_bar)
    self.info_label = QLabel("比例：未校准（1 px = 1 个无单位图形单位）", container)
    self.info_label.setWordWrap(True)
    layout.addWidget(self.info_label)
    layout.addStretch(1)

    # Photo corner/calibration actions use the existing unknown-paper default.
    self.paper_size_combo = QComboBox(container)
    self.paper_size_combo.addItem("未知（无单位像素）", (None, "auto"))
    self.paper_size_combo.hide()
    self.tabs.removeTab(self.tabs.indexOf(self.corrected_canvas))
    self.tabs.removeTab(self.tabs.indexOf(self.preprocess_tabs))
    self.corrected_canvas.hide()
    self.preprocess_tabs.hide()
    self.tabs.setTabText(self.tabs.indexOf(self.detected_canvas), "FINAL OUTPUT PREVIEW / CAD 预览")
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(container)
    scroll.setMinimumWidth(500)
    return scroll
