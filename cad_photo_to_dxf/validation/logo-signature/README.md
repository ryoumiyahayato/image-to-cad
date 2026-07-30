# 阶段九：Logo 与签名的独立视觉证据

## 结论

Logo 与签名只能由源图几何证据分类。OCR 字符串、对象名称和识别框重叠
都不能触发 Logo 或签名 IMAGE。证据不足时，源墨迹继续由普通轮廓、结构线
或文字所有者保留。

固定基线标签为
`baseline/phase9-logo-signature-evidence-2026-07-30`。

## 生产规则

- Logo 候选保存精确源像素 mask、视觉类型、闭合复杂度、孔洞、轮廓、
  密度和反射相似度。视觉类型显式区分 `graphic_mark` 与 `wordmark`。
- `设计`、`集团`、`DESIGN`、`GROUP` 等词不能参与 Logo 分类。
- 签名候选保存精确源像素 mask，不使用 OCR 框扩张，也不做形态学膨胀。
- 签名 IMAGE 除原有几何条件外，还必须同时具有正、负两个方向的长对角
  源笔画支撑。只有单向支撑的工程线、引线和标题栏笔画回退为轮廓。
- Logo、签名、正文和结构线仍由阶段八的统一像素归属器仲裁；任何语义
  对象只能导出最终属于自己的源像素。

## 前后证据

10 个唯一真实页面共含 3,104,606 个源前景像素和 12 个 Logo/签名标注区域。

| 指标 | 阶段八基线 | 阶段九 |
| --- | ---: | ---: |
| Logo 候选数 | 0 | 0 |
| Logo 最终语义像素 | 0 | 0 |
| 签名候选数 | 2 | 0 |
| 签名候选像素 | 1,292 | 0 |
| 签名最终语义像素 | 1,253 | 0 |
| 标注区域外签名语义像素 | 1,253 | 0 |
| 邻近普通文字被语义对象捕获的像素 | 0 | 0 |
| 候选背景像素 | 0 | 0 |
| 最终 mask 超出候选 mask 的像素 | 0 | 0 |

阶段八的两处签名候选只有单向对角支撑：

- `environment-scan-page-002-120dpi`：703 个最终误归属像素；
- `environment-scan-page-004-120dpi`：550 个最终误归属像素。

阶段九将两者安全降级为轮廓。6 个 Logo 标注区域和 6 个签名标注区域的源
墨迹均未丢失；当前真实集没有足够视觉证据将它们强制提升为语义对象，因此
混淆矩阵为 `logo -> fallback_outline: 6`、
`signature -> fallback_outline: 6`。

## 负例

专项测试覆盖：

- 正文包含“设计集团”；
- 标题包含 `DESIGN`；
- 签名紧邻普通正文；
- Logo 紧邻项目名称；
- 类似字母的工程符号；
- 只有一个方向的工程线段。

这些负例均不能仅凭词义或矩形框重叠获得 Logo/签名所有权。

## 验证

- 专项真实页验证：10 页，11 项严格验收全部通过；
- 全量单元测试：242 项通过，0 失败、0 错误、0 跳过；
- 真实文档回归：12/12 通过，10 个唯一页面，22 类覆盖；
- 第二次严格回归使用独立录制的候选清单，五个管线阶段全部完成；
- Ruff、`compileall` 和 `git diff --check` 通过。

本机 Python 3.14.6 与项目 `mypy.ini` 的 Python 3.11 目标不一致，当前 NumPy
类型包使用 Python 3.12 以上泛型语法；使用当前解释器覆盖目标后，Mypy 仍
报告仓库既有依赖链类型错误。因此本阶段不把 Mypy 标为通过，也没有修改
无关模块来隐藏这些错误。

## 证据文件

- `phase9-before.json`：阶段八两处误归属的精确像素和视觉证据；
- `phase9-after.json`：10 页 Logo/签名 mask、标注和混淆矩阵审计；
- `phase9-recording.json`：候选真实文档基线录制；
- `phase9-recorded-manifest.json`：只更新 `expected` 的独立候选清单；
- `phase9-real-regression.json`：对候选清单的第二次严格重跑；
- `phase9-pytest.xml`：242 项全量测试；
- `phase9-verification.json`：阶段验收摘要和证据哈希。

## 复现命令

在 `cad_photo_to_dxf` 目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\run_logo_signature_validation.py `
  --input-manifest output\ci\phase5-comparison-inputs\input-manifest.json `
  --output validation\logo-signature\phase9-after.json `
  --enable-ocr `
  --enforce

.\.venv\Scripts\python.exe -m pytest -q `
  --junitxml=validation\logo-signature\phase9-pytest.xml

.\.venv\Scripts\python.exe scripts\run_real_document_regression.py `
  --manifest validation\logo-signature\phase9-recorded-manifest.json `
  --output validation\logo-signature\phase9-real-regression.json `
  --artifacts output\ci\phase9-real-regression-artifacts
```

任一候选 mask 捕获背景、最终 mask 超出候选、邻近普通文字被语义捕获、
标注源墨迹丢失、Logo 分类器出现禁用词义规则，或真实回归指标变化时，
命令返回非零状态。
