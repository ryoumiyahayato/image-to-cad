# 阶段十一：模板、缓存和 GUI 架构

## 结论

通用生产流程不包含固定标题栏模板、固定字段词表或 OCR 误字别名。版式特化状态现在是
显式配置，默认值为 `disabled`；仓库当前没有安装任何版式 profile，试图把未安装
profile 送入通用生产服务会直接失败，不会静默启用模板规则。

缓存键已从“文件路径 + 页码”升级为完整的处理契约；活动 GUI 的单页和多页处理均调用
同一个 `ProductionProcessingService`。缓存恢复、文字复核、GUI 预览和 DXF 导出都以
同一个不可变 `FinalStructure` 为边界。

本阶段没有新增识别类型、标题栏模板或界面功能，也没有改变任何识别阈值。固定基线标签
为 `baseline/phase11-template-cache-gui-2026-07-30`。

## 模板与 profile

- 通用 OCR、Logo、签名、对象归属流程中不存在固定标题栏区域、固定字段词表和误字
  别名。
- `LayoutProfileSelection` 明确保存 `enabled` 和 `name`。
- 默认 profile 为 `{"enabled": false, "name": "disabled"}`。
- 未显式启用时不能携带 profile 名；显式启用却未安装的 profile 不能进入通用生产
  流程。
- profile 状态同时进入配置摘要和缓存键。

## 完整缓存键

缓存键和缓存文件内嵌元数据均包含：

1. 输入文件内容 SHA-256；
2. 一基页码；
3. DPI；
4. OCR 开关；
5. 算法版本；
6. 模型版本；
7. 完整配置摘要；
8. 版式 profile；
9. `FinalStructure` schema 版本；
10. 关键阈值摘要。

关键阈值摘要只记录既有默认值，不改变阈值。缓存文件版本从 7 升至 8；旧缓存或键缺失、
内容不匹配、配置不匹配、结构指纹不匹配时均不得命中。

专项测试和 10 页真实验证均确认：同一路径内容变化、OCR 开关变化、DPI 变化、算法版本
变化、模型版本变化、配置变化和 profile 变化都会生成不同缓存键，并拒绝旧缓存。

## GUI 与 FinalStructure

- 活动 GUI 的单页和多页处理只调用
  `ProductionProcessingService.process_page`。
- GUI 把 OCR、DPI、阈值和 profile 状态组成不可变
  `ProductionProcessingConfig` 后交给服务，不再依赖隐藏的算法配置。
- 处理服务只向来源元数据附加配置契约，不改变结构内容；添加契约前后的
  `structure_id` 必须相同。
- 活动缓存恢复会验证内嵌缓存键，恢复完整 `FinalStructure`，并同步
  `_preview_structure_id`。
- GUI 文字复核不再只修改 `_ocr_texts`；它会重建新的不可变
  `FinalStructure`、更新文字输出观察记录和 `structure_id`，随后缓存与导出消费该
  结构。
- `FinalStructure` 的像素数组不可写，来源和观察映射也改为只读映射。
- 单页导出前仍强制要求 GUI 预览的 `structure_id` 与待导出结构一致。

## 真实页面验证

10 个唯一真实页面执行 80 项逐页检查，另有 5 项架构检查，全部通过：

- 10/10 `structure_id` 与第 10 阶段独立基线完全一致；
- 代表页即时重复处理得到相同 `structure_id` 和内容摘要；
- 10/10 缓存保存/读取后结构与缓存键完全一致；
- 10/10 的七类缓存键变化全部未命中；
- 10/10 的轮廓和预览 mask 保持不可写；
- 固定模板/词表未回到通用流程；
- 单页与多页共享处理服务；
- 活动缓存恢复、文字复核、预览和导出都保持 `FinalStructure` 边界。

正式真实文档回归直接使用第 10 阶段清单，没有录制新基线：12/12 通过，10 个唯一
页面，22 类覆盖，全部 OCR、结构分析、预览、DXF 和内容审计阶段完成。

## 测试

- 全量 Pytest：257 通过，0 失败，0 错误，0 跳过。
- Ruff：`app scripts tests` 全部通过。
- `compileall`：通过。
- `git diff --check`：通过。

Mypy 未标记为通过：本机 Python 3.14.6 与仓库 `mypy.ini` 的 Python 3.11 目标不一致，
当前 NumPy 类型包使用 Python 3.12 以上泛型语法，Mypy 在检查项目代码前停止。本阶段
没有修改无关依赖或放宽检查来掩盖该环境问题。

## 证据文件

- `phase11-before.json`：阶段十基线的模板、缓存键和活动 GUI 缺口。
- `phase11-after.json`：10 页配置、完整缓存键、内容摘要和逐页检查。
- `phase11-real-regression.json`：正式 12 页零变化回归。
- `phase11-pytest.xml`：257 项全量测试结果。
- `phase11-verification.json`：验收摘要与证据哈希。

## 复现命令

```powershell
.\.venv\Scripts\python.exe scripts\run_architecture_validation.py `
  --input-manifest output\ci\phase5-comparison-inputs\input-manifest.json `
  --expected validation\text-output-contract\phase10-after.json `
  --output validation\template-cache-gui\phase11-after.json `
  --artifacts output\ci\phase11-cache-artifacts `
  --enforce

.\.venv\Scripts\python.exe scripts\run_real_document_regression.py `
  --manifest tests\real_regression\manifest.json `
  --output validation\template-cache-gui\phase11-real-regression.json `
  --artifacts output\ci\phase11-real-regression-artifacts

.\.venv\Scripts\python.exe -m pytest -q `
  --junitxml=validation\template-cache-gui\phase11-pytest.xml
```

任一必需缓存字段缺失、旧缓存键匹配失败却仍被复用、配置变化仍命中、活动 GUI 直接
调用核心处理函数、缓存恢复未建立 `FinalStructure`、文字复核与导出结构不同步、结构
内容偏离第 10 阶段基线或真实回归变化时，校验返回非零状态。
