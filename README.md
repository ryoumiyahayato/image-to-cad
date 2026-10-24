# Image to CAD — source-first development preview

当前版本 **0.3.0-dev**。目标仍是高保真、合理可编辑的二维 CAD，并减少人工核查和修正。

## 最新状态：2026-10-24

S0 A/B 对照中，直接保留 PDF 原路径和原字形的 B 方案明显改善默认显示。近期重点转为**先保留原生来源，再按需添加语义编辑**，暂停小型数值模型的追加训练。
这不是任意扫描图、完整工程对象理解或真人净省时已完成的声明。

新增 [native-first 工具](tools/native_first/README_ZH.md)：
- 离线 PDF 路径导入不调用 OCR/大模型，不需要 API Key。
- 可选文字建议支持用户自带模型、端点和 API Key；默认不联网，不自动改写 CAD。
- 现有 GUI/扫描处理路径保持。新路径是显式选择的独立 CLI，尚未接入 GUI 或完成跨编辑器验收。

[本轮整合与证据](docs/project/NATIVE_FIRST_20261024.md) · [本地删除后的恢复](docs/project/RESTORE_AFTER_LOCAL_REMOVAL.md) · [旧分支归档清单](docs/project/BRANCH_ARCHIVE_20261024.json)

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
