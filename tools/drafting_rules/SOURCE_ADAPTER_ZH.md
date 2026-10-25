# 真实来源证据接入 — CLOSED

本阶段基准：main `e333dc48e98aeebbda373d3d00c7779448e9a3d1`，初始工作区干净。
闭合范围：接入一类真实文字来源归属，给出真实正例、失败和不完整证据的弃判；不要求消除全部弃判。
`cn-sheet-text-table@0.1.1` 的六条规则、原引擎、原测试、原报告、旧基线均保留。新增适配入口，不扩充领域、规则数量或生产 schema。

## 使用

在仓库根目录使用已有环境；不需要 Windows、外部模型或新依赖：

```bash
export QT_QPA_PLATFORM=offscreen
export XDG_CACHE_HOME=/workspace/.cache
export PYTHONPATH="$PWD/cad_photo_to_dxf"
.venv/bin/python -m tools.drafting_rules.source_study --output local-artifacts/drafting-rules/my-source-study
```

目录必须不存在。研究驱动器在新目录内生成生产缓存、正式导出器的 DXF、改字副本及控制样例；原 PDF 不变。
它复用仓库已有转录观察，不重新识别、不训练。`source_study` 的样本坐标只属于夹具；适配器不含文件名、坐标或文字特例。

独立只读验证：

```bash
.venv/bin/python -m tools.drafting_rules.source_adapter \
  --before local-artifacts/drafting-rules/my-source-study/w02-single/before.dxf \
  --after local-artifacts/drafting-rules/my-source-study/w02-single/after.dxf \
  --cache local-artifacts/drafting-rules/my-source-study/w02-single/trace.npz \
  --source cad_photo_to_dxf/tests/real_regression/assets/sources/warehouse-electrical-vector.pdf \
  --evidence local-artifacts/drafting-rules/my-source-study/w02-single/evidence.json \
  --dpi 136 --output local-artifacts/drafting-rules/my-source-study/independent-report.json
```

退出码沿用只读检查器含义：0＝无 FAIL（仍可能有 ABSTAIN）；1＝有 FAIL；2＝输入身份/格式错误。
API：`source_adapter.validate_with_source(before, after, source, evidence_path, cache, dpi)`。
输入沿用原 `evidence.schema.json`；缓存通过原 `save_trace_cache(..., cache_key=...)` 保存上下文：
`source_sha256`、1 起算的 `page`、`dpi`、整页渲染像素坐标下的 `crop=[left,top,right,bottom]`。
没有上下文不会得到完整来源 PASS；上下文冲突或 PDF/缓存像素不一致会拒绝输入。
手工补写这些键也不充分，适配器仍重新读 PDF、比较生产二值图、重放归属证明并绑定实际保存的 TEXT。

## 证据链与只读边界（代码事实）

1. 原 PDF 摘要、物理页、DPI、选区、整页尺寸与生产缓存上下文一致；再次渲染后以原阈值调用 `prepare_scan_page`，要求与缓存 `preview_binary` 逐像素相等。
2. 用缓存候选重放 `constrain_texts_to_table_cells(..., verified_sources=...)`；独立行使用 `prepare_safe_candidate`。复用实际 `VerifiedCellTextSource`，不把缓存布尔值当作证明。
3. 调用原 `partition_content`、`complete_verified_text_ownership`，带入缓存中的结构线、Logo、签名。结构/背景争议像素不得被适配器改判为文字。
4. 以生产阈值下的连通载体为可见来源成员，记录规范像素区间、摘要、共享行和未归属数量。相邻行可以共享同一载体，不虚构逐行独占所有权。
5. 将原 `accepted_ocr_texts` 顺序与 `OCR_TEXT_LINE` 元数据、原字符串、字号/宽度/插入点/旋转和 LFF 字体一起核对，绑定基线实际 TEXT 句柄。保存后继续检查同句柄和编辑字符串。
6. 只读的 `DocumentView` 将已核实原生正文排除出残留几何视图，复用生产 DXF 预览器。适配器既不删除实体，也不保存 DXF；只写新检查报告。
7. 可见几何覆盖已归属文字源核可构成失败反例。完整通过还要求：整载体有归属、缓存遮罩覆盖、无边界截断、共享行均绑定、原生替换已核实、几何支持范围已知且无相交。

几何检查仅支持世界 XY 平面的直 LINE 和零宽、无 bulge、默认 OCS 的 LWPOLYLINE；其他可见对象导致弃判。
不调用旧预览器去解释镜像/倾斜 OCS。旧 0.1.1 的世界坐标反例继续运行，未修改其修复。
除栅格墨迹外还检查扩张线段包络：只要不能排除亚像素接触就弃判，避免仅因预览没画到一个像素而误报通过。
报告的支持范围是生产阈值与来源像素坐标，不是无限分辨率的原 PDF 路径证明或目标 CAD 软件显示认证。

`source_ledger` 记录源摘要、缓存摘要、`structure_id`、阈值、页/选区/DPI、候选身份、原识别内容/来源/置信度、编辑后内容、TEXT 句柄、源核和载体区间、共享成员、未覆盖部分及残留句柄。
`preservation` 列出其他模型空间成员及其指纹摘要，沿用 `edit-isolation` 保护邻接格线和其他内容。
这不等于获得了 Logo 或完整表线的语义归属，也不会自动扩大允许修改的成员集合。
来源适配模式下，背景和表线规则始终保留 ABSTAIN；手工提供角色、句柄或集合完整性标记不会覆盖这一限制。其他成员发生变化仍由 `edit-isolation` 报错。

**没有用 PDF PATH 包围框相交来赋权。** 原生绘制 PATH 身份没有传到本适配路径，报告明确标为 `NOT_AVAILABLE`。
成员 ID 是源身份、页、DPI、选区和像素区间的摘要，不是捏造的原 CAD/PDF 句柄。

## 真实输入与结果（自动化事实）

原件：`warehouse-electrical-vector.pdf`，SHA-256 `8967fc042f4979f017ca4d27d25e66e7c9fbb2e46d840d0fd81e68268af31017`。
两个局部均为同一第 2 页、136 DPI；不计作两个设计或独立泛化来源。

| 来源与操作 | 0.1.1 | 来源适配后 | 含义 |
| --- | --- | --- | --- |
| 原三行 W02，`[4080,2200,4390,2410]`；Discipline→DisciplineA 后保存读回 | 7 PASS / 5 ABSTAIN | 7 PASS / 1 FAIL / 4 ABSTAIN | 中文行从未知变为有源核/句柄支持的残留失败；两行英文、背景、表线仍弃判 |
| 同页既有“施工图”观察，`[4463,2558,4592,2659]`；施工图→施工表后保存读回 | 2 PASS / 4 ABSTAIN | 3 PASS / 3 ABSTAIN | 585 个源载体像素覆盖完整且已退出；单元格规范、背景与完整表线未声明，继续弃判 |

原三行中，中文涉及 1,840 个载体像素，重放归属仍缺 23 个、缓存归属遮罩缺 251 个。
其已归属文字源核与实际 DXF 可见几何有 54 个像素相交，绑定到基线句柄 `E0/E1/E2`；因此可以证明存在残留，而不能声称整载体都归中文独占。
另一个可见载体成员位于争议区域，没有越权归为已证明文字残留。两行英文共享 1,132 像素载体，各有 5 个归属缺口及 233 个缓存覆盖缺口，保持弃判。
句柄只对本轮保存文件有效，适配程序不会硬编码这些值。

源笔画恢复控制：从真实缓存遮罩经原 `semantic_paths` 恢复原字形到新 DXF 副本，退出检查 FAIL。
混合成员控制：一条几何路径同时覆盖目标源核并延伸到非目标区域，报告 FAIL，但源成员区间保持不变，不把整条路径归给文字，也不删除它。
缺来源上下文控制 ABSTAIN，错误来源身份 INPUT_ERROR；没有把无证据输入判作空白或正常。

本轮完整源核/成员绑定和正常/失败报告见 [证据目录](evidence/source-adapter-v1/)。两份逐项比较均来自相同前后文件，使用不变的 0.1.1 检查器和新增来源适配入口。
旧报告未覆盖，生成的大 DXF/PDF/PNG/缓存仍在忽略目录；只有有限 JSON 证据保留到 Git。

## 测试与反例

```bash
.venv/bin/python -m pytest -q tools/drafting_rules/tests --junitxml=local-artifacts/drafting-rules/source-adapter/all-tests.xml
.venv/bin/python -m pytest -q cad_photo_to_dxf/tests/test_source_text_layout.py cad_photo_to_dxf/tests/test_table_text_layout.py cad_photo_to_dxf/tests/test_scanned_text_rows.py cad_photo_to_dxf/tests/test_content_ownership.py cad_photo_to_dxf/tests/test_ownership_commit_veto.py cad_photo_to_dxf/tests/test_text_output_contract.py cad_photo_to_dxf/tests/test_signature_overlay.py cad_photo_to_dxf/tests/test_text_protection.py cad_photo_to_dxf/tests/test_review_save_preservation.py cad_photo_to_dxf/tests/test_native_text_geometry.py cad_photo_to_dxf/tests/test_portable_font_bundle.py tools/native_first/tests --junitxml=local-artifacts/drafting-rules/source-adapter/regression.xml
.venv/bin/python maintenance/preservation_check.py
.venv/bin/python -m ruff check --config cad_photo_to_dxf/ruff.toml tools/drafting_rules
.venv/bin/python -m compileall -q tools/drafting_rules
```

71 项包测试通过：原 49 项不变，新增 22 项。相关旧回归 113 项通过；保真检查 EXACT，匹配 2026-10-24 基线，P10-A 身份和旧 LINE 来源义务保持。Ruff/编译通过。
新增测试区分真实正例/失败与合成控制：共享 PDF PATH（同一 PATH 含字形和结构）在来源身份有效时仍弃判；缺遮罩、错误页/DPI/选区/摘要、TEXT 绑定不符、混合几何、镜像 OCS、无替换 TEXT 均有明确拒绝或弃判。
实际表线缺失/重复/延伸及其他轮廓被改时，`edit-isolation` 失败；背景和表线专属规则依旧弃判。原合成保护测试继续验证有完整声明时的背景/表线行为，不冒充真实映射已完成。
独立新进程运行来源 CLI 通过，输入 PDF、缓存、前后 DXF 和证据摘要不变。

## 尚缺数据、最小接口与下一阶段

| 位置 | 实际保存/丢失的信息 | 最小后续接口；本轮不修改生产 |
| --- | --- | --- |
| `optimized_trace` 中 `verified_text_sources` → `build_final_structure` | 完整单元格证明和逐行源核是局部对象，未作为逐候选证明写入 FS/cache；只有汇总遮罩，故本轮从实际来源重放 | 在既有观察/侧车接口保留证明区间、成员摘要、共享行、冲突归属和阶段身份 |
| `commit_source_objects` 等最终归属路由 → FS | W02 中文最终 `replacement_safe` 为 false，来源回退与最终成员之间缺少完整生命周期记录；哪一阶段首次造成残留尚未定位 | 对同一源成员记录路由前后所有者及最终成员；不得先删整条 PATH 来掩盖问题 |
| `semantic_paths` / 正式几何写出 | 共享遮罩转为轮廓后没有逐文字源成员到几何句柄的可持久绑定；TEXT 只有行序/内容/几何等 XDATA | 独立导出侧车记录源支持区间 ↔ 最终成员 ↔ 保存后句柄，不改 FS schema 或生产阈值 |
| Logo/签名与表线 | FS 有受支持的 Logo/签名记录，但当前局部没有可靠独立角色映射；已检测结构线不等于完整表线集合 | 先形成来源角色及集合完整性的独立证据，缺失时继续弃判 |

开发中一个极简合成单连通域触发既有 `signature_overlay._component_groups` 对空数组求 quantile 的异常，未改生产修复；共享 PATH 控制改为明确的合成 FS/cache/正式导出器测试，不声称它通过完整 OCR 链。真实两局部均跑完整现有转换链（使用已有转录注入）。

**结论：本次使“给定真实来源的旧笔画是否已经退出、是否还有可证明残留”首次能由来源像素、生产归属与保存 CAD 联合核实。实际原 W02 暴露失败，干净对照证明退出；这是 CAD 交付可验证性的提高，不是生产质量问题已修复。**
本有限适配阶段 CLOSED。下一阶段建议只追踪并局部修复 W02 中文残留的成员生命周期，同时回归格线、英文与非目标保护；不自动执行。
LibreCAD GUI 的改字/移动/保存/完全关闭重开、DWG 往返、未见设计泛化与真人净劳动均为 NOT_RUN；没有新的 User UAT 事实。
