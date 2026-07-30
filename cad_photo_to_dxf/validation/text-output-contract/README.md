# 阶段十：文字输出契约

## 结论

OCR 候选现在只能稳定进入三种互斥的文字输出状态：可靠且可安全替换的候选导出为原生
`TEXT`；可靠但不可安全替换的候选保留源轮廓并进入
`TEXT_FALLBACK_OUTLINE`；不可靠或不合格的候选保留为
`RESIDUAL_GRAPHIC`。可靠签名仍由阶段九的独立视觉证据链导出为顶层图像，不参与文字状态判定。

本阶段没有新增功能，也没有调整任何识别阈值。固定基线标签为
`baseline/phase10-text-output-contract-2026-07-30`。

## 输出契约

- `editable_text`：OCR 内容非空、类型受支持、已批准、置信证据可靠且
  `replacement_safe=true`。导出为 `OCR_TEXT` 层上的原生 `TEXT`，删除对应源字形轮廓。
- `text_fallback_outline`：识别证据可靠，但 `replacement_safe=false`。保留源轮廓，
  放入 `TEXT_FALLBACK_OUTLINE`，明确标记为不可编辑，记录
  `replacement_unsafe`。
- `residual_graphic`：OCR 内容、类型、批准状态或置信证据不满足契约。保留源轮廓，
  放入 `RESIDUAL_GRAPHIC`，不得导出为正文或签名，并记录稳定降级原因。
- 可靠签名：只允许阶段九确认的精确源 mask 生成独立 `SIGNATURE_OVERLAY`
  图像；不得捕获相邻正文。

人工复核可以确认低置信 OCR 证据，但不能绕过 `replacement_safe=false`。字体选择只影响
显示：TTF、OTF、LFF 或 SHX 均不能改变对象是否可编辑，也不能把降级轮廓重新分类为
`TEXT`。

原生 `TEXT` 同时写入 `TEXT_OUTPUT_CONTRACT` XDATA，保存状态、OCR 来源、字体族、
字体文件、DXF 样式、插入位置、旋转角、置信度和替换安全状态。导出结果、单页报告、
多页报告和真实文档回归均报告 OCR 候选、`TEXT`、降级轮廓、残留图形、Logo、签名及
全部降级原因。

## 真实页面证据

10 个唯一真实页面的专项强制验证结果：

| 指标 | 阶段九 | 阶段十 |
| --- | ---: | ---: |
| 独占输出状态 | 无 | 有 |
| OCR 候选数 | 未报告 | 1,188 |
| 原生可编辑 `TEXT` | 仅通用 DXF 计数 | 197 |
| `TEXT_FALLBACK_OUTLINE` | 未报告 | 977 |
| `RESIDUAL_GRAPHIC` | 未报告 | 14 |
| Logo | 未与文字契约联合报告 | 0 |
| 签名 | 未与文字契约联合报告 | 0 |
| `replacement_unsafe` | 未报告 | 977 |
| `confidence_below_contract` | 未报告 | 14 |

每页执行 13 项检查，共 130 项全部通过。检查覆盖状态计数、实体图层、原生
`TEXT` XDATA、签名图像约束、字体独立性、相同证据的重复判定、降级原因完整性和 DXF
审计。

两个低置信小框曾覆盖较长的残留轮廓。最终规则按候选框内的源轮廓覆盖率识别其唯一
所有者，并把整条所有者轮廓放入 `RESIDUAL_GRAPHIC`；不复制、不裁剪、不删除轮廓，
也不改变阶段八的单一像素归属。

## 正式回归与测试

- 候选真实文档基线录制：12/12 通过，10 个唯一页面，22 类覆盖。
- 独立严格重放：12/12 通过；两次运行的每页指标与内容审计完全一致，仅耗时和产物
  路径不同。
- 候选清单除各页 `expected` 外与原正式清单完全一致；正式清单现与候选清单语义
  完全一致。
- 全量 Pytest：248 通过，0 失败，0 错误，0 跳过。
- Ruff、`compileall` 和 `git diff --check` 通过。

Mypy 未标记为通过：本机 Python 3.14.6 与仓库 `mypy.ini` 的 Python 3.11 目标不一致，
当前 NumPy 类型包使用 Python 3.12 以上的泛型语法，Mypy 在分析项目代码前即终止。
本阶段没有修改无关依赖或放宽类型检查来掩盖该环境问题。

## 证据文件

- `phase10-before.json`：阶段九基线中缺失的文字状态、图层和统计契约。
- `phase10-after.json`：10 页逐页输出状态、图层、XDATA、稳定性和 DXF 审计。
- `phase10-recording.json`：使用正式清单录制的候选真实文档结果。
- `phase10-recorded-manifest.json`：仅更新各页 `expected` 的独立候选清单。
- `phase10-real-regression.json`：对候选清单的独立严格重放。
- `phase10-pytest.xml`：248 项全量测试结果。
- `phase10-verification.json`：验收摘要与证据哈希。

## 复现命令

在 `cad_photo_to_dxf` 目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\run_text_contract_validation.py `
  --input-manifest output\ci\phase5-comparison-inputs\input-manifest.json `
  --output validation\text-output-contract\phase10-after.json `
  --artifacts output\ci\phase10-text-contract-artifacts `
  --enforce

.\.venv\Scripts\python.exe scripts\run_real_document_regression.py `
  --manifest validation\text-output-contract\phase10-recorded-manifest.json `
  --output validation\text-output-contract\phase10-real-regression.json `
  --artifacts output\ci\phase10-real-regression-artifacts

.\.venv\Scripts\python.exe -m pytest -q `
  --junitxml=validation\text-output-contract\phase10-pytest.xml
```

任一候选被同时导出为多种语义、人工复核绕过替换安全、字体改变可编辑性、降级缺少
原因、需要的源轮廓未进入明确图层、签名图像数量不匹配、DXF 审计失败或真实回归指标
变化时，校验返回非零状态。
