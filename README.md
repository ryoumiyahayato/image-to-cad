# Image-to-CAD — 扫描图纸 → 可编辑的二维 CAD

> **研发预览：0.3.0-dev · 尚未达到产品验收条件（LOCAL_NO_GO）。**
> 当前开发目标是把图片／扫描 PDF 中的图纸内容重建成**完整、可独立选择和修改的原生 CAD 对象**，而非像素描摹或 HATCH 拼贴。

**[当前权威设计与验收基准](docs/project/NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)** · [真实研发状态](docs/project/PROJECT_STATUS.md) · [当前任务](docs/project/CURRENT_TASK.md) · [下一步](docs/project/NEXT_TASK.md) · [Agent 执行协议](docs/project/AGENT_OPERATING_PROTOCOL.md)

## 产品要交付什么

用户选择图片、TIFF 或 PDF 的页面/区域，软件在保留原图证据的前提下，尽量重建为原生 LINE、ARC、LWPOLYLINE、TEXT/MTEXT、INSERT/BLOCK 等合理完整的对象，最终导出 DXF。对象能独立删除、移动、改形状或改文字，且不留下不合理碎片、不损伤邻近图形。

有来源证据才画；模糊且无法确认的内容在正式结果中留白并定位待修，原图作为独立参考保留。不允许以填色 HATCH、逐像素小线段、伪文字或整页底图冒充完成重建。文字内容、房号框、多行注释、门洞、墙线、连接关系、符号框和实例隔离都必须按对象或对象组验证。

**扫描锯齿逐像素相等不是产品成功标准。** 但也绝不允许漏掉真实标注、封闭真实开口、捏造数字、错接线路或删除真实短线。像素覆盖、诊断渲染与单项测试不能替代最终对象质量、CAD 编辑和人工劳动证明。

## 已实现与未实现，不能混为一谈

| 范围 | 当前可确认事实 | 仍不成立的承诺 |
| --- | --- | --- |
| 公开 main | 保留 0.3.0-dev 既有 GUI、扫描/PDF 处理与 DXF 基础设施，以及早期测试和隔离研究 | 公开 main **不等于** 已包含 11 月 17—20 日所有私有实验 |
| 独立研发（尚未合并） | 一些真实输入已生成原生 LINE、真 TEXT/MTEXT、闭合房号框、门 INSERT、可编辑路径；有保存冷读、来源核对、Linux GUI 与后台任务的有限证据 | 私有v8.4已出一份完整区域DXF，但完整内容、文字/交汇、CAD兼容和工程师省时验收仍是 **LOCAL_NO_GO** |
| 桌面产品 | Linux 上的源码原型已在有限范围内运行；仓库已有部分 Windows 相关设施和历史检查 | **未有基于最新原生重建流程的、干净 Windows 环境实测通过的 EXE/安装器** |
| 移动与文件格式 | DXF 是首要交付格式；Android 可作为待验证目标 | 当前无已验收的 APK、DWG 全流程往返或 Android 实测性能结果 |

**不要用私有研究包中的成果数量当作已发布的软件能力。** 每项都需真实进入当前正式入口并重新检查。旧研究失败证据与原始文件继续保留；旧研究方案不再决定当前产品优先级。

## 当前最重要的质量问题

冻结对象：A2-SG-008.tiff 的连续四分之一区域，原像素裁框 `[1400,1000,5000,3411]`。固定反例包括房号 `210`、完整三行 `DN. TO / LIGHTS ON / 1ST FLOOR`、`EBB-3`、完整墙与门、交叉连接和真实短划。

私有v8.4已实际完成同一固定区域的正式执行链和主DXF，并完成295项去向及LibreCAD八项普通编辑/退出重开；仍未通过完整内容验收。R1/R2旧逻辑缺陷已在私有版本修复，不重复作为新任务。当前优先：PANTRY和完整墙组退化、完整连接与交汇（含C07/C08）、i/I/1冲突与标签后缀；同时将实际源码迁入持续研发分支。公开main能力仍按下方入口和[项目状态](docs/project/PROJECT_STATUS.md)判断。

正式工程师验收仍需：无须清理无意义碎线或填色垃圾，所有漏项补绘、纠错及核对计入人工修图时间，人工修图用时 **≤ 同范围、同质量从零重画时间的 50%**。未有真实计时，不能宣布通过。

## 运行和开发

本仓库的历史应用源码位于 `cad_photo_to_dxf/`。在兼容环境下按既有 `requirements.txt` 和 `main.py` 启动原有 GUI；具体解释器、OCR、Qt、字体与操作系统要求以**当前代码和对应功能的实测记录**为准。不要把原有 GUI 的启动命令当成最新隔离研发包能够独立安装/使用的保证。

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

历史仅支持部分原生矢量 PDF 的独立工具仍见 [native-first 工具说明](tools/native_first/README_ZH.md)，**不代表扫描图纸已经重建完成**。

### 当前入口和默认构建的边界

GUI 与 CLI 仍调用 `ProductionProcessingService.process_page`，使用已保留的 `FinalStructure` 和 DXF serializer。最新私有 `app/native_objects` 研究尚未迁入这个公开入口；界面、CLI 帮助和导出报告明确标为 `LOCAL_NO_GO / preserved_main_baseline`，不得按目标规范倒推实现已经完成。

当前保留基线把单页和多页 GUI 的默认保存格式统一为 **DXF**；DWG 仍须显式选择外部转换器，未取得产品往返验收。默认打包继续使用同一公开入口，同时携带当前产品基准和状态。`0.3.0-dev` 或未达到 GO 的版本不能通过正式 Release 发布门禁；开发构建仍可运行。

## 状态、历史与代码合入

- 项目当前版本仍为 `0.3.0-dev`，暂不宣称正式发布。
- 研究、产品源码、私有原图与可公开文档分层管理。与新设计冲突的旧路线转历史或标记 SUPERSEDED，不再作为默认开发任务。
- 历史清理已关闭#38/#39、删除7条冗余分支和11个重复/空文件，见[当时执行账本](docs/project/CLEANUP_EXECUTED_20261120.md)。#41包含#40，是唯一清理合并入口；维护合并不代表产品发布。当前删除/保留及恢复规则见[G1收口记录](docs/project/G1_CLOSEOUT_20261120.md)。
- 原版长期意图备忘录、旧研究与工程证据可供历史追溯，但**当前产品契约**由 [2026-11-20 基准](docs/project/NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md) 定义。
- 无论独立研究输出多漂亮，都必须在最终保存 DXF 中核对，并经过目标 CAD 的打开、编辑、保存和重开。未测即 NOT_RUN。

