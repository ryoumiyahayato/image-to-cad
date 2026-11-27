# Image to CAD — 纯图像／PDF 转可编辑二维 CAD

**当前版本 `0.4.0-dev`（开发基座阶段）。** 主攻**无矢量信息的纯图像、扫描件和照片**到可编辑二维 CAD（DXF）的完整重建；原生矢量 PDF 解析作为附带快车道工具提供。

完整产品构想与三层架构定义见 [产品意图与知识包指南](docs/project/PRODUCT_INTENT_AND_KNOWLEDGE_PACKS_ZH.md) · [三层架构蓝图与防跑偏路线图](docs/project/ARCHITECTURE_AND_ROADMAP_ZH.md) · [Agent 工作入口](AGENTS.md) · [执行协议](docs/project/AGENT_OPERATING_PROTOCOL.md) · [验收标准](docs/project/ACCEPTANCE_GATES.md)。

---

## 不可退回的产品要求（既有标准）

质量与实际人工劳动节省优先于转换速度；不以“系统理解工程语义”为先决条件。新算法、工具或模型接入均不得降低以下任何一条红线：

| 内容用途 | 必需能力 | 严禁作为替代的结果 |
| --- | --- | --- |
| **表格、图签、编号、数值、中英文正文与说明** | 内容正确的原生 `TEXT`/`MTEXT`；可改单字、改整串并整体移动；合理可读替代字体、字号、字间距、对齐与单元格布局 | 仅保留字形轮廓、拆成单字 `TEXT`、把笔画编为 `GROUP`、或只提供默认关闭的候选文字 |
| **Logo、设计集团标志、签名、印章等非编辑背景** | 单独划定归属并与正文隔离，以可靠原生几何或独立透明 `IMAGE` 保真且默认受保护，随 DXF 交付资源 | 将 Logo/签名当正文 OCR 成字母、拆坏标志、改字时误删背景；**禁止用整页底图或残余墨迹图片掩盖内容缺失** |
| **圈内 R、方框设备符号等复合工程图案** | 保留外框、内部字符、相对位置及必要连接关系，按实际操作需要成组／成块 | 只输出字母丢掉外框，或拆成大量碎片难以选中编辑 |
| **普通线、圆弧、轮廓、填充、表格边框** | 使用单根中心线原生实体（`LINE`、`ARC`、`CIRCLE`、`LWPOLYLINE`、`HATCH`），保持真实开口、线宽档位与交点 | 双侧空心像素轮廓圈、`HATCH` 涂色像素拼贴、重复重叠线段、跨越真实白缝的误桥接 |
| **残缺、模糊、难以判读区域** | 保留实际可见证据，在可一键关闭的 `SUGGEST_REPAIR` 层输出带来源与不确定标记的可编辑／可撤销补绘建议 | 直接留白丢弃或全页无约束桥接，以及用自然外观冒充已观察事实或猜改工程数值 |

- **“可编辑”验证**：必须通过真实 CAD 软件（AutoCAD / 中望 / 浩辰 / LibreCAD）中**改单字、移动、删除、保存、完全退出并重新打开**核实。改字后不得残留旧字笔画，不得切断或误改邻近表框、文字与受保护背景。
- **字形原则**：允许使用合理替代字体（如 Noto Sans CJK / `wqy-unicode`），不以像素级复刻原图特殊字体作为核心门槛。

---

## 核心三层架构（开发方向）

工程制图在逻辑层存在确定解，但扫描件在交叉口与粘连处存在像素级多解。项目唯一认可的架构为**三层协同流水线**（详情见 [ARCHITECTURE_AND_ROADMAP_ZH.md](docs/project/ARCHITECTURE_AND_ROADMAP_ZH.md)）：

1. **第 1 层 · 高召回非学习机械提取层**：扫描去污与透视校正 → 签章/Logo 分离 → 中英文整行 OCR 与紧凑字形擦除（保护长格线）→ 单像素骨架「节点—边链」拓扑与竞争多解候选。
2. **第 2 层 · 机器可执行制图知识包 + 学习/模型中央总控决策层**：将人类绘图语法写成可执行算子（跨交点贯通、正交与交点吸附、表框闭合、字线分离、复合符号成组、线宽归一化），由总控结合局部切片消解第 1 层多解并产出正式实体与 `SUGGEST_REPAIR` 建议。
3. **第 3 层 · 独立全页双向残差分析质检层**：关闭一切参考底图与残余图像，重渲染输出 DXF 与原图做全页正向漏画／反向误画比对，联合可编辑性往返测试守门。

---

## 当前代码状态与已知缺口（`0.4.0-dev`）

当前主线仅完成了**代码清场与桌面／命令行基础入口贯通**（共享入口 `cad_photo_to_dxf/app/core/conversion.py`），**距离完整三层架构与“人工修图耗时 ≤ 从零手画 50%”仍有重大差距**：

- **已接通基础部件**：
  - 扫描清理（`app/geometry/scan_cleanup.py`）、透视校正（`app/core/perspective.py`）、单像素骨架基础几何提取（`app/geometry/scan_geometry.py`）、离线 RapidOCR 中英文整行识别（`app/ocr/line_recognition.py`）、签名形态初筛与人工框选保护（`app/ocr/signature_overlay.py`）、中文字体准备（`app/export/product_fonts.py`）、PySide6 桌面端与 PyInstaller Windows 打包脚本，以及附带的矢量 PDF 原生路径提取（`app/core/pdf_conversion.py`）。
- **必须优先修复的 2 处代码缺陷**：
  1. **残余图像遮羞问题**：`app/core/scan_conversion.py` 当前将未拟合墨迹与低置信文字写入默认开启显示的 `REVIEW_SOURCE`（`unresolved-ink.png`），导致渲染预览图掩盖了实际未转换的线条缺口。
  2. **OCR 框涂白切断表线**：`app/core/scan_conversion.py` 当前将整个 `line.quad` 矩形膨胀涂白，会把穿行或紧邻文字的表格线直接啃断。
- **尚未建成的 3 块核心主干**：第 2 层机器可执行知识包算子库、学习/模型中央总控消歧层、第 3 层全页双向残差分析器目前均为 **未实现**。

---

## 运行与开发验证

环境要求：Python 3.11+。

### 1. 准备资源与启动应用（在 `cad_photo_to_dxf/` 目录）

```powershell
cd cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/prepare_cad_fonts.py
python scripts/prepare_ocr_models.py
python main.py
```

### 2. 命令行调用（与桌面共用 `app/core/conversion.py`）

```powershell
# 扫描图／照片转换（可选 --perspective 开启纸张透视校正）
python main.py --input scan.png --dpi 300 --perspective --output output/scan.dxf

# 手动框选保护黑白 Logo／签章区域（像素坐标 x0 y0 x1 y1）
python main.py --input scan.png --preserve-region 100 200 450 350 --output output/scan.dxf

# 按已知比例导出（例如 1:100 输入 100；未知比例默认纸面毫米）
python main.py --input drawing.pdf --page 1 --scale 100 --output output/page1.dxf

# 为当前用户安装 Noto CJK 系统字体及 LibreCAD 文泉驿字体
python main.py --install-cad-fonts
```

分发送达 DXF 时需保留同目录下的 `fonts/` 与 `<文件名>_assets/`（或原生 PDF 产生的 `<文件名>_images/`）依赖目录。附带矢量 PDF 单页命令行见 [tools/native_first/README_ZH.md](tools/native_first/README_ZH.md)。

### 3. 本地检查与构建

```powershell
cd cad_photo_to_dxf
python -m pip install -r requirements-test.txt
python -m ruff check app tests scripts main.py ../tools/native_first
python -m pytest tests ../tools/native_first/tests -q
python scripts/product_smoke.py --source-main main.py --work ./smoke-output
```

Windows 打包需安装 `requirements-dev.txt` 后执行 `python -m PyInstaller --noconfirm cad_photo_to_dxf.spec`，安装包配置位于 `cad_photo_to_dxf/installer/cad_photo_to_dxf.iss`。
