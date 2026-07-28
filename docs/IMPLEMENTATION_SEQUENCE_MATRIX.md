# 阶段二：实施顺序与完成度矩阵

## 审计结论

审计范围为 `d9fbda763e95c6dd7154934b801b59dbf034e711^..d898400b69f86b625ce71e9689b5d5f8e877d66a`，按 Git 父子关系和作者时间顺序核验。

范围内只有三个提交：

1. `d9fbda7`：同时引入自动直线重连、签名处理、OCR/导出调整、GUI、缓存、测试和人工 DXF 输出；
2. `5a1b065`：同时引入结构 ROI、连通性安全、对象归属、Logo、`FinalStructure`、统一预览/导出、缓存调整、真实回归和 CI；
3. `d898400`：只冻结双基线证据和复现工具。

因此可以证明当前终态中存在若干模块和测试，也可以证明阶段一双基线已经独立完成；但不能从 Git 证明 `5a1b065` 内部的七项系统重构按约定顺序分别实施、分别验收或分别回退。除阶段一外，不能仅因终态代码存在相关模块就标为“已完成”。

状态定义：

- **已完成**：存在独立提交、代码位置、测试和真实输出证据，并满足该阶段当前验收条件；
- **部分完成**：有可定位的终态代码或测试，但缺少部分验收项或独立阶段证据；
- **未完成**：缺少该阶段要求的主要实现或交付物；
- **无法证明**：可能存在终态实现，但 Git 和保存证据不能证明实施顺序或当时验收。

## 完整提交时间线

| 顺序 | commit / 时间 | 提交目标 | 算法行为 | 数据结构 | GUI | 缓存 | 测试 | 真实图片验证 |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `d9fbda763e95c6dd7154934b801b59dbf034e711`<br>2026-07-27 19:27:48 +08:00<br>主题：`1` | 主题未描述目标；根据差异只能推断为一次混合功能提交：自动直线重连、OCR/文字导出、签名叠加、字体、GUI 和缓存一起变化 | **是**。新增 `straight_line_reconstruction.py`、`signature_overlay.py`，修改预处理、OCR、追踪和导出 | **是**。增加签名区域、直线及缓存持久化字段 | **是**。修改 4 个 GUI release 文件 | **是**。修改 `trace_storage.py` | **是**。修改/新增 12 个测试文件；没有保存该 commit 的 JUnit | **有人工输出，无机器验收**。保存 2 份 DXF、2 份签名 PNG 和 1 份合成图；没有输入清单、内容哈希、期望指标或通过报告 |
| 2 | `5a1b06585b6f068bb5f61e16fd32b96e4f54275b`<br>2026-07-28 21:18:31 +08:00<br>主题：`refactor: freeze current system baseline (phase 1)` | 主题称“冻结”，但差异实际是 49 文件的混合系统重构：ROI、连通性、归属、Logo、最终结构、预览/导出、缓存、回归和 CI 同时落地 | **是**。修改主追踪、OCR、扫描清理、直线重建、对象识别和导出 | **是**。新增 `FinalStructure`、`ContentOwnership`、`StructuralRoi`、`ConnectivityDecision`、`LogoRegion` | **是**。修改 `gui_exact_release.py` | **是**。修改 `trace_storage.py` 和 GUI 缓存消费 | **是**。新增/修改 12 个测试文件；其精确 commit 后由阶段一保存 205 项零失败 JUnit | **是，但只有 3 页**。新增 3 份完整页面、manifest、运行器和 CI；阶段一保存了默认配置双基线，另有 OCR 开启 3/3 回归结果 |
| 3 | `d898400b69f86b625ce71e9689b5d5f8e877d66a`<br>2026-07-28 21:46:20 +08:00<br>主题：`test: record dual frozen baselines (phase 1)` | 独立完成阶段一：固定当前与旧算法 commit、配置、测试和 6 份 DXF，提供复现工具 | **否**。未修改 `app/` | **否** | **否** | **否** | **未新增测试逻辑；新增测试证据**。保存当前 205 项和旧算法 156 项 JUnit | **是**。同 3 页分别运行两个冻结版本，保存 6 份 DXF、结构统计、输入/DXF 哈希和零错误审计 |

差异规模：

| commit | 文件 | 新增行 | 删除行 | 说明 |
| --- | ---: | ---: | ---: | --- |
| `d9fbda7` | 43 | 461,297 | 348 | 大部分新增行来自字体和 DXF，但应用代码仍跨越多个核心边界 |
| `5a1b065` | 49 | 4,595 | 933 | 七项重构和测试/CI被压在同一提交中 |
| `d898400` | 15 | 971 | 0 | DXF 按二进制记录，不计入文本行数 |

### 关于“修改目标”的证据边界

`d9fbda7` 的提交主题只有 `1`，所以表中的目标是根据文件差异作出的推断，不是作者提交信息。`5a1b065` 的主题只说明“冻结基线”，却包含大量会改变算法和数据结构的差异，因此不能把它当作纯标签或纯文档提交。`d898400` 的主题、差异和交付物一致，是范围内唯一能够单独验收的阶段性提交。

## 原定阶段映射与完成度

| 原定阶段 | 状态 | 对应 commit | 代码位置 | 测试或输出证据 | 结论与缺口 |
| --- | --- | --- | --- | --- | --- |
| 冻结基线 | **已完成** | `5a1b065`、`d898400`；标签 `baseline/current-refactor-2026-07-28`、`baseline/old-algorithm-pre-d9fbda7`、`baseline/phase1-evidence-2026-07-28` | `cad_photo_to_dxf/scripts/capture_frozen_baseline.py` | `cad_photo_to_dxf/validation/system-refactor-baselines/`：两份配置、两份 JUnit、六份 DXF；当前 205/205、旧算法 156/156，DXF 审计错误均为 0 | 有独立提交、明确命令和精确 commit，可回退、比较和复现 |
| 补可观测性 | **未完成** | `5a1b065` 只有最终结构和回归摘要，没有独立可观测性提交 | `app/final_structure.py:88`；`scripts/run_real_document_regression.py:216` | `tests/test_system_refactor_invariants.py:83` 只验证最终结构一致性 | 尚无要求的 26 个阶段产物、统一元数据、上游阶段标识或一键调试包；无法追踪任意像素从原始输入到最终对象 |
| 建立真实回归集 | **部分完成** | `5a1b065`，阶段一在 `d898400` 固定输出 | `scripts/run_real_document_regression.py:98`；`.github/workflows/ci.yml:61` | `tests/real_regression/manifest.json` 有 3 页且 OCR 开启；`tests/test_real_document_regression_contract.py:16`；阶段一保存 3 页输出 | 已有非空、完整页、内容哈希、来源说明、期望指标和 CI 强制执行，但当前门槛仍是 3 页，不满足至少 10 页及规定类别覆盖 |
| 关闭全页拓扑修改 | **部分完成；独立顺序无法证明** | 相关变化混在 `5a1b065` | `app/preprocess.py:58`；`app/scan_cleanup.py:144`；`app/straight_line_reconstruction.py:645` | `tests/test_system_refactor_invariants.py:21` 只排除字面 `MORPH_CLOSE`；`tests/test_straight_line_reconstruction.py:16` 等局部行为测试 | 有终态静态约束和局部测试，但没有独立提交，也没有对所有等价膨胀/腐蚀、Hough gap、全页桥接/吸附/延伸做生产调用链审计，更没有至少 10 页的关闭前后像素和连通域对照 |
| 实现结构 ROI | **部分完成；独立顺序无法证明** | `5a1b065` | `app/structural_roi.py:14`、`:153`；`app/straight_line_reconstruction.py:645` | `tests/test_straight_line_reconstruction.py:29`、`:64` | 有源像素支持的 ROI 类型、ROI 内桥接和保护区测试；缺少独立提交，以及 ROI mask、来源类型、置信度、扩张距离、ROI 外拒绝候选的真实页输出 |
| 重写连接判定 | **部分完成；独立顺序无法证明** | `5a1b065` | `app/connectivity_safety.py:18`、`:35`；`app/straight_line_reconstruction.py:557` | `tests/test_straight_line_reconstruction.py:29`、`:64`、`:140`、`:190` | 连通性模块已与对象类型解耦并检查 ROI、保护区、源像素和连通域；缺少独立提交、物理单位记录、人工标注集以及 precision/recall/F1、误桥接和拒绝原因统计 |
| 重构对象归属 | **部分完成；独立顺序无法证明** | `5a1b065` | `app/content_ownership.py:222`、`:252`；`app/final_structure.py:88` | `tests/test_content_ownership.py:17`、`:71`、`:110`；`tests/test_system_refactor_invariants.py:62` | 有互斥 line/text/graphic/signature/residual mask 和残留像素测试；缺少独立提交与真实页冲突报告，也未保存每类置信度、重叠像素、仲裁原因和降级原因的完整审计记录 |
| 修复签名和 Logo | **部分完成；独立顺序无法证明** | `d9fbda7` 首次加入签名；`5a1b065` 重写签名并新增 Logo | `app/signature_overlay.py:225`、`:290`；`app/logo_detection.py:111` | `tests/test_signature_overlay.py:55`、`:71`、`:258`、`:275`、`:298`、`:323`、`:360`；`tests/test_content_ownership.py:110` | 终态测试覆盖不依赖 OCR 词义/页面位置、邻近正文和闭合图形 Logo；没有独立阶段提交、逐像素真实签名/Logo 混淆矩阵或规定反例的完整真实页验收 |
| 明确文字输出合同 | **部分完成；独立顺序无法证明** | OCR/文字导出变化横跨 `d9fbda7` 和 `5a1b065` | `app/ocr_outline_export.py:205`；`app/trace_dxf_entities.py:368`；`app/content_ownership.py:205` | `tests/test_trace_export.py:55`、`:90`、`:111`；`tests/test_ocr_layout.py:44`、`:56`、`:80` | 可证明部分文字输出为原生可编辑 `TEXT`，不安全候选可保留轮廓；但没有独立提交，也没有把四种状态、fallback 图层、残留类型和全部降级原因固化为完整合同及统计 |
| 处理模板、缓存和 GUI 架构 | **部分完成；独立顺序无法证明** | `d9fbda7` 和 `5a1b065` 均修改 GUI/缓存 | `app/gui_exact_release.py:210`、`:229`、`:261`；`app/trace_storage.py:289`、`:557`；`app/gui_trace_release.py:173` | `tests/test_exact_gui_cache.py:51`、`:65`；`tests/test_system_refactor_invariants.py:30`、`:83`、`:106` | GUI 预览和 DXF 已消费同一不可变 `FinalStructure`，缓存保存并校验 `structure_id`；但当前 GUI trace key 仍仅为来源键与页码（`gui_trace_release.py:173-178`），未包含内容哈希、DPI、OCR、算法/模型、配置、profile、schema 和关键阈值，不能标为完成 |

## 逐提交完整文件清单

以下清单来自 `git show --name-status --find-renames <commit>`，没有省略修改文件。

### `d9fbda7`

应用与说明：

- `cad_photo_to_dxf/README.md`
- `cad_photo_to_dxf/app/document_export.py`
- `cad_photo_to_dxf/app/dxf_exporter.py`
- `cad_photo_to_dxf/app/font_library.py`
- `cad_photo_to_dxf/app/gui_exact_release.py`
- `cad_photo_to_dxf/app/gui_librecad_release.py`
- `cad_photo_to_dxf/app/gui_public_release.py`
- `cad_photo_to_dxf/app/gui_trace_release.py`
- `cad_photo_to_dxf/app/ocr_layout.py`
- `cad_photo_to_dxf/app/ocr_outline_export.py`
- `cad_photo_to_dxf/app/ocr_pipeline.py`
- `cad_photo_to_dxf/app/ocr_review.py`
- `cad_photo_to_dxf/app/optimized_trace.py`
- `cad_photo_to_dxf/app/raster_trace.py`
- `cad_photo_to_dxf/app/scan_cleanup.py`
- `cad_photo_to_dxf/app/signature_overlay.py`（新增）
- `cad_photo_to_dxf/app/straight_line_reconstruction.py`（新增）
- `cad_photo_to_dxf/app/trace_document_export.py`
- `cad_photo_to_dxf/app/trace_dxf_entities.py`
- `cad_photo_to_dxf/app/trace_gui_export.py`
- `cad_photo_to_dxf/app/trace_single_export.py`
- `cad_photo_to_dxf/app/trace_storage.py`

资源：

- `cad_photo_to_dxf/resources/fonts/WQY-LICENSE-Apache-2.0.txt`（新增）
- `cad_photo_to_dxf/resources/fonts/librecad-font.lock.json`（新增）
- `cad_photo_to_dxf/resources/fonts/wqy-unicode.lff`（新增）
- `cad_photo_to_dxf/resources/fonts/wqy-unicode.zip`（新增）

测试：

- `cad_photo_to_dxf/tests/test_exact_ui_reduction.py`
- `cad_photo_to_dxf/tests/test_font_aware_ocr_export.py`
- `cad_photo_to_dxf/tests/test_gui_architecture.py`
- `cad_photo_to_dxf/tests/test_librecad_lff_export.py`
- `cad_photo_to_dxf/tests/test_ocr_layout.py`
- `cad_photo_to_dxf/tests/test_ocr_overlap.py`
- `cad_photo_to_dxf/tests/test_optimized_ocr.py`
- `cad_photo_to_dxf/tests/test_scan_cleanup.py`
- `cad_photo_to_dxf/tests/test_signature_overlay.py`（新增）
- `cad_photo_to_dxf/tests/test_straight_line_reconstruction.py`（新增）
- `cad_photo_to_dxf/tests/test_trace_export.py`
- `cad_photo_to_dxf/tests/test_trace_storage_v2.py`

人工验证输出：

- `cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.dxf`（新增）
- `cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.signature-001.png`（新增）
- `cad_photo_to_dxf/validation/user-pdf-check/environment-page-001.signature-002.png`（新增）
- `cad_photo_to_dxf/validation/user-pdf-check/environment-signature-composite.png`（新增）
- `cad_photo_to_dxf/validation/user-pdf-check/warehouse-page-001.dxf`（新增）

### `5a1b065`

CI、设计与应用：

- `.github/workflows/ci.yml`
- `docs/SYSTEM_REFACTOR_DESIGN.md`（新增）
- `cad_photo_to_dxf/app/connectivity_safety.py`（新增）
- `cad_photo_to_dxf/app/content_ownership.py`（新增）
- `cad_photo_to_dxf/app/document_export.py`
- `cad_photo_to_dxf/app/dxf_exporter.py`
- `cad_photo_to_dxf/app/final_structure.py`（新增）
- `cad_photo_to_dxf/app/gui_exact_release.py`
- `cad_photo_to_dxf/app/line_detect.py`
- `cad_photo_to_dxf/app/logo_detection.py`（新增）
- `cad_photo_to_dxf/app/ocr_fast.py`
- `cad_photo_to_dxf/app/ocr_layout.py`
- `cad_photo_to_dxf/app/ocr_outline_export.py`
- `cad_photo_to_dxf/app/ocr_pipeline.py`
- `cad_photo_to_dxf/app/ocr_recognition.py`
- `cad_photo_to_dxf/app/ocr_tile_filter.py`
- `cad_photo_to_dxf/app/optimized_trace.py`
- `cad_photo_to_dxf/app/preprocess.py`
- `cad_photo_to_dxf/app/preview_renderer.py`（新增）
- `cad_photo_to_dxf/app/raster_trace.py`
- `cad_photo_to_dxf/app/scan_artifact_filter.py`（新增）
- `cad_photo_to_dxf/app/scan_cleanup.py`
- `cad_photo_to_dxf/app/signature_overlay.py`
- `cad_photo_to_dxf/app/straight_line_reconstruction.py`
- `cad_photo_to_dxf/app/structural_roi.py`（新增）
- `cad_photo_to_dxf/app/text_protection.py`
- `cad_photo_to_dxf/app/trace_document_export.py`
- `cad_photo_to_dxf/app/trace_dxf_entities.py`
- `cad_photo_to_dxf/app/trace_gui_export.py`
- `cad_photo_to_dxf/app/trace_single_export.py`
- `cad_photo_to_dxf/app/trace_storage.py`
- `cad_photo_to_dxf/mypy.ini`

真实回归：

- `cad_photo_to_dxf/scripts/run_real_document_regression.py`（新增）
- `cad_photo_to_dxf/tests/real_regression/assets/environment-page-003.png`（新增）
- `cad_photo_to_dxf/tests/real_regression/assets/test.jpg`（新增）
- `cad_photo_to_dxf/tests/real_regression/assets/warehouse-page-001.png`（新增）
- `cad_photo_to_dxf/tests/real_regression/manifest.json`（新增）

测试：

- `cad_photo_to_dxf/tests/test_content_ownership.py`（新增）
- `cad_photo_to_dxf/tests/test_exact_gui_cache.py`
- `cad_photo_to_dxf/tests/test_ocr_layout.py`
- `cad_photo_to_dxf/tests/test_ocr_recognition.py`
- `cad_photo_to_dxf/tests/test_optimized_ocr.py`
- `cad_photo_to_dxf/tests/test_real_document_regression_contract.py`（新增）
- `cad_photo_to_dxf/tests/test_scan_artifact_filter.py`（新增）
- `cad_photo_to_dxf/tests/test_scan_cleanup.py`
- `cad_photo_to_dxf/tests/test_signature_overlay.py`
- `cad_photo_to_dxf/tests/test_straight_line_reconstruction.py`
- `cad_photo_to_dxf/tests/test_system_refactor_invariants.py`（新增）
- `cad_photo_to_dxf/tests/test_trace_export.py`

### `d898400`

- `.gitattributes`
- `cad_photo_to_dxf/scripts/capture_frozen_baseline.py`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/README.md`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/current/baseline-result.json`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/current/config-snapshot.json`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/environment-page-003.dxf`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/test.dxf`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/current/outputs/warehouse-page-001.dxf`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/current/tests/pytest-junit.xml`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/old/baseline-result.json`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/old/config-snapshot.json`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/environment-page-003.dxf`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/test.dxf`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/old/outputs/warehouse-page-001.dxf`（新增）
- `cad_photo_to_dxf/validation/system-refactor-baselines/old/tests/pytest-junit.xml`（新增）

## 可复核命令

```powershell
$from = 'd9fbda763e95c6dd7154934b801b59dbf034e711'
$to = 'd898400b69f86b625ce71e9689b5d5f8e877d66a'

git log --reverse --date=iso-strict `
  --format='%H|%aI|%s|parents=%P' "$from^..$to"

git show --name-status --find-renames $from
git show --name-status --find-renames 5a1b06585b6f068bb5f61e16fd32b96e4f54275b
git show --name-status --find-renames $to

git show --shortstat --format='%H|%aI|%s' $from
git show --shortstat --format='%H|%aI|%s' 5a1b06585b6f068bb5f61e16fd32b96e4f54275b
git show --shortstat --format='%H|%aI|%s' $to
```

阶段二是只读历史审计。其提交不得修改 `cad_photo_to_dxf/app`、现有测试逻辑或回归期望；可用以下命令确认应用树保持阶段一状态：

```powershell
git rev-parse d898400b69f86b625ce71e9689b5d5f8e877d66a:cad_photo_to_dxf/app
git rev-parse HEAD:cad_photo_to_dxf/app
```

两条输出都必须是 `5ada4371eccc058fe2897f466c1aefd774aa2905`。
