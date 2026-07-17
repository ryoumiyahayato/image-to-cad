# 扫描图片 / PDF 转可编辑 CAD v1.2.0

这是一个面向纸质图纸扫描件、手机照片和“只有图片、没有矢量数据”的 PDF 的半自动 CAD 转换工具。

程序同时保留两类信息：

1. 将能够可靠识别的结构线导出为可编辑 `LINE`，人工确认的圆导出为 `CIRCLE`，可选 OCR 文字导出为 `TEXT`；
2. 将校正后的扫描图保存为同目录 `.scan.png`，并作为 CAD `IMAGE` 底图链接，从而保留原图中的施工说明、文字、符号、细节和暂时无法可靠矢量化的内容。

它不是原始 CAD 恢复器。它不会自动恢复 DWG 约束、块、标注关联、字体、设计意图或可靠工程尺寸，也不能在未经人工复核时用于制造、施工或尺寸交付。

## 支持的输入

GUI 支持：

- JPG；
- JPEG；
- PNG；
- 扫描 PDF 或图片型 PDF。

多页 PDF 导入时会要求选择具体页码。PDF 页面默认按 300 DPI 渲染，并对异常大的页面进行像素总量限制，避免一次渲染占用过多内存。

本程序不读取 PDF 内部是否存在原始 CAD 矢量。当前 PDF 路径统一按页面图像处理，适合扫描仪生成或把纸质图纸封装成 PDF 的情况。

## 输出

### DXF

DXF 是程序的原生输出。可包含：

- `LINE`：经过检测、清理、交点分割和图层分类的线；
- `CIRCLE`：达到置信度门槛并由用户逐项确认的圆；
- `TEXT`：启用 OCR 且选择导出后，达到导出门槛的文字候选；
- `IMAGE`：校正后的扫描底图外部引用。

### DWG

GUI 可以选择 `.dwg`。程序会先生成同名 DXF，再调用用户电脑中已安装的 **ODA File Converter** 转成 DWG。

DWG 转换的限制：

- ODA File Converter 不随本程序捆绑；
- 第一次转换时，如果没有自动找到，程序会要求选择 `ODAFileConverter.exe`；
- 转换失败时不会删除已经生成的 DXF；
- 可选择 AutoCAD 2018、2013 或 2010 目标版本；
- DWG 只是 DXF 的格式转换，不会凭空恢复原始 DWG 约束、块和设计语义。

### 扫描底图

默认会生成：

```text
图纸.dxf 或 图纸.dwg
图纸.scan.png
图纸.report.json
```

扫描底图是外部链接，不嵌入 DXF/DWG。移动、复制或交付文件时，必须把 CAD 文件和 `.scan.png` 放在同一目录并一起移动。底图用于保留文字和复杂细节，矢量层用于选择、编辑和重新绘制可靠结构线。

## 文字保护

旧版本可能把“施工说明”等文字的笔画识别成大量短横线、短竖线，导致文字消失并污染 CAD。

v1.2.0 在直线检测前增加了保守的文字区域保护：

- 根据紧凑的小型连通组件识别疑似文字区域；
- 阻止主要位于文字区域内的短线进入 CAD；
- 尽量保留穿过文字区域的长结构线；
- 原始文字仍完整保存在扫描底图中；
- 启用 OCR 后，可将高置信度候选另行导出为可编辑 `TEXT`。

这只是减少文字碎线，不代表文字识别一定正确。OCR 字符、位置和字体仍需人工校对。

## 坐标模式

报告和界面明确区分三种坐标空间：

- `pixel`：尚未校准的图像坐标；DXF 声明为无单位；
- `paper_mm`：根据已接受纸张边界得到的纸面毫米坐标；
- `model_mm`：通过已知实际尺寸进行独立人工校准后的模型坐标。

纸面 A4 宽约 297 mm，并不表示图中标注为 12000 的对象已经恢复为 12000 mm。没有独立模型尺度校准时，不得把 `paper_mm` 解释为工程真实尺寸。

## 环境与安装

- Windows 10/11；
- Python 3.11；
- Windows GUI 和安装包为主要发布目标。

源码运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

可选 OCR：

```powershell
python -m pip install -r requirements-ocr.txt
```

`pytesseract` 仍要求系统另行安装 Tesseract。未安装时，扫描底图和文字保护仍可使用，但不能生成 OCR `TEXT`。

## GUI 1–9 作业流程

1. **导入图片 / 扫描 PDF**  
   选择 JPG、PNG 或 PDF。多页 PDF 选择一页。

2. **纸张规格与坐标**  
   选择 A0～A4、LETTER、LEGAL 和方向；不知道纸张规格时选择无单位像素。

3. **纸张校正**  
   先尝试自动识别；置信度不足时使用“3B. 手动点击四角并校正”。

4. **图像预处理**  
   检查灰度、去阴影、阈值、清噪和文字保护掩膜。黑白图应保留主要线条，同时保持背景干净。

5. **识别线条**  
   执行 Hough/LSD 检测、粗线中心化、文字区域过滤、吸附、合并、去重、交点分割和拓扑检查。

6. **人工复核图层**  
   逐条检查自动图层。图层名称是启发式分类，不等于已经恢复设计语义。

7. **人工确认圆形**  
   圆形默认不导出；只有达到门槛并由用户确认的候选才会成为 `CIRCLE`。

8. **校准模型尺寸**  
   在校正图上点击一条已知尺寸的两个端点，输入真实模型长度（mm）。不要用同一尺寸同时做校准和最终误差验证。

9. **导出 CAD**  
   选择 DWG 或 DXF；决定是否附带扫描底图、是否导出 OCR `TEXT`，并选择 DWG 版本。

修改纸张、阈值、检线、吸附、分类等参数后，旧识别结果和人工圆形确认会失效，必须重新处理。

## 查看细节

所有原图、校正图、预处理图和识别结果都支持：

- 鼠标滚轮：放大或缩小；
- 左键拖动：平移；
- 双击：适应窗口；
- 视图按钮：放大、缩小、适应窗口、100%；
- 快捷键：`Ctrl++`、`Ctrl+-`、`Ctrl+0`、`Ctrl+1`。

导出的 DXF 也会写入模型空间视口范围，使 CAD 软件首次打开时尽量直接显示全部实体。必要时仍可在 CAD 软件中执行 `ZOOM EXTENTS`。

## 命令行

命令行仍以 DXF 为主要输出。PDF 输入默认处理第一页；多页选择和 DWG 转换目前由 GUI 提供。

```powershell
python main.py --headless `
  --input samples/test.jpg `
  --output output/output.dxf `
  --preview output/preview.png `
  --report output/report.json `
  --debug-dir output/debug `
  --paper-size A4 `
  --paper-orientation landscape `
  --auxiliary `
  --verbose
```

主要参数：

- `--min-line-length`：必须大于 0；
- `--paper-size`：`A0`～`A4`、`LETTER`、`LEGAL` 或 `UNKNOWN`；
- `--paper-width-mm`、`--paper-height-mm`：自定义纸张尺寸；
- `--paper-orientation`：`auto`、`portrait` 或 `landscape`；
- `--allow-uncorrected`：纸张识别失败时保留原图，不应用可疑透视；
- `--allow-empty`：仅供受控调试；
- `--no-hatch`：删除高置信度 HATCH；
- `--debug-dir`：输出预处理阶段图像；
- `--auxiliary`：生成圆形和矩形候选；
- `--ocr`：生成 OCR 候选。

退出码：

- `0`：成功；
- `2`：参数错误；
- `3`：输入不存在、不可用或接近空白；
- `4`：纸张边界或严格置信度校验失败；
- `5`：没有有效几何；
- `130`：取消。

## 图层

- `SCAN_UNDERLAY`：校正扫描底图；
- `OUTLINE`：长粗外轮廓候选；
- `WALL_OR_FRAME`：正交墙体或框架候选；
- `GRID_OR_AXIS`：长细轴线候选；
- `HATCH`：高置信度填充线；
- `HATCH_CANDIDATE`：疑似填充；
- `DETAIL`：其他线条；
- `CIRCLE_CONFIRMED`：人工确认圆；
- `OCR_TEXT`：高置信度 OCR 文字。

除确认圆的几何类型、OCR 的候选文字及扫描底图本身外，其他图层名称仍属于启发式分类。

## 验证

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m ruff check app tests validation main.py
python -m mypy app/resolution.py app/scale_calibrator.py app/reporting.py app/auxiliary_recognition.py
python -m compileall -q app tests validation main.py
```

机器可读 DXF 验证：

```powershell
python validation/validate_dxf.py `
  --input output/output.dxf `
  --output output/output.validation.json
```

验证器检查 DXF audit、`LINE`、`CIRCLE`、`TEXT`、`IMAGE`、空几何、非有限坐标、零长度线、重复实体、图层、边界和拓扑指标。其他未声明的模型空间实体仍会导致验证失败。

## 技术边界

- 严重折叠、局部波浪和复杂非刚性形变无法通过单一透视变换恢复；
- 文字保护可能误判极小结构线，因此必须对照扫描底图人工复核；
- OCR 不能保证中文、尺寸、符号和标点正确；
- Hough/LSD 仍从图像证据产生候选，粗线中心化不是墙体语义恢复；
- 开放线、轴线和标注线可能合法存在，“悬空端点”只是复核指标；
- 圆弧、复杂曲线、块、标注关联和建筑符号仍未可靠恢复；
- 图层分类、HATCH、闭合关系和最终端点吸附仍需人工检查；
- 没有真实扫描件、原始 CAD 标准答案和明确误差阈值时，不能宣称工程精度。
