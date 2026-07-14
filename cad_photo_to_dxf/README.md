# 纸质 CAD 图纸照片转可编辑 DXF v1.1.0

这是一个半自动纸面矢量化工具：导入手机拍摄或扫描的纸质图纸，人工确认纸张边界、尺度和语义候选后，导出可编辑的 DXF `LINE`，以及经过置信度门槛和人工确认的 `CIRCLE`。

它不是原始 CAD 恢复器。它不会自动恢复 DWG 约束、块、标注关联、设计意图或可靠工程尺寸，也不能在未经人工复核时用于制造、施工和尺寸交付。

## 坐标模式

报告和界面明确区分三种坐标空间：

- `pixel`：尚未校准的图像坐标；DXF 声明为无单位，1 px 对应 1 个无单位图形单位；
- `paper_mm`：根据已接受的纸张透视边界得到的纸面毫米坐标；
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
5. 未确认透视时，GUI 会阻止预处理、识别和导出。
6. 重新自动校正会先失效旧校正图、旧比例、旧几何和旧人工确认，避免失败后继续导出旧结果。
7. 检查灰度、去噪、去阴影、对比度、阈值和清噪阶段。
8. 执行共享矢量化管线：检线、粗线中心化、几何清理、最终去重、交点分割、拓扑检查和图层分类。
9. 在“人工复核图层”中逐条确认或修改启发式图层；修改会保留自动分类理由和人工覆盖历史。
10. 启用辅助识别后，可在“人工确认圆形”中查看达到置信度阈值的圆形候选。所有候选默认不导出，必须逐项勾选后才会写入 DXF `CIRCLE`。
11. 检查预览、图层数量、警告、悬空端点和小间隙。
12. 明确选择或复核 `pixel`、`paper_mm` 或 `model_mm` 尺度。
13. 导出 DXF；同目录生成统一 `.report.json`。

修改纸张、阈值、检线、吸附、分类或 HATCH 参数后，旧结果和已确认圆形会失效，必须重新处理并重新确认。

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

- `--min-line-length`：必须是大于 0 的整数；
- `--paper-size`：`A0`～`A4`、`LETTER`、`LEGAL` 或 `UNKNOWN`；
- `--paper-width-mm`、`--paper-height-mm`：自定义纸张尺寸，必须同时提供，并且必须是有限正数；
- `--paper-orientation`：`auto`、`portrait` 或 `landscape`；
- `--allow-uncorrected`：纸张识别失败或候选置信度不足时保留原图继续处理，不应用可疑透视，也不自动生成 `paper_mm`；
- `--allow-empty`：允许生成 0 条线的空 DXF，仅适合受控调试；正式验证器会拒绝空几何；
- `--no-hatch`：删除高置信度 HATCH；不确定结果保留为 `HATCH_CANDIDATE`；
- `--debug-dir`：输出各预处理阶段图像；
- `--auxiliary`：生成圆形和矩形符号候选；
- `--ocr`：生成文字和尺寸文字候选。

命令行模式不会自动导出圆形。圆形 `CIRCLE` 导出必须经过 GUI 中的人工确认，且导出器会再次执行置信度门槛。

退出码：

- `0`：成功；
- `2`：参数错误；
- `3`：输入不存在、不可用或接近空白；
- `4`：纸张边界或严格置信度校验失败；
- `5`：没有有效几何；
- `130`：合作式取消。

## 处理链

GUI 和 CLI 共用 `PipelineService`：

1. 8 位灰度、单通道、BGR 或 BGRA 输入格式校验；
2. 分辨率归一化预处理；
3. Hough/LSD 直线候选；
4. 保守粗线中心脊线校正；
5. 正交化、吸附、共线合并和去重；
6. 所有坐标修改完成后的最终规范化与再次去重；
7. 交点分割；
8. 端点图和拓扑指标；
9. 图层启发式分类；
10. 人工图层复核，以及可选的高置信度圆形人工确认；
11. DXF 导出；
12. 统一报告。

缓存二值图必须与当前校正图尺寸一致，并通过与新预处理相同的通道和 dtype 校验。固定像素参数优先根据完整校正图长边统一缩放；独立几何工具没有图像上下文时才回退到线段跨度。默认一像素细线去噪保持关闭。

## 报告

GUI 和 CLI 均通过 `ReportBuilder` 生成 schema `1.3`，包含：

- 应用版本、开始时间和运行时长；
- 输入路径和图像尺寸；
- 自动/手工角点、候选是否检测、是否应用、是否因低置信度被拒绝，以及相关警告；
- 图像质量；
- 全部处理参数和实际分辨率倍率；
- 原始检测线、最终实体和源线谱系；
- 正交化、吸附、合并、过滤和最终去重数量；
- 交点分割、完全/近似重复、悬空端点、小间隙、连接分量和闭合/开放分量；
- 自动图层理由和人工图层覆盖历史；
- 辅助候选、人工确认圆形的中心、半径、置信度和实际导出数量；
- `pixel`、`paper_mm` 或 `model_mm` 坐标模式；
- 未校准时 `mm_per_pixel` 为 `null`，另以 `drawing_units_per_pixel` 记录无单位换算。

报告通过唯一临时文件原子写入，避免并发进程共享同一个临时文件名。

## 图层

- `OUTLINE`：长粗外轮廓候选；
- `WALL_OR_FRAME`：正交墙体或框架候选；
- `GRID_OR_AXIS`：长细轴线候选；
- `HATCH`：高置信度填充线；
- `HATCH_CANDIDATE`：证据不足的疑似填充；
- `DETAIL`：其他线条；
- `CIRCLE_CONFIRMED`：达到门槛并由用户逐项确认的圆形实体。

除 `CIRCLE_CONFIRMED` 的几何类型和人工确认事实外，其他图层名称仍属于启发式分类，不代表已经恢复设计语义。

## 验证

运行单元测试、静态检查、首轮核心类型检查和语法编译：

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m ruff check app tests validation main.py
python -m mypy app/resolution.py app/scale_calibrator.py app/reporting.py app/auxiliary_recognition.py
python -m compileall -q app tests validation main.py
```

生成机器可读 DXF 验证证据：

```powershell
python validation/validate_dxf.py `
  --input output/output.dxf `
  --output output/output.validation.json
```

验证器会检查 `ezdxf` audit、LINE/CIRCLE 数量、实体类型、空几何、非有限坐标、零长度线、非正圆半径、完全重复、图层、边界和拓扑指标。空 DXF 或出现产品未声明的模型空间实体类型会失败。

在安装 FreeCAD 的环境中执行独立导入：

```powershell
FreeCADCmd validation/freecad_import_check.py `
  --input output/output.dxf `
  --output output/output.freecad.json
```

FreeCAD 脚本记录 FreeCAD 版本、输入 SHA-256、导入对象和非空 Shape 数量。只有至少一个对象包含非空几何才判成功。脚本存在不等于已经通过；正式发布必须保留实际成功的 JSON 证据。

## Windows 构建与发布

Windows PR 工作流执行：

1. pytest、Ruff、核心 mypy 和 compileall；
2. PyInstaller 便携版构建与冒烟测试；
3. Inno Setup 安装器构建；
4. 安装、启动和卸载冒烟测试；
5. 上传按应用版本命名的产物。

正式 Release 只允许通过 `v*` tag 触发：

- tag 必须与 `app.__version__` 一致；
- 只读 `build` job 构建、测试并上传经过验证的产物；
- 只有依赖 build 成功、并通过 `production-release` Environment 审批的 `publish` job 获得 `contents: write`；
- 已存在 Release 时失败，不删除或覆盖；
- 发布资产生成 SHA-256；
- 发布目标固定为触发 tag 的精确提交。

仓库管理员必须在 GitHub 中配置 `production-release` Environment 的人工审批保护，否则引用该 Environment 本身不会自动产生审批门槛。

## 技术边界

- 严重折叠、局部波浪和复杂非刚性形变无法通过单一透视变换恢复；
- Hough/LSD 仍从图像证据产生候选，粗线中心化不是墙体语义恢复；
- 开放线、轴线和标注线可能合法存在，因此“悬空端点”是复核指标而非自动错误判定；
- 只有达到阈值并经人工确认的完整圆形可导出为 `CIRCLE`；圆弧、文字、尺寸关联和建筑符号仍是辅助候选；
- 图层分类、HATCH、闭合关系和最终端点吸附仍需人工检查；
- 没有真实手机照片、原始 CAD ground truth 和明确误差阈值时，不能宣称工程精度；
- Git 历史中的大文件清理属于独立仓库治理任务。

整改进度和未完成事项见 [`../docs/AUDIT_REMEDIATION.md`](../docs/AUDIT_REMEDIATION.md)。
