# Image to CAD（开发预览）

产品版本唯一来源为 `app/version.py`。运行 `python main.py --version` 查看名称和版本。
开发版本的 Windows numeric file version 使用前三段数字并补零；资源中的显示版本保留开发后缀。

这是一个面向纸质图纸扫描件、手机照片和 PDF 的 CAD 转换工具。

2026-10-14 产品状态见 [PROJECT_STATUS.md](../docs/project/PROJECT_STATUS.md)。原生 PDF 的可信简单圆弧可经可选证据、完整源匹配和原子替换进入正式 ARC 输出。扫描输入沿用图像流程；P10-A 已支持完整独立细直笔画的受约束 LINE 恢复。复杂裁剪、混合成员和不明节点继续保留原表示。

当前版本默认输出可编辑结构线和单行文字：长直线重建为中心线 `LINE`，已识别的汉字、英文、数字和标点写入原生 `TEXT`，签名保留为独立的透明前景图像。扫描底图是可选项，不是正常可编辑结果的必需组成。自动矢量化不是原始 DWG 恢复，也不承诺从破损扫描件恢复原始设计语义。

## 输入与多页 PDF

GUI 支持 JPG、JPEG、PNG、扫描 PDF 和图片型 PDF。

多页 PDF 不再要求导入时只选一页。程序会把 PDF 作为一个文档载入：

- 通过“上一页 / 下一页 / 页面选择器”逐页查看；
- 当前页可单独识别和可视化修改；
- 可批量自动识别全部页面；
- 导出当前页，或把已处理页面导出为每页独立的 DXF/DWG；
- 未处理页面可以跳过；
- 主动启用扫描底图时，才生成对应的 PNG。

PDF 页面本身已是矩形纸面，因此直接按页面载入，不再强制执行照片透视校正。照片输入仍可使用自动或手动四角校正。

## 输出

多页 PDF 默认生成：

```text
文档.dxf 或 文档.dwg
文档.report.json
```

只有启用“附加原扫描底图”时才生成 `page-###.scan.png`。扫描底图是外部链接，不嵌入 DXF/DWG；启用后移动、复制或交付时，必须把 CAD 文件和全部底图放在同一目录。

DWG 仍由本机安装的 ODA File Converter 从 DXF 转换。ODA 不随程序捆绑；转换失败时已生成的 DXF 和扫描底图会保留。

## 文字与符号

程序在原始分辨率下分块识别文字，并在 OCR 视图中临时去除长表格线，避免边框切断字符。达到置信度要求的印刷文字直接输出为原生、可修改内容的单行 CAD `TEXT`；对应的扫描字形会从轮廓源中抑制，同时恢复穿过文字框的表格线，避免空心字形和重复叠字。

可编辑文字位于独立且默认可见的 `OCR_TEXT` 图层。每个 OCR 文字行对应一个 `TEXT` 实体，不使用 `MTEXT`，可在 LibreCAD/AutoCAD 中直接双击修改。程序随项目提供覆盖中文、英文、数字和常用标点的 Unicode 单线字体。

跨越图框的签名和大幅手写批注会按清理后的原始墨迹宽度保留为透明 PNG，不再骨架化或智能补笔，并放在独立、默认可见且位于边框上方的 `SIGNATURE_OVERLAY` 图层。疑似 Logo 或连接图形的 OCR 框保留为原始图形轮廓，不会整框擦除。移动、复制或交付时，必须把 DXF 和同名 `signature-###.png` 文件放在同一目录。CAD 文字支持整行内容编辑，但不提供 Word 的自动换行和段落排版能力。

## 可视化人工修改

正常流程不要求人工确认。需要修正特殊图纸时，可选用直接图上编辑：

- 使用黑色画笔补充内容、白色画笔删除内容；
- 缩放、撤销一笔或清除修改；
- 保存后更新 CAD 预览和导出结果；
- 未修改直接保存时保留原有 FinalStructure 和直线。

## 视图保真

大图缩小时采用分级预览和面积采样，并对被平均变灰的细线做显示补偿。该处理只影响界面预览，不修改原始扫描图，也不修改导出的底图。缩到整张超大图纸时，显示器像素数量仍然有限；需要判断细节时应放大查看。

## 视觉验收

处理完成后，“视觉验收”页签会并排显示原始图、最终重建和同坐标叠加图。三个视图联动缩放和平移，并提供结构线、文字、符号、未确认几何及警告区域开关；鼠标位置以页面百分比显示，方便准确描述问题。

用户可以选择“通过 / 部分通过 / 不通过”，并勾选漏内容、多画、乱连接、位置、文字、符号或整体错误。选择视觉验收页签时，会在 `Documents/CADPhotoToDXF/visual-acceptance/<run-id>/` 下生成 `visual_acceptance_overview.png`、三张分视图、人工结论和开发详情。最终重建直接读取与 DXF 导出相同的不可变 `FinalStructure`，不会另算一套预览几何。

## 简化 GUI 流程

1. **导入图片 / 扫描 PDF**：多页 PDF 作为一个文档载入。
2. **照片校正（仅照片需要）**：PDF 页面直接使用原始矩形页面。
3. **处理当前页或全部页面**：自动清理扫描底色、识别单行文字、提取签名并重建中心直线。
4. **视觉验收**：直接比较原图、最终重建和叠加结果，记录人工结论。
5. **CAD 预览**：单独查看最终矢量结果。
6. **模型尺寸校准（可选）**：用独立已知尺寸建立 `model_mm`。
7. **导出 CAD**：每页生成独立 DXF/DWG；只有主动启用时才附加扫描底图。

界面保留页面选择、处理、文字检查、比例和导出设置。

## 坐标模式

- `pixel`：尚未校准的图像坐标；
- `paper_mm`：PDF 或已知纸张的纸面毫米；
- `model_mm`：通过已知实际尺寸独立校准后的模型坐标。

纸面毫米不是工程模型尺寸。没有独立模型尺度校准时，不得把 `paper_mm` 解释为真实施工尺寸。

## 环境

- Windows 10/11 x64；
- Python 3.11+；
- Windows GUI 和安装包为主要目标。

源码运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

验证：

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m ruff check app tests validation main.py
python -m mypy app/core/resolution.py app/core/scale_calibrator.py app/core/reporting.py app/ocr/auxiliary_recognition.py
python -m compileall -q app tests validation main.py
```

## 维护入口

GUI 和 headless CLI 都调用 `app/core/processing.py` 的
`ProductionProcessingService.process_page`。图片入口使用相同的 DPI 设置；
PDF 页按页面尺寸调整 DPI。CLI 保留照片透视确认和纸面尺寸参数。
旧 `--min-line-length`、`--threshold-strength`、`--no-hatch`、`--auxiliary`
参数已删除，使用时 argparse 会报错；它们不属于当前生产处理设置。`--ocr` 启用当前生产 OCR。

- `core/`：数据模型、配置、缓存、图像载入和坐标转换；
- `geometry/`：扫描预处理、结构线、ownership 和 reconciliation；
- `ocr/`：当前文字识别、字体和图形候选数据；
- `export/`：单一 DXF 实体 serializer，以及单页/文档文件布局；
- `gui/`：一个 MainWindow 和按职责组织的页面、处理、审阅方法；
- `diagnostics/`：可选的观察记录、debug bundle 和视觉验收。

预览、缓存、GUI 和 CLI 导出读取同一个 FinalStructure。
生产 processing 不需要 Git、网络、GPU 或本地审计 artifact 目录。
重构验证与必要性说明在仓库的 `docs/refactor/`；代表输入比较命令是
`python ../maintenance/preservation_check.py`，依赖结构检查命令是
`python ../maintenance/verify_architecture.py`。

## 当前边界

- 严重模糊、遮挡或破损区域仍可能产生 OCR 错字；已识别文字可以直接在 CAD 中修正；
- 自动结构线仍可能漏检或误检；短线、圆弧、样条和复杂符号不一定能恢复原始 CAD 语义；
- 圆弧、样条、块、标注关联、字体、图层语义和设计约束仍无法可靠恢复；
- ODA 转换只改变文件格式，不恢复原始 DWG 语义；
- 没有原始 CAD 标准答案、逐页配准和明确误差指标时，不得宣称工程级精度；
- 当前仍是内部预览版本，不应作为正式发布或施工交付完成状态。
