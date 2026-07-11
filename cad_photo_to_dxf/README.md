# CAD Photo to Editable DXF

Windows/Python 桌面工具，用于把打印图纸照片中的直线转换为可独立编辑的 DXF `LINE` 实体。

## 产品边界

当前版本是半自动纸面直线矢量化工具，不是原始 CAD 恢复器。

可以合理使用于：

- 从 JPG/PNG 中提取可编辑直线；
- 自动或手动确认纸张四角并做透视校正；
- 对直线进行吸附、共线合并、最终去重和基础图层分类；
- 输出 DXF R2010、预览图、处理报告和几何谱系；
- 对导出的 DXF 执行结构、重复、零长度和拓扑诊断验证。

当前不能保证：

- 恢复原始 DWG、约束、块、图层语义或设计历史；
- 从打印纸宽度自动推导工程设计尺寸；
- 恢复圆、圆弧、文字、尺寸标注和建筑符号为可靠 CAD 实体；
- 生成闭合、可直接制造或施工的拓扑；
- 处理纸张折皱、波浪等需要非刚性局部展平的形变；
- 在未经人工复核时稳定处理任意手机照片。

这些未承诺能力属于后续路线图，不应被描述为当前版本已经实现后又发生回归。

## 坐标模式

导出报告中的 `coordinate_mode` 是强制字段：

| 模式 | 含义 | DXF 单位 |
|---|---|---|
| `pixel_units` | 未校准图像坐标 | 无单位 |
| `paper_mm` | 打印纸面上的毫米坐标 | mm |
| `model_mm` | 由已知设计尺寸校准的模型坐标 | mm |

`paper_mm` 不是工程模型真实尺寸。只有输入图纸比例或在图中选取两点并输入已知设计长度后，才能进入 `model_mm`。即使进入 `model_mm`，也必须使用第二个独立尺寸复核。

## 安装与运行

要求 Python 3.11。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

GUI 处理顺序为：

```text
导入 → 确认纸张四角/透视 → 预处理 → 识别与清理 → 尺寸校准 → 导出
```

没有确认透视校正时，GUI 会阻止预处理和识别，不再把原始照片静默当作校正结果。

## 自动纸张识别

自动候选必须同时满足面积、凸四边形、矩形度、纸张内部与外部背景对比、边界位置和可选纸张长宽比条件。低于最低置信度的候选会失败，用户必须手动点击四角。

严格模式表示“低置信度时失败”，不表示算法可以可靠识别所有真实纸张。

## CLI

严格处理示例：

```powershell
python main.py --headless `
  --input samples/test.jpg `
  --output output/result.dxf `
  --preview output/preview.png `
  --report output/report.json `
  --paper-size A4 `
  --paper-orientation landscape
```

允许未校正原图继续处理：

```powershell
python main.py --headless --input input.jpg --allow-uncorrected
```

此模式会在报告中记录警告，且不能宣称透视或尺寸可靠。

常用参数：

- `--paper-size`：`UNKNOWN/A0/A1/A2/A3/A4/LETTER/LEGAL`；
- `--paper-orientation`：`auto/portrait/landscape`；
- `--paper-width-mm`、`--paper-height-mm`：自定义纸张；
- `--min-line-length`：参考分辨率下的最小线长；
- `--threshold-strength`：二值化强度；
- `--no-hatch`：只删除高置信度填充线；
- `--auxiliary`：输出圆和符号候选供人工复核；
- `--ocr`：启用可选 OCR 候选；
- `--debug-dir`：保存处理阶段图；
- `--allow-empty`：允许空 DXF。

## 分辨率处理

检线和几何清理的像素阈值会按输入长边或图形坐标范围相对缩放。处理报告同时记录用户参数、实际有效参数和分辨率系数。

这只能降低分辨率差异，不能保证不同相机、压缩、线宽和光照条件得到完全相同的几何。

## 粗线处理

Hough 和 LSD 只提供候选证据。边缘候选会沿法向搜索距离变换脊线并尝试移动到印刷笔画中心，再由后续共线合并和去重处理。

该步骤不把所有相邻平行线强制合并，因为两条线可能是真实墙体边界，而不是同一粗线的双边。

## 取消行为

GUI 支持取消处理，并在 Python 循环和各原生调用前后检查取消状态。OpenCV 或 OCR 的单次原生调用正在执行时不能被线程安全地强制终止；取消会在该调用返回后生效。

因此当前版本没有宣称实现“立即强杀任意原生调用”。需要进程隔离和强制终止的取消机制属于后续路线图。

## 导出验证

每次 `export_dxf()` 后都会重新打开文件并记录：

- ezdxf audit 错误和自动修复数量；
- LINE 实体数量；
- 非有限坐标；
- 零长度实体；
- 完全或容差重复实体；
- 唯一端点和悬空端点数量；
- 连通、开放和简单闭合组件；
- 近距离未连接端点；
- 未分割交叉点和检查上限状态。

默认结构通过条件是：audit 错误为 0、audit 自动修复为 0、非法坐标为 0、零长度为 0、重复实体为 0。悬空端点、近断点和开放组件只作为诊断指标，因为轴线、标注线和局部线可能有意开放。

独立验证：

```powershell
python scripts/validate_dxf.py output/result.dxf `
  --output output/result.validation.json
```

可选 FreeCAD 验证：

```powershell
python scripts/validate_dxf.py output/result.dxf `
  --freecad-command "C:\Program Files\FreeCAD 1.0\bin\FreeCADCmd.exe" `
  --output output/result.validation.json
```

没有实际执行 FreeCAD 时，报告不能写成“FreeCAD 已验证”。CI 和发布门禁使用固定 Ubuntu 22.04 环境中的 `freecad=0.19.2+dfsg1-3ubuntu1`，并记录提交、输入、DXF、报告和验证文件的 SHA-256。

## 测试

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall -q app scripts main.py
```

真实图片验收必须遵守 [`tests/fixtures/README.md`](tests/fixtures/README.md)。现有 `samples/test.jpg` 仅用于烟雾测试，缺少原始 CAD、来源许可和设计尺寸，不能作为精度证据。

普通 CI 会验证所有已存在夹具的清单。正式发布还会要求完整真实照片类别覆盖，并运行候选 DXF 与 ground truth 的角点、实体、图层、端点、角度、比例和 Hausdorff 误差比较。非纸张负例只有在严格纸张识别阶段被拒绝时才算通过。

## Windows 构建

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
pyinstaller --noconfirm --clean cad_photo_to_dxf.spec
```

应用版本只维护在 `app/version.py`。PyInstaller 资源版本由该值生成；Windows 和发布工作流把同一三段应用版本显式传给 Inno Setup，安装脚本仅在手工构建未传值时回退读取 EXE 文件版本。不要手工维护第二份版本字符串。

Windows 工作流只读仓库内容并上传短期 CI artifact。它不会删除或覆盖 tag、Release 或发布分支。

## 发布要求

正式发布前至少需要：

1. Python 测试、Ruff 和编译检查通过；
2. Windows portable 与安装/卸载烟雾测试通过；
3. DXF 结构验证通过；
4. 固定版本 FreeCAD 导入证据；
5. 真实照片夹具覆盖规定类别并达到声明的误差阈值；
6. 发布物包含 SHA-256、源码 commit 和构建来源；
7. 已存在的 tag 或 Release 必须导致发布失败，禁止先删除再覆盖；
8. GitHub `release` Environment 已配置 required reviewers，且发布作业实际等待审批。

当前没有合格真实照片 ground-truth 数据集，且仓库侧 `release` Environment 审批设置仍需人工确认，因此发布流程应保持阻塞状态。

## 安全与工程使用

处理默认在本机完成。项目不需要上传图纸，也不包含凭据收集或远程控制逻辑。

DXF 能被解析不代表几何正确。用于制造、施工、报价或尺寸交付前，必须由具备相应资质的人员在 CAD 软件中复核比例、尺寸、重复、缺口、交点和闭合轮廓。
