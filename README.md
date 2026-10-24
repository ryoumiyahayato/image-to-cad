# Image to CAD — editable CAD development preview


**Agent 必读：** [产品意图与知识包实施指南](docs/project/PRODUCT_INTENT_AND_KNOWLEDGE_PACKS_ZH.md) · [Agent 执行协议](docs/project/AGENT_OPERATING_PROTOCOL.md)。这份指南记录既有用户要求、设计目标与实现边界，不代表对应能力已全部完成。
当前版本 **0.3.0-dev**。目标仍是内容正确、合理可编辑且显示清楚的二维 CAD，并减少人工核查和修正；质量与人工劳动节省优先于转换速度。

## 不可退回的产品要求（既有标准）

以下是对早期产品要求的重申，不是 2026-10-24 新增的需求。新方法、实验工具和 API 接入都不能降低这些要求。

| 内容用途 | 必需能力 | 不能作为替代的结果 |
|---|---|---|
| 表格、图签、编号、数值、中英文正文与说明 | 内容正确的原生 TEXT/MTEXT；能修改字符串中的字、移动位置；字体、字号、字间距、对齐和单元格布局合理 | 只保留字形轮廓、把笔画组成 GROUP、仅提供默认关闭的替代文字，不能计为已经完成可编辑文字交付 |
| Logo、设计集团标志、签名等非编辑背景 | 单独提取并与正文隔离，整体保真保留、默认受保护；不参与正文 OCR 替换或逐字编辑 | 拆成普通文字、误识别替换、改正文时误删背景；用整页底图掩盖其他内容缺失 |
| 圈内 R、方框内字符等工程符号 | 保留边界、内部字符、位置及必要连接关系，并按完整对象组织 | 只留下字符、丢外框，或因轮廓、字体和显示失真而无法辨认 |

允许合理替代字体。恢复与原图完全相同的字体属于可选增强，不是上述文字交付的核心门槛；识别内容、字形可读性与合理排版仍须验证。

“可编辑”要通过改字、移动、保存和重新读取确认，不能由未编辑截图、DXF 合法或实体数量推断。修改文字后不能残留旧字笔画或影响邻近表框、其他文字和受保护背景。DXF 程序读回、目标 CAD 软件打开/编辑/保存，以及 DWG 往返须分项记录；未运行不算通过。

后续验收同时保留可读性、文字编辑、背景隔离及保存保护，不得只检验本轮新增能力。历史已完成项要注明来源和范围；出现同类问题先核对版本、入口和覆盖范围，不能把旧需求重新当新功能，也不能未经定位就声称旧实现被覆盖。

## 最新状态：2026-10-24

S0 A/B 对照中，直接保留 PDF 原路径和原字形的 B 改善了默认显示，但默认字形不是可改字符串的文字；A 已有真实 TEXT 编辑能力，显示和识别仍有缺陷。该对照不能得出 B 在完整产品目标上全面优于 A。

近期整合方向是**按内容用途分流：保留已有文字编辑能力，吸收来源几何保真方法，独立保护非编辑背景**。源路径导入可以是内部处理步骤，但表格和正文的语义编辑不能被降级为可选附件。暂停小型数值模型的追加训练，不否定尚未验证的其他学习方案。

新增 [native-first 工具](tools/native_first/README_ZH.md)：
- 离线 PDF 路径导入不调用 OCR/大模型，不需要 API Key。
- 可选模型文字建议支持用户自带模型、端点和 API Key；默认不联网，不自动改写 CAD。可选的是建议供应商，不是产品要求中的文字编辑能力。
- 现有 GUI/扫描处理路径保持。新路径是显式选择的独立 CLI，尚未接入 GUI；它只是有限来源导入部件，不是完整产品验收结果。

[整合与勘误](docs/project/NATIVE_FIRST_20261024.md) · [本地删除后的恢复](docs/project/RESTORE_AFTER_LOCAL_REMOVAL.md) · [旧分支归档清单](docs/project/BRANCH_ARCHIVE_20261024.json)

## 运行

现有 GUI（已验收环境为 Python 3.11）：

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

新增独立导入工具（在仓库根目录）：

```powershell
python -m venv .venv-native
.\.venv-native\Scripts\python.exe -m pip install -r tools/native_first/requirements.txt
.\.venv-native\Scripts\python.exe -m tools.native_first.import_pdf input.pdf --page 1 --inspect
.\.venv-native\Scripts\python.exe -m tools.native_first.import_pdf input.pdf --page 1 --output local-artifacts/native/page.dxf
```

支持范围、局限及 BYOK 示例见工具 README。默认纸面毫米坐标，不推断未知设计比例。输出图像依赖应与 DXF 一同交付。

## 历史工程资产与验收

PR #35 已合入 P11—P20 已审查运行基准及隔离 Goal01—22 研究。相关来源、缓存、保存合同、校对和回归设施继续保留，研究代码不因存入 main 自动晋级。

[PR35 审查](docs/project/PR35_REVIEW_20261024.md) · [同步范围](docs/project/SOURCE_SYNC_RESULT_20261024.md) · [项目状态](docs/project/PROJECT_STATUS.md) · [工程证据](docs/project/ENGINEERING_EVIDENCE_INDEX.jsonl)

现有正常入口是 `ProductionProcessingService`；保存后的 DXF 才是预览依据。
`start-stable.ps1` 使用当前检出，可通过 `-Python` 指定解释器。旧活动工作树里的同名脚本并不自动代表稳定版本。

本次独立工具有自己的测试与 Windows/Linux 工作流：

```text
python -m pytest -q tools/native_first/tests
```

现有核心 CI、保存行为、仓库卫生和构建流程保持。CI 成功不替代真实图纸、编辑器往返和人工劳动测量。

## 文件与恢复

main 是日常入口。被删除旧分支的提交先保存在 `archive/20261024/<原分支名>` 标签，归档标签不是产品 Release。
本地程序被用户报告删除；未跟踪且未归档的真实材料、详细记录、模型和环境不保证可以从 GitHub 恢复。
私人技术小包不是全部资料备份。已有合法跟踪字体和测试素材保留，不把新真实图纸、API Key、环境或运行结果提交到公开仓库。

本次没有发布新版本或 Release。详细恢复命令见上述恢复文档。
