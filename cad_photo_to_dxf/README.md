# 纸质 CAD 图纸照片转可编辑 DXF v1.1.0

这是一个半自动纸面矢量化工具：导入手机拍摄或扫描的纸质图纸，人工确认纸张边界和尺度后，提取可编辑的 DXF `LINE` 几何候选。

它不是原始 CAD 恢复器。它不会自动恢复 DWG 约束、块、标注关联、设计意图或可靠工程尺寸，也不能在未经人工复核时用于制造、施工和尺寸交付。

## 坐标模式

报告和界面明确区分三种坐标空间：

- `pixel`：尚未校准的图像坐标；
- `paper_mm`：根据打印纸外边界得到的纸面毫米坐标；
- `model_mm`：通过图纸比例或已知实际尺寸进行独立人工校准后的模型坐标。

纸面 A4 宽约 297 mm，并不表示图中标注为 12000 的对象已经恢复为 12000 mm。没有独立模型尺度校准时，不得把 `paper_mm` 解释为工程真实尺寸。

## 环境与安装

- Windows 10/11、macOS 或 Linux；
- Python 3.11；
- Windows GUI/安装包为主要发布目标。

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

`pytesseract` 仍要求系统另行安装 Tesseract。OCR 结果只进入辅助报告，不自动写入 DXF 主体。

## GUI 作业流程

1. 导入 JPG、JPEG 或 PNG。
2. 选择纸张规格和方向。
3. 执行自动纸张识别，或手工点击纸张外边缘四角。
4. 自动候选低于严格置信度阈值时，必须手工确认四角。
5. 未确认透视时，GUI 会阻止预处理、识别和导出，不会再把原图静默当成校正图。
6. 检查灰度、去噪、去阴影、对比度、阈值和清噪阶段。
7. 执行共享矢量化管线：检线、粗线中心化、几何清理、最终去重、交点分割、拓扑检查和图层分类。
8. 检查预览、图层数量、警告、悬空端点和小间隙。
9. 明确选择或复核 `paper_mm` / `model_mm` 尺度。
10. 导出 DXF；同目录生成统一 `.report.json`。

修改纸张、阈值、检线、吸附、分类或 HATCH 参数后，旧结果会失效，必须重新处理。

## 命令行

默认采用严格模式：无法可靠识别纸张或没有有效线时返回非零退出码。

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

- `--paper-size`：`A0`～`A4`、`LETTER`、`LEGAL` 或 `UNKNOWN`；
- `--paper-width-mm`、`--paper-height-mm`：自定义纸张尺寸，必须同时提供；
- `--paper-orientation`：`auto`、`portrait` 或 `landscape`；
- `--allow-uncorrected`：显式允许纸张识别失败后使用原图，仅适合受控测试；
- `--allow-empty`：允许生成 0 条线的空 DXF；
- `--no-hatch`：删除高置信度 HATCH；不确定结果保留为 `HATCH_CANDIDATE`；
- `--debug-dir`：输出各预处理阶段图像；
- `--auxiliary`：生成圆和矩形符号候选；
- `--ocr`：生成文字和尺寸文字候选。

退出码：

- `0`：成功；
- `2`：参数错误；
- `3`：输入不存在、不可用或接近空白；
- `4`：纸张边界或严格置信度校验失败；
- `5`：没有有效几何；
- `130`：合作式取消。

## 处理链

GUI 和 CLI 共用 `PipelineService`：

1. 分辨率归一化预处理；
2. Hough/LSD 直线候选；
3. 保守粗线中心脊线校正；
4. 正交化、吸附、共线合并和去重；
5. 所有坐标修改完成后的最终规范化与再次去重；
6. 交点分割；
7. 端点图和拓扑指标；
8. 图层启发式分类；
9. DXF 导出；
10. 统一报告。

固定像素参数会根据图像长边或图形尺度统一缩放。默认一像素细线去噪保持关闭，不会因高分辨率自动启用中值滤波。

## 报告

GUI 和 CLI 均通过 `ReportBuilder` 生成同一结构，包含：

- 应用版本、开始时间和运行时长；
- 输入路径和图像尺寸；
- 自动/手工角点、置信度、目标纸张比例和警告；
- 图像质量；
- 全部处理参数和实际分辨率倍率；
- 原始检测线、最终实体和源线谱系；
- 正交化、吸附、合并、过滤和最终去重数量；
- 交点分割、完全/近似重复、悬空端点、小间隙、连接分量和闭合/开放分量；
- 图层、辅助候选和导出结果；
- `pixel`、`paper_mm` 或 `model_mm` 坐标模式。

## 图层

- `OUTLINE`：长粗外轮廓候选；
- `WALL_OR_FRAME`：正交墙体或框架候选；
- `GRID_OR_AXIS`：长细轴线候选；
- `HATCH`：高置信度填充线；
- `HATCH_CANDIDATE`：证据不足的疑似填充；
- `DETAIL`：其他线条。

这些标签属于启发式分类，不是确定 CAD 语义。导出后仍需人工确认。

## 验证

运行单元测试和静态检查：

```powershell
python -m pytest -q
python -m ruff check app tests validation main.py
python -m compileall -q app tests validation main.py
```

生成机器可读 DXF 验证证据：

```powershell
python validation/validate_dxf.py `
  --input output/output.dxf `
  --output output/output.validation.json
```

该脚本检查 `ezdxf` audit、非有限坐标、零长度、完全重复、图层、边界和拓扑指标。

在安装 FreeCAD 的环境中执行独立导入：

```powershell
FreeCADCmd validation/freecad_import_check.py `
  --input output/output.dxf `
  --output output/output.freecad.json
```

FreeCAD 脚本记录 FreeCAD 版本、输入 SHA-256、导入对象、错误和清理结果。脚本存在不等于已经通过；正式发布必须保留实际成功的 JSON 证据。

## Windows 构建

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
pyinstaller --noconfirm --clean cad_photo_to_dxf.spec
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows_smoke.ps1 `
  -Executable .\dist\CADPhotoToDXF\CADPhotoToDXF.exe `
  -Sample .\samples\test.jpg `
  -WorkingDirectory "$env:TEMP\cad-photo-portable-smoke"
```

安装器版本从 `app.__version__` 注入 Inno Setup，不再单独硬编码。

## 发布

正式 Release 只允许通过 `v*` tag 触发：

- tag 必须与 `app.__version__` 一致；
- 构建精确 tag 提交；
- 普通 CI 只读；
- 已存在 Release 时失败，不删除或覆盖；
- 发布资产生成 SHA-256；
- 工作流引用 `production-release` Environment。

仓库管理员必须在 GitHub 中配置该 Environment 的人工审批保护，否则工作流引用本身不会自动产生审批门槛。

## 技术边界

- 严重折叠、局部波浪和复杂非刚性形变无法通过单一透视变换恢复；
- Hough/LSD 仍从图像证据产生候选，粗线中心化不是墙体语义恢复；
- 开放线、轴线和标注线可能合法存在，因此“悬空端点”是复核指标而非自动错误判定；
- 圆、圆弧、文字、尺寸和建筑符号仍是辅助候选；
- 图层分类、HATCH 和闭合关系仍需人工检查；
- 没有真实手机照片、原始 CAD ground truth 和明确误差阈值时，不能宣称工程精度；
- 当前索引和 Git 历史中的构建产物清理属于独立仓库治理任务。

整改进度和未完成事项见 [`../docs/AUDIT_REMEDIATION.md`](../docs/AUDIT_REMEDIATION.md)。
