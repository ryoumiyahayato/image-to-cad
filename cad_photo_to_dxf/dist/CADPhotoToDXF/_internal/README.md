# 纸质 CAD 图纸照片转可编辑 DXF v1.1

这是一个半自动图纸矢量化工具：导入手机拍摄的纸质 CAD 图纸，完成纸张校正、去阴影、二值化、直线检测、基础几何修正、图层分类和比例校准，最终导出 DXF R2010。

它不会恢复原始 DWG，也不会把概率性的 OCR、圆弧或建筑符号候选直接写入 DXF 主体。

## 环境与安装

- Windows 10/11、macOS 或 Linux
- Python 3.11 或更高版本

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

可选 OCR：

```powershell
pip install -r requirements-ocr.txt
```

`pytesseract` 仍要求系统另行安装 Tesseract 可执行程序。OCR 在 v1.1 中只进入辅助报告。

## GUI 作业流程

1. 导入 JPG、JPEG 或 PNG 原始照片。
2. 选择纸张规格和方向；未知规格只能视为结构模式。
3. 自动识别纸张，或手动点击纸张外边缘四角。
4. 检查透视校正结果；纸张规格会约束目标长宽比。
5. 执行图像预处理，在“预处理阶段”页检查灰度、去噪、去阴影、对比度、阈值和清噪结果。
6. 执行线条识别与清理。任务在后台运行，GUI 显示进度并允许请求取消。
7. 检查识别预览和各图层数量。
8. 已知纸张规格时比例由纸张外边界推导；仍建议用图内已知尺寸复核或重新两点校准。
9. 导出 DXF；同目录会生成 `.report.json`，包含参数、阶段修改数量和完整线段谱系。

修改二值化、检线、吸附、分类或 HATCH 参数后，旧识别结果会自动失效，必须重新处理后才能导出。

## 命令行

v1.1 默认采用严格模式：无法识别纸张或没有有效线时返回非零退出码。

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

重要参数：

- `--paper-size`：`A0`～`A4`、`LETTER`、`LEGAL` 或 `UNKNOWN`。
- `--paper-width-mm`、`--paper-height-mm`：自定义纸张尺寸，必须同时提供。
- `--paper-orientation`：`auto`、`portrait` 或 `landscape`。
- `--allow-uncorrected`：纸张识别失败后仍按原图处理。
- `--allow-empty`：允许生成 0 条线的空 DXF。
- `--no-hatch`：只删除高置信度 HATCH；不确定对象保留在 `HATCH_CANDIDATE`。
- `--debug-dir`：输出每个预处理算子的图像。
- `--auxiliary`：生成圆和矩形符号辅助候选。
- `--ocr`：调用可选 OCR，并把文字和尺寸文字候选写入报告。

退出码：

- `0`：成功。
- `2`：参数错误。
- `3`：输入不存在、不可用或接近空白。
- `4`：纸张边界识别失败。
- `5`：没有有效线实体。
- `130`：合作式取消。

## 报告与谱系

JSON 报告包含：

- 软件和报告模式版本。
- 输入、校正角点、置信度和目标纸张比例。
- 图像质量、阴影和折叠风险。
- 全部处理参数及逐算子调试文件。
- 原始检测线数量、几何阶段修改数量和图层数量。
- 每个 `HOUGH-*`、`LSD-*` 原始源线到最终 `LINE-*` 实体的映射。
- 被过滤源线、合并操作和最终实体坐标。
- 圆、OCR、尺寸文字和矩形符号辅助候选。
- 导出比例、实体数量和警告。

## 图层

- `OUTLINE`：明确的长粗线。
- `WALL_OR_FRAME`：正交的中长墙体或框架线。
- `GRID_OR_AXIS`：长而较细的轴线。
- `HATCH`：高置信度、间距规律且具有保守封闭边界支持的填充线。
- `HATCH_CANDIDATE`：疑似填充但封闭关系或其他证据不足。
- `DETAIL`：其他线条。

## 参数注意事项

- 二值化强度过大可能删除浅色细线。
- 最大断线距离过大可能跨越真实门洞。
- 端点吸附采用最大簇直径约束，但仍应检查密集节点。
- 正交容差过大会破坏真实斜线，通常建议 2°～5°。
- 不建议删除 `HATCH_CANDIDATE`；应在 CAD 中关闭或人工检查。
- 纸张比例只能校正整体单应性，不能修复局部波浪。

## 仍然存在的技术边界

- 严重折叠、局部波浪和复杂非刚性形变不能保证整页误差小于 2%。系统会记录风险，不会输出虚假的精度保证。
- 后台取消会在处理阶段和 Python 循环内检查，但不能安全强制中断正在执行的单次 OpenCV 或 OCR 原生调用。
- 线段谱系已覆盖当前 Hough/LSD 原始源线、合并、过滤、分类和最终实体；像素级证据到源线的逐像素谱系不在 v1.1 范围。
- HATCH 综合平行度、间距、长度、线宽、密度和封闭边界；封闭区域包含关系仍采用保守的轴对齐近似。
- GUI 已提供逐算子独立预览页，CLI 可通过 `--debug-dir` 输出全部阶段图像。
- OCR、圆弧、尺寸文字和建筑符号仍是辅助识别结果，不自动进入 DXF 主体。

## 测试

```powershell
python -m unittest discover -s tests -v
```

回归测试覆盖空白图拒绝、四角排序、纸张比例、细线保留、粗线宽度、受限吸附、共享交点、完整谱系、HATCH 防误删、合作式取消、辅助圆检测、JSON 报告和 DXF 审计。

## Windows v1.1 构建和安装包

本地构建：

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
pyinstaller --noconfirm --clean cad_photo_to_dxf.spec
.\scripts\windows_smoke.ps1 `
  -Executable .\dist\CADPhotoToDXF\CADPhotoToDXF.exe `
  -Sample .\samples\test.jpg `
  -WorkingDirectory "$env:TEMP\cad-photo-portable-smoke"
```

安装包由 Inno Setup 配置 `installer/cad_photo_to_dxf.iss` 生成。GitHub Actions 工作流会执行：

1. 安装 Python 3.11 和依赖。
2. 运行回归测试。
3. 使用 PyInstaller 构建便携版。
4. 对便携 EXE 执行无界面转换冒烟测试。
5. 生成 Inno Setup 安装包。
6. 静默安装、启动无界面转换、静默卸载并验证文件清理。
7. 上传便携目录和 `CADPhotoToDXF-1.1.0-Setup.exe`。

旧 v1.0.0 EXE 不包含 v1.1 修改，不能通过替换说明文档升级。正式 v1.1.0 安装包必须由 Windows Runner 或受控 Windows 构建机重新构建，并以工作流的安装、启动和卸载冒烟结果作为发布依据。
